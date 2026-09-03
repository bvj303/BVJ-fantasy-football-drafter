"""Configuration, loaded from the environment / a gitignored .env file.

Credential values (`espn_s2`, `SWID`) are held in memory only. They are never
logged, never written to the database, and never included in an export.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


DEFAULT_DB_PATH = Path("data/league.db")
DEFAULT_EXPORT_PATH = Path("data/latest.json")
DEFAULT_CACHE_DIR = Path("data/cache")


@dataclass
class Config:
    league_id: int
    year: int
    espn_s2: Optional[str] = field(default=None, repr=False)
    espn_swid: Optional[str] = field(default=None, repr=False)
    my_team_name: Optional[str] = None
    db_path: Path = DEFAULT_DB_PATH
    export_path: Path = DEFAULT_EXPORT_PATH
    cache_dir: Path = DEFAULT_CACHE_DIR

    @property
    def is_private(self) -> bool:
        return bool(self.espn_s2 and self.espn_swid)

    def __repr__(self) -> str:  # pragma: no cover - exercised via tests
        creds = "***set***" if self.is_private else "***unset***"
        return (f"Config(league_id={self.league_id}, year={self.year}, "
                f"my_team_name={self.my_team_name!r}, credentials={creds})")

    __str__ = __repr__

    @classmethod
    def from_env(cls, load_dotenv_file: bool = True) -> "Config":
        if load_dotenv_file:
            load_dotenv()

        league_id = _require("ESPN_LEAGUE_ID")
        try:
            league_id = int(league_id)
        except ValueError:
            raise ConfigError(
                f"ESPN_LEAGUE_ID must be a number, got {league_id!r}. "
                "It is the leagueId in your league's espn.com URL."
            ) from None

        year = _require("ESPN_YEAR")
        try:
            year = int(year)
        except ValueError:
            raise ConfigError(f"ESPN_YEAR must be a year, got {year!r}.") from None

        s2 = _clean(os.environ.get("ESPN_S2"))
        swid = _clean(os.environ.get("ESPN_SWID"))
        if s2 and not swid:
            raise ConfigError("ESPN_S2 is set but ESPN_SWID is not — private "
                              "leagues need both cookies. See .env.example.")
        if swid and not s2:
            raise ConfigError("ESPN_SWID is set but ESPN_S2 is not — private "
                              "leagues need both cookies. See .env.example.")
        if swid and not swid.startswith("{"):
            swid = "{" + swid.strip("{}") + "}"

        return cls(
            league_id=league_id,
            year=year,
            espn_s2=s2,
            espn_swid=swid,
            my_team_name=_clean(os.environ.get("ESPN_TEAM_NAME")),
            db_path=Path(os.environ.get("FFDRAFT_DB_PATH", DEFAULT_DB_PATH)),
            export_path=Path(os.environ.get("FFDRAFT_EXPORT_PATH",
                                            DEFAULT_EXPORT_PATH)),
            cache_dir=Path(os.environ.get("FFDRAFT_CACHE_DIR",
                                          DEFAULT_CACHE_DIR)),
        )


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _require(key: str) -> str:
    value = _clean(os.environ.get(key))
    if not value:
        raise ConfigError(
            f"{key} is not set. Copy .env.example to .env and fill it in."
        )
    return value
