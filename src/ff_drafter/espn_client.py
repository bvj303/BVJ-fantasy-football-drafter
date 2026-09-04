"""Adapter over `espn_api.football.League`.

The library's objects are only ever read here; everything this module returns
is one of our own dataclasses, so a breaking change upstream is contained to
this file.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .config import Config
from .models import Activity, LeagueSnapshot, Player, Team


def build_espn_client(config: Config) -> "EspnClient":
    """Connect to the real ESPN API using the configured credentials."""
    from espn_api.football import League

    league = League(
        league_id=config.league_id,
        year=config.year,
        espn_s2=config.espn_s2,
        swid=config.espn_swid,
    )
    return EspnClient(league, my_team_name=config.my_team_name)


class EspnClient:
    def __init__(self, league: Any, my_team_name: Optional[str] = None):
        self._league = league
        self._my_team_name = (my_team_name or "").strip().casefold() or None

    # --- teams --------------------------------------------------------------

    def fetch_teams(self) -> list[Team]:
        return [self._to_team(t) for t in self._league.teams]

    def fetch_my_team(self) -> Team:
        teams = self.fetch_teams()
        mine = [t for t in teams if t.is_mine]
        if mine:
            return mine[0]
        names = ", ".join(t.name for t in teams)
        raise ValueError(
            f"Could not identify your team. ESPN_TEAM_NAME is "
            f"{self._my_team_name!r}; league teams are: {names}"
        )

    def _is_mine(self, team: Any) -> bool:
        if self._my_team_name:
            return str(team.team_name).strip().casefold() == self._my_team_name
        # No name configured: fall back to the team the cookies authenticate as,
        # which espn_api exposes on the team's owner records.
        for owner in getattr(team, "owners", []) or []:
            if isinstance(owner, dict) and owner.get("isLeagueManager") is None:
                continue
        return False

    def _to_team(self, team: Any) -> Team:
        is_mine = self._is_mine(team)
        name = str(team.team_name)
        return Team(
            team_id=team.team_id,
            name=name,
            abbrev=getattr(team, "team_abbrev", ""),
            roster=[self._to_player(p, team_name=name) for p in team.roster],
            wins=getattr(team, "wins", 0),
            losses=getattr(team, "losses", 0),
            ties=getattr(team, "ties", 0),
            points_for=getattr(team, "points_for", 0.0),
            points_against=getattr(team, "points_against", 0.0),
            standing=getattr(team, "standing", 0),
            owners=_owner_names(getattr(team, "owners", []) or []),
            is_mine=is_mine,
        )

    # --- players ------------------------------------------------------------

    def _to_player(self, p: Any, team_name: Optional[str]) -> Player:
        return Player(
            name=str(getattr(p, "name", "") or ""),
            espn_id=_int_or_none(getattr(p, "playerId", None)),
            position=getattr(p, "position", "") or "",
            pro_team=getattr(p, "proTeam", "") or "",
            lineup_slot=getattr(p, "lineupSlot", "") or "",
            team_name=team_name,
            espn_injury_status=_text_or_none(getattr(p, "injuryStatus", None)),
            injured=bool(getattr(p, "injured", False)),
            total_points=_num(getattr(p, "total_points", 0.0)),
            projected_total_points=_num(getattr(p, "projected_total_points", 0.0)),
            avg_points=_num(getattr(p, "avg_points", 0.0)),
            projected_avg_points=_num(getattr(p, "projected_avg_points", 0.0)),
            percent_owned=_num(getattr(p, "percent_owned", 0.0)),
            percent_started=_num(getattr(p, "percent_started", 0.0)),
            position_rank=getattr(p, "posRank", 0) or 0,
            eligible_slots=list(getattr(p, "eligibleSlots", []) or []),
            acquisition_type=_text_or_none(getattr(p, "acquisitionType", None)),
        )

    def fetch_free_agents(self, size: int = 100,
                          position: Optional[str] = None) -> list[Player]:
        agents = self._league.free_agents(size=size, position=position)
        return [self._to_player(p, team_name=None) for p in agents]

    # --- activity -----------------------------------------------------------

    def fetch_recent_activity(self, size: int = 25) -> list[Activity]:
        rows: list[Activity] = []
        for activity in self._league.recent_activity(size=size):
            when = _epoch_millis_to_utc(getattr(activity, "date", 0))
            for action in getattr(activity, "actions", []) or []:
                team, verb, player, bid = _unpack_action(action)
                rows.append(Activity(
                    timestamp=when,
                    team_name=str(team.team_name) if team else None,
                    action=verb,
                    player_name=_player_label(player),
                    bid_amount=int(bid or 0),
                ))
        return rows

    # --- snapshot -----------------------------------------------------------

    def build_snapshot(self, free_agent_size: int = 100,
                       activity_size: int = 25) -> LeagueSnapshot:
        return LeagueSnapshot(
            taken_at=datetime.now(timezone.utc),
            league_id=getattr(self._league, "league_id", 0),
            year=getattr(self._league, "year", 0),
            current_week=getattr(self._league, "current_week", 0),
            teams=self.fetch_teams(),
            free_agents=self.fetch_free_agents(size=free_agent_size),
            activity=self.fetch_recent_activity(size=activity_size),
        )


def _unpack_action(action: Any):
    """espn_api emits 4-tuples now and 3-tuples in older releases."""
    if len(action) >= 4:
        return action[0], action[1], action[2], action[3]
    team, verb, player = action[0], action[1], action[2]
    return team, verb, player, 0


def _player_label(player: Any) -> str:
    name = getattr(player, "name", None)
    return str(name) if name else str(player)


def _owner_names(owners: list[Any]) -> list[str]:
    names = []
    for owner in owners:
        if isinstance(owner, dict):
            full = " ".join(filter(None, [owner.get("firstName"),
                                          owner.get("lastName")])).strip()
            names.append(full or owner.get("displayName") or "Unknown")
        else:
            names.append(str(owner))
    return names


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _text_or_none(value: Any) -> Optional[str]:
    """Normalize a scalar string field coming out of espn_api.

    The library's `json_parsing` helper returns an empty list for any field
    that is absent from the underlying JSON, so an uninjured player's
    `injuryStatus` and a free agent's `acquisitionType` arrive as `[]` rather
    than None. Left alone, those lists blow up the SQLite insert. Anything that
    is not a plain, non-empty scalar becomes None.
    """
    if value is None or isinstance(value, (list, tuple, dict, set)):
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _epoch_millis_to_utc(millis: Any) -> datetime:
    try:
        return datetime.fromtimestamp(float(millis) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now(timezone.utc)
