"""
Tests for Wimbledon's web routes: bracket-centric views, WC-only pages
gracefully 404ing, and WC2026 remaining completely unaffected by a second,
differently-shaped tournament being registered.
"""

import os
import re

import pytest

os.environ.setdefault("DISABLE_LIVE_POLLER", "1")


@pytest.fixture(scope="module")
def client():
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_wimbledon_home_renders_with_real_champion_favored(client):
    resp = client.get("/t/wimbledon-2026/")
    assert resp.status_code == 200
    assert b"Jannik Sinner" in resp.data  # the real 2026 champion, seed 1


def test_wimbledon_bracket_renders_all_rounds(client):
    resp = client.get("/t/wimbledon-2026/bracket")
    assert resp.status_code == 200
    for label in (b"First round", b"Quarterfinals", b"Semifinals", b"Final"):
        assert label in resp.data
    assert resp.data.count(b"Jannik Sinner") >= 7  # appears once per round he's in


@pytest.mark.parametrize("path", [
    "/t/wimbledon-2026/groups",
    "/t/wimbledon-2026/teams",
    "/t/wimbledon-2026/fixtures",
    "/t/wimbledon-2026/draw",
])
def test_wc_only_pages_404_for_wimbledon(client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 404, f"{path} -> {resp.status_code}"


@pytest.mark.parametrize("path", [
    "/t/wimbledon-2026/results/manual",
    "/t/wimbledon-2026/scenarios/compare",
    "/t/wimbledon-2026/admin/diagnostics",
    "/t/wimbledon-2026/retrospective",
])
def test_wc_only_login_required_pages_redirect_before_404_for_wimbledon(client, path):
    # These routes are @login_required, so an anonymous request never reaches
    # the group-stage-format guard — it redirects to /login first. That is
    # correct, expected Flask-Login behavior, not a regression.
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login")


def test_wimbledon_nav_hides_group_stage_links(client):
    resp = client.get("/t/wimbledon-2026/")
    assert b">Groups<" not in resp.data
    assert b">Draw<" not in resp.data
    assert b">Bracket<" in resp.data


def test_wc2026_unaffected_by_second_tournament(client):
    """The core Stage 3 regression check: WC2026's own pages must render
    identically to before Wimbledon was registered."""
    resp = client.get("/t/world-cup-2026/")
    assert resp.status_code == 200
    resp = client.get("/t/world-cup-2026/groups")
    assert resp.status_code == 200
    resp = client.get("/t/world-cup-2026/bracket")
    assert resp.status_code == 200


def test_picker_lists_both_tournaments(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert b"World Cup" in resp.data or b"world-cup-2026" in resp.data
    assert b"Wimbledon" in resp.data


def test_tournament_switcher_present_with_two_tournaments(client):
    resp = client.get("/t/world-cup-2026/")
    assert b"dropdown-toggle" in resp.data
    assert b"wimbledon-2026" in resp.data


def test_header_shows_tournament_short_name_not_hardcoded_wc(client):
    resp = client.get("/t/wimbledon-2026/")
    assert b"Wimbledon 2026" in resp.data
    resp = client.get("/t/world-cup-2026/")
    assert b"WC" in resp.data
    assert b"navbar-brand" in resp.data


def test_switcher_button_does_not_leak_full_tournament_name(client):
    # The switcher button itself should be compact/icon-only -- the name
    # belongs in the navbar-brand, not duplicated onto the switcher control.
    resp = client.get("/t/world-cup-2026/").data.decode()
    switcher_start = resp.index("tournament-switcher")
    switcher_button_html = resp[switcher_start:switcher_start + 300]
    assert "FIFA World Cup 2026" not in switcher_button_html


def test_wimbledon_players_page_ranked_by_atp_rank(client):
    resp = client.get("/t/wimbledon-2026/players")
    assert resp.status_code == 200
    text = resp.data.decode()
    # Sinner is ATP rank 1 -- must appear before the next few ranked seeds.
    assert text.index("Jannik Sinner") < text.index("Alexander Zverev")
    assert b"\xf0\x9f\x8f\x86 Champion" in resp.data  # trophy emoji badge


def test_wimbledon_matches_page_groups_by_day_with_real_scores(client):
    resp = client.get("/t/wimbledon-2026/matches")
    assert resp.status_code == 200
    # Dates use the same notation as the WC bracket ("Sun 12 Jul"), not raw ISO.
    assert b"Sun 12 Jul" in resp.data  # the real final date
    assert b"2026-07-12" not in resp.data
    assert "6–7(7–9)".encode() in resp.data  # real final score, first set


@pytest.mark.parametrize("path", ["/t/world-cup-2026/players", "/t/world-cup-2026/matches"])
def test_tennis_only_pages_404_for_wc2026(client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 404, f"{path} -> {resp.status_code}"


def test_seeds_shown_inline_as_name_bracket_number(client):
    resp = client.get("/t/wimbledon-2026/bracket")
    text = resp.data.decode()
    assert "Jannik Sinner" in text
    assert '<span class="bracket-seed">[1]</span>' in text
    resp = client.get("/t/wimbledon-2026/players")
    text = resp.data.decode()
    assert "Jannik Sinner" in text and "[1]" in text
    assert '<th>Seed</th>' not in text  # folded into the Player column, not a separate column


def test_bracket_shows_inline_per_set_scores_with_tiebreak_superscript(client):
    resp = client.get("/t/wimbledon-2026/bracket")
    text = resp.data.decode()
    # Final: Sinner def. Zverev 6-7(7-9), 7-6(7-2), 6-3, 6-4 -- Sinner's own
    # first-set tiebreak points (7) must render as a <sup>, not inline text.
    assert '<span class="bracket-set-score">6<sup>7</sup></span>' in text
    assert '<span class="bracket-set-score">7<sup>9</sup></span>' in text


def test_bracket_dates_use_shared_notation_not_iso(client):
    """Dates read the same on every bracket regardless of sport: the WC
    bracket renders "Mon 29 Jun, 22:30" via the local_time filter, so a
    format with no per-match kickoff shows "Mon 29 Jun" — never raw ISO."""
    text = client.get("/t/wimbledon-2026/bracket").data.decode()
    assert "Mon 29 Jun" in text
    assert "Mon 29 Jun – Tue 30 Jun" in text  # round played over two days
    assert "2026-06-29" not in text


def test_tennis_quality_badge_shows_world_rank_not_stars(client):
    text = client.get("/t/wimbledon-2026/bracket").data.decode()
    assert 'title="World ranking at the start of the tournament">#1<' in text
    assert "★" not in text  # the Elo star tier is football's quality measure


def test_football_quality_badge_still_shows_stars(client):
    text = client.get("/t/world-cup-2026/bracket").data.decode()
    assert "★" in text
    assert 'title="World ranking at the start of the tournament"' not in text


def test_no_rank_badge_invented_for_players_without_a_published_rank(client):
    """Only 42 of the 128 entrants have a real sourced world ranking; the
    rest must render no rank pill rather than a made-up number."""
    import json

    with open("data/tournaments/wimbledon_2026/entries.json") as f:
        entries = json.load(f)
    unranked = next(e for e in entries if e.get("atp_rank") is None)
    text = client.get("/t/wimbledon-2026/players").data.decode()
    assert unranked["name"] in text
    ranks = {e["atp_rank"] for e in entries if e.get("atp_rank") is not None}
    shown = set(re.findall(r'the tournament">#(\d+)<', text))
    assert shown == {str(r) for r in ranks}


def test_tennis_form_badge_reflects_real_over_and_underperformance(client):
    """Form is computed from actual results vs Elo expectation, the same way
    it is for football — a wildcard semifinalist should read as strongly up."""
    from app import _bracket_badge_context, get_registry

    ctx = _bracket_badge_context(get_registry().get("wimbledon-2026"))
    form = ctx["team_form"]
    assert form["Arthur Fery"] > 15      # wildcard who reached the semifinals
    assert form["Ben Shelton"] < -15     # seed 4, lost in the first round


def test_completed_tennis_tournament_gets_champion_hero_and_podium(client):
    resp = client.get("/t/wimbledon-2026/")
    text = resp.data.decode()
    assert resp.status_code == 200
    assert "WIMBLEDON 2026 CHAMPION" in text.upper()
    assert "Pre-tournament win probability" in text
    assert "Jannik Sinner" in text        # champion
    assert "Alexander Zverev" in text     # runner-up on the podium
    assert "Novak Djokovic" in text       # beaten semifinalist
    assert "Most Likely Champion" not in text  # projection view is superseded


def test_wc2026_completed_front_page_unchanged(client):
    """The shared podium macros must not regress WC's own finished-tournament
    home page."""
    text = client.get("/t/world-cup-2026/").data.decode()
    assert "2026 FIFA World Cup Champion" in text
    assert "Pre-tournament win probability" in text
    assert "World Champion" in text
    assert "Spain" in text
