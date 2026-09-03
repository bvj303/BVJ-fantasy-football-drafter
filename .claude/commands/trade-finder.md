---
description: Propose fair trades that improve my team
allowed-tools: Bash(.venv/bin/ffdraft:*), Bash(ffdraft:*), Read, WebSearch, WebFetch
---

Find me trades worth proposing.

**Data first.** Read `data/latest.json`. If it is missing, or its `taken_at` is
more than ~24 hours old, run `.venv/bin/ffdraft sync && .venv/bin/ffdraft export`
first and then read it.

**Then reason it out yourself.** The pipeline gives you the state of the league;
it deliberately holds no trade-value model. The analysis is yours to do.

1. **Diagnose my roster** (`my_team` in the JSON). Where am I actually weak —
   not by name value, but by what I start each week? Look at starters vs bench,
   points scored vs projected, injuries (`injury_status`), and positions where
   my starter is replacement-level. Note upcoming bye-week holes.
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
