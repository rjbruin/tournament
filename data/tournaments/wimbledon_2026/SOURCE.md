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

- `atp_rank`: the real ATP ranking number (distinct from ATP ranking
  *points*) — **42/128 players, real, sourced, not fabricated for the
  rest**:
  - The 32 seeds: from the same seeded-players table's "Rank" column.
  - 10 more from the draw article's "Other entry information" section —
    the "Protected ranking" entrant's rank, and 9 replacement players'
    ranks given alongside the withdrawn player they replaced (e.g.
    "Carlos Alcaraz (2) → replaced by Jan Choinski (104)").
  - The remaining 86 (mostly qualifiers, wildcards, and other direct
    entrants outside the seeds): Wikipedia's draw article doesn't publish
    individual rankings for them, and a full historical ATP ranking
    snapshot for 29 June 2026 covering that range (roughly top 100–400)
    wasn't found — Wikipedia's own "Current tennis rankings" transclusion
    only goes to No. 20 (checked the archived revision from that date),
    and the men's singles *qualifying* draw's seed list is ordinal
    (1–32) rather than absolute rank. These 86 stay `null` rather than
    guessed.

## Match results and schedule (`matches.json`, `actuals.json`)

Since the real 2026 Championships concluded before this data was added
(final: 12 July 2026), match results were pulled too, from the same
draw article's bracket templates (`{{16TeamBracket-Compact-Tennis5}}` ×8
sections + `{{8TeamBracket-Tennis5}}` for QF/SF/F) — winner, opponent, and
full set score for all 127 matches, real. `actuals.json`'s
`knockout_results` is populated from this, so the live app now shows the
real completed bracket rather than a blank pre-tournament draw.

**Match dates**: Wikipedia's draw article itself carries no per-match
dates (confirmed — neither this article nor prior years' equivalents
include them). A separate real source did exist for a meaningful subset:
[`2026 Wimbledon Championships – Day-by-day summaries`](https://en.wikipedia.org/wiki/2026_Wimbledon_Championships_%E2%80%93_Day-by-day_summaries)
lists exact per-match dates for "main court" (marquee) matches only. Cross-
referencing by player pair against the 127 parsed matches gave:
- **Real, exact dates for 55/127 matches** (`date_confirmed: true`,
  `date` set) — this is **100% of the Round of 16 onward** (all 8 R16, all
  4 QF, both SF, and the Final — every match from that point on happened
  to be a main-court match) plus 40 marquee matches from the first three
  rounds.
- **No exact date for the remaining 72 matches** (`date_confirmed: false`,
  `date: null`), all in the first three rounds — Wikipedia doesn't publish
  a per-match date for non-featured early-round matches, and other sources
  checked (wimbledon.com, ATP tour) were unreachable or blocked. Each of
  these carries a `date_range` (e.g. `["2026-06-29","2026-06-30"]`) — the
  real two-day window that round was played over, from the tournament's
  official dates (29 June – 12 July 2026) — rather than a fabricated exact
  day.
