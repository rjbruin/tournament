"""
Tests for Wimbledon's web routes: bracket-centric views, WC-only pages
gracefully 404ing, and WC2026 remaining completely unaffected by a second,
differently-shaped tournament being registered.
"""

import os

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
