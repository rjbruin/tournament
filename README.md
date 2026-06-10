# WC 2026 Tournament Simulator

A Flask web app that runs Monte Carlo simulations of the 2026 FIFA World Cup
(12 groups of 4, round of 32 through the final, with the official Annex C
tiebreak rules for third-placed teams) and presents the results through:

- A groups overview with standings, advance probabilities, and fixtures.
- A chronological fixtures list with timezone-aware kickoff times.
- A spatially-aligned, animated, scrollable knockout bracket.
- Team detail pages.
- Simulation history with the ability to compare and remove past runs.
- An "Ask AI" chat interface for natural-language questions about the
  simulation results (via OpenRouter).

## Requirements

- Python 3.11+
- See `requirements.txt`

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp data/settings.example.json data/settings.json   # then fill in your API key
python run.py
```

The app runs at http://localhost:5001.

## Configuration

App settings live in `data/settings.json` (gitignored — copy from
`data/settings.example.json`). Key settings:

- `openrouter_api_key` — API key for the "Ask AI" feature (OpenRouter). Can
  also be supplied via the `OPENROUTER_API_KEY` environment variable.
- `openrouter_model` — model to use for the chat interface.
- `display_timezone` — IANA timezone name used to display fixture times.

### Running alongside another app

To run on a different port and/or under a URL subpath (e.g. so it can sit
behind a reverse proxy at `http://<host>:<port>/tournament`), set:

- `PORT` — port to listen on (default `5001`).
- `URL_PREFIX` — subpath to mount the app under, e.g. `tournament`. All
  generated links, redirects, static assets, and API calls automatically
  account for the prefix.
- `HOST` — interface to bind to (default `127.0.0.1`).

```bash
PORT=5050 URL_PREFIX=/tournament python run.py
# now serves at http://127.0.0.1:5050/tournament/
```

If you're putting this behind nginx/Apache, proxy `/tournament/` to
`http://127.0.0.1:5050/tournament/` and set `URL_PREFIX=/tournament` for the
app process — no `ProxyPass`-rewrite of paths is needed since the app emits
prefixed URLs itself.

## Releases

`scripts/release.sh <version>` bumps `VERSION`, tags the commit, pushes it,
and creates a GitHub release.

## Deployment

`scripts/deploy.sh <version> [install-dir]` downloads a tagged release
tarball from GitHub, installs it into a versioned directory under
`<install-dir>/releases/`, sets up a virtualenv, links persistent data
(`snapshots.json`, `settings.json`, `actuals.json`) from a shared directory,
and points `<install-dir>/current` at the new release. See the script for
systemd integration.

If the server can't reach GitHub directly (e.g. private repo without
credentials, or no internet access), fetch the tarball on a machine that
does have access and pass it in instead:

```bash
# On your machine (authenticated with gh):
scripts/fetch-release.sh v0.1.0
scp tournament-v0.1.0.tar.gz myserver:/tmp/

# On the server:
/opt/tournament/scripts/deploy.sh v0.1.0 /opt/tournament --tarball /tmp/tournament-v0.1.0.tar.gz
```
