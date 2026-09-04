"""Sleeper client tests — parsing and caching, never live network."""
import json
import time

import pytest

from ff_drafter.sleeper_client import SleeperClient


class RecordingSession:
    """Stands in for requests.Session; serves fixtures and counts calls."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        for fragment, payload in self.routes.items():
            if fragment in url:
                return _Response(payload)
        raise AssertionError(f"unexpected request to {url}")


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


@pytest.fixture
def session(sleeper_players, trending_add, trending_drop):
    return RecordingSession({
        "/players/nfl/trending/add": trending_add,
        "/players/nfl/trending/drop": trending_drop,
        "/players/nfl": sleeper_players,
    })


@pytest.fixture
def client(tmp_path, session):
    return SleeperClient(cache_dir=tmp_path, session=session)


def test_fetch_players_returns_full_map(client, sleeper_players):
    players = client.fetch_players()
    assert len(players) == len(sleeper_players)
    assert players["4034"]["full_name"] == "Christian McCaffrey"


def test_player_dump_is_cached_to_disk(client, tmp_path):
    client.fetch_players()
    assert (tmp_path / "sleeper_players.json").exists()


def test_second_fetch_within_a_day_uses_cache(client, session):
    client.fetch_players()
    client.fetch_players()
    dump_calls = [c for c in session.calls if c[0].endswith("/players/nfl")]
    assert len(dump_calls) == 1


def test_stale_cache_is_refreshed(client, session, tmp_path):
    client.fetch_players()
    stale = time.time() - (60 * 60 * 25)
    cache = tmp_path / "sleeper_players.json"
    import os
    os.utime(cache, (stale, stale))
    client.fetch_players()
    dump_calls = [c for c in session.calls if c[0].endswith("/players/nfl")]
    assert len(dump_calls) == 2


def test_corrupt_cache_falls_back_to_network(client, session, tmp_path):
    client.fetch_players()
    (tmp_path / "sleeper_players.json").write_text("{not json")
    players = client.fetch_players()
    assert players["4034"]["full_name"] == "Christian McCaffrey"


def test_trending_adds_are_returned_as_counts_by_player_id(client):
    adds = client.fetch_trending("add")
    assert adds["9508"] == 206565
    assert adds["11628"] == 15003


def test_trending_drops_are_separate_from_adds(client):
    assert client.fetch_trending("drop")["11533"] == 44012


def test_trending_passes_lookback_and_limit_params(client, session):
    client.fetch_trending("add", lookback_hours=48, limit=10)
    url, params = [c for c in session.calls if "trending" in c[0]][-1]
    assert params["lookback_hours"] == 48
    assert params["limit"] == 10


def test_invalid_trending_type_is_rejected(client):
    with pytest.raises(ValueError):
        client.fetch_trending("sideways")


def test_trending_is_not_cached_to_disk(client, tmp_path):
    client.fetch_trending("add")
    assert not (tmp_path / "sleeper_trending_add.json").exists()


# --- projections ------------------------------------------------------------

@pytest.fixture
def proj_session(sleeper_players, trending_add, trending_drop, proj_season,
                 proj_week1):
    return RecordingSession({
        "/players/nfl/trending/add": trending_add,
        "/players/nfl/trending/drop": trending_drop,
        "/players/nfl": sleeper_players,
        "/projections/nfl/2026/1": proj_week1,
        "/projections/nfl/2026": proj_season,
    })


@pytest.fixture
def proj_client(tmp_path, proj_session):
    return SleeperClient(cache_dir=tmp_path, session=proj_session)


def test_fetch_season_projections_returns_points_by_format(proj_client):
    proj = proj_client.fetch_projections(2026)
    cmc = proj["4034"]
    assert cmc["ppr"] > 0
    assert cmc["half"] <= cmc["ppr"]
    assert cmc["std"] <= cmc["half"]


def test_fetch_weekly_projections_hits_week_endpoint(proj_client, proj_session):
    proj_client.fetch_projections(2026, week=1)
    assert any("/projections/nfl/2026/1" in c[0] for c in proj_session.calls)


def test_season_and_weekly_use_different_endpoints(proj_client, proj_session):
    proj_client.fetch_projections(2026)
    urls = [c[0] for c in proj_session.calls]
    assert any(u.endswith("/projections/nfl/2026") for u in urls)
    assert not any("/projections/nfl/2026/1" in u for u in urls)


def test_projections_are_cached_to_disk(proj_client, tmp_path):
    proj_client.fetch_projections(2026)
    assert list(tmp_path.glob("sleeper_proj*.json"))


def test_second_projection_fetch_uses_cache(proj_client, proj_session):
    proj_client.fetch_projections(2026)
    proj_client.fetch_projections(2026)
    calls = [c for c in proj_session.calls if c[0].endswith("/nfl/2026")]
    assert len(calls) == 1


def test_missing_points_field_is_none_not_crash(proj_client):
    proj = proj_client.fetch_projections(2026)
    # every returned record must carry all three keys, even if None
    assert all({"ppr", "half", "std"} <= set(v) for v in proj.values())
