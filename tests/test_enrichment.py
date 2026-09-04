"""Join logic between ESPN players and Sleeper's player universe."""
import pytest

from ff_drafter.enrichment import Enricher, normalize_name
from ff_drafter.models import Player


def mk(name, espn_id, position, pro_team="FA"):
    return Player(name=name, espn_id=espn_id, position=position,
                  pro_team=pro_team, lineup_slot="BE")


@pytest.fixture
def enricher(sleeper_players, trending_add, trending_drop):
    return Enricher(sleeper_players,
                    trending_add={d["player_id"]: d["count"] for d in trending_add},
                    trending_drop={d["player_id"]: d["count"] for d in trending_drop})


# --- name normalization -----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Christian McCaffrey", "christianmccaffrey"),
    ("Ja'Marr Chase", "jamarrchase"),
    ("Amon-Ra St. Brown", "amonrastbrown"),
    ("Marvin Harrison Jr.", "marvinharrison"),
    ("Michael Pittman Jr", "michaelpittman"),
    ("Kenneth Walker III", "kennethwalker"),
    ("  Bijan   Robinson  ", "bijanrobinson"),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_normalize_name_handles_none():
    assert normalize_name(None) == ""


# --- joining ----------------------------------------------------------------

def test_matches_on_espn_id_when_available(enricher):
    p = enricher.enrich(mk("Christian McCaffrey", 3117251, "RB", "SF"))
    assert p.sleeper_id == "4034"
    assert p.match_method == "espn_id"
    assert p.injury_status == "Questionable"
    assert p.injury_body_part == "Undisclosed"


def test_espn_id_match_wins_even_if_espn_name_differs(enricher):
    # ESPN sometimes carries a different display name than Sleeper.
    p = enricher.enrich(mk("C. McCaffrey", 3117251, "RB", "SF"))
    assert p.sleeper_id == "4034"
    assert p.match_method == "espn_id"


def test_falls_back_to_name_and_position_when_no_espn_id_match(enricher):
    p = enricher.enrich(mk("Ja'Marr Chase", 999999, "WR", "CIN"))
    assert p.sleeper_id == "7564"
    assert p.match_method == "name"
    assert p.injury_status == "Questionable"


def test_name_suffix_is_ignored_when_matching(enricher):
    p = enricher.enrich(mk("Marvin Harrison Jr.", 888888, "WR", "ARI"))
    assert p.sleeper_id == "11628"


def test_duplicate_names_are_disambiguated_by_position(enricher):
    # Sleeper has both a WR and an LB named Justin Jefferson.
    wr = enricher.enrich(mk("Justin Jefferson", 777777, "WR", "MIN"))
    assert wr.sleeper_id == "6794"
    assert wr.position == "WR"


def test_unmatched_player_is_returned_with_null_enrichment(enricher):
    p = enricher.enrich(mk("Nobody McGhost", 424242, "WR", "FA"))
    assert p.sleeper_id is None
    assert p.match_method is None
    assert p.injury_status is None
    assert p.trending_add_count is None


def test_unmatched_player_does_not_raise(enricher):
    enricher.enrich(mk("", None, "WR"))  # must not blow up the sync


def test_trending_counts_are_attached(enricher):
    p = enricher.enrich(mk("Tyjae Spears", 100006, "RB", "TEN"))
    assert p.trending_add_count == 206565
    assert p.trending_drop_count is None


def test_player_can_be_trending_in_both_directions(enricher):
    p = enricher.enrich(mk("Trey Benson", 100008, "RB", "ARI"))
    assert p.trending_add_count == 83405
    assert p.trending_drop_count == 98110


def test_enrichment_does_not_mutate_the_input_player(enricher):
    original = mk("Christian McCaffrey", 3117251, "RB", "SF")
    enriched = enricher.enrich(original)
    assert original.sleeper_id is None
    assert enriched is not original


def test_enrich_all_processes_a_collection(enricher):
    players = [mk("Christian McCaffrey", 3117251, "RB", "SF"),
               mk("Nobody McGhost", 424242, "WR", "FA")]
    out = enricher.enrich_all(players)
    assert len(out) == 2
    assert out[0].sleeper_id == "4034"
    assert out[1].sleeper_id is None


def test_espn_injury_status_is_preserved_alongside_sleeper_status(enricher):
    p = mk("Christian McCaffrey", 3117251, "RB", "SF")
    p.espn_injury_status = "QUESTIONABLE"
    out = enricher.enrich(p)
    assert out.espn_injury_status == "QUESTIONABLE"
    assert out.injury_status == "Questionable"


def test_sleeper_records_without_a_name_are_skipped_safely(enricher):
    # The DEF entry in the fixture has full_name = null.
    p = enricher.enrich(mk("San Francisco 49ers D/ST", 111, "D/ST", "SF"))
    assert p.sleeper_id is None or p.position == "D/ST"


# --- projections ------------------------------------------------------------

@pytest.fixture
def enricher_with_proj(sleeper_players, proj_season, proj_week1):
    season = {r["player_id"]: {"ppr": r["stats"].get("pts_ppr"),
                               "half": r["stats"].get("pts_half_ppr"),
                               "std": r["stats"].get("pts_std")}
              for r in proj_season}
    week = {r["player_id"]: {"ppr": r["stats"].get("pts_ppr"),
                             "half": r["stats"].get("pts_half_ppr"),
                             "std": r["stats"].get("pts_std")}
            for r in proj_week1}
    return Enricher(sleeper_players, projections_season=season,
                    projections_week=week, scoring_format="ppr")


def test_projection_is_attached_in_league_scoring_format(enricher_with_proj):
    p = enricher_with_proj.enrich(mk("Christian McCaffrey", 3117251, "RB", "SF"))
    assert p.sleeper_proj_season is not None
    assert p.sleeper_proj_season > 0


def test_scoring_format_selects_the_right_points(sleeper_players, proj_season):
    season = {r["player_id"]: {"ppr": 300.0, "half": 250.0, "std": 200.0}
              for r in proj_season}
    for fmt, expected in (("ppr", 300.0), ("half", 250.0), ("std", 200.0)):
        e = Enricher(sleeper_players, projections_season=season,
                     scoring_format=fmt)
        p = e.enrich(mk("Christian McCaffrey", 3117251, "RB", "SF"))
        assert p.sleeper_proj_season == expected


def test_unmatched_player_has_no_projection(enricher_with_proj):
    p = enricher_with_proj.enrich(mk("Nobody McGhost", 424242, "WR", "FA"))
    assert p.sleeper_proj_season is None


def test_projection_absent_for_player_not_in_projection_set(sleeper_players):
    e = Enricher(sleeper_players, projections_season={}, scoring_format="ppr")
    p = e.enrich(mk("Christian McCaffrey", 3117251, "RB", "SF"))
    assert p.sleeper_id == "4034"          # still matched for injury data
    assert p.sleeper_proj_season is None   # just no projection available


def test_enricher_without_projections_still_works(enricher):
    p = enricher.enrich(mk("Christian McCaffrey", 3117251, "RB", "SF"))
    assert p.injury_status == "Questionable"
    assert p.sleeper_proj_season is None
