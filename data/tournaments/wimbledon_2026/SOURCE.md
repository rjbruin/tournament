# Data provenance — 2026 Wimbledon Championships, Gentlemen's Singles

`entries.json` (128 players) and `positions.json` (draw order, seat 0..127)
were parsed from the raw wikitext of:

  https://en.wikipedia.org/wiki/2026_Wimbledon_Championships_%E2%80%93_Men%27s_singles

fetched 2026-08 via the MediaWiki `action=raw` endpoint (not the rendered
page) and parsed directly from the `{{16TeamBracket-Compact-Tennis5}}` draw
templates and the seeded-players table — not summarized through an
intermediate model, so names, seeds, countries, and draw positions should be
exact.

**What's real vs. modeled:**
- Names, countries, seed numbers (1–32), entry status (Q/WC/LL/PR), and
  draw positions (all 128): directly parsed from Wikipedia, real.
- The 32 seeds' `elo_grass`: derived from real ATP ranking points (also
  from the same Wikipedia table) via a log-scale mapping anchored at
  Elo 2300 (seed 1, 13,450 pts) to Elo 1900 (seed 32, 1,349 pts). The
  *points* are real; the *points-to-Elo curve* is a documented modeling
  choice for this simulator, not a published Elo rating.
- The other 96 real, named entrants: Wikipedia's seeded-players table only
  covers the 32 seeds, so individual ranking data for the rest wasn't
  pulled. They get a flat baseline Elo by entry tier instead of a
  fabricated precise rating: 1750 for unseeded direct entries, 1600 for
  qualifiers/wildcards/lucky-losers/protected-ranking entrants (consistent
  with usually sitting outside the ATP top ~100).

No match results were transcribed (this instance starts from an empty
`actuals.json`, i.e. purely the pre-tournament draw) — the champion
(Jannik Sinner, who won the real 2026 final) is not baked in anywhere; the
simulator projects it the same way it would have before a ball was hit.
