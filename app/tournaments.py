"""
Tournament registry: enumerates configured tournament instances from
config/instances/*.yaml and builds a SimulationEngine + display metadata for
each. This is the seam multi-tournament routing/caching/theming hang off of.

Scope note: for now this still constructs one `SimulationEngine` per
instance exactly as app/__init__.py did for the single WC2026 case before
Stage 2 — the registry's job is enumeration and metadata, not a new
simulation-construction path. A YAML-declarative bracket template (so a new
football-format tournament needs no Python) is Stage 3's concern, once
Wimbledon's very different format (no groups, no Annex C) proves out what a
genuinely reusable template needs to express.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import yaml

from app.simulation.engine import SimulationEngine

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")


def _resolve_path(rel_path: str) -> str:
    return os.path.join(ROOT_DIR, rel_path)


@dataclass
class TournamentTheme:
    palette: str = "default"
    primary_color: str = "#0a3b2a"
    bright_color: str = "#00843d"
    gold_color: str = "#ffc72c"
    gold_deep_color: str = "#e6a800"
    pink_color: str = "#ff3b6e"
    blue_color: str = "#0b3954"
    bg_color: str = "#f4f7f4"
    logo: str | None = None
    landing_template: str | None = None


@dataclass
class TournamentInstance:
    id: str
    slug: str
    name: str
    short_name: str
    template: str
    sport: str
    year: int
    host_countries: list[str]
    theme: TournamentTheme
    engine: object  # SimulationEngine (WC) or BracketEngine (Wimbledon) — both expose .run()
    data_paths: dict[str, str]
    defaults: dict = field(default_factory=dict)
    results_compat: dict = field(default_factory=dict)


_REQUIRED_KEYS = ("id", "slug", "name", "template", "sport", "year", "data")

# Per-template required `data:` keys and the function that builds this
# instance's engine + resolved data_paths from the config. Adding a new
# groups-less bracket format (a second BracketEngine user) means adding one
# entry here, not touching the dispatch logic itself.
_DATA_KEYS_BY_TEMPLATE = {
    "fifa_world_cup": ("tournament_data", "actuals", "scenarios_dir", "retrospective"),
    "wimbledon": ("entries", "positions", "actuals", "scenarios_dir", "retrospective"),
}


def _build_wc_engine(data_cfg: dict) -> tuple:
    tournament_data_path = _resolve_path(data_cfg["tournament_data"])
    with open(tournament_data_path) as f:
        tournament_data = json.load(f)
    engine = SimulationEngine(tournament_data)
    data_paths = {
        "tournament_data": tournament_data_path,
        "annex_c": _resolve_path(data_cfg["annex_c"]) if "annex_c" in data_cfg else None,
    }
    return engine, data_paths


def _build_wimbledon_engine(data_cfg: dict) -> tuple:
    from app.simulation.bracket_engine import BracketEngine
    from app.simulation.spec import from_wimbledon_json

    entries_path = _resolve_path(data_cfg["entries"])
    positions_path = _resolve_path(data_cfg["positions"])
    with open(entries_path) as f:
        entries = json.load(f)
    with open(positions_path) as f:
        positions = json.load(f)
    spec = from_wimbledon_json(
        entries, positions,
        elo_field=data_cfg.get("elo_field", "elo_grass"),
        sets_to_win=data_cfg.get("sets_to_win", 3),
    )
    engine = BracketEngine(spec)
    data_paths = {"entries": entries_path, "positions": positions_path}
    if data_cfg.get("matches"):
        data_paths["matches"] = _resolve_path(data_cfg["matches"])
    return engine, data_paths


_ENGINE_BUILDERS = {
    "fifa_world_cup": _build_wc_engine,
    "wimbledon": _build_wimbledon_engine,
}


def _load_instance(config_path: str) -> TournamentInstance:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"{config_path}: missing required key(s) {missing}")
    template = cfg["template"]
    if template not in _ENGINE_BUILDERS:
        raise ValueError(f"{config_path}: unknown template {template!r}; "
                          f"known: {sorted(_ENGINE_BUILDERS)}")
    data_cfg = cfg["data"]
    required_data_keys = _DATA_KEYS_BY_TEMPLATE[template]
    missing_data = [k for k in required_data_keys if k not in data_cfg]
    if missing_data:
        raise ValueError(f"{config_path}: data section missing key(s) {missing_data}")

    engine, format_data_paths = _ENGINE_BUILDERS[template](data_cfg)

    theme_cfg = cfg.get("theme", {}) or {}
    theme = TournamentTheme(
        palette=theme_cfg.get("palette", cfg["id"]),
        primary_color=theme_cfg.get("primary_color", "#0a3b2a"),
        bright_color=theme_cfg.get("bright_color", "#00843d"),
        gold_color=theme_cfg.get("gold_color", "#ffc72c"),
        gold_deep_color=theme_cfg.get("gold_deep_color", "#e6a800"),
        pink_color=theme_cfg.get("pink_color", "#ff3b6e"),
        blue_color=theme_cfg.get("blue_color", "#0b3954"),
        bg_color=theme_cfg.get("bg_color", "#f4f7f4"),
        logo=theme_cfg.get("logo"),
        landing_template=theme_cfg.get("landing"),
    )

    data_paths = {
        **format_data_paths,
        "actuals": _resolve_path(data_cfg["actuals"]),
        "scenarios_dir": _resolve_path(data_cfg["scenarios_dir"]),
        "retrospective": _resolve_path(data_cfg["retrospective"]),
    }

    return TournamentInstance(
        id=cfg["id"], slug=cfg["slug"], name=cfg["name"],
        short_name=cfg.get("short_name") or cfg["name"], template=cfg["template"],
        sport=cfg["sport"], year=cfg["year"], host_countries=cfg.get("host_countries", []),
        theme=theme, engine=engine, data_paths=data_paths,
        defaults=cfg.get("defaults", {}) or {},
        results_compat=cfg.get("results_compat", {}) or {},
    )


class TournamentRegistry:
    def __init__(self, instances: list[TournamentInstance]):
        self._by_slug = {inst.slug: inst for inst in instances}
        self._by_id = {inst.id: inst for inst in instances}
        self._order = [inst.slug for inst in instances]

    def get(self, slug: str) -> TournamentInstance | None:
        return self._by_slug.get(slug)

    def get_by_id(self, tid: str) -> TournamentInstance | None:
        return self._by_id.get(tid)

    def default_slug(self) -> str:
        return self._order[0]

    def default_id(self) -> str:
        return self._by_slug[self._order[0]].id

    def list(self) -> list[TournamentInstance]:
        return [self._by_slug[slug] for slug in self._order]

    def slugs(self) -> list[str]:
        return list(self._order)


def load_registry(config_dir: str = CONFIG_DIR) -> TournamentRegistry:
    instances_dir = os.path.join(config_dir, "instances")
    instances = []
    for fname in sorted(os.listdir(instances_dir)):
        if not fname.endswith(".yaml"):
            continue
        instances.append(_load_instance(os.path.join(instances_dir, fname)))
    if not instances:
        raise ValueError(f"no tournament instances found in {instances_dir}")
    return TournamentRegistry(instances)
