"""
BracketEngine: a lightweight ``.run()`` facade for single-elimination,
groups-less tournaments (Wimbledon and, later, any similar bracket-only
format) — the counterpart to ``SimulationEngine`` for formats that don't
need round-robin groups, Annex-C-style wildcards, or the legacy WC results
shape.

Deliberately much smaller than ``SimulationEngine``: it exposes exactly what
the app layer needs generically (``.run()``, ``.team_names``/``.entry_idx``/
``.entry_elos``, ``.data``) and nothing WC-specific (no ``.groups``,
``.r32_defs``, ...) — a bracket-only tournament's views don't need them (see
Task 22: Wimbledon's pages are bracket-centric, no groups/thirds/draw UI).
"""

from __future__ import annotations

from app.simulation.results import to_results
from app.simulation.run import simulate


class BracketEngine:
    def __init__(self, spec, raw_data: dict | None = None):
        self.spec = spec
        self.data = raw_data or spec.raw_data
        self.team_names = spec.entry_names   # alias so app-layer code that
        self.entry_names = spec.entry_names  # generically reads either name works
        self.entry_idx = spec.entry_idx
        self.entry_elos = spec.entry_elos

    def run(self, n: int = 10_000, actuals: dict | None = None, groups: dict | None = None) -> dict:
        actuals = actuals or {"knockout_results": {}}
        run = simulate(self.spec, actuals=actuals, n=n, groups=groups)
        return to_results(run)
