"""Tests for app.tournaments — the config-driven tournament registry."""

import os

import pytest

from app.tournaments import TournamentRegistry, load_registry


def test_load_registry_finds_wc2026():
    reg = load_registry()
    assert "world-cup-2026" in reg.slugs()


def test_wc2026_instance_metadata():
    reg = load_registry()
    inst = reg.get("world-cup-2026")
    assert inst.id == "wc2026"
    assert inst.name == "FIFA World Cup 2026"
    assert inst.sport == "football"
    assert inst.year == 2026
    assert inst.host_countries == ["USA", "Canada", "Mexico"]


def test_wc2026_engine_is_functional():
    reg = load_registry()
    inst = reg.get("world-cup-2026")
    assert len(inst.engine.team_names) == 48
    results = inst.engine.run(n=200)
    assert sum(results["winner_prob"].values()) == pytest.approx(1.0, abs=0.05)


def test_data_paths_resolve_to_existing_files():
    reg = load_registry()
    inst = reg.get("world-cup-2026")
    for key in ("tournament_data", "annex_c", "actuals"):
        assert os.path.exists(inst.data_paths[key]), f"{key} -> {inst.data_paths[key]}"
    assert os.path.isdir(inst.data_paths["scenarios_dir"])


def test_theme_defaults_and_overrides():
    reg = load_registry()
    inst = reg.get("world-cup-2026")
    assert inst.theme.palette == "wc2026"
    assert inst.theme.primary_color == "#0a3b2a"


def test_get_unknown_slug_returns_none():
    reg = load_registry()
    assert reg.get("nonexistent") is None


def test_default_slug_is_first_in_order():
    reg = load_registry()
    assert reg.default_slug() == "world-cup-2026"


def test_missing_required_key_raises(tmp_path):
    import textwrap

    bad_dir = tmp_path / "instances"
    bad_dir.mkdir()
    (bad_dir / "bad.yaml").write_text(textwrap.dedent("""
        id: bad
        slug: bad-slug
        # missing name/template/sport/year/data
    """))
    with pytest.raises(ValueError, match="missing required key"):
        load_registry(config_dir=str(tmp_path))


def test_empty_instances_dir_raises(tmp_path):
    (tmp_path / "instances").mkdir()
    with pytest.raises(ValueError, match="no tournament instances found"):
        load_registry(config_dir=str(tmp_path))


def test_registry_class_direct_construction():
    reg = load_registry()
    inst = reg.get("world-cup-2026")
    fresh = TournamentRegistry([inst])
    assert fresh.slugs() == ["world-cup-2026"]
    assert fresh.get_by_id("wc2026") is inst
