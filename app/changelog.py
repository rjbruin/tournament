"""
Application changelog and version.

``APP_VERSION`` is the single source of truth for the running version; bump it
when cutting a release and add a matching entry to ``CHANGELOG`` (newest
first). The changelog page and the "What's New" popup both read from here.

Each entry is ``{"version", "date", "features": [...], "fixes": [...]}``.
"""

from __future__ import annotations

APP_VERSION = "1.5.1"

CHANGELOG: list[dict] = [
    {
        "version": "1.5.1",
        "date": "2026-06-20",
        "features": [
            "Teams page now shows a single Status column: active teams show advance and win odds badges; eliminated teams show a KO badge with the stage and opponent they lost to.",
            "Win odds badges are now always yellow; eliminated teams show a red badge with a cross.",
            "Bracket page shows win probability once both opponents in a fixture are confirmed.",
        ],
        "fixes": [
            "Cross symbol in eliminated badges is now visible (was a red emoji on a red background).",
        ],
    },
    {
        "version": "1.5.0",
        "date": "2026-06-20",
        "features": [
            "Team page now shows quality rating and form in the Team Info card.",
            "Bracket page shows team quality and form badges instead of win odds.",
            "Ask AI knows about live match scores, team info, and individual fixture details.",
        ],
        "fixes": [
            "Explanation texts removed from the Fixtures and Bracket pages.",
        ],
    },
    {
        "version": "1.4.8",
        "date": "2026-06-20",
        "fixes": [
            "Team page now shows fixtures in the correct chronological order.",
            "The odds chart on team pages now always ends with the current simulation results.",
        ],
    },
    {
        "version": "1.4.7",
        "date": "2026-06-20",
        "fixes": [
            "Expired or invalid invite links now show a clear error message.",
        ],
    },
    {
        "version": "1.4.6",
        "date": "2026-06-20",
        "fixes": [
            "New app icon.",
        ],
    },
    {
        "version": "1.4.4",
        "date": "2026-06-20",
        "features": [
            "What’s at Stake now highlights the outcome that matches the current live score.",
        ],
    },
    {
        "version": "1.4.3",
        "date": "2026-06-20",
        "fixes": [
            "Fixture team names now scale correctly on mobile.",
        ],
    },
    {
        "version": "1.4.0",
        "date": "2026-06-19",
        "features": [
            "New fixture card design with full-bleed flag images and larger team names.",
            "Live goal and full-time notifications appear as banners below the navigation bar.",
        ],
    },
    {
        "version": "1.3.1",
        "date": "2026-06-19",
        "features": [
            "Knockout stage: home page now shows your team’s likely path to the final.",
            "Eliminated teams are greyed out across the bracket, teams list, and fixtures.",
            "Penalty shootout scores shown as (5) 1–1 (4).",
            "Live results now update every 10 seconds.",
        ],
    },
    {
        "version": "1.3.0",
        "date": "2026-06-19",
        "features": [
            "Matchday 3 ready: simultaneous group matches shown together with shared standings and What’s at Stake.",
        ],
    },
    {
        "version": "1.2.4",
        "date": "2026-06-19",
        "features": [
            "Fixture cards now show team quality (★ rating) and form (↑↓) alongside the advance odds.",
        ],
    },
    {
        "version": "1.2.3",
        "date": "2026-06-19",
        "fixes": [
            "“A draw is enough” headlines and ✅ badges now only appear when qualification is mathematically certain.",
        ],
    },
    {
        "version": "1.2.0",
        "date": "2026-06-19",
        "features": [
            "What’s at Stake shows Win / Draw / Loss odds and a one-line headline.",
            "Group standings tiebreakers follow the official FIFA procedure.",
            "Advance badge shows Q ✓ when qualification is secured.",
            "Admin usage statistics page.",
        ],
    },
    {
        "version": "1.1.0",
        "date": "2026-06-18",
        "features": [
            "What’s at Stake qualification scenarios from matchday 2 onwards.",
            "Group standings highlight qualification places as they are secured.",
            "Odds badges now show a cup icon for tournament win and a marker for group advance.",
        ],
        "fixes": [],
    },
    {
        "version": "1.0.2",
        "date": "2026-06-18",
        "features": [
            "Draw comparison shows the real draw’s effect vs. the average across all possible draws.",
        ],
        "fixes": [],
    },
    {
        "version": "1.0.1",
        "date": "2026-06-18",
        "features": [
            "Fixtures page organised by round with a jump bar.",
        ],
        "fixes": [],
    },
    {
        "version": "1.0.0",
        "date": "2026-06-18",
        "features": [
            "Automatic live scores: updates at least once a minute during matches.",
            "Goal and card events shown on the home page and in fixture lists.",
        ],
        "fixes": [],
    },
]


def _version_tuple(v: str) -> tuple:
    """Parse a dotted version string into a comparable tuple, ignoring any
    non-numeric suffix on a component."""
    parts = []
    for p in str(v).split("."):
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def is_newer(a: str, b: str) -> bool:
    """True if version ``a`` is strictly newer than version ``b``."""
    return _version_tuple(a) > _version_tuple(b)


def entries_since(last_seen: str | None) -> list[dict]:
    """Changelog entries newer than ``last_seen`` (newest first).

    With no ``last_seen`` (a first-time visitor) return only the latest entry,
    so newcomers get a single "What's New" rather than the entire history.
    """
    if not last_seen:
        return CHANGELOG[:1]
    return [e for e in CHANGELOG if is_newer(e["version"], last_seen)]
