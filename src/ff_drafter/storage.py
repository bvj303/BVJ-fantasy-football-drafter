"""SQLite persistence.

Every sync writes a new, complete snapshot rather than overwriting the last
one, so a player's trajectory over the season — injury designations changing,
ownership climbing, moving between rosters — is queryable after the fact.
Credentials are never written here; only league data is.

All timestamps are stored as UTC ISO-8601 strings and returned as tz-aware
UTC datetimes.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import (Activity, InjuryChange, LeagueSnapshot, Player,
                     PlayerHistoryEntry, SnapshotDiff, Team)

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at       TEXT    NOT NULL,
    league_id      INTEGER NOT NULL,
    year           INTEGER NOT NULL,
    current_week   INTEGER NOT NULL,
    scoring_format TEXT,
    lineup_slots   TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id    INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    team_id        INTEGER NOT NULL,
    name           TEXT    NOT NULL,
    abbrev         TEXT,
    wins           INTEGER, losses INTEGER, ties INTEGER,
    points_for     REAL,    points_against REAL,
    standing       INTEGER,
    owners         TEXT,
    is_mine        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS snapshot_players (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id            INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    team_name              TEXT,
    name                   TEXT    NOT NULL,
    espn_id                INTEGER,
    sleeper_id             TEXT,
    match_method           TEXT,
    position               TEXT,
    pro_team               TEXT,
    lineup_slot            TEXT,
    espn_injury_status     TEXT,
    injured                INTEGER,
    injury_status          TEXT,
    injury_body_part       TEXT,
    injury_notes           TEXT,
    practice_participation TEXT,
    depth_chart_order      INTEGER,
    total_points           REAL,
    projected_total_points REAL,
    avg_points             REAL,
    projected_avg_points   REAL,
    percent_owned          REAL,
    percent_started        REAL,
    position_rank          INTEGER,
    eligible_slots         TEXT,
    acquisition_type       TEXT,
    trending_add_count     INTEGER,
    trending_drop_count    INTEGER,
    sleeper_proj_season    REAL,
    sleeper_proj_week      REAL
);

CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    timestamp   TEXT NOT NULL,
    team_name   TEXT,
    action      TEXT,
    player_name TEXT,
    bid_amount  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_players_snapshot ON snapshot_players(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_players_espn_id  ON snapshot_players(espn_id);
CREATE INDEX IF NOT EXISTS idx_players_name     ON snapshot_players(name);
CREATE INDEX IF NOT EXISTS idx_teams_snapshot   ON teams(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_taken  ON snapshots(taken_at);
"""

_PLAYER_COLUMNS = (
    "team_name", "name", "espn_id", "sleeper_id", "match_method", "position",
    "pro_team", "lineup_slot", "espn_injury_status", "injured",
    "injury_status", "injury_body_part", "injury_notes",
    "practice_participation", "depth_chart_order", "total_points",
    "projected_total_points", "avg_points", "projected_avg_points",
    "percent_owned", "percent_started", "position_rank", "eligible_slots",
    "acquisition_type", "trending_add_count", "trending_drop_count",
    "sleeper_proj_season", "sleeper_proj_week",
)

# Columns added after the initial schema. Applied idempotently on open so a
# database created by an earlier version gains them without a manual rebuild.
_MIGRATIONS = {
    "snapshots": [("scoring_format", "TEXT"), ("lineup_slots", "TEXT")],
    "snapshot_players": [("sleeper_proj_season", "REAL"),
                         ("sleeper_proj_week", "REAL")],
}


class Storage:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        for table, columns in _MIGRATIONS.items():
            existing = {row["name"] for row in
                        self.conn.execute(f"PRAGMA table_info({table})")}
            for name, coltype in columns:
                if name not in existing:
                    self.conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def table_names(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return [r["name"] for r in rows]

    # --- writing ------------------------------------------------------------

    def write_snapshot(self, snapshot: LeagueSnapshot) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO snapshots (taken_at, league_id, year, current_week, "
            "scoring_format, lineup_slots) VALUES (?, ?, ?, ?, ?, ?)",
            (_to_utc_iso(snapshot.taken_at), snapshot.league_id,
             snapshot.year, snapshot.current_week, snapshot.scoring_format,
             json.dumps(snapshot.lineup_slots)),
        )
        snapshot_id = cur.lastrowid

        for team in snapshot.teams:
            cur.execute(
                "INSERT INTO teams (snapshot_id, team_id, name, abbrev, wins, "
                "losses, ties, points_for, points_against, standing, owners, "
                "is_mine) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (snapshot_id, team.team_id, team.name, team.abbrev, team.wins,
                 team.losses, team.ties, team.points_for, team.points_against,
                 team.standing, "|".join(team.owners), int(team.is_mine)),
            )
            for player in team.roster:
                self._insert_player(cur, snapshot_id, player, team.name)

        for player in snapshot.free_agents:
            self._insert_player(cur, snapshot_id, player, None)

        for act in snapshot.activity:
            cur.execute(
                "INSERT INTO activity (snapshot_id, timestamp, team_name, "
                "action, player_name, bid_amount) VALUES (?,?,?,?,?,?)",
                (snapshot_id, _to_utc_iso(act.timestamp), act.team_name,
                 act.action, act.player_name, act.bid_amount),
            )

        self.conn.commit()
        return snapshot_id

    def _insert_player(self, cur, snapshot_id: int, player: Player,
                       team_name: Optional[str]) -> None:
        values = (
            snapshot_id, team_name, player.name, player.espn_id,
            player.sleeper_id, player.match_method, player.position,
            player.pro_team, player.lineup_slot, player.espn_injury_status,
            int(player.injured), player.injury_status, player.injury_body_part,
            player.injury_notes, player.practice_participation,
            player.depth_chart_order, player.total_points,
            player.projected_total_points, player.avg_points,
            player.projected_avg_points, player.percent_owned,
            player.percent_started, player.position_rank,
            "|".join(player.eligible_slots), player.acquisition_type,
            player.trending_add_count, player.trending_drop_count,
            player.sleeper_proj_season, player.sleeper_proj_week,
        )
        placeholders = ",".join("?" * (len(_PLAYER_COLUMNS) + 1))
        cur.execute(
            f"INSERT INTO snapshot_players (snapshot_id, "
            f"{','.join(_PLAYER_COLUMNS)}) VALUES ({placeholders})",
            values,
        )

    # --- reading ------------------------------------------------------------

    def _latest_snapshot_row(self, offset: int = 0) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM snapshots ORDER BY taken_at DESC, id DESC "
            "LIMIT 1 OFFSET ?", (offset,)).fetchone()

    def latest_snapshot(self) -> Optional[LeagueSnapshot]:
        row = self._latest_snapshot_row()
        return self._load_snapshot(row) if row else None

    def _load_snapshot(self, row: sqlite3.Row) -> LeagueSnapshot:
        snapshot_id = row["id"]
        players = self.conn.execute(
            "SELECT * FROM snapshot_players WHERE snapshot_id = ?",
            (snapshot_id,)).fetchall()
        by_team: dict[Optional[str], list[Player]] = {}
        for p in players:
            by_team.setdefault(p["team_name"], []).append(_row_to_player(p))

        teams = []
        for t in self.conn.execute(
                "SELECT * FROM teams WHERE snapshot_id = ? ORDER BY standing",
                (snapshot_id,)).fetchall():
            teams.append(Team(
                team_id=t["team_id"], name=t["name"], abbrev=t["abbrev"] or "",
                roster=by_team.get(t["name"], []), wins=t["wins"],
                losses=t["losses"], ties=t["ties"], points_for=t["points_for"],
                points_against=t["points_against"], standing=t["standing"],
                owners=[o for o in (t["owners"] or "").split("|") if o],
                is_mine=bool(t["is_mine"]),
            ))

        activity = [
            Activity(timestamp=_from_utc_iso(a["timestamp"]),
                     team_name=a["team_name"], action=a["action"],
                     player_name=a["player_name"], bid_amount=a["bid_amount"])
            for a in self.conn.execute(
                "SELECT * FROM activity WHERE snapshot_id = ? "
                "ORDER BY timestamp DESC", (snapshot_id,)).fetchall()
        ]

        return LeagueSnapshot(
            taken_at=_from_utc_iso(row["taken_at"]), league_id=row["league_id"],
            year=row["year"], current_week=row["current_week"], teams=teams,
            free_agents=by_team.get(None, []), activity=activity,
            scoring_format=(row["scoring_format"] or "ppr"),
            lineup_slots=json.loads(row["lineup_slots"])
            if row["lineup_slots"] else {},
        )

    def player_history(self, espn_id: Optional[int] = None,
                       name: Optional[str] = None) -> list[PlayerHistoryEntry]:
        if espn_id is None and not name:
            raise ValueError("player_history needs either espn_id or name")

        clause, params = ("sp.espn_id = ?", [espn_id]) if espn_id is not None \
            else ("sp.name = ?", [name])
        rows = self.conn.execute(
            f"SELECT sp.*, s.taken_at FROM snapshot_players sp "
            f"JOIN snapshots s ON s.id = sp.snapshot_id "
            f"WHERE {clause} ORDER BY s.taken_at ASC, s.id ASC", params
        ).fetchall()
        return [
            PlayerHistoryEntry(
                taken_at=_from_utc_iso(r["taken_at"]), name=r["name"],
                espn_id=r["espn_id"], team_name=r["team_name"],
                lineup_slot=r["lineup_slot"] or "",
                injury_status=r["injury_status"],
                espn_injury_status=r["espn_injury_status"],
                percent_owned=r["percent_owned"] or 0.0,
                trending_add_count=r["trending_add_count"],
                trending_drop_count=r["trending_drop_count"],
                total_points=r["total_points"] or 0.0,
            ) for r in rows
        ]

    # --- diffing ------------------------------------------------------------

    def diff_latest(self) -> SnapshotDiff:
        """Compare the two most recent snapshots."""
        current_row = self._latest_snapshot_row()
        if current_row is None:
            return SnapshotDiff(is_first_snapshot=True)
        previous_row = self._latest_snapshot_row(offset=1)
        if previous_row is None:
            return SnapshotDiff(is_first_snapshot=True)

        current = self._load_snapshot(current_row)
        previous = self._load_snapshot(previous_row)

        def index(snap: LeagueSnapshot) -> dict[Any, Player]:
            out = {}
            for team in snap.teams:
                for p in team.roster:
                    out[_player_key(p)] = p
            for p in snap.free_agents:
                out[_player_key(p)] = p
            return out

        now_players, then_players = index(current), index(previous)

        injury_changes = [
            InjuryChange(name=p.name, team_name=p.team_name,
                         previous=then_players[key].injury_status,
                         current=p.injury_status)
            for key, p in now_players.items()
            if key in then_players
            and (then_players[key].injury_status or None) != (p.injury_status or None)
        ]

        then_fa = {_player_key(p) for p in previous.free_agents}
        now_fa = {_player_key(p) for p in current.free_agents}
        new_free_agents = [p for p in current.free_agents
                           if _player_key(p) not in then_fa]
        rostered_away = [p for key, p in now_players.items()
                         if key in then_fa and key not in now_fa]

        seen = {(a.timestamp, a.player_name, a.action) for a in previous.activity}
        roster_moves = [a for a in current.activity
                        if (a.timestamp, a.player_name, a.action) not in seen]

        return SnapshotDiff(
            is_first_snapshot=False,
            injury_changes=injury_changes,
            new_free_agents=new_free_agents,
            rostered_away=rostered_away,
            roster_moves=roster_moves,
        )


def _player_key(player: Player) -> Any:
    return player.espn_id if player.espn_id is not None else (
        player.name, player.position)


def _row_to_player(row: sqlite3.Row) -> Player:
    return Player(
        name=row["name"], espn_id=row["espn_id"], position=row["position"] or "",
        pro_team=row["pro_team"] or "", lineup_slot=row["lineup_slot"] or "",
        team_name=row["team_name"],
        espn_injury_status=row["espn_injury_status"],
        injured=bool(row["injured"]), total_points=row["total_points"] or 0.0,
        projected_total_points=row["projected_total_points"] or 0.0,
        avg_points=row["avg_points"] or 0.0,
        projected_avg_points=row["projected_avg_points"] or 0.0,
        percent_owned=row["percent_owned"] or 0.0,
        percent_started=row["percent_started"] or 0.0,
        position_rank=row["position_rank"] or 0,
        eligible_slots=[s for s in (row["eligible_slots"] or "").split("|") if s],
        acquisition_type=row["acquisition_type"],
        sleeper_id=row["sleeper_id"], match_method=row["match_method"],
        injury_status=row["injury_status"],
        injury_body_part=row["injury_body_part"],
        injury_notes=row["injury_notes"],
        practice_participation=row["practice_participation"],
        depth_chart_order=row["depth_chart_order"],
        trending_add_count=row["trending_add_count"],
        trending_drop_count=row["trending_drop_count"],
        sleeper_proj_season=row["sleeper_proj_season"],
        sleeper_proj_week=row["sleeper_proj_week"],
    )


def _to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _from_utc_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
