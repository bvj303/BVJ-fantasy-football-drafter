"""SQLite snapshot persistence and history queries."""
from datetime import datetime, timedelta, timezone

import pytest

from ff_drafter.models import (Activity, LeagueSnapshot, Player, Team)
from ff_drafter.storage import Storage


def mk_player(name, espn_id, position="RB", **kw):
    return Player(name=name, espn_id=espn_id, position=position,
                  pro_team=kw.pop("pro_team", "SF"),
                  lineup_slot=kw.pop("lineup_slot", "RB"), **kw)


def mk_snapshot(taken_at, injury="Questionable", trending=100, week=3):
    cmc = mk_player("Christian McCaffrey", 3117251, injury_status=injury,
                    trending_add_count=trending, team_name="Team Bologna")
    fa = mk_player("Tyjae Spears", 100006, team_name=None, lineup_slot="FA",
                   trending_add_count=5000)
    team = Team(team_id=1, name="Team Bologna", abbrev="TB", roster=[cmc],
                wins=2, losses=1, ties=0, points_for=310.4,
                points_against=288.1, standing=2, is_mine=True)
    act = Activity(timestamp=taken_at, team_name="Gridiron Goblins",
                   action="WAIVER ADDED", player_name="Ja'Marr Chase",
                   bid_amount=17)
    return LeagueSnapshot(taken_at=taken_at, league_id=999, year=2025,
                          current_week=week, teams=[team], free_agents=[fa],
                          activity=[act])


@pytest.fixture
def storage(tmp_path):
    with Storage(tmp_path / "test.db") as s:
        yield s


NOW = datetime(2025, 9, 15, 17, 0, tzinfo=timezone.utc)


def test_schema_is_created_on_open(storage):
    tables = storage.table_names()
    assert {"snapshots", "snapshot_players", "teams", "activity"} <= set(tables)


def test_write_snapshot_returns_an_id(storage):
    assert isinstance(storage.write_snapshot(mk_snapshot(NOW)), int)


def test_latest_snapshot_round_trips(storage):
    storage.write_snapshot(mk_snapshot(NOW))
    snap = storage.latest_snapshot()
    assert snap.current_week == 3
    assert snap.taken_at == NOW
    assert snap.teams[0].name == "Team Bologna"
    assert snap.teams[0].roster[0].name == "Christian McCaffrey"
    assert snap.teams[0].is_mine is True
    assert snap.free_agents[0].name == "Tyjae Spears"
    assert snap.activity[0].player_name == "Ja'Marr Chase"


def test_latest_snapshot_is_the_most_recent_one(storage):
    storage.write_snapshot(mk_snapshot(NOW - timedelta(days=1), week=2))
    storage.write_snapshot(mk_snapshot(NOW, week=3))
    assert storage.latest_snapshot().current_week == 3


def test_latest_snapshot_is_none_on_an_empty_database(storage):
    assert storage.latest_snapshot() is None


def test_free_agents_are_not_attached_to_a_team(storage):
    storage.write_snapshot(mk_snapshot(NOW))
    snap = storage.latest_snapshot()
    assert all(p.team_name is None for p in snap.free_agents)
    assert [p.name for p in snap.teams[0].roster] == ["Christian McCaffrey"]


def test_timestamps_are_stored_and_returned_in_utc(storage):
    local = datetime(2025, 9, 15, 13, 0,
                     tzinfo=timezone(timedelta(hours=-4)))
    storage.write_snapshot(mk_snapshot(local))
    got = storage.latest_snapshot().taken_at
    assert got.tzinfo == timezone.utc
    assert got == local


def test_player_history_tracks_changes_across_snapshots(storage):
    storage.write_snapshot(mk_snapshot(NOW - timedelta(days=2),
                                       injury=None, trending=10))
    storage.write_snapshot(mk_snapshot(NOW - timedelta(days=1),
                                       injury="Questionable", trending=5000))
    storage.write_snapshot(mk_snapshot(NOW, injury="Out", trending=90000))
    hist = storage.player_history(espn_id=3117251)
    assert [h.injury_status for h in hist] == [None, "Questionable", "Out"]
    assert [h.trending_add_count for h in hist] == [10, 5000, 90000]
    assert hist[0].taken_at < hist[-1].taken_at


def test_player_history_can_be_looked_up_by_name(storage):
    storage.write_snapshot(mk_snapshot(NOW))
    assert len(storage.player_history(name="Christian McCaffrey")) == 1


def test_player_history_of_unknown_player_is_empty(storage):
    storage.write_snapshot(mk_snapshot(NOW))
    assert storage.player_history(espn_id=1) == []


def test_player_history_requires_an_identifier(storage):
    with pytest.raises(ValueError):
        storage.player_history()


def test_diff_reports_injury_status_changes(storage):
    storage.write_snapshot(mk_snapshot(NOW - timedelta(days=1), injury=None))
    storage.write_snapshot(mk_snapshot(NOW, injury="Out"))
    diff = storage.diff_latest()
    changes = [c for c in diff.injury_changes
               if c.name == "Christian McCaffrey"]
    assert changes[0].previous == "Was healthy" or changes[0].previous is None
    assert changes[0].current == "Out"


def test_diff_reports_new_free_agents(storage):
    first = mk_snapshot(NOW - timedelta(days=1))
    second = mk_snapshot(NOW)
    second.free_agents.append(mk_player("Cade Otton", 100007, position="TE",
                                        team_name=None, lineup_slot="FA"))
    storage.write_snapshot(first)
    storage.write_snapshot(second)
    assert "Cade Otton" in [p.name for p in storage.diff_latest().new_free_agents]


def test_diff_against_a_single_snapshot_is_empty(storage):
    storage.write_snapshot(mk_snapshot(NOW))
    diff = storage.diff_latest()
    assert diff.injury_changes == []
    assert diff.new_free_agents == []
    assert diff.is_first_snapshot is True


def test_storage_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deeper" / "ff.db"
    with Storage(path) as s:
        s.write_snapshot(mk_snapshot(NOW))
    assert path.exists()
