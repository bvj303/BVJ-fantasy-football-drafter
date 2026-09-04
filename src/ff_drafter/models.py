"""Plain dataclasses the rest of the codebase speaks in.

Nothing outside `espn_client` should touch `espn_api`'s own objects, and
nothing outside `sleeper_client`/`enrichment` should touch Sleeper's raw dicts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Player:
    """One player, optionally enriched with Sleeper data.

    Enrichment fields are all optional: an unmatched player still flows through
    the pipeline with them left as None rather than failing the sync.
    """

    name: str
    espn_id: Optional[int]
    position: str
    pro_team: str
    lineup_slot: str = "BE"

    # Team this player is rostered on. None means free agent.
    team_name: Optional[str] = None

    # --- ESPN-sourced ---
    espn_injury_status: Optional[str] = None
    injured: bool = False
    total_points: float = 0.0
    projected_total_points: float = 0.0
    avg_points: float = 0.0
    projected_avg_points: float = 0.0
    percent_owned: float = 0.0
    percent_started: float = 0.0
    position_rank: int = 0
    eligible_slots: list[str] = field(default_factory=list)
    acquisition_type: Optional[str] = None

    # --- Sleeper-sourced (populated by enrichment.Enricher) ---
    sleeper_id: Optional[str] = None
    match_method: Optional[str] = None
    injury_status: Optional[str] = None
    injury_body_part: Optional[str] = None
    injury_notes: Optional[str] = None
    practice_participation: Optional[str] = None
    depth_chart_order: Optional[int] = None
    trending_add_count: Optional[int] = None
    trending_drop_count: Optional[int] = None

    # --- Sleeper projections, already converted to the league's scoring ---
    sleeper_proj_season: Optional[float] = None
    sleeper_proj_week: Optional[float] = None

    # Slots that only ever hold a player who is not in the starting lineup.
    BENCH_SLOTS = ("BE", "IR", "FA", "")

    @property
    def is_starter(self) -> bool:
        return self.lineup_slot not in self.BENCH_SLOTS

    @property
    def is_free_agent(self) -> bool:
        return self.team_name is None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_starter"] = self.is_starter
        return data


@dataclass
class Team:
    team_id: int
    name: str
    abbrev: str
    roster: list[Player] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    standing: int = 0
    owners: list[str] = field(default_factory=list)
    is_mine: bool = False

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")

    @property
    def starters(self) -> list[Player]:
        return [p for p in self.roster if p.is_starter]

    @property
    def bench(self) -> list[Player]:
        return [p for p in self.roster if not p.is_starter]

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "abbrev": self.abbrev,
            "record": self.record,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "points_for": self.points_for,
            "points_against": self.points_against,
            "standing": self.standing,
            "owners": self.owners,
            "is_mine": self.is_mine,
            "roster": [p.to_dict() for p in self.roster],
        }


@dataclass
class Activity:
    """One row of league transaction history (add/drop/trade)."""

    timestamp: datetime
    team_name: Optional[str]
    action: str
    player_name: str
    bid_amount: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "team_name": self.team_name,
            "action": self.action,
            "player_name": self.player_name,
            "bid_amount": self.bid_amount,
        }


@dataclass
class LeagueSnapshot:
    """The full state of the league at one point in time."""

    taken_at: datetime
    league_id: int
    year: int
    current_week: int
    teams: list[Team] = field(default_factory=list)
    free_agents: list[Player] = field(default_factory=list)
    activity: list[Activity] = field(default_factory=list)
    scoring_format: str = "ppr"
    lineup_slots: dict[str, int] = field(default_factory=dict)

    @property
    def my_team(self) -> Optional[Team]:
        return next((t for t in self.teams if t.is_mine), None)

    def team_by_name(self, name: str) -> Optional[Team]:
        wanted = (name or "").strip().casefold()
        return next((t for t in self.teams
                     if t.name.strip().casefold() == wanted), None)

    def to_dict(self) -> dict[str, Any]:
        my = self.my_team
        return {
            "taken_at": self.taken_at.isoformat(),
            "league_id": self.league_id,
            "year": self.year,
            "current_week": self.current_week,
            "scoring_format": self.scoring_format,
            "lineup_slots": self.lineup_slots,
            "my_team": my.to_dict() if my else None,
            "teams": [t.to_dict() for t in self.teams],
            "free_agents": [p.to_dict() for p in self.free_agents],
            "activity": [a.to_dict() for a in self.activity],
        }


@dataclass
class PlayerHistoryEntry:
    """One player's recorded state at one snapshot, for trend queries."""

    taken_at: datetime
    name: str
    espn_id: Optional[int]
    team_name: Optional[str]
    lineup_slot: str
    injury_status: Optional[str]
    espn_injury_status: Optional[str]
    percent_owned: float
    trending_add_count: Optional[int]
    trending_drop_count: Optional[int]
    total_points: float


@dataclass
class InjuryChange:
    name: str
    team_name: Optional[str]
    previous: Optional[str]
    current: Optional[str]


@dataclass
class SnapshotDiff:
    """What moved between the two most recent snapshots."""

    is_first_snapshot: bool = False
    injury_changes: list[InjuryChange] = field(default_factory=list)
    new_free_agents: list[Player] = field(default_factory=list)
    rostered_away: list[Player] = field(default_factory=list)
    roster_moves: list[Activity] = field(default_factory=list)
