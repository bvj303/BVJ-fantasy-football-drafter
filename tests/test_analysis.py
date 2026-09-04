"""Roster weak-spot analysis, measured relative to the rest of the league."""
from datetime import datetime, timezone

import pytest

from ff_drafter.analysis import (analyze_team, optimal_lineup,
                                  positional_benchmarks, proj_value)
from ff_drafter.models import LeagueSnapshot, Player, Team

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)
LINEUP = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "K": 1}


def P(name, pos, proj, team_name=None, espn_proj=None, **kw):
    return Player(name=name, espn_id=abs(hash(name)) % 10**6, position=pos,
                  pro_team=kw.pop("pro_team", "SF"), lineup_slot="BE",
                  team_name=team_name, sleeper_proj_season=proj,
                  projected_total_points=espn_proj if espn_proj is not None
                  else (proj or 0.0), **kw)


def team(name, players, is_mine=False, standing=1):
    for p in players:
        p.team_name = name
    return Team(team_id=abs(hash(name)) % 1000, name=name, abbrev=name[:3],
                roster=players, is_mine=is_mine, standing=standing)


def snap(teams, free_agents=None):
    return LeagueSnapshot(taken_at=NOW, league_id=1, year=2026, current_week=1,
                          teams=teams, free_agents=free_agents or [],
                          scoring_format="ppr", lineup_slots=LINEUP)


@pytest.fixture
def league():
    # My team: strong RB, weak WR. Two rivals: average and WR-loaded.
    mine = team("Mine", [
        P("Stud RB", "RB", 300), P("Good RB", "RB", 240),
        P("Weak WR1", "WR", 120), P("Weak WR2", "WR", 90),
        P("Mid QB", "QB", 260), P("Mid TE", "TE", 130), P("A Kicker", "K", 130),
        P("Bench RB", "RB", 150),
    ], is_mine=True, standing=2)
    rivalA = team("RivalA", [
        P("RB a1", "RB", 220), P("RB a2", "RB", 180),
        P("WR a1", "WR", 250), P("WR a2", "WR", 210),
        P("QB a", "QB", 270), P("TE a", "TE", 150), P("K a", "K", 125),
    ], standing=1)
    rivalB = team("RivalB", [
        P("RB b1", "RB", 200), P("RB b2", "RB", 160),
        P("WR b1", "WR", 280), P("WR b2", "WR", 230),
        P("QB b", "QB", 250), P("TE b", "TE", 120), P("K b", "K", 120),
    ], standing=3)
    return snap([mine, rivalA, rivalB])


# --- helpers ----------------------------------------------------------------

def test_proj_value_prefers_sleeper_then_espn_then_zero():
    assert proj_value(P("a", "RB", 100, espn_proj=80)) == 100
    p = P("b", "RB", None, espn_proj=80)
    assert proj_value(p) == 80
    p2 = Player(name="c", espn_id=1, position="RB", pro_team="SF",
                lineup_slot="BE")
    assert proj_value(p2) == 0.0


def test_optimal_lineup_fills_flex_with_best_leftover():
    players = [P("RB1", "RB", 300), P("RB2", "RB", 200), P("RB3", "RB", 190),
               P("WR1", "WR", 250), P("WR2", "WR", 180),
               P("QB1", "QB", 260), P("TE1", "TE", 130), P("K1", "K", 120)]
    lineup = optimal_lineup(players, LINEUP)
    assigned = {lbl: pk.name for lbl, pk in lineup if pk}
    # the RB/WR/TE flex should take RB3 (190) over WR2 (180)
    flex = [pk.name for lbl, pk in lineup if lbl == "RB/WR/TE"]
    assert flex == ["RB3"]


def test_optimal_lineup_leaves_slot_empty_when_no_eligible_player():
    players = [P("QB1", "QB", 260)]
    lineup = optimal_lineup(players, {"QB": 1, "RB": 1})
    rb = [pk for lbl, pk in lineup if lbl == "RB"][0]
    assert rb is None


# --- benchmarks -------------------------------------------------------------

def test_positional_benchmarks_rank_by_projection(league):
    bench = positional_benchmarks(league)
    assert bench["WR"].elite == 280        # WR b1
    assert bench["RB"].elite == 300        # my Stud RB
    assert bench["WR"].count == 6


# --- team analysis ----------------------------------------------------------

def test_weak_spot_is_surfaced_at_wr(league):
    analysis = analyze_team(league)
    weak_positions = {w.position for w in analysis.weak_spots}
    assert "WR" in weak_positions


def test_strength_is_not_flagged_as_weak(league):
    analysis = analyze_team(league)
    assert "RB" not in {w.position for w in analysis.weak_spots}


def test_weak_spots_are_ranked_worst_first(league):
    analysis = analyze_team(league)
    gaps = [w.gap_to_median for w in analysis.weak_spots]
    assert gaps == sorted(gaps)          # most negative first


def test_slot_assessment_reports_my_player_and_gap(league):
    analysis = analyze_team(league)
    wr_slots = [s for s in analysis.slots if s.position == "WR"]
    assert wr_slots
    assert all(s.gap_to_median < 0 for s in wr_slots)   # both my WRs below median
    assert any(s.player == "Weak WR1" for s in wr_slots)


def test_analysis_defaults_to_my_team(league):
    assert analyze_team(league).team_name == "Mine"


def test_analysis_can_target_a_named_team(league):
    assert analyze_team(league, team_name="RivalA").team_name == "RivalA"


def test_unknown_team_raises(league):
    with pytest.raises(ValueError, match="RivalB"):
        analyze_team(league, team_name="Nope")


def test_injury_on_a_starter_is_flagged(league):
    league.teams[0].roster[0].injury_status = "Out"   # Stud RB
    analysis = analyze_team(league)
    assert any("Stud RB" in f.player for f in analysis.injury_flags)


def test_projection_disagreement_is_flagged(league):
    # ESPN loves a player Sleeper is cool on -> uncertainty signal.
    league.teams[0].roster[2].sleeper_proj_season = 90    # Weak WR1
    league.teams[0].roster[2].projected_total_points = 200
    analysis = analyze_team(league)
    assert any("Weak WR1" in d.player for d in analysis.projection_disagreements)


def test_analysis_is_serializable(league):
    d = analyze_team(league).to_dict()
    assert d["team_name"] == "Mine"
    assert isinstance(d["weak_spots"], list)
    assert "slots" in d


def test_missing_lineup_slots_falls_back_to_a_default(league):
    league.lineup_slots = {}
    analysis = analyze_team(league)         # must not crash
    assert analysis.slots
