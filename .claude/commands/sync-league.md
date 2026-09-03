---
description: Pull fresh ESPN + Sleeper data and summarize what changed
allowed-tools: Bash(.venv/bin/ffdraft:*), Bash(ffdraft:*), Read
---

Refresh the league data and tell me what moved.

1. Run `.venv/bin/ffdraft sync` (fall back to `ffdraft sync` if that path does
   not exist).
2. Run `.venv/bin/ffdraft export` so `data/latest.json` is current for the
   analysis commands.
3. Summarize the result for me in chat — do not just paste the raw output:
   - Any injury designation changes, and specifically whether they hit **my**
     starters or a player I'd want to stream.
   - Notable adds/drops by other managers, especially anything that signals a
     rival is shoring up a position I was hoping to trade into.
   - Anyone newly available on waivers who is worth a look.
   - If nothing meaningful changed, say so in one line rather than padding.

If the sync fails on ESPN auth, the likely cause is expired `ESPN_S2` /
`ESPN_SWID` cookies in `.env` — tell me to refresh them from the browser rather
than trying to work around it.
