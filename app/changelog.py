"""
Application changelog and version.

``APP_VERSION`` is the single source of truth for the running version; bump it
when cutting a release and add a matching entry to ``CHANGELOG`` (newest
first). The changelog page and the "What's New" popup both read from here.

Each entry is ``{"version", "date", "features": [...], "fixes": [...]}``.
"""

from __future__ import annotations

APP_VERSION = "1.10.1"

CHANGELOG: list[dict] = [
    {
        "version": "1.10.1",
        "date": "2026-06-28",
        "features": [],
        "fixes": [
            "Removed the 'Explore' hypothetical scenario button from fixture cards — the feature was no longer working.",
        ],
    },
    {
        "version": "1.10.0",
        "date": "2026-06-28",
        "features": [
            "Bracket: live knockout matches now show the current score next to each team, with a pulsating red outline on the card and a 🔴 live badge showing the minute.",
            "Bracket: finished knockout matches show the final score, with penalties written as '1 (5)' when applicable, and the winning team's row subtly highlighted.",
            "Bracket: quality and form badges moved below the team name for a cleaner layout; scores and win odds use a larger, more prominent font.",
        ],
        "fixes": [
            "Fixed a crash on the home page ('list object has no attribute odds') that appeared once the group stage was complete.",
        ],
    },
    {
        "version": "1.9.1",
        "date": "2026-06-26",
        "features": [],
        "fixes": [
            "Knockout fixtures now show a tournament win odds badge (🏆) instead of the advance badge — the teams have obviously already advanced.",
            "Path to the Cup on the home page is now a single shared column (both teams in a bracket match face the same future opponents), with no redundant team label.",
            "Featured fixture header now shows the round name for knockout matches, e.g. 'Up Next — Round of 32'.",
        ],
    },
    {
        "version": "1.9.0",
        "date": "2026-06-26",
        "features": [],
        "fixes": [
            "Live match minute is now shown in real time (football-data.org API v4.1 added the minute field to the Livescore plan).",
            "Team page: group placement odds (1st/2nd/3rd/4th) are hidden once all three group-stage matches have been played.",
            "Team page: the odds graph no longer extends the 'advance from group' line into knockout-round checkpoints.",
            "Team page: a knockout round is removed from 'Likely opponents' once both bracket teams are confirmed.",
            "Team page loads much faster: chart checkpoints now run at 10 000 iterations, and a background thread pre-warms all played checkpoints on startup.",
        ],
    },
    {
        "version": "1.8.0",
        "date": "2026-06-25",
        "features": [
            "What's at Stake: each team's entry now shows a plain-English sentence describing what each match outcome means — e.g. 'Win or draw to qualify in second place' or 'Win to place third and wait for other groups, lose to be knocked out.'",
            "Bracket: venues now show the city name instead of the stadium name for a cleaner look.",
        ],
        "fixes": [
            "Removed the 'Full scenarios' detail block from What's at Stake — the outcome text and odds chips cover the same ground more clearly.",
        ],
    },
    {
        "version": "1.7.5",
        "date": "2026-06-25",
        "features": [
            "Fixtures page: new 'Today' button in the section nav jumps directly to the section containing today's (or next upcoming) matches.",
        ],
        "fixes": [
            "Advance odds badges no longer show '100%' or '0%': the percentage filter now uses decimal-aware thresholds so values that would round to 100% show '>99%' and values that would round to 0% show '<1%'.",
        ],
    },
    {
        "version": "1.7.4",
        "date": "2026-06-21",
        "features": [],
        "fixes": [
            "Page-view statistics are now preserved across version upgrades (pageviews.jsonl was not included in the persistent shared-data symlinks, so it was reset to empty on every deploy).",
        ],
    },
    {
        "version": "1.7.3",
        "date": "2026-06-21",
        "features": [
            "Admin footer now has Usage and Diagnostics links (admin-only).",
            "New Diagnostics page (/admin/diagnostics) shows the 3rd-place points range table for all groups — useful for verifying best-third clinch logic.",
        ],
        "fixes": [
            "Best-third clinch now correctly counts equal-points groups as threats (was using strict > instead of >=), preventing teams from being incorrectly marked as clinched when another group's third-place finisher can match their points tally.",
        ],
    },
    {
        "version": "1.7.2",
        "date": "2026-06-21",
        "features": [],
        "fixes": [
            "Groups page: a team marked 'Best 3rd ✓' now also shows ✓ in its Advance column (previously showed a statistical >99.9% because the groups-page table didn't apply the best-third clinch to the advance badge).",
            "3rd-place standings table now reflects mathematical clinch/elimination in its Advance badges, consistent with every other standings view.",
        ],
    },
    {
        "version": "1.7.1",
        "date": "2026-06-21",
        "features": [],
        "fixes": [
            "What's at Stake chips now show ✓ for all outcomes when a team has already clinched as best third-place (previously showed statistical odds instead of ✓ because the per-outcome analysis only checked within-group clinch logic).",
            "What's at Stake chips now show ✗ when an outcome mathematically eliminates the team from the group (finishing 4th regardless of other results), consistent with the advance badge in the standings table.",
            "Advance badges no longer show ✗ for statistical 0% odds; ✗ is reserved for mathematically confirmed elimination, while near-zero statistical odds show <0.1% instead.",
        ],
    },
    {
        "version": "1.7.0",
        "date": "2026-06-21",
        "features": [
            "Theoretical best-third qualification: a team now shows Q ✓ when it is mathematically guaranteed to advance as one of the 8 best third-place finishers across all 12 groups, not just when it clinches a top-two spot.",
            "Third-place clinch uses points-only reasoning while any group is still live (GD and GF are unbounded in unfinished groups), and upgrades to full (pts, GD, GF) comparison once both sides of the comparison are complete.",
            "Clinched best-third rows appear with a distinct green tint and a 'Best 3rd ✓' marker in group standings, consistent with the existing top-two secured styling.",
        ],
        "fixes": [],
    },
    {
        "version": "1.6.2",
        "date": "2026-06-21",
        "features": [
            "Team quality and form are now shown as a single joined badge — grey (≤2★), bronze (≤3.5★), or gold (>3.5★) for quality, with form arrow alongside.",
            "Quality badge now shown everywhere form was shown: team info card, likely opponents list, fixture rows, and standings.",
            "Mobile chart fix: tournament odds graph now has a proper fixed height on small screens.",
        ],
        "fixes": [
            "Match pages for upcoming knockout matches (TBD opponents) no longer crash with a JSON serialization error.",
            "Match pages are now accessible without logging in.",
            "Live score display now updates immediately in the fixture card when a goal is detected, without waiting for the full page reload.",
        ],
    },
    {
        "version": "1.6.1",
        "date": "2026-06-21",
        "features": [
            "New app icon: football with white ball body, dark green pentagon patches, and transparent background.",
        ],
        "fixes": [],
    },
    {
        "version": "1.6.0",
        "date": "2026-06-21",
        "features": [
            "Theoretical qualification: Q ✓ now means a team has mathematically clinched a top-two place — no combination of remaining results can knock them out, computed exactly under the official FIFA 2026 tiebreakers (points → head-to-head → goal difference → goals scored).",
            "Q >99.9% continues to mean near-certain in the simulations but not yet mathematically guaranteed.",
            "Q ✗ marks a team that is guaranteed to finish last in their group, no matter what.",
            "The distinction is applied consistently everywhere: group standings, Groups overview, Teams list, individual team pages, match pages, and What's at Stake outcome chips.",
            "What's at Stake outcome chips show ✓ only when a specific result exactly clinches top-two; statistical odds are used otherwise.",
            "Explained on the 'How the Simulation Works' page.",
        ],
        "fixes": [],
    },
    {
        "version": "1.5.2",
        "date": "2026-06-20",
        "features": [
            "Each fixture now has its own dedicated page with full match details.",
            "Fixtures in the Fixtures list and Groups page are clickable — tap a match to open its page.",
            "Match pages show group standings, advance odds, and clinching badges as they stood at the end of that specific match.",
        ],
        "fixes": [],
    },
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
