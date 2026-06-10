# Changelog

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
