"""
Wildcard allocators: given a per-group comparison key (e.g. the 3rd-placed
entry's overall rank_key from every group), decide which groups qualify for
a cross-group wildcard and — for LUT-based allocators — which specific
wildcard slot each qualifying group's entry lands in.

Two allocators:
  - ``top_k_by_key``: the generic case. The k groups with the best key at a
    given position qualify; a qualifier's "wildcard index" is just its rank
    among the qualifiers. Sufficient for an unordered "N best runners-up"
    format.
  - ``LutBitmaskAllocator``: the FIFA Annex C case. An official table maps
    *which combination* of groups qualified to a specific permutation of
    wildcard slots — so which bracket match a 3rd-placed team lands in
    depends on the full combination of qualifying groups, not just its own
    rank. Generalizes ``SimulationEngine._annex_lut`` (engine.py:216-218,
    599-624), a dense ``(4096, 8)`` array hardcoded to 12 groups / 8
    wildcards, to any ``(n_groups, k)`` via an externally supplied table.
"""

from __future__ import annotations

import numpy as np


def top_k_by_key(key: np.ndarray, k: int) -> np.ndarray:
    """The k groups with the best ``key`` per simulation.

    Args:
        key: ``(n, n_groups)`` — the candidate entry's overall rank_key from
            each group.
        k: number of wildcard slots.

    Returns:
        ``(n, k)`` group indices, descending by key, ties broken by
        ascending group index (stable).
    """
    order = np.argsort(-key, axis=1, kind="stable")
    return order[:, :k]


class LutBitmaskAllocator:
    """A dense lookup table from "which n_groups-choose-k combination of
    groups qualified" (as a bitmask) to "which group's entry occupies each
    of the k named wildcard slots"."""

    def __init__(self, n_groups: int, k: int, match_order: list, lut: dict):
        self.n_groups = n_groups
        self.k = k
        self.match_order = list(match_order)  # slot index -> external slot id
        size = 1 << n_groups
        self._dense = np.full((size, k), -1, dtype=np.int64)
        for mask_key, group_idxs in lut.items():
            mask = int(mask_key)
            if len(group_idxs) != k:
                raise ValueError(
                    f"lut entry for mask {mask} has {len(group_idxs)} groups, expected {k}"
                )
            self._dense[mask] = group_idxs

    @classmethod
    def from_annex_c(cls, annex_c: dict, n_groups: int = 12) -> "LutBitmaskAllocator":
        return cls(n_groups=n_groups, k=len(annex_c["match_order"]),
                    match_order=annex_c["match_order"], lut=annex_c["lut"])

    def assign(self, key: np.ndarray) -> dict:
        """
        Args:
            key: ``(n, n_groups)`` — candidate entry's overall rank_key per
                group.

        Returns:
            ``{slot_id: (n,) group-index array}`` for every slot in
            ``match_order``.

        Raises:
            ValueError: if any simulation's qualifying-group combination has
                no entry in the LUT (an incomplete table — today's engine
                silently returns -1 and lets it propagate; this is stricter
                on purpose, see tests/golden/test_annex_c.py's documented
                baseline of the old behaviour).
        """
        n, n_groups = key.shape
        if n_groups != self.n_groups:
            raise ValueError(f"key has {n_groups} groups, allocator expects {self.n_groups}")

        order = np.argsort(-key, axis=1, kind="stable")
        topk = order[:, :self.k]

        bitmask = np.zeros(n, dtype=np.int64)
        for c in range(self.k):
            bitmask |= (1 << topk[:, c])

        assign_groups = self._dense[bitmask]
        if (assign_groups < 0).any():
            bad = np.where((assign_groups < 0).any(axis=1))[0]
            raise ValueError(
                f"{len(bad)} simulation(s) hit a group combination with no LUT "
                f"entry (e.g. bitmask {int(bitmask[bad[0]])}) — the table is incomplete"
            )
        return {slot_id: assign_groups[:, i] for i, slot_id in enumerate(self.match_order)}

    def possible_sources(self, slot_id) -> set[int]:
        """All group indices that can occupy ``slot_id`` across every valid
        combination in the LUT — the generalization of
        ``view_helpers._build_seed_labels``'s per-slot possibility set
        (e.g. "3rd of A/C/D/F/G/H"), computed from the allocator instead of
        re-reading the JSON files separately."""
        i = self.match_order.index(slot_id)
        valid_mask = (self._dense >= 0).all(axis=1)
        return set(int(g) for g in self._dense[valid_mask, i])
