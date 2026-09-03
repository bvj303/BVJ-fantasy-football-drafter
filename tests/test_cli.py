"""CLI wiring — exercised against an in-process fake league, no network."""
import json

import pytest
from click.testing import CliRunner

from ff_drafter import cli as cli_module
from ff_drafter.config import Config
from ff_drafter.enrichment import Enricher
from ff_drafter.espn_client import EspnClient


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def wired(monkeypatch, tmp_path, fake_espn_league, sleeper_players,
          trending_add, trending_drop):
    """Point the CLI at fakes and a temp database."""
    cfg = Config(league_id=999, year=2025, espn_s2=None, espn_swid=None,
                 my_team_name="Team Bologna",
                 db_path=tmp_path / "ff.db",
                 export_path=tmp_path / "latest.json",
                 cache_dir=tmp_path / "cache")
    monkeypatch.setattr(cli_module.Config, "from_env",
                        classmethod(lambda cls, **kw: cfg))
    monkeypatch.setattr(cli_module, "build_espn_client",
                        lambda c: EspnClient(fake_espn_league,
                                             my_team_name=c.my_team_name))

    class FakeSleeper:
        def __init__(self, *a, **kw):
            pass

        def fetch_players(self):
            return sleeper_players

        def fetch_trending(self, kind, lookback_hours=24, limit=25):
            data = trending_add if kind == "add" else trending_drop
            return {d["player_id"]: d["count"] for d in data}

    monkeypatch.setattr(cli_module, "SleeperClient", FakeSleeper)
    return cfg


def test_sync_writes_a_snapshot_and_reports(runner, wired):
    res = runner.invoke(cli_module.cli, ["sync"])
    assert res.exit_code == 0, res.output
    assert wired.db_path.exists()
    assert "first snapshot" in res.output.lower()


def test_second_sync_reports_changes_section(runner, wired):
    runner.invoke(cli_module.cli, ["sync"])
    res = runner.invoke(cli_module.cli, ["sync"])
    assert res.exit_code == 0, res.output
    assert "changes since last sync" in res.output.lower()


def test_roster_defaults_to_my_team(runner, wired):
    runner.invoke(cli_module.cli, ["sync"])
    res = runner.invoke(cli_module.cli, ["roster"])
    assert res.exit_code == 0, res.output
    assert "Team Bologna" in res.output
    assert "Christian McCaffrey" in res.output


def test_roster_accepts_a_team_flag(runner, wired):
    runner.invoke(cli_module.cli, ["sync"])
    res = runner.invoke(cli_module.cli, ["roster", "--team", "Gridiron Goblins"])
    assert res.exit_code == 0, res.output
    assert "Bijan Robinson" in res.output
    assert "Christian McCaffrey" not in res.output


def test_roster_with_unknown_team_fails_helpfully(runner, wired):
    runner.invoke(cli_module.cli, ["sync"])
    res = runner.invoke(cli_module.cli, ["roster", "--team", "Nope"])
    assert res.exit_code != 0
    assert "Gridiron Goblins" in res.output


def test_commands_require_a_sync_first(runner, wired):
    res = runner.invoke(cli_module.cli, ["roster"])
    assert res.exit_code != 0
    assert "ffdraft sync" in res.output


def test_league_prints_standings_and_every_roster(runner, wired):
    runner.invoke(cli_module.cli, ["sync"])
    res = runner.invoke(cli_module.cli, ["league"])
    assert res.exit_code == 0, res.output
    assert "Team Bologna" in res.output and "Gridiron Goblins" in res.output
    assert "Bijan Robinson" in res.output


def test_export_writes_the_analysis_brief(runner, wired):
    runner.invoke(cli_module.cli, ["sync"])
    res = runner.invoke(cli_module.cli, ["export"])
    assert res.exit_code == 0, res.output
    data = json.loads(wired.export_path.read_text())
    assert data["my_team"]["name"] == "Team Bologna"
    assert {t["name"] for t in data["teams"]} == {"Team Bologna",
                                                  "Gridiron Goblins"}
    assert any(p["name"] == "Tyjae Spears" for p in data["free_agents"])
    assert data["current_week"] == 3


def test_export_includes_enrichment_for_the_analysis_commands(runner, wired):
    runner.invoke(cli_module.cli, ["sync"])
    runner.invoke(cli_module.cli, ["export"])
    data = json.loads(wired.export_path.read_text())
    cmc = [p for p in data["my_team"]["roster"]
           if p["name"] == "Christian McCaffrey"][0]
    assert cmc["injury_status"] == "Questionable"
    spears = [p for p in data["free_agents"]
              if p["name"] == "Tyjae Spears"][0]
    assert spears["trending_add_count"] == 206565


def test_export_never_contains_credentials(runner, wired, monkeypatch):
    runner.invoke(cli_module.cli, ["sync"])
    runner.invoke(cli_module.cli, ["export"])
    text = wired.export_path.read_text().lower()
    assert "espn_s2" not in text and "swid" not in text
