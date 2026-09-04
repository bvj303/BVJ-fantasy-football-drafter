---
description: Rank the best waiver pickups actually available in my league
allowed-tools: Bash(.venv/bin/ffdraft:*), Bash(ffdraft:*), Read, WebSearch, WebFetch
---

Tell me who to pick up.

**Data first.** Read `data/latest.json`. If it is missing or `taken_at` is more
than ~24 hours old, run `.venv/bin/ffdraft sync && .venv/bin/ffdraft export`
first.

**Constraint that matters:** only recommend players in the `free_agents` list.
That list is who is genuinely available in *my* league — a player trending up
league-wide is useless to me if a rival already rostered him. Never recommend
someone who appears on any team's roster in `teams`.

1. Start from `free_agents`, weighting `trending_add_count` (Sleeper's
   cross-platform add signal over the last 24h) alongside `sleeper_proj_season`
   / `projected_total_points` (rest-of-season projections), season points so
   far, and `percent_owned`. Aim the search at the positions in
   `analysis.weak_spots` — a great WR on the wire barely helps if my WRs are
   already above league median and my hole is at RB.
2. Treat `injury_status` as a filter, not a footnote — a trending add who is
   `Out` or on IR is a stash, not a starter, and you should label it as such.
3. Use WebSearch on your top candidates before recommending them. Trending adds
   are usually reacting to news you can't see in the JSON: a starter went down,
   a backfield cleared out, a coach named a starter. Confirm *why* each player
   is trending, and drop anyone whose bump was a one-week fluke.
4. Give me a ranked list of the top 5–8, and for each:
   - **Who and why now** — the actual catalyst, in one line.
   - **Role outlook** — is this a season-long starter, a bye-week fill, or a
     lottery-ticket stash?
   - **Who I drop for him** — name a specific player from my bench and say why
     he's the most expendable. If nobody on my roster is worth dropping for a
     given target, say so.
5. Flag separately anyone on **my** roster that `trending_drop_count` suggests
   the wider market is abandoning, so I can decide whether to cut bait.
