"""Wire session-recall into the user's Copilot instruction file."""
from __future__ import annotations

import sqlite3

from ..config import get_db_path
from ..db.schema_check import FEATURE_SUPPORT_SCHEMA, schema_check
from ..util.db_probe import open_for_check
from ..util.format_output import fmt_json, sanitize_for_terminal
from ..util.instructions import ensure_instruction_block


def _verification_report() -> dict:
    db_path = get_db_path()
    probe = open_for_check(db_path)
    report = {
        "db_path": db_path,
        "db_exists": probe.get("exit_code") != 4,
        "schema_ok": False,
        "problems": [],
        "session_count": None,
        "connection_ok": probe["ok"],
        "connection_error": probe.get("message"),
        "exit_code": probe.get("exit_code"),
    }
    if not probe["ok"]:
        return report
    conn = probe["conn"]
    try:
        report["db_exists"] = True
        problems = schema_check(conn, FEATURE_SUPPORT_SCHEMA)
        report["problems"] = problems
        report["schema_ok"] = not problems
        report["session_count"] = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    except sqlite3.Error as exc:
        report["problems"] = [f"verification failed: {exc}"]
    finally:
        conn.close()
    return report


def run(args) -> int:
    state = ensure_instruction_block()
    verification = _verification_report()
    result = {
        "ok": state["ok"],
        "changed": state["changed"],
        "path": state["path"],
        "configured": state["configured"],
        "message": state["message"],
        "verification": verification,
    }
    if getattr(args, "json", False):
        print(fmt_json(result))
        return 0 if state["ok"] else 2

    print(f"{'Updated' if state['changed'] else 'Checked'} instruction file:")
    print(f"  {sanitize_for_terminal(state['path'])}")
    print(sanitize_for_terminal(state["message"]))
    if verification["connection_ok"] and verification["schema_ok"]:
        session_count = verification["session_count"] or 0
        print(f"Schema check OK against {sanitize_for_terminal(verification['db_path'])}")
        if session_count:
            print(f"Visible sessions: {session_count}")
        else:
            print("Visible sessions: 0 (normal on a fresh install)")
    elif verification["connection_ok"]:
        print("Schema check found issues:")
        for problem in verification["problems"]:
            print(f"  - {sanitize_for_terminal(problem)}")
    else:
        print(sanitize_for_terminal(verification["connection_error"] or "Database probe failed"))
    print("Next: run `session-recall doctor` for the full setup check.")
    return 0 if state["ok"] else 2
