"""
Application changelog and version.

``APP_VERSION`` is the single source of truth for the running version; bump it
when cutting a release and add a matching entry to ``CHANGELOG`` (newest
first). The changelog page and the "What's New" popup both read from here.

Each entry is ``{"version", "date", "features": [...], "fixes": [...]}``.
"""

from __future__ import annotations

APP_VERSION = "1.2.0"

CHANGELOG: list[dict] = [
    {
        "version": "1.2.0",
        "date": "2026-06-19",
        "features": [
            "Qualification scenarios now show per-outcome advancement odds "
            "(Win / Draw / Loss) and a one-line headline, replacing the verbose "
            "decision tree. On the final matchday, the full scenario tree is "
            "still available in an expandable section.",
            "Group standings tiebreakers now follow the official FIFA procedure: "
            "head-to-head points, then head-to-head goal difference, then "
            "head-to-head goals scored — before falling back to overall goal "
            "difference and goals scored.",
            "The advance odds badge in the standings and fixture display shows a "
            "green Q ✓ when qualification is mathematically secured, and "
            ">99.9 % when it rounds to 100 % but is not yet certain.",
            "Admin usage statistics page: page views, unique visitors, hourly "
            "traffic chart, and top pages/users.",
            "Admin-only button on the live match card to immediately fetch fresh "
            "results from the data feed.",
        ],
        "fixes": [
            "The separate grey Q ✓ badge after team names in the standings "
            "has been removed — the advance column badge covers that information.",
        ],
    },
    {
        "version": "1.1.0",
        "date": "2026-06-18",
        "features": [
            "Qualification scenarios on the home page from matchday 2 onwards: "
            "for the featured match, see what each team needs to reach the "
            "knockouts — or a note when nothing can be settled in that match yet.",
            "New changelog page (linked in the footer) and this “What’s New” "
            "popup, which highlights what changed since your last visit.",
            "Group standings now highlight qualification places — subtly while a "
            "team merely occupies a spot, and clearly once first place, second "
            "place, or a knockout berth is mathematically secured.",
            "Odds badges now carry an icon for the type of odds: a cup for "
            "winning the tournament and a marker for advancing from the group.",
        ],
        "fixes": [],
    },
    {
        "version": "1.0.2",
        "date": "2026-06-18",
        "features": [
            "The draw comparison now isolates the draw’s own effect, comparing "
            "the real draw before any matches are played against the average "
            "over possible draws.",
        ],
        "fixes": [
            "The live status badge no longer shows a stray apostrophe when the "
            "data feed doesn’t provide an elapsed minute.",
        ],
    },
    {
        "version": "1.0.1",
        "date": "2026-06-18",
        "features": [
            "The fixtures page is now organised into sections by round — the "
            "three group matchdays, then each knockout round — with a navigation "
            "bar to jump between them.",
        ],
        "fixes": [],
    },
    {
        "version": "1.0.0",
        "date": "2026-06-18",
        "features": [
            "Automatic live results: while a match is being played, the "
            "scoreline updates at least once a minute and stops when it ends.",
            "Goal and card events are shown on the home page and, collapsibly, "
            "in the fixtures and group lists.",
            "Visitors without an account now see fixture times in Amsterdam "
            "local time by default.",
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
