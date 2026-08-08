"""
Tests for Stage 2's multi-tournament routing: the /t/<slug> prefix on
tournament-scoped pages, legacy-path 301 redirects, the picker homepage,
and account-scoped pages staying at the top level.
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


def test_root_shows_picker_with_multiple_tournaments(client):
    """As of Stage 3 (Wimbledon added), the registry has >1 tournament, so
    "/" shows the picker rather than auto-redirecting through — the
    single-tournament auto-redirect case is covered separately below with
    a registry temporarily pared down to one entry."""
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert b"world-cup-2026" in resp.data or b"World Cup" in resp.data
    assert b"wimbledon-2026" in resp.data or b"Wimbledon" in resp.data


def test_root_redirects_when_only_one_tournament_registered():
    """Single-tournament case: "/" should 302 straight through rather than
    showing a picker with one option — isolated from the module-scoped
    `client` fixture since it needs a pared-down registry."""
    import app as app_module
    from app.tournaments import TournamentRegistry

    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        saved = app_module._registry
        try:
            wc_only = app_module.get_registry().get("world-cup-2026")
            app_module._registry = TournamentRegistry([wc_only])
            resp = c.get("/", follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["Location"] == "/t/world-cup-2026/"
        finally:
            app_module._registry = saved


def test_tournament_scoped_index_renders(client):
    resp = client.get("/t/world-cup-2026/")
    assert resp.status_code == 200
    assert b"WC" in resp.data


def test_unknown_slug_404s(client):
    resp = client.get("/t/does-not-exist/groups")
    assert resp.status_code == 404


@pytest.mark.parametrize("path,expected_target", [
    ("/groups", "/t/world-cup-2026/groups"),
    ("/bracket", "/t/world-cup-2026/bracket"),
    ("/teams", "/t/world-cup-2026/teams"),
    ("/team", "/t/world-cup-2026/team"),
    ("/team/Spain", "/t/world-cup-2026/team/Spain"),
    ("/group/A", "/t/world-cup-2026/group/A"),
    ("/fixtures", "/t/world-cup-2026/fixtures"),
    ("/match/103", "/t/world-cup-2026/match/103"),
    ("/results/manual", "/t/world-cup-2026/results/manual"),
    ("/draw", "/t/world-cup-2026/draw"),
    ("/scenarios/compare", "/t/world-cup-2026/scenarios/compare"),
    ("/admin/diagnostics", "/t/world-cup-2026/admin/diagnostics"),
    ("/retrospective", "/t/world-cup-2026/retrospective"),
])
def test_legacy_paths_301_to_tournament_scoped(client, path, expected_target):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 301, f"{path} -> {resp.status_code}"
    assert resp.headers["Location"] == expected_target


def test_legacy_redirect_preserves_query_string(client):
    resp = client.get("/groups?s=match-0", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["Location"] == "/t/world-cup-2026/groups?s=match-0"


@pytest.mark.parametrize("path", [
    "/manifest.json", "/changelog", "/simulation-logic", "/settings", "/onboarding",
])
def test_account_pages_stay_at_top_level(client, path):
    resp = client.get(path, follow_redirects=False)
    # Public ones 200, gated ones redirect to /login — either way NOT a
    # 301 to /t/<slug>/... (they must not have been swept into the
    # tournament-scoped blueprint).
    assert resp.status_code in (200, 302)
    if resp.status_code == 302:
        assert resp.headers["Location"].startswith("/login")


def test_settings_requires_login(client):
    resp = client.get("/settings", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login")


def test_retrospective_requires_login_after_redirect(client):
    resp = client.get("/t/world-cup-2026/retrospective", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login?next=")
    assert "world-cup-2026%2Fretrospective" in resp.headers["Location"] or \
           "world-cup-2026/retrospective" in resp.headers["Location"]


def test_public_tournament_pages_accessible_anonymously(client):
    for path in ["/t/world-cup-2026/groups", "/t/world-cup-2026/bracket",
                 "/t/world-cup-2026/fixtures", "/t/world-cup-2026/teams"]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} -> {resp.status_code}"


def test_scenario_switch_query_param_preserved_under_prefix(client):
    resp = client.get("/t/world-cup-2026/groups?s=match-0", follow_redirects=True)
    assert resp.status_code == 200
    # match-0 is the pre-tournament checkpoint scenario; its label appears
    # in the "viewing scenario" banner when the ?s= param is honoured.
    assert b"Before the first match" in resp.data


def test_manifest_json_content_type(client):
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/manifest+json")
