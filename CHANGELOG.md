# Changelog

## v0.7.4

- Scenarios are now an auto-maintained backend feature: one canonical
  scenario per tournament state (before the first match, then after each
  played match), rebuilt automatically. A one-time purge clears the old
  ad-hoc scenarios.
- The homepage hero button is now "Update results" (runs the results
  sync); scenario management moved to a "Manage scenarios" modal on the
  Settings page.
- The "Update results" button is disabled and reads "Results up to date"
  when every match that has already kicked off has a recorded result; it
  re-enables as soon as a started match is missing its result.
- The homepage "Last updated" notice now includes the scenario progress
  label, e.g. "Last updated: Group stage day 4 - all games played
  (15-06 07:28)".
- Scenario list in the Manage scenarios modal is ordered from most
  matches played to least.

## v0.7.3

- Odds/probability displays now show ✅ for exactly 100% and ❌ for
  exactly 0% instead of "100.0%"/"0.0%", across all pages.

## v0.7.2

- New **Teams page** (replacing the "Team" nav entry): lists all teams
  ranked by current Elo (base Elo adjusted by form), with FIFA rank,
  confederation, form badge, and a rank-change badge showing movement
  vs. the base FIFA ranking.
- New **favorite team** setting, featured prominently at the top of the
  Teams page.

## v0.7.1

- Fixed the "Switch scenario" button disappearing off-screen on mobile
  when the active scenario's label is long.
- Fixed shuffled date/time/venue/place data for several Round of 32
  knockout matches (73-90 range) so they match the official 2026 World
  Cup schedule.
- Removed a stale "live" flag for a group-stage fixture that already had
  a final score recorded.

## v0.6.0

- Added support for marking a group-stage fixture as **"in progress"** with
  a live scoreline (`actuals["live_matches"]`). In-progress matches
  propagate into standings/brackets as if completed, but are visually
  flagged with a "🔴 LIVE" badge.
- The homepage's featured fixture card now shows **"Live match"** as its
  header when the match is in progress or within 2 hours of its scheduled
  kickoff, and offers an **"📡 Edit live score"** action (alongside
  "🔍 Explore") to record/update the live scoreline via the new
  `POST /api/actuals/live_score` endpoint.
- When the featured (or a fixtures-list) match is live, a collapsed
  "standings before this match" table is shown alongside the current
  standings, so you can see the effect of the live result.
- The hypothetical "what if" scenario now records which match was edited
  (`featured_match`), so the homepage features that match (with its
  hypothetical scoreline treated as final) instead of the next upcoming
  fixture.
- Removed the duplicate outer box around the featured fixture card.
- New **data migration framework** (`app/migrations/`): on-disk data files
  are automatically brought up to date on startup (and via
  `scripts/migrate.py`), tracked in `data/.migrations.json`. This release
  includes a migration that adds the new `live_matches` and
  `featured_match` fields to existing `data/actuals.json` and scenario
  files.

## v0.5.0

- Added a **draw phase**: the 48 teams are split into 4 pots of 12, following
  the real 2026 World Cup draw procedure (hosts seeded to A1/B1/D1,
  Spain/Argentina and France/England placed in opposite bracket halves,
  confederation constraints with the UEFA exception). See `data/draw_pots.json`
  and `app/simulation/draw.py`.
- New **"Draw" page**: view the pots, the actual draw, and simulate a fresh
  random draw (savable as a new scenario).
- New virtual **"pre-draw" scenario**: marginalizes tournament projections
  over many randomly simulated draws, so the actual draw's effect on each
  team's odds can be seen by comparing "current" vs. "pre-draw".
- Scenarios can now carry a (possibly partial) `"draw"` — `SimulationEngine.run()`
  accepts a `groups` override, and partially-drawn scenarios are projected by
  marginalizing over draws that complete the fixed part.
- New API endpoints: `GET /api/draw/pots`, `POST /api/draw/simulate`,
  `POST /api/draw/save`, `GET /api/draw/opponent_stats`.

## v0.4.0

- Added **scenarios**: a scenario is a named set of fixture results. "Current"
  always reflects the real-world tournament; users can create, view, and
  delete additional "what if" scenarios from the new Scenarios page, and
  compare any two scenarios head-to-head (top-5 predicted winners + a chosen
  team's odds).
- Any results/standings/bracket/fixtures page can be loaded for a particular
  scenario via `?s=<scenario_id>`.
- The homepage is now viewable without an account (always showing the
  "current" scenario), with a sign-in hint to unlock other scenarios and Ask
  AI. Logged-in users see a "current/next fixture" card at the top with an
  inline score-update form (optionally saving as a new "what if" scenario).
- `/api/results/sync` now archives the current real-world scenario before
  overwriting it with newly-fetched results, so earlier states remain
  explorable.
- The `/api/actuals/*` endpoints, `/api/query` (Ask AI), and the stats
  endpoints now accept a `?s=<scenario_id>` parameter (and `?fork=true` for
  result edits) for scenario-aware results.
- Added a new `GET /api/scenarios` endpoint, with optional quality filters
  (`group_stage_complete`, `has_group_results`, `has_knockout_results`,
  `knockout_complete`).
- Added a configurable "Default team" setting (used on the Team page and
  Scenario comparison page), defaulting to Netherlands for new accounts.

## v0.3.5

- Ask AI now remembers the conversation: the chat page sends recent message
  history along with each new question, so follow-up questions ("what about
  for Brazil?") have context from earlier turns.

## v0.3.4

- Fixed account data (`data/users.json`) being silently lost on every
  deploy: the atomic save in `app/auth.py` used `os.replace()` directly on
  `USERS_PATH`, which is a symlink into the persistent shared directory on
  the VPS. `os.replace()` doesn't follow a symlink for its destination — it
  deleted the symlink and wrote the new file into the (ephemeral) release
  directory instead, so registered accounts disappeared after the next
  update. The save now resolves the symlink first and writes through to the
  real shared file.

## v0.3.3

- Ask AI can now answer questions about fixtures: a new `get_fixtures` tool
  returns match details (teams, group, kickoff date/time/venue, and either
  the actual result or simulated win/draw/loss probabilities), with optional
  filters by group, team, or group-stage vs. knockout.

## v0.3.0

- Added user accounts (register/login/logout) with PBKDF2 password hashing,
  CSRF protection, secure session cookies, and login throttling. Each
  account has its own simulation results, snapshot history, settings,
  timezone, and a per-account API key (slug) for headless API access.
- Added a configurable "number of simulations" setting (per account,
  default 100,000), used as the default for new runs.
- The homepage hero now links to the Simulations page when no simulation
  has been run yet.
- Added integration with football-data.org to fetch official World Cup
  results: a new "Update Results & Re-simulate" button on the homepage
  fetches finished group-stage results, updates `data/actuals.json`, and
  re-runs the simulation. The football-data.org API key is configured on
  the Settings page.
- Added `scripts/start.sh` (systemd-friendly start script with the VPS
  configuration) and `scripts/update.sh` (update an existing VPS install to
  the latest or a specified release).
- `scripts/deploy.sh` now persists per-account data (`data/users.json`,
  `data/users/`) across releases.

## v0.2.0

- The app now reads `PORT` and `HOST` environment variables, so it can run
  on a different port alongside another Flask app.
- Added `URL_PREFIX` environment variable to mount the app under a subpath
  (e.g. `/tournament`), so it can be reverse-proxied at
  `http://<host>:<port>/tournament`. All generated links, redirects, static
  assets, and client-side API calls respect the prefix.

## v0.1.1

- `scripts/deploy.sh` can now install from a local tarball (`--tarball
  <path>`) for servers that can't reach GitHub directly.
- Added `scripts/fetch-release.sh` to download a release tarball from a
  machine with GitHub access, for transfer to such servers.

## v0.1.0

Initial release.

- Flask web UI: groups, fixtures, knockout bracket, team pages, simulation
  history, settings, "Ask AI" chat interface.
- Monte Carlo simulation engine using Elo-based win probabilities and the
  official 2026 FIFA World Cup format (12 groups of 4, round of 32 through
  final, Annex C tiebreak lookup table for third-placed teams).
- Real 2026 schedule data (dates, kickoff times, venues) sourced from
  Wikipedia, with timezone-aware display.
- Spatially-aligned, animated, horizontally-scrollable knockout bracket view
  with connector lines and edge fade indicators.
- LLM-driven natural-language query interface over simulation results.
