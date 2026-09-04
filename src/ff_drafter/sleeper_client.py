"""Client for Sleeper's free, keyless public API (https://docs.sleeper.com).

Three things are pulled:
  * the full NFL player dump, for injury designations. It is ~14MB, and
    Sleeper explicitly asks callers to fetch it at most once per day, so it is
    cached on disk with a 24h TTL.
  * the trending add/drop endpoints, which give a genuine cross-platform
    waiver signal. These are small and always fetched fresh.
  * season and weekly projections (points in std / half-PPR / PPR), a genuine
    second opinion to triangulate against ESPN's own numbers. Cached with a
    shorter TTL since they move through the week.

The projections endpoint sits at the API root, not under /v1.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

BASE_URL = "https://api.sleeper.app/v1"
ROOT_URL = "https://api.sleeper.app"
PLAYER_CACHE_FILENAME = "sleeper_players.json"
PLAYER_CACHE_TTL_SECONDS = 24 * 60 * 60
PROJECTION_CACHE_TTL_SECONDS = 6 * 60 * 60
TRENDING_TYPES = ("add", "drop")
REQUEST_TIMEOUT_SECONDS = 60

# Sleeper's per-format scoring keys, mapped to our short format names.
_POINTS_KEYS = {"ppr": "pts_ppr", "half": "pts_half_ppr", "std": "pts_std"}


class SleeperClient:
    def __init__(self, cache_dir: Path, session: Any = None,
                 ttl_seconds: int = PLAYER_CACHE_TTL_SECONDS):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self._session = session
        self._memo: Optional[dict[str, Any]] = None
        self._memo_at: float = 0.0

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    @property
    def cache_path(self) -> Path:
        return self.cache_dir / PLAYER_CACHE_FILENAME

    # --- player dump --------------------------------------------------------

    def fetch_players(self) -> dict[str, Any]:
        if self._memo is not None and not self._memo_is_stale():
            return self._memo
        cached = self._read_cache()
        if cached is not None:
            self._remember(cached)
            return cached

        response = self.session.get(f"{BASE_URL}/players/nfl",
                                    timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        players = response.json()
        self._write_cache(players)
        self._remember(players)
        return players

    def _remember(self, players: dict[str, Any]) -> None:
        self._memo = players
        self._memo_at = time.time()

    def _memo_is_stale(self) -> bool:
        """Age the in-memory copy by the cache file it mirrors.

        The file's mtime is re-read on every call so the two can never
        disagree: expiring the cache on disk expires the memo with it. Only
        when there is no cache file (a failed write) does the memo fall back
        to ageing itself.
        """
        try:
            return self._is_stale(self.cache_path.stat().st_mtime)
        except OSError:
            return self._is_stale(self._memo_at)

    def _is_stale(self, when: float) -> bool:
        return (time.time() - when) > self.ttl_seconds

    def _read_cache(self) -> Optional[dict[str, Any]]:
        path = self.cache_path
        if not path.exists():
            return None
        if self._is_stale(path.stat().st_mtime):
            return None
        try:
            with open(path) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            # A truncated or corrupt cache should never block a sync.
            return None

    def _write_cache(self, players: dict[str, Any]) -> None:
        self._write_cache_file(self.cache_path, players)

    def _read_cache_file(self, path: Path, ttl: int) -> Optional[Any]:
        if not path.exists() or (time.time() - path.stat().st_mtime) > ttl:
            return None
        try:
            with open(path) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache_file(self, path: Path, data: Any) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w") as fh:
                json.dump(data, fh)
            tmp.replace(path)
        except OSError:
            # Caching is an optimisation, not a requirement.
            tmp.unlink(missing_ok=True)

    # --- projections --------------------------------------------------------

    def fetch_projections(self, season: int,
                          week: Optional[int] = None) -> dict[str, dict]:
        """Season (week=None) or weekly projected points, keyed by Sleeper id.

        Each value carries all three scoring formats — {"ppr", "half", "std"}
        — so the caller picks the one matching the league. A player missing a
        format still has the key, set to None, so consumers never KeyError.
        """
        suffix = f"{season}" if week is None else f"{season}_w{week}"
        cache_path = self.cache_dir / f"sleeper_proj_{suffix}.json"
        cached = self._read_cache_file(cache_path, PROJECTION_CACHE_TTL_SECONDS)
        if cached is not None:
            return cached

        url = f"{ROOT_URL}/projections/nfl/{season}"
        if week is not None:
            url = f"{url}/{week}"
        response = self.session.get(
            url,
            params={"season_type": "regular", "order_by": "pts_ppr"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        out: dict[str, dict] = {}
        for row in response.json():
            pid = row.get("player_id")
            if not pid:
                continue
            stats = row.get("stats") or {}
            out[str(pid)] = {fmt: stats.get(key)
                             for fmt, key in _POINTS_KEYS.items()}
        self._write_cache_file(cache_path, out)
        return out

    # --- trending -----------------------------------------------------------

    def fetch_trending(self, kind: str, lookback_hours: int = 24,
                       limit: int = 25) -> dict[str, int]:
        if kind not in TRENDING_TYPES:
            raise ValueError(
                f"trending type must be one of {TRENDING_TYPES}, got {kind!r}"
            )
        response = self.session.get(
            f"{BASE_URL}/players/nfl/trending/{kind}",
            params={"lookback_hours": lookback_hours, "limit": limit},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return {row["player_id"]: row["count"] for row in response.json()
                if row.get("player_id")}
