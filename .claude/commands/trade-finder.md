---
description: Propose fair trades that improve my team
allowed-tools: Bash(.venv/bin/ffdraft:*), Bash(ffdraft:*), Read, WebSearch, WebFetch
---

Find me trades worth proposing.

**Data first.** Read `data/latest.json`. If it is missing, or its `taken_at` is
more than ~24 hours old, run `.venv/bin/ffdraft sync && .venv/bin/ffdraft export`
first and then read it.

**Then reason it out yourself.** The pipeline gives you the state of the league
plus a deterministic weak-spot map; it deliberately holds no trade-value model.
The judgement is yours to do.

1. **Start from the `analysis` block**, then sanity-check it against the rosters.
   `analysis.weak_spots` already ranks the starting slots where I project below
   my league's median starter (worst first), `analysis.slots` gives every slot's
   gap and percentile, `analysis.injury_flags` names hurt starters, and
   `analysis.projection_disagreements` flags players where ESPN and Sleeper
   diverge — often a buy-low or sell-high angle. Each player carries two
   projections: `projected_total_points` (ESPN) and `sleeper_proj_season`
   (Sleeper, in my league's scoring) — lean on both, and treat a wide split as
   uncertainty. Confirm the flagged holes are real by eyeballing my starters vs
   bench before you build around them.
2. **Read the other rosters** (`teams`). For each rival, find the mirror image:
   who has a surplus at my position of need, and a hole at a position where I
   have surplus? Those are the only managers worth approaching.
3. **Check what's current.** Use WebSearch for anything time-sensitive before
   you commit to a name — this week's injury news, a player's role change,
   whether a hot streak is real or a one-week spike, current rest-of-season
   rankings. The JSON has season-to-date points and Sleeper injury flags, but
   it does not know what happened this morning.
4. **Propose 2–4 concrete trades.** For each one give me:
   - **The trade**: exact players each side sends, and which manager to ask.
   - **Why they'd accept**: the fairness case in their terms — comparable
     production or consensus value, and the hole it fills on *their* roster.
     I have to actually get this accepted, so a lopsided offer is a wasted
     proposal. Say plainly if a deal is close-to-even rather than overselling.
   - **Why I want it**: the specific gain — fills a starting slot, covers a bye,
     buys low on a player whose usage says he'll rebound, sells high on someone
     outperforming his role.
   - **The risk**: what would make this look bad in a month.
5. Rank them, best first. If the honest answer is that no good trade exists
   right now, say that instead of manufacturing one.
