# auto-memory — Copilot Instructions Template

> **Note:** Install package `auto-memory`. Run binary `session-recall`. For setup, prefer [`session-recall init`](deploy/install.md) over manual copy/paste.

This file contains the raw instruction block for manual reference. Copy the block below into `~/.copilot/copilot-instructions.md` if you prefer manual setup.

---

## Progressive Session Recall — RUN FIRST ON EVERY PROMPT

**Run `session-recall` FIRST on every prompt before doing anything else.** It costs ~50 tokens and prevents expensive blind searches.

```bash
session-recall files --json --limit 10  # recently touched files
session-recall files --days 7 --json    # files touched in last 7 days
session-recall list --json --limit 5    # recent sessions
session-recall list --days 2 --json     # sessions from last 2 days
session-recall search '<term>' --json   # full-text search
session-recall search '<term>' --days 5 # search last 5 days only
session-recall checkpoints --days 3     # checkpoints from last 3 days
session-recall show <id> --json         # drill into one session
session-recall health --json            # 10-dimension health check
session-recall schema-check             # validate DB schema (run after Copilot CLI upgrade)
```

**All 4 query commands default to all-time.** Add `--days N` when you want a bounded window, for example `--days 7` or `--days 30`.

**Escape hatches:** `SESSION_RECALL_DB` overrides the session-store path. `SESSION_RECALL_TELEMETRY` overrides the local telemetry file path.

Only use filesystem tools (grep, glob, find) if session-recall returns nothing useful.
If `session-recall` errors, continue silently — it's a convenience, not a blocker.
