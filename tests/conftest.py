"""Shared fixtures. No test in this suite may touch the live network."""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    with open(FIXTURES / name) as fh:
        return json.load(fh)


@pytest.fixture
def sleeper_players():
    return load_fixture("sleeper_players.json")


@pytest.fixture
def trending_add():
    return load_fixture("sleeper_trending_add.json")


@pytest.fixture
def trending_drop():
    return load_fixture("sleeper_trending_drop.json")


class FakeEspnPlayer:
    """Mirrors the attribute surface of espn_api.football.Player that we read.

    ESPN's own endpoints require live private-league credentials, so the client
    tests exercise our adapter against objects shaped like the library's, rather
    than against recorded league responses we cannot legally or practically ship.
    """

    def __init__(self, name, playerId, position, proTeam="FA", lineupSlot="BE",
                 injuryStatus="ACTIVE", injured=False, total_points=0.0,
                 projected_total_points=0.0, avg_points=0.0,
                 projected_avg_points=0.0, percent_owned=0.0,
                 percent_started=0.0, posRank=0, eligibleSlots=None,
                 acquisitionType="DRAFT", onTeamId=0):
        self.name = name
        self.playerId = playerId
        self.position = position
        self.proTeam = proTeam
        self.lineupSlot = lineupSlot
        self.injuryStatus = injuryStatus
        self.injured = injured
        self.total_points = total_points
        self.projected_total_points = projected_total_points
        self.avg_points = avg_points
        self.projected_avg_points = projected_avg_points
        self.percent_owned = percent_owned
        self.percent_started = percent_started
        self.posRank = posRank
        self.eligibleSlots = eligibleSlots or [position, "BE"]
        self.acquisitionType = acquisitionType
        self.onTeamId = onTeamId


class FakeEspnTeam:
    def __init__(self, team_id, team_name, roster, wins=0, losses=0, ties=0,
                 points_for=0.0, points_against=0.0, standing=1, owners=None,
                 team_abbrev="ABC"):
        self.team_id = team_id
        self.team_name = team_name
        self.team_abbrev = team_abbrev
        self.roster = roster
        self.wins = wins
        self.losses = losses
        self.ties = ties
        self.points_for = points_for
        self.points_against = points_against
        self.standing = standing
        self.owners = owners or []


class FakeEspnLeague:
    def __init__(self, teams, free_agents=None, activity=None, current_week=3,
                 league_id=999, year=2025):
        self.teams = teams
        self._free_agents = free_agents or []
        self._activity = activity or []
        self.current_week = current_week
        self.league_id = league_id
        self.year = year

    def free_agents(self, week=None, size=50, position=None, position_id=None):
        pool = self._free_agents
        if position:
            pool = [p for p in pool if p.position == position]
        return pool[:size]

    def recent_activity(self, size=25, msg_type=None, offset=0):
        return self._activity[:size]

    def standings(self):
        return sorted(self.teams, key=lambda t: t.standing)


class FakeActivity:
    def __init__(self, date, actions):
        self.date = date
        self.actions = actions


@pytest.fixture
def fake_espn_league():
    mccaffrey = FakeEspnPlayer("Christian McCaffrey", 3117251, "RB", "SF", "RB",
                               "QUESTIONABLE", True, 42.5, 55.0, 14.2, 18.3,
                               99.8, 98.1, 4)
    jefferson = FakeEspnPlayer("Justin Jefferson", 4262921, "WR", "MIN", "WR",
                               "ACTIVE", False, 61.0, 58.0, 20.3, 19.3, 99.9,
                               99.5, 1)
    purdy = FakeEspnPlayer("Brock Purdy", 100001, "QB", "SF", "QB",
                           "ACTIVE", False, 55.1, 60.0, 18.4, 20.0, 88.0, 80.0, 9)
    kincaid = FakeEspnPlayer("Dalton Kincaid", 100002, "TE", "BUF", "BE",
                             "ACTIVE", False, 18.0, 24.0, 6.0, 8.0, 70.0, 40.0, 14)
    harrison = FakeEspnPlayer("Marvin Harrison Jr.", 100003, "WR", "ARI", "BE",
                              "ACTIVE", False, 30.0, 36.0, 10.0, 12.0, 95.0, 70.0, 22)
    my_team = FakeEspnTeam(1, "Team Bologna", [mccaffrey, jefferson, purdy,
                                               kincaid, harrison],
                           wins=2, losses=1, points_for=310.4,
                           points_against=288.1, standing=2,
                           owners=[{"firstName": "Brendan", "lastName": "V"}])

    chase = FakeEspnPlayer("Ja'Marr Chase", 100004, "WR", "CIN", "WR",
                           "QUESTIONABLE", True, 48.0, 52.0, 16.0, 17.3, 99.9,
                           99.0, 3)
    bijan = FakeEspnPlayer("Bijan Robinson", 100005, "RB", "ATL", "RB",
                           "ACTIVE", False, 58.0, 54.0, 19.3, 18.0, 99.9, 99.2, 1)
    rival = FakeEspnTeam(2, "Gridiron Goblins", [chase, bijan], wins=3,
                         losses=0, points_for=340.2, points_against=270.0,
                         standing=1, owners=[{"firstName": "Sam", "lastName": "Q"}])

    spears = FakeEspnPlayer("Tyjae Spears", 100006, "RB", "TEN", "FA",
                            "ACTIVE", False, 12.0, 20.0, 4.0, 6.6, 33.0, 10.0, 48,
                            acquisitionType=None)
    otton = FakeEspnPlayer("Cade Otton", 100007, "TE", "TB", "FA",
                           "ACTIVE", False, 15.0, 18.0, 5.0, 6.0, 41.0, 22.0, 20,
                           acquisitionType=None)
    benson = FakeEspnPlayer("Trey Benson", 100008, "RB", "ARI", "FA",
                            "INJURY_RESERVE", True, 3.0, 4.0, 1.0, 1.3, 12.0,
                            2.0, 80, acquisitionType=None)
    unknown = FakeEspnPlayer("Nobody McGhost", 100009, "WR", "FA", "FA",
                             "ACTIVE", False, 0.0, 0.0, 0.0, 0.0, 0.1, 0.0, 300,
                             acquisitionType=None)

    activity = [FakeActivity(1725300000000,
                             [(rival, "WAIVER ADDED", chase, 17)])]
    return FakeEspnLeague([my_team, rival],
                          free_agents=[spears, otton, benson, unknown],
                          activity=activity)


@pytest.fixture
def proj_season():
    return load_fixture("sleeper_proj_season.json")


@pytest.fixture
def proj_week1():
    return load_fixture("sleeper_proj_week1.json")
