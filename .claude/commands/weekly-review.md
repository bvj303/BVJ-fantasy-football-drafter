---
description: Full weekly roster review — start/sit, injuries, waivers, and trades
allowed-tools: Bash(.venv/bin/ffdraft:*), Bash(ffdraft:*), Read, WebSearch, WebFetch
---

Run my weekly fantasy football review. Work through every step below and give me
the output in that order. Read my team, scoring, and lineup from the data rather
than assuming — don't hardcode anything about the league.

## 1. Refresh the data

Run (fall back to bare `ffdraft` if the `.venv` path is absent):

```
.venv/bin/ffdraft sync
.venv/bin/ffdraft export
```

If sync fails on ESPN auth, my `ESPN_S2` / `ESPN_SWID` cookies in `.env` have
expired — stop and tell me to refresh them; do not try to work around it.

Then read `data/latest.json`. It holds `my_team`, every team's roster,
`free_agents`, `activity`, `scoring_format`, `lineup_slots`, and an `analysis`
block (per-slot grades, ranked `weak_spots`, `injury_flags`,
`projection_disagreements`, `bench_depth`). Each player carries two projections
— `projected_total_points` (ESPN, season) and `sleeper_proj_season` (Sleeper,
in my scoring) — plus `sleeper_proj_week` (this week), `injury_status`, and
`trending_add_count` / `trending_drop_count`. Note `current_week`.

## 2. What changed since last week

Summarize the sync's change report: injury designations that moved (call out any
hitting my starters), players my leaguemates added or dropped, and anyone newly
available worth a look. One tight paragraph — skip it if nothing material moved.

## 3. This week's start / sit

Set my optimal lineup for `current_week` using `sleeper_proj_week` and the
`lineup_slots` structure (respect flex/superflex eligibility). Then:
- Call out the genuinely close calls (two players within ~2 pts for one slot)
  and make a recommendation, using WebSearch for this week's matchup, weather,
  or role news that a projection won't capture.
- Flag any starter who is `Questionable`/`Doubtful`/`Out` and name the specific
  bench replacement if I need one.
- Note any player on bye I might be about to start by mistake.

## 4. Injuries and depth risk

List my injured or trending-down players, and for each say whether I'm covered
on my own bench or need to hit the waiver wire.

## 5. Waiver targets

Recommend ONLY players in `free_agents` (never someone already rostered). Weight
`trending_add_count` alongside `sleeper_proj_week` / `sleeper_proj_season` and
my `weak_spots` — a hot name at a position I'm already strong at isn't a
priority. Treat `injury_status` as a filter (label an `Out`/IR trending add as a
stash, not a starter). WebSearch your top candidates to confirm *why* they're
trending before recommending them. For each, name a specific drop from my bench
and why he's most expendable. Give me a ranked top 3–6.

## 6. Trade opportunities (only if one is clearly worth it)

If `analysis.weak_spots` shows a real, persistent hole that waivers can't fix,
scan the other rosters for a manager whose surplus mirrors my need and who has a
hole where I have surplus. Propose 1–2 fair trades — exact players both ways,
the fairness case in their terms (I have to get it accepted, so no lopsided
offers), the gain to me, and the risk. If nothing clean exists this week, say so
in one line rather than forcing it.

---

Keep it skimmable — I'm reading this once a week before I set my lineup and
process waivers. Lead with the start/sit calls, since those are time-sensitive.
