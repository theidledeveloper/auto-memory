"""Instruction-file helpers for init/doctor flows."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..config import INSTRUCTION_MARKER, INSTRUCTION_PATHS

INSTRUCTION_BLOCK = """## Progressive Session Recall — RUN FIRST ON EVERY PROMPT

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
"""


def primary_instruction_path() -> Path:
    return Path(INSTRUCTION_PATHS[0]).expanduser()


def inspect_instruction_file(path: Path | None = None) -> dict:
    target = path or primary_instruction_path()
    exists = target.exists()
    is_symlink = target.is_symlink()
    is_regular_file = target.is_file() if exists and not is_symlink else False
    content = ""
    error = None
    if exists and not is_symlink:
        if not is_regular_file:
            error = "Instruction path is not a regular file; refusing to use it."
        else:
            try:
                content = target.read_text()
            except OSError as exc:
                error = f"Instruction file could not be read: {exc}"
    return {
        "path": str(target),
        "exists": exists,
        "is_symlink": is_symlink,
        "is_regular_file": is_regular_file,
        "error": error,
        "configured": INSTRUCTION_MARKER in content,
    }


def ensure_instruction_block(path: Path | None = None) -> dict:
    target = path or primary_instruction_path()
    state = inspect_instruction_file(target)
    if state["is_symlink"]:
        return {**state, "ok": False, "changed": False, "message": "Instruction file is a symlink; refusing to modify it."}
    if state["error"]:
        return {**state, "ok": False, "changed": False, "message": state["error"]}
    if state["configured"]:
        return {**state, "ok": True, "changed": False, "message": "Instruction file already includes session-recall recall block."}

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text() if target.exists() else ""
        new_content = existing
        if new_content and not new_content.endswith("\n"):
            new_content += "\n"
        if new_content and not new_content.endswith("\n\n"):
            new_content += "\n"
        new_content += INSTRUCTION_BLOCK.rstrip() + "\n"

        fd, tmp_path = tempfile.mkstemp(prefix=".session-recall-", dir=str(target.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(new_content)
            os.replace(tmp_path, target)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    except OSError as exc:
        return {**state, "ok": False, "changed": False, "message": f"Instruction file could not be updated: {exc}"}

    return {
        **inspect_instruction_file(target),
        "ok": True,
        "changed": True,
        "message": "Instruction file updated with session-recall recall block.",
    }
