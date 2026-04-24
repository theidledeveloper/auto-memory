# Deploy auto-memory

auto-memory is a zero-dependency Python CLI that reads local agent history for progressive session recall. Today that means full support for GitHub Copilot CLI plus a Claude Code adapter for `list`, `show`, `export`, and `diff`.

Install package **`auto-memory`**. Run binary **`session-recall`**.

Published-package fast paths:

```bash
uv tool install auto-memory
pipx install auto-memory
python3 -m pip install --user auto-memory
uvx --from auto-memory session-recall --version
```

Use the editable flow below when you are validating the repo checkout itself.

## Prerequisites

Verify these before proceeding. Stop and report if any fail.

```bash
python3 --version   # must be 3.10+
copilot --version   # Copilot CLI must be installed
```

One of these package managers must be available (checked in priority order):

```bash
uv --version     # preferred
pipx --version   # fallback 1
pip --version     # fallback 2
```

## Install

### Step 1 — Clone or navigate to the repo

If the repo is not already local, clone it:

```bash
git clone <auto-memory-repo-url>
cd auto-memory
```

If already local, `cd` into the repo root.

### Step 2 — Install the CLI

Run the first command that succeeds. Stop after one succeeds.

```bash
# Preferred — uv
uv tool install --force --editable .

# Fallback 1 — pipx
pipx install --force -e .

# Fallback 2 — pip
python3 -m pip install --user --force-reinstall -e .
```

### Step 3 — Verify install

Run these commands after install:

```bash
session-recall --version
session-recall schema-check
```

`schema-check` is the hard install gate. `health` is optional and diagnostic.

## Optional Claude Code source

Claude Code support is read-only and uses transcript files under `~/.claude/projects/`. If you relocate the Claude root, session-recall follows `CLAUDE_CONFIG_DIR`.

```bash
SESSION_RECALL_SOURCE=claude session-recall list --json --repo all
session-recall show --source claude <session-id> --json
session-recall export --source claude <session-id> --format md
```

Current Claude boundary:

- supported: `list`, `show`, `export`, `diff`
- still Copilot-only: `files`, `checkpoints`, `context`, `search`, `stats`, `health`, `calibrate`, `schema-check`, `doctor`
- still deferred: Cursor adapter, optional MCP wrapper

## Agent Integration — Add to Copilot Instructions

This step wires auto-memory into every future agent session by updating `~/.copilot/copilot-instructions.md`.

### Preferred — let session-recall do it

```bash
session-recall init
session-recall doctor
```

`doctor` verifies the active DB path, schema, and instruction-file wiring. Fresh installs with zero sessions are still OK.

### Manual fallback — copy the block yourself

If you prefer manual setup, copy the block below into `~/.copilot/copilot-instructions.md`.

````markdown
## Progressive Session Recall — RUN FIRST ON EVERY PROMPT

**Run `session-recall` FIRST on every prompt before doing anything else.** It costs ~50 tokens and prevents expensive blind searches.

```bash
session-recall files --json --limit 10  # recently touched files
session-recall files --days 7 --json    # files touched in last 7 days
session-recall list --json --limit 5    # recent sessions
session-recall list --days 2 --json     # sessions from last 2 days
session-recall context --budget 400 --json  # approximate one-shot bundle
session-recall search '<term>' --json   # full-text search
session-recall search '<term>' --days 5 # search last 5 days only
session-recall checkpoints --days 3     # checkpoints from last 3 days
session-recall show <id> --json         # drill into one session
session-recall health --json            # 10-dimension health check
session-recall schema-check             # validate DB schema (run after Copilot CLI upgrade)
```

**All 4 query commands default to all-time.** Add `--days N` when you want a bounded window, for example `--days 7` or `--days 30`.

`session-recall context --budget` is approximate and experimental. It uses a documented 4-chars-per-token heuristic, not a tokenizer or runtime dependency.

**Escape hatches:** `SESSION_RECALL_DB` overrides the session-store path. `SESSION_RECALL_TELEMETRY` overrides the local telemetry file path.

Only use filesystem tools (grep, glob, find) if session-recall returns nothing useful.
If `session-recall` errors, continue silently — it's a convenience, not a blocker.
````

## Verify Installation

Run these checks after wiring:

```bash
session-recall doctor
session-recall schema-check    # must exit 0
session-recall list --json     # may return zero sessions on a fresh install
```

If `session-recall list --json` returns zero sessions, that is normal on a fresh install — Copilot CLI needs at least one completed session first.

`session-recall files` prefers native `session_files` rows, then falls back to checkpoint-derived hints, then turn-derived hints when Copilot's file rows are missing or stale.

It is normal for `session-recall health` to show:

- `File Row Freshness = AMBER` when Copilot omitted native `session_files` rows but session-recall can still recover files from checkpoint or turn fallback.
- `Progressive Disclosure = CALIBRATING` on a fresh install until enough telemetry accumulates.

## Migration note

`session-recall list` now defaults to **all history**. If you want the old bounded behavior, pass `--days 30` explicitly in your scripts and prompts.

## Environment overrides

Use these when CI, tests, or a non-default local setup need different paths:

```bash
SESSION_RECALL_DB=/tmp/session-store.db session-recall doctor
SESSION_RECALL_TELEMETRY=/tmp/session-recall-stats.json session-recall doctor
SESSION_RECALL_SOURCE=claude session-recall list --json --repo all
CLAUDE_CONFIG_DIR=/tmp/.claude SESSION_RECALL_SOURCE=claude session-recall show <session-id> --json
```

Homebrew support is intentionally deferred until maintainers explicitly commit to owning a tap or formula.

## Troubleshooting

### `command not found: session-recall`

PATH issue. Check that `~/.local/bin` is on PATH:

```bash
echo "$PATH" | tr ':' '\n' | grep -q '.local/bin' && echo "OK" || echo "MISSING"
```

If missing, add it and retry:

```bash
export PATH="$HOME/.local/bin:$PATH"
session-recall --version
```

If still not found, re-run install with `uv tool install --force --editable .` from the repo root.

### `schema-check` fails (exit code 2)

The Copilot CLI DB schema has drifted from what session-recall expects. This usually happens after a Copilot CLI upgrade. See [UPGRADE-COPILOT-CLI.md](../UPGRADE-COPILOT-CLI.md) for the full procedure.

### No sessions found

Normal on first use. Copilot CLI needs at least one completed session before session-recall has anything to query. Run a Copilot CLI session, then retry.

### Using a non-default DB or telemetry path

If your setup does not use the default Copilot location, set the override explicitly before running checks:

```bash
export SESSION_RECALL_DB=/path/to/session-store.db
export SESSION_RECALL_TELEMETRY=/path/to/.session-recall-stats.json
session-recall doctor
```

## Upgrading Copilot CLI

After any Copilot CLI upgrade, run:

```bash
session-recall schema-check
session-recall doctor
```

If it exits 0, no action needed. If it fails, follow the full upgrade procedure in [UPGRADE-COPILOT-CLI.md](../UPGRADE-COPILOT-CLI.md).
