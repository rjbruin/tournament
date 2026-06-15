"""Tests for the 2026 draw simulator (app/simulation/draw.py).

The draw must satisfy several hard constraints; a violated constraint would be
a real bug, so we generate many (seeded, deterministic) draws and assert that
every one of them is valid.
"""

import pytest

from app.simulation.draw import (
    GROUP_LETTERS,
    HALF_A,
    HALF_B,
    is_draw_complete,
    load_draw_pots,
    opponent_stats,
    simulate_many_draws,
)


@pytest.fixture(scope="module")
def pots_data():
    return load_draw_pots()


@pytest.fixture(scope="module")
def draws():
    # Deterministic via the seed; enough draws to exercise the constraints.
    return simulate_many_draws(40, seed=2026)


def _half(letter):
    return "A" if letter in HALF_A else "B"


def test_every_group_has_one_team_from_each_pot(pots_data, draws):
    pots = pots_data["pots"]
    pot_of = {team: i for i, pot in enumerate(pots) for team in pot}
    for draw in draws:
        assert set(draw) == set(GROUP_LETTERS)
        for letter, teams in draw.items():
            assert len(teams) == 4
            assert [pot_of[t] for t in teams] == [0, 1, 2, 3]


def test_all_48_teams_used_exactly_once(pots_data, draws):
    all_teams = {t for pot in pots_data["pots"] for t in pot}
    for draw in draws:
        placed = [t for teams in draw.values() for t in teams]
        assert len(placed) == 48
        assert set(placed) == all_teams


def test_hosts_are_seeded_to_their_groups(pots_data, draws):
    host_groups = pots_data["host_groups"]
    for draw in draws:
        for team, letter in host_groups.items():
            assert draw[letter][0] == team


def test_confederation_constraint(pots_data, draws):
    confeds = pots_data["confederations"]
    for draw in draws:
        for letter, teams in draw.items():
            counts = {}
            for t in teams:
                c = confeds.get(t)
                counts[c] = counts.get(c, 0) + 1
            for conf, count in counts.items():
                limit = 2 if conf == "UEFA" else 1
                assert count <= limit, f"{conf} appears {count}x in group {letter}"


def test_rival_pairs_in_opposite_halves(pots_data, draws):
    for draw in draws:
        letter_of = {t: letter for letter, teams in draw.items() for t in teams}
        for a, b in pots_data["rival_pairs"]:
            assert _half(letter_of[a]) != _half(letter_of[b]), \
                f"{a} and {b} ended up in the same half"


def test_halves_partition_all_groups():
    assert HALF_A | HALF_B == set(GROUP_LETTERS)
    assert HALF_A & HALF_B == set()


# ---------------------------------------------------------------------------
# is_draw_complete / opponent_stats
# ---------------------------------------------------------------------------

def test_is_draw_complete():
    assert is_draw_complete(None) is False
    assert is_draw_complete({}) is False
    full = {l: ["a", "b", "c", "d"] for l in GROUP_LETTERS}
    assert is_draw_complete(full) is True
    partial = dict(full)
    partial["A"] = ["a", "b", None, "d"]
    assert is_draw_complete(partial) is False
    short = dict(full)
    short["B"] = ["a", "b", "c"]
    assert is_draw_complete(short) is False


def test_opponent_stats_probabilities(draws):
    stats = opponent_stats(draws)
    # Every team has opponents, and each probability is in [0, 1].
    assert len(stats) == 48
    for team, opps in stats.items():
        for other, p in opps.items():
            assert 0.0 <= p <= 1.0
            assert other != team


def test_opponent_stats_is_symmetric(draws):
    stats = opponent_stats(draws)
    some_team = next(iter(stats))
    for other, p in stats[some_team].items():
        assert stats[other][some_team] == pytest.approx(p)
