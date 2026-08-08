"""
Generic row-wise ranking primitive, replacing the hand-packed int64 keys in
``app.simulation.engine._rank_group_with_h2h`` (engine.py:60-64, 143-157).

That packing is only valid for a 4-team group — the field widths in its
"scale verification" comment are hardcoded to at most 3 matches per team
(9 points, 27 goals). ``rank_rows`` instead uses ``np.lexsort`` directly over
a stack of per-criterion arrays, so it works for any group size or number of
criteria with no overflow proof required, and is verified byte-for-byte
equivalent to the current single-criterion argsort in
tests/golden/test_keys.py.
"""

from __future__ import annotations

import numpy as np


def rank_rows(criteria: list[tuple[np.ndarray, bool]]) -> np.ndarray:
    """Independently rank ``m`` entries within each of ``n`` rows by a
    sequence of criteria.

    Args:
        criteria: ordered list of ``(array, descending)`` pairs, MOST
            significant criterion first. Each array has shape ``(n, m)``.
            ``descending=True`` ranks higher values first.

    Returns:
        ``order``: ``(n, m)`` int array — the column (entry) index at each
        rank position, best to worst. Ties are broken by ascending original
        column index (matches ``np.argsort(..., kind="stable")`` applied to
        a single descending key — i.e. "first-declared wins ties").

    Raises:
        ValueError: if ``criteria`` is empty or the arrays' shapes disagree.
    """
    if not criteria:
        raise ValueError("rank_rows requires at least one criterion")
    n, m = criteria[0][0].shape
    for arr, _ in criteria:
        if arr.shape != (n, m):
            raise ValueError(f"criterion shape {arr.shape} != expected {(n, m)}")

    # np.lexsort's primary key is the LAST array in the sequence, so the
    # most-significant criterion (criteria[0]) must end up last. The
    # least-significant key of all is the original column index, ascending
    # — the declaration-order tiebreak for anything left fully tied.
    idx_tiebreak = np.broadcast_to(np.arange(m), (n, m))
    keys = [idx_tiebreak]
    for arr, descending in reversed(criteria):
        keys.append(-arr if descending else arr)

    return np.lexsort(keys, axis=1)


def pack_key(fields: list[tuple[np.ndarray, int, int]]) -> np.ndarray:
    """Pack several bounded integer fields into one int64 sort key, most
    significant field first.

    Args:
        fields: ordered list of ``(array, offset, max_abs_value)`` — most
            significant first. ``offset`` is added before packing (use it to
            make signed fields like goal difference non-negative).
            ``max_abs_value`` is the maximum value the *offset* field can
            take (i.e. ``max(array + offset)``); used only to size the
            multiplier for the next-less-significant field, so a runtime
            assertion can catch a misdeclared bound instead of silently
            overflowing into the wrong field.

    Returns:
        ``np.int64`` array, same shape as the input fields.

    Raises:
        AssertionError: if a declared ``max_abs_value`` is smaller than the
            actual maximum observed in ``array + offset`` (would silently
            corrupt a more-significant field).
    """
    multiplier = 1
    packed = np.zeros(fields[0][0].shape, dtype=np.int64)
    # Build from least to most significant so each field's multiplier is
    # exactly "product of all less-significant fields' ranges".
    for arr, offset, max_abs_value in reversed(fields):
        shifted = (arr.astype(np.int64) + offset)
        actual_max = int(shifted.max()) if shifted.size else 0
        if actual_max > max_abs_value:
            raise AssertionError(
                f"pack_key: declared max_abs_value={max_abs_value} but observed "
                f"{actual_max} — field would overflow into the next one"
            )
        packed += shifted * multiplier
        multiplier *= (max_abs_value + 1)
    return packed
