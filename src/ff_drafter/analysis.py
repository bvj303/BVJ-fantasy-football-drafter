"""Roster analysis: where is my team weak relative to the rest of the league?

The judgement here is deliberately deterministic and comparative. A weak spot
is not "a low projection" in the abstract — it is a starting slot where my
player projects below what my *actual opponents* start at the same slot. That
is what decides matchups, and it is what a trade or a waiver claim can fix.

Projections come from Sleeper (converted to the league's scoring in
enrichment), falling back to ESPN's own projection when Sleeper has none, so
every rostered player carries a comparable number.

The richer, less mechanical reasoning — which trade to actually propose, is a
slump real — stays in the slash commands. This module hands them a defensible
map of the holes.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Optional

from .models import LeagueSnapshot, Player, Team

# A slot label maps to the set of base positions eligible to fill it.
_SLOT_ELIGIBILITY = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"},
    "D/ST": {"DST"}, "DST": {"DST"}, "HC": {"HC"},
    "OP": {"QB", "RB", "WR", "TE"},        # ESPN "offensive player" superflex
    "SUPERFLEX": {"QB", "RB", "WR", "TE"},
    "FLEX": {"RB", "WR", "TE"},
}

# Used only when a snapshot carries no lineup structure at all.
_DEFAULT_LINEUP = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1,
                   "D/ST": 1, "K": 1}

_INJURY_BENCHWORTHY = {"OUT", "DOUBTFUL", "IR", "PUP", "SUSPENDED"}
_INJURY_WATCH = {"QUESTIONABLE"}
_DISAGREEMENT_MIN_POINTS = 40.0   # absolute season-point gap worth noting
_DISAGREEMENT_MIN_RATIO = 0.25    # relative gap worth noting


def base_position(position: Optional[str]) -> str:
    p = (position or "").upper()
    if p in ("D/ST", "DEF", "DST"):
        return "DST"
    return p


def proj_value(player: Player) -> float:
    """The player's season projection, Sleeper first then ESPN, else 0."""
    if player.sleeper_proj_season is not None:
        return float(player.sleeper_proj_season)
    if player.projected_total_points:
        return float(player.projected_total_points)
    return 0.0


def slot_eligibility(label: str) -> set[str]:
    if label in _SLOT_ELIGIBILITY:
        return _SLOT_ELIGIBILITY[label]
    if "/" in label:
        return {base_position(part) for part in label.split("/")}
    return {label}


def _expand_slots(lineup_slots: dict[str, int]) -> list[str]:
    """Individual starting slots, most restrictive first so flex takes leftovers."""
    slots: list[str] = []
    for label, count in lineup_slots.items():
        slots.extend([label] * int(count))
    slots.sort(key=lambda label: (len(slot_eligibility(label)), label))
    return slots


def optimal_lineup(players: list[Player],
                   lineup_slots: dict[str, int]) -> list[tuple[str, Optional[Player]]]:
    """Greedily assign a team's best eligible players to its starting slots.

    Filling the most restrictive slots first (dedicated positions before flex)
    yields the lineup a rational manager would set, and lets flex/superflex
    slots absorb the best remaining eligible player.
    """
    pool = sorted(players, key=proj_value, reverse=True)
    used: set[int] = set()
    result: list[tuple[str, Optional[Player]]] = []
    for label in _expand_slots(lineup_slots):
        eligible = slot_eligibility(label)
        pick = None
        for player in pool:
            if id(player) in used:
                continue
            if base_position(player.position) in eligible:
                pick = player
                used.add(id(player))
                break
        result.append((label, pick))
    return result


@dataclass
class PositionBenchmark:
    position: str
    count: int
    elite: float
    starter_median: float
    replacement: float


def positional_benchmarks(snapshot: LeagueSnapshot) -> dict[str, PositionBenchmark]:
    lineup = snapshot.lineup_slots or _DEFAULT_LINEUP
    teams = snapshot.teams
    by_pos: dict[str, list[float]] = {}
    for t in teams:
        for p in t.roster:
            by_pos.setdefault(base_position(p.position), []).append(proj_value(p))

    dedicated: dict[str, int] = {}
    for label, count in lineup.items():
        elig = slot_eligibility(label)
        if len(elig) == 1:
            dedicated[next(iter(elig))] = dedicated.get(next(iter(elig)), 0) + int(count)

    benchmarks = {}
    for pos, values in by_pos.items():
        values = sorted(values, reverse=True)
        demand = dedicated.get(pos, 1) * len(teams)
        starters = values[:demand] or values[:1]
        replacement = values[demand] if len(values) > demand else (
            values[-1] if values else 0.0)
        benchmarks[pos] = PositionBenchmark(
            position=pos, count=len(values), elite=values[0] if values else 0.0,
            starter_median=round(statistics.median(starters), 1),
            replacement=round(replacement, 1),
        )
    return benchmarks


@dataclass
class SlotAssessment:
    slot: str                 # e.g. "RB", "RB/WR/TE"
    label: str                # e.g. "RB2", "FLEX"
    position: str             # base position of my player, or slot's family
    player: Optional[str]
    my_proj: float
    league_median: float
    gap_to_median: float
    percentile: float         # share of teams I'm at or above in this slot

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Flag:
    player: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RosterAnalysis:
    team_name: str
    scoring_format: str
    slots: list[SlotAssessment] = field(default_factory=list)
    weak_spots: list[SlotAssessment] = field(default_factory=list)
    injury_flags: list[Flag] = field(default_factory=list)
    projection_disagreements: list[Flag] = field(default_factory=list)
    bench_depth: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "team_name": self.team_name,
            "scoring_format": self.scoring_format,
            "slots": [s.to_dict() for s in self.slots],
            "weak_spots": [s.to_dict() for s in self.weak_spots],
            "injury_flags": [f.to_dict() for f in self.injury_flags],
            "projection_disagreements":
                [f.to_dict() for f in self.projection_disagreements],
            "bench_depth": self.bench_depth,
        }


def _slot_labels(expanded: list[str]) -> list[str]:
    """Turn ['RB','RB','WR',...] into ['RB1','RB2','WR1',...]."""
    seen: dict[str, int] = {}
    out = []
    for slot in expanded:
        seen[slot] = seen.get(slot, 0) + 1
        pretty = slot.replace("RB/WR/TE", "FLEX").replace("OP", "SFLEX")
        out.append(f"{pretty}{seen[slot]}" if _repeats(expanded, slot) else pretty)
    return out


def _repeats(expanded: list[str], slot: str) -> bool:
    return expanded.count(slot) > 1


def analyze_team(snapshot: LeagueSnapshot,
                 team_name: Optional[str] = None) -> RosterAnalysis:
    team = _resolve_team(snapshot, team_name)
    lineup = snapshot.lineup_slots or _DEFAULT_LINEUP
    expanded = _expand_slots(lineup)
    labels = _slot_labels(expanded)

    lineups = {t.name: optimal_lineup(t.roster, lineup) for t in snapshot.teams}
    mine = lineups[team.name]

    slots: list[SlotAssessment] = []
    for i, (slot, pick) in enumerate(mine):
        across = sorted(proj_value(lineups[t.name][i][1])
                        if lineups[t.name][i][1] else 0.0
                        for t in snapshot.teams)
        my_proj = proj_value(pick) if pick else 0.0
        median = round(statistics.median(across), 1) if across else 0.0
        at_or_below = sum(1 for v in across if v <= my_proj)
        slots.append(SlotAssessment(
            slot=slot, label=labels[i],
            position=base_position(pick.position) if pick else
            "/".join(sorted(slot_eligibility(slot))),
            player=pick.name if pick else None,
            my_proj=round(my_proj, 1), league_median=median,
            gap_to_median=round(my_proj - median, 1),
            percentile=round(at_or_below / len(across), 2) if across else 0.0,
        ))

    weak_spots = sorted((s for s in slots if s.gap_to_median < 0),
                        key=lambda s: s.gap_to_median)

    injury_flags = []
    starters = {id(pick) for _, pick in mine if pick}
    for _, pick in mine:
        if not pick:
            continue
        status = (pick.injury_status or pick.espn_injury_status or "").upper()
        if status in _INJURY_BENCHWORTHY or status in _INJURY_WATCH:
            injury_flags.append(Flag(
                player=pick.name,
                detail=f"starting despite {pick.injury_status or status.title()}"
                + (f" ({pick.injury_body_part})" if pick.injury_body_part else "")))

    disagreements = []
    for p in team.roster:
        s, e = p.sleeper_proj_season, p.projected_total_points
        if s is None or not e:
            continue
        gap = abs(s - e)
        if gap >= _DISAGREEMENT_MIN_POINTS and gap / max(s, e) >= _DISAGREEMENT_MIN_RATIO:
            higher = "ESPN" if e > s else "Sleeper"
            disagreements.append(Flag(
                player=p.name,
                detail=f"{higher} higher by {gap:.0f} pts "
                       f"(ESPN {e:.0f} vs Sleeper {s:.0f}) — usage worth a look"))

    benchmarks = positional_benchmarks(snapshot)
    bench_depth = {}
    for pos, bench in benchmarks.items():
        mine_at_pos = [p for p in team.roster
                       if base_position(p.position) == pos]
        startable = sum(1 for p in mine_at_pos
                        if proj_value(p) >= bench.replacement)
        bench_depth[pos] = startable

    return RosterAnalysis(
        team_name=team.name, scoring_format=snapshot.scoring_format,
        slots=slots, weak_spots=weak_spots, injury_flags=injury_flags,
        projection_disagreements=disagreements, bench_depth=bench_depth,
    )


def _resolve_team(snapshot: LeagueSnapshot, team_name: Optional[str]) -> Team:
    if team_name:
        t = snapshot.team_by_name(team_name)
        if t is None:
            names = ", ".join(x.name for x in snapshot.teams)
            raise ValueError(f"No team named {team_name!r}. Teams: {names}")
        return t
    if snapshot.my_team is None:
        raise ValueError("No team is marked as mine; pass team_name.")
    return snapshot.my_team
