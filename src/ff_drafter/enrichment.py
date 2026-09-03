"""Join ESPN players to Sleeper's player universe.

Sleeper publishes an `espn_id` on some records, which is an exact, unambiguous
key — but it covers under half of fantasy-relevant players, so a normalized
name match is a necessary fallback rather than an edge case. Names collide
across positions (Sleeper lists both a WR and an LB named Justin Jefferson),
so the fallback is keyed on name *and* position, with the pro team breaking
any remaining tie.

A player who matches nothing is returned unenriched rather than dropped: a
missing injury designation must never fail a sync.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from typing import Any, Optional

from .models import Player

# Generational suffixes ESPN appends but Sleeper's search name omits.
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_NON_ALPHA = re.compile(r"[^a-z0-9 ]")


def normalize_name(name: Optional[str]) -> str:
    """Fold a display name down to a comparable key.

    "Amon-Ra St. Brown" and "Marvin Harrison Jr." become "amonrastbrown" and
    "marvinharrison" — matching the shape of Sleeper's own `search_full_name`.
    """
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(name))
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    cleaned = _NON_ALPHA.sub(" ", ascii_only.lower())
    parts = [p for p in cleaned.split() if p and p not in _SUFFIXES]
    return "".join(parts)


class Enricher:
    def __init__(self, sleeper_players: dict[str, Any],
                 trending_add: Optional[dict[str, int]] = None,
                 trending_drop: Optional[dict[str, int]] = None):
        self._players = sleeper_players or {}
        self._trending_add = trending_add or {}
        self._trending_drop = trending_drop or {}
        self._by_espn_id: dict[str, dict] = {}
        self._by_name_position: dict[tuple[str, str], list[dict]] = {}
        self._build_indexes()

    def _build_indexes(self) -> None:
        for player_id, record in self._players.items():
            if not isinstance(record, dict):
                continue
            record = dict(record, player_id=record.get("player_id", player_id))

            espn_id = record.get("espn_id")
            if espn_id is not None:
                self._by_espn_id.setdefault(str(espn_id), record)

            key = normalize_name(record.get("full_name")) or \
                (record.get("search_full_name") or "")
            if not key:
                # Team defenses carry no personal name; nothing to match on.
                continue
            position = (record.get("position") or "").upper()
            self._by_name_position.setdefault((key, position), []).append(record)

    # --- matching -----------------------------------------------------------

    def _match(self, player: Player) -> tuple[Optional[dict], Optional[str]]:
        if player.espn_id is not None:
            found = self._by_espn_id.get(str(player.espn_id))
            if found is not None:
                return found, "espn_id"

        key = normalize_name(player.name)
        if not key:
            return None, None
        position = (player.position or "").upper()
        candidates = self._by_name_position.get((key, position), [])
        if not candidates:
            return None, None
        if len(candidates) == 1:
            return candidates[0], "name"

        # Same name, same position: the pro team settles it.
        pro_team = (player.pro_team or "").upper()
        for candidate in candidates:
            if (candidate.get("team") or "").upper() == pro_team:
                return candidate, "name"
        return candidates[0], "name"

    # --- enrichment ---------------------------------------------------------

    def enrich(self, player: Player) -> Player:
        """Return a copy of `player` with Sleeper fields attached."""
        record, method = self._match(player)
        if record is None:
            return replace(player)

        sleeper_id = str(record.get("player_id"))
        return replace(
            player,
            sleeper_id=sleeper_id,
            match_method=method,
            injury_status=record.get("injury_status"),
            injury_body_part=record.get("injury_body_part"),
            injury_notes=record.get("injury_notes"),
            practice_participation=record.get("practice_participation"),
            depth_chart_order=record.get("depth_chart_order"),
            trending_add_count=self._trending_add.get(sleeper_id),
            trending_drop_count=self._trending_drop.get(sleeper_id),
        )

    def enrich_all(self, players: list[Player]) -> list[Player]:
        return [self.enrich(p) for p in players]
