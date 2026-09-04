# BVJ Fantasy Football Drafter

A personal ESPN Fantasy Football trade and waiver assistant.

It pulls your league's full state from ESPN (your roster, every rival's roster,
standings, free agents, transaction history), enriches it with live injury
designations and cross-platform waiver-trend data from Sleeper, and stores a
dated snapshot every time it runs so trends are queryable across the season.

The **analysis** — which trades to propose, who to pick up — is deliberately not
in the code. The pipeline's job is to assemble a clean, complete brief; the
reasoning happens on demand through three Claude Code slash commands, which can
also search the web for this morning's news that no stored snapshot could know.

---

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### Configure your league

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable | What it is |
| --- | --- |
| `ESPN_LEAGUE_ID` | The `leagueId` in your league's espn.com URL |
| `ESPN_YEAR` | Season year, e.g. `2025` |
| `ESPN_TEAM_NAME` | Your team's name exactly as ESPN shows it |
| `ESPN_S2` | Session cookie (private leagues only) |
| `ESPN_SWID` | Session cookie (private leagues only) |

### Getting the private-league cookies

A private league needs two cookies from a logged-in browser session:

1. Log in at <https://fantasy.espn.com> and open your league.
2. Open DevTools → **Application** (Chrome) or **Storage** (Firefox) →
   **Cookies** → `https://fantasy.espn.com`.
3. Copy the values of `espn_s2` and `SWID` into `.env`.

`SWID` includes its surrounding braces — `{ABC12345-...}`. If you paste it
without them they get added for you.

These are session credentials. `.env` is gitignored, the values are never
logged, never written to the database, and never included in an export — but
they do expire when you log out of ESPN, which is the usual cause of a sync
suddenly failing to authenticate.

---

## Daily use

```bash
.venv/bin/ffdraft sync
```

Pulls fresh data, writes a snapshot to `data/league.db`, and prints what changed
since last time — injury designations that moved, players newly on waivers,
players a rival just claimed.

```bash
.venv/bin/ffdraft roster                        # your team
.venv/bin/ffdraft roster --team "Some Rival"    # anyone else's
.venv/bin/ffdraft league                        # standings + every roster
.venv/bin/ffdraft analyze                        # weak spots vs the league
.venv/bin/ffdraft analyze --team "Some Rival"    # grade anyone's roster
.venv/bin/ffdraft export                        # write data/latest.json
.venv/bin/ffdraft history "Christian McCaffrey" # one player across syncs
```

### Projections and roster analysis

Every sync now pulls **two independent projections** per player: ESPN's own
(`projected_total_points`) and Sleeper's (`sleeper_proj_season`), converted to
your league's scoring — which is **auto-detected** (PPR / half / standard) from
ESPN's settings, along with your exact starting-lineup structure. Where the two
projections disagree sharply, that's a signal in its own right.

`ffdraft analyze` sets your optimal lineup, then grades **each starting slot
against what your actual opponents start at the same slot** — so a "weak spot"
is a slot where you'd lose the positional matchup most weeks, not just a low
number in the abstract. It reports the gap to your league's median starter, your
percentile, injury flags on starters, ESPN-vs-Sleeper disagreements, and your
startable depth by position. The same analysis rides along in
`data/latest.json` (an `analysis` block) so `/trade-finder` and
`/waiver-targets` reason from it.

### The slash commands

Run these in Claude Code from this directory. Each reads `data/latest.json`,
re-syncing first if it's stale.

| Command | What it does |
| --- | --- |
| `/sync-league` | Refreshes the data and summarizes what actually matters in the changes |
| `/trade-finder` | Diagnoses your roster's real weaknesses, finds the rivals whose surpluses mirror them, and proposes 2–4 specific trades — each with the fairness case the other manager would need to hear, the concrete gain to you, and the risk |
| `/waiver-targets` | Ranks pickups **actually available in your league**, cross-referenced against Sleeper's trending adds, with a specific drop candidate for each |

A typical week: `/sync-league` after Tuesday's waivers process, then
`/waiver-targets` before your claim deadline and `/trade-finder` when you want
to shop a surplus.

---

## How it fits together

```
ESPN (espn_api)  ─┐
                  ├─→ enrichment ─→ storage (SQLite snapshots) ─→ export ─→ slash commands
Sleeper (public) ─┘                                                          (Claude reasons here)
```

| Module | Responsibility |
| --- | --- |
| `config.py` | Loads `.env`; credentials are `repr`-masked so they can't leak into a log |
| `espn_client.py` | The only place that touches `espn_api`; converts its objects into our own dataclasses |
| `sleeper_client.py` | Sleeper's free public API. The ~14MB player dump is disk-cached with a 24h TTL, as Sleeper asks; the small trending endpoints are always fresh |
| `sleeper_client.py` | *(also)* serves season/weekly **projections** (std/half/PPR), cached with a shorter TTL since they move through the week |
| `enrichment.py` | Joins the two sources (see below) and attaches projections in the league's scoring |
| `analysis.py` | Deterministic roster analysis: optimal-lineup fill, per-slot benchmarking against the league, weak-spot ranking |
| `storage.py` | SQLite. Each sync appends a complete snapshot rather than overwriting, so history is queryable. Schema changes apply via idempotent migrations on open |
| `cli.py` | The `ffdraft` command. Contains no *trade* judgement by design; `analyze` is deterministic and comparative |

### On matching players between ESPN and Sleeper

Sleeper publishes an `espn_id` on some records, which is exact and unambiguous —
but it covers only about **46%** of fantasy-relevant players, so a normalized
name match is a necessary fallback rather than an edge case.

Names collide: Sleeper lists both a WR and an LB named Justin Jefferson. So the
fallback keys on name *and* position, with the pro team breaking any remaining
tie. Normalization folds out punctuation, accents, and generational suffixes, so
`Marvin Harrison Jr.` and `Amon-Ra St. Brown` match cleanly.

A player who matches nothing flows through unenriched rather than being dropped
— a missing injury designation must never fail a sync. `match_method` on each
player records which path matched, so a bad join is diagnosable.

---

## Tests

```bash
.venv/bin/python -m pytest
```

The suite is fully offline — no test makes a live network call. Sleeper fixtures
are real recorded API responses, trimmed to a set that exercises the hard cases
(the `espn_id` path, the name-only path, duplicate names across positions,
apostrophes and suffixes, and a team defense with no personal name).

ESPN's endpoints require live private-league credentials, so the ESPN adapter is
tested against objects shaped like `espn_api`'s rather than against recorded
league responses, which can't be shipped in a public repo.
