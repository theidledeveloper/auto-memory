"""Verify session-recall setup end-to-end without mutating the session store."""
from __future__ import annotations

import os
import sqlite3
import shutil
from pathlib import Path

from ..config import get_db_path, get_telemetry_path
from ..db.schema_check import FEATURE_SUPPORT_SCHEMA, schema_check
from ..util.db_probe import open_for_check
from ..util.format_output import fmt_json, sanitize_for_terminal
from ..util.instructions import inspect_instruction_file


def _check_binary() -> dict:
    binary = shutil.which("session-recall")
    return {
        "name": "binary",
        "ok": binary is not None,
        "detail": "session-recall is on PATH" if binary else "session-recall is not on PATH",
        "path": binary,
    }


def _check_instruction_file() -> dict:
    state = inspect_instruction_file()
    if state["is_symlink"]:
        return {
            "name": "instructions",
            "ok": False,
            "detail": "Instruction file is a symlink; refusing to trust it",
            "path": state["path"],
        }
    if state["error"]:
        return {
            "name": "instructions",
            "ok": False,
            "detail": state["error"],
            "path": state["path"],
        }
    if not state["configured"]:
        return {
            "name": "instructions",
            "ok": False,
            "detail": "Recall block is missing from the instruction file",
            "path": state["path"],
        }
    return {
        "name": "instructions",
        "ok": True,
        "detail": "Recall block present",
        "path": state["path"],
    }


def _check_database() -> list[dict]:
    db_path = get_db_path()
    probe = open_for_check(db_path)
    if not probe["ok"]:
        return [
            {
                "name": "db_path",
                "ok": False,
                "detail": probe["message"] or "Database open failed",
                "path": db_path,
            }
        ]

    conn = probe["conn"]
    try:
        problems = schema_check(conn, FEATURE_SUPPORT_SCHEMA)
        session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    except sqlite3.Error as exc:
        return [
            {"name": "db_path", "ok": True, "detail": "Database file is readable", "path": db_path},
            {
                "name": "schema",
                "ok": False,
                "detail": f"Verification failed: {exc}",
            },
        ]
    finally:
        conn.close()

    return [
        {"name": "db_path", "ok": True, "detail": "Database file is readable", "path": db_path},
        {
            "name": "schema",
            "ok": not problems,
            "detail": "Schema OK" if not problems else "; ".join(problems),
        },
        {
            "name": "sessions",
            "ok": True,
            "detail": f"Visible sessions: {session_count}",
        },
    ]


def _check_telemetry_path() -> dict:
    telemetry_path = Path(get_telemetry_path())
    parent = telemetry_path.parent
    if parent.exists():
        writable = os.access(parent, os.W_OK)
        return {
            "name": "telemetry",
            "ok": writable,
            "detail": "Telemetry directory is writable" if writable else "Telemetry directory is not writable",
            "path": str(telemetry_path),
        }
    ancestor = parent.parent if parent.parent != parent else parent
    creatable = ancestor.exists() and os.access(ancestor, os.W_OK)
    return {
        "name": "telemetry",
        "ok": creatable,
        "detail": "Telemetry directory can be created" if creatable else "Telemetry directory cannot be created",
        "path": str(telemetry_path),
    }


def run(args) -> int:
    checks = [_check_binary(), _check_instruction_file(), *_check_database(), _check_telemetry_path()]
    telemetry_path = get_telemetry_path()
    result = {
        "ok": all(check["ok"] for check in checks if check["name"] != "sessions"),
        "paths": {
            "db": get_db_path(),
            "telemetry": telemetry_path,
            "instructions": inspect_instruction_file()["path"],
        },
        "checks": checks,
    }

    if getattr(args, "json", False):
        print(fmt_json(result))
        return 0 if result["ok"] else 1

    print("session-recall doctor")
    for check in checks:
        icon = "OK" if check["ok"] else "FIX"
        detail = sanitize_for_terminal(check["detail"])
        print(f"[{icon}] {detail}")
        if check.get("path"):
            print(f"      path: {sanitize_for_terminal(check['path'])}")
    if result["ok"]:
        print("Ready. Init block, schema, and active DB wiring all look good.")
    else:
        print("Not ready yet. Fix the items marked FIX, then rerun `session-recall doctor`.")
    return 0 if result["ok"] else 1
