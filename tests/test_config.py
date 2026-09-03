"""Config loading — must never leak or persist credential values."""
import pytest

from ff_drafter.config import Config, ConfigError


BASE = {"ESPN_LEAGUE_ID": "123456", "ESPN_YEAR": "2025"}


def test_loads_required_values(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    cfg = Config.from_env(load_dotenv_file=False)
    assert cfg.league_id == 123456
    assert cfg.year == 2025


def test_missing_league_id_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ESPN_LEAGUE_ID", raising=False)
    monkeypatch.setenv("ESPN_YEAR", "2025")
    with pytest.raises(ConfigError, match="ESPN_LEAGUE_ID"):
        Config.from_env(load_dotenv_file=False)


def test_non_numeric_league_id_is_rejected(monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", "not-a-number")
    monkeypatch.setenv("ESPN_YEAR", "2025")
    with pytest.raises(ConfigError, match="ESPN_LEAGUE_ID"):
        Config.from_env(load_dotenv_file=False)


def test_cookies_are_optional_for_public_leagues(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ESPN_S2", raising=False)
    monkeypatch.delenv("ESPN_SWID", raising=False)
    cfg = Config.from_env(load_dotenv_file=False)
    assert cfg.espn_s2 is None
    assert cfg.is_private is False


def test_both_cookies_are_required_together(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ESPN_S2", "abc")
    monkeypatch.delenv("ESPN_SWID", raising=False)
    with pytest.raises(ConfigError, match="ESPN_SWID"):
        Config.from_env(load_dotenv_file=False)


def test_swid_braces_are_added_when_missing(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ESPN_S2", "abc")
    monkeypatch.setenv("ESPN_SWID", "AAAA-BBBB")
    assert Config.from_env(load_dotenv_file=False).espn_swid == "{AAAA-BBBB}"


def test_repr_never_exposes_credentials(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ESPN_S2", "super-secret-cookie-value")
    monkeypatch.setenv("ESPN_SWID", "{SECRET-SWID}")
    cfg = Config.from_env(load_dotenv_file=False)
    for text in (repr(cfg), str(cfg)):
        assert "super-secret-cookie-value" not in text
        assert "SECRET-SWID" not in text
    assert "***" in repr(cfg)
