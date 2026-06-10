# Changelog

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
