"""Adapter tests: espn_api objects -> our own dataclasses."""
import pytest

from ff_drafter.espn_client import EspnClient
from ff_drafter.models import LeagueSnapshot, Player, Team


@pytest.fixture
def client(fake_espn_league):
    return EspnClient(fake_espn_league, my_team_name="Team Bologna")


def test_fetch_teams_returns_our_dataclasses(client):
    teams = client.fetch_teams()
    assert all(isinstance(t, Team) for t in teams)
    assert [t.name for t in teams] == ["Team Bologna", "Gridiron Goblins"]


def test_team_record_and_points_are_carried_over(client):
    mine = client.fetch_my_team()
    assert (mine.wins, mine.losses, mine.ties) == (2, 1, 0)
    assert mine.points_for == 310.4
    assert mine.standing == 2
    assert mine.is_mine is True


def test_other_teams_are_not_flagged_as_mine(client):
    rival = [t for t in client.fetch_teams() if t.name == "Gridiron Goblins"][0]
    assert rival.is_mine is False


def test_roster_players_map_espn_fields(client):
    mine = client.fetch_my_team()
    cmc = [p for p in mine.roster if p.name == "Christian McCaffrey"][0]
    assert isinstance(cmc, Player)
    assert cmc.espn_id == 3117251
    assert cmc.position == "RB"
    assert cmc.pro_team == "SF"
    assert cmc.lineup_slot == "RB"
    assert cmc.espn_injury_status == "QUESTIONABLE"
    assert cmc.total_points == 42.5
    assert cmc.projected_total_points == 55.0
    assert cmc.percent_owned == 99.8


def test_starters_are_distinguished_from_bench(client):
    mine = client.fetch_my_team()
    starters = {p.name for p in mine.roster if p.is_starter}
    assert "Christian McCaffrey" in starters
    assert "Dalton Kincaid" not in starters


def test_fetch_free_agents_marks_players_as_unrostered(client):
    fas = client.fetch_free_agents(size=10)
    assert {p.name for p in fas} >= {"Tyjae Spears", "Cade Otton", "Trey Benson"}
    assert all(p.team_name is None for p in fas)


def test_fetch_free_agents_respects_size(client):
    assert len(client.fetch_free_agents(size=2)) == 2


def test_fetch_recent_activity_flattens_actions(client):
    acts = client.fetch_recent_activity(size=10)
    assert len(acts) == 1
    act = acts[0]
    assert act.team_name == "Gridiron Goblins"
    assert act.action == "WAIVER ADDED"
    assert act.player_name == "Ja'Marr Chase"
    assert act.bid_amount == 17
    # Epoch millis must be surfaced as a tz-aware UTC timestamp.
    assert act.timestamp.tzinfo is not None
    assert act.timestamp.utcoffset().total_seconds() == 0


def test_build_snapshot_contains_teams_free_agents_and_activity(client):
    snap = client.build_snapshot()
    assert isinstance(snap, LeagueSnapshot)
    assert len(snap.teams) == 2
    assert len(snap.free_agents) == 4
    assert len(snap.activity) == 1
    assert snap.current_week == 3
    assert snap.taken_at.tzinfo is not None


def test_my_team_name_is_matched_case_insensitively(fake_espn_league):
    c = EspnClient(fake_espn_league, my_team_name="  team BOLOGNA ")
    assert c.fetch_my_team().name == "Team Bologna"


def test_unknown_my_team_name_raises_with_available_names(fake_espn_league):
    c = EspnClient(fake_espn_league, my_team_name="Not A Team")
    with pytest.raises(ValueError, match="Gridiron Goblins"):
        c.fetch_my_team()


# --- regression: espn_api yields [] for absent scalar fields ---------------
# Real ESPN data returns an empty list (not None) for any field missing from
# the underlying JSON: acquisitionType on every free agent, injuryStatus on
# defenses/coaches. Those must normalize to None or the SQLite insert fails.

def _league_with(player):
    from conftest import FakeEspnLeague, FakeEspnTeam
    team = FakeEspnTeam(1, "Team Bologna", [player])
    return EspnClient(FakeEspnLeague([team], free_agents=[player]),
                      my_team_name="Team Bologna")


def test_absent_injury_status_list_becomes_none():
    from conftest import FakeEspnPlayer
    p = FakeEspnPlayer("Jaguars D/ST", 12345, "D/ST", injuryStatus=[])
    player = _league_with(p).fetch_my_team().roster[0]
    assert player.espn_injury_status is None


def test_absent_acquisition_type_list_becomes_none():
    from conftest import FakeEspnPlayer
    p = FakeEspnPlayer("Josh Jacobs", 23456, "RB", acquisitionType=[])
    player = _league_with(p).fetch_free_agents()[0]
    assert player.acquisition_type is None


def test_empty_string_injury_status_is_normalized_to_none():
    from conftest import FakeEspnPlayer
    p = FakeEspnPlayer("Someone", 34567, "WR", injuryStatus="")
    assert _league_with(p).fetch_my_team().roster[0].espn_injury_status is None


def test_non_int_player_id_becomes_none():
    from conftest import FakeEspnPlayer
    p = FakeEspnPlayer("Ghost", None, "WR")
    p.playerId = []
    assert _league_with(p).fetch_my_team().roster[0].espn_id is None


def test_snapshot_with_absent_fields_is_storable(tmp_path):
    """The end-to-end guard: a snapshot of such players must write to SQLite."""
    from conftest import FakeEspnPlayer
    from ff_drafter.storage import Storage
    p = FakeEspnPlayer("Chiefs D/ST", 45678, "D/ST", injuryStatus=[],
                       acquisitionType=[])
    snap = _league_with(p).build_snapshot()
    with Storage(tmp_path / "reg.db") as store:
        store.write_snapshot(snap)
        assert store.latest_snapshot().teams[0].roster[0].name == "Chiefs D/ST"
