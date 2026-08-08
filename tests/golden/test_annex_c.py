"""
Golden test: the engine's dense Annex C lookup table
(``SimulationEngine._annex_lut``, a ``(4096, 8)`` array built from
``data/annex_c.json`` at engine.py:216-218) against the raw JSON file, and a
documented baseline for its behaviour on invalid (non-popcount-8) masks.
"""

import json
import os

import numpy as np
import pytest

from tests.golden.generators import all_thirds_masks

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="module")
def annex_raw():
    with open(os.path.join(ROOT, "data", "annex_c.json")) as f:
        return json.load(f)


def test_valid_masks_match_json_exactly(engine, annex_raw):
    """Every popcount-8 mask in the LUT must resolve to exactly the group
    indices recorded in annex_c.json — no off-by-one, no truncation."""
    valid, _ = all_thirds_masks()
    assert len(valid) == 495, f"expected C(12,8)=495 valid masks, found {len(valid)}"
    lut = annex_raw["lut"]
    checked = 0
    for mask in valid:
        key = str(mask)
        assert key in lut, f"mask {mask} (popcount 8) missing from annex_c.json"
        expected = lut[key]
        actual = engine._annex_lut[mask].tolist()
        assert actual == expected, f"mask {mask}: engine LUT {actual} != json {expected}"
        assert len(actual) == 8
        assert len(set(actual)) == 8, f"mask {mask}: duplicate group indices in {actual}"
        assert all(0 <= g < 12 for g in actual)
        checked += 1
    assert checked == 495


def test_json_has_no_extra_entries(annex_raw):
    """Every key in the JSON LUT must be a valid popcount-8 mask — otherwise
    the dense array build (engine.py:217-218) would silently accept garbage."""
    valid, _ = all_thirds_masks()
    valid_set = set(valid)
    for key in annex_raw["lut"]:
        mask = int(key)
        assert mask in valid_set, f"annex_c.json has non-popcount-8 mask {mask} ({key})"


def test_match_order_is_the_documented_eight(annex_raw):
    assert annex_raw["match_order"] == [74, 77, 79, 80, 81, 82, 85, 87]


def test_invalid_masks_are_minus_one(engine):
    """Documented current behaviour (not necessarily desired): masks that are
    not popcount-8 are untouched by the JSON load and stay at the np.full
    fill value of -1 (engine.py:216). This is a baseline for the future
    allocator rewrite — if this test starts failing, the fill/validation
    behaviour has changed and allocators.py needs to account for it."""
    _, invalid = all_thirds_masks()
    assert len(invalid) == 4096 - 495
    # Spot-check a sample (checking all 3601 is unnecessary — the fill value
    # is uniform) rather than every single one.
    rng = np.random.default_rng(1)
    sample = rng.choice(invalid, size=200, replace=False)
    for mask in sample:
        assert (engine._annex_lut[mask] == -1).all(), f"mask {mask} unexpectedly not -1"
