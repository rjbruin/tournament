"""
Application changelog and version.

``APP_VERSION`` is the single source of truth for the running version; bump it
when cutting a release and add a matching entry to ``CHANGELOG`` (newest
first). The changelog page and the "What's New" popup both read from here.

Each entry is ``{"version", "date", "features": [...], "fixes": [...]}``.
"""

from __future__ import annotations

APP_VERSION = "1.4.7"

CHANGELOG: list[dict] = [
    {
        "version": "1.4.7",
        "date": "2026-06-20",
        "fixes": [
            "Invite links that are invalid or already exhausted now show a clear "
            "error message instead of the generic 'Registration is by invite only' "
            "wall, so users know to ask the admin for a fresh link.",
        ],
    },
    {
        "version": "1.4.6",
        "date": "2026-06-20",
        "fixes": [
            "App icon replaced with a hand-crafted design: two soccer balls "
            "with a diagonal green bar. Served as an SVG favicon in modern "
            "browsers, with PNG fallbacks at 180, 192 and 512 px.",
        ],
    },
    {
        "version": "1.4.5",
        "date": "2026-06-20",
        "fixes": [
            "Fixed TemplateRuntimeError on the home page: replaced Ansible-only "
            "'combine' filter with standard Jinja2 namespace logic for the live "
            "outcome highlight introduced in v1.4.4.",
        ],
    },
    {
        "version": "1.4.4",
        "date": "2026-06-20",
        "features": [
            "What's at Stake now highlights the outcome chip that is currently "
            "in effect for a live match — e.g. if it's 1–0, the Win chip for "
            "the home team and the Loss chip for the away team are subtly "
            "outlined to show what each team's advance odds look like right now.",
        ],
        "fixes": [
            "Advance odds delta badges (▲/▼) are now slightly transparent so "
            "they read as secondary information relative to the main odds chip.",
        ],
    },
    {
        "version": "1.4.3",
        "date": "2026-06-20",
        "fixes": [
            "App icon replaced with a custom soccer ball + 'WC' design matching "
            "the app's dark green brand colour.",
            "Qualification odds delta badges (▲/▼) are now fully opaque — "
            "previously the semi-transparent green/red was invisible over flag images.",
            "Fixture team names scale down on mobile so they still fit in the "
            "narrower viewport.",
        ],
    },
    {
        "version": "1.4.2",
        "date": "2026-06-19",
        "fixes": [
            "Fixed UndefinedError on the Teams page: Jinja2 does not expose "
            "Python builtins like set(), replaced with a safe null-guard.",
        ],
    },
    {
        "version": "1.4.1",
        "date": "2026-06-19",
        "fixes": [
            "Fixed TypeError in production: normalize_bracket_match() was "
            "updated to accept penalty score data but the change was never "
            "committed, causing a crash on any page showing knockout fixtures.",
        ],
    },
    {
        "version": "1.4.0",
        "date": "2026-06-19",
        "features": [
            "Fixture cards redesigned with a full-bleed flag image on each "
            "team side, fading into the dark green background. Flag images "
            "are loaded from flagcdn.com for all 48 teams. Team names are "
            "much larger with a text stroke so they stand out against any "
            "flag colour.",
            "Live goal and full-time notifications: when the backend detects "
            "a score change, a banner slides in below the navbar showing "
            "'GOAL!' with the scoring team's flag, or 'Full Time' with the "
            "result. Banners auto-dismiss after 12 seconds.",
        ],
    },
    {
        "version": "1.3.1",
        "date": "2026-06-19",
        "features": [
            "Knockout stage support: frontpage now shows 'Path to the Cup' "
            "with likely opponents by round when a knockout match is featured. "
            "Knocked-out teams are greyed out with strikethrough on the teams "
            "page, the bracket, and fixture displays. The winner prediction "
            "hides eliminated teams. Penalty shootout scores display as "
            "(5) 1–1 (4).",
            "Live score polling is now done entirely in the backend every 10 s "
            "(previously 60 s). The frontpage polls a lightweight status "
            "endpoint and reloads only once the backend has finished "
            "re-simulating, so refreshed odds are available instantly.",
        ],
    },
    {
        "version": "1.3.0",
        "date": "2026-06-19",
        "features": [
            "Matchday 3 ready: when two matches in the same group kick off "
            "simultaneously, both fixtures are shown stacked in one card with "
            "a shared group standings table and combined What's at Stake "
            "section. The Fetch Live button refreshes both at once. "
            "Up Next similarly shows both upcoming matches when they're "
            "scheduled at the same time.",
        ],
    },
    {
        "version": "1.2.5",
        "date": "2026-06-19",
        "fixes": [
            "Fixed a crash on the home page caused by passing an unexpected "
            "keyword argument to the group standings table macro.",
        ],
    },
    {
        "version": "1.2.4",
        "date": "2026-06-19",
        "features": [
            "Fixture cards now show team quality (★ rating) and form (↑↓ badge) "
            "on the same line as the advance odds — team names are cleaner and all "
            "key indicators are grouped together at a glance.",
        ],
    },
    {
        "version": "1.2.3",
        "date": "2026-06-19",
        "fixes": [
            "✅ and \"A draw is enough to go through\" now only appear when an "
            "outcome is guaranteed across every simulation — zero exceptions. "
            "Anything short of that shows >99.9 % or the exact percentage. "
            "Odds chips and headlines are fully consistent.",
        ],
    },
    {
        "version": "1.2.2",
        "date": "2026-06-19",
        "fixes": [
            "What's at Stake headline and odds badges are now fully consistent: "
            "the headline uses the same rounded probability as the displayed chip, "
            "so \"A draw is enough\" only appears when DRAW shows ✅ and vice versa.",
        ],
    },
    {
        "version": "1.2.1",
        "date": "2026-06-19",
        "fixes": [
            "What's at Stake headlines (e.g. \"A draw is enough to go through\") "
            "are now only shown when the outcome is mathematically certain across "
            "all simulations. Previously a ~99.7 % draw rate could trigger the "
            "headline even though qualification was not fully secured.",
        ],
    },
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
