"""Structured DB probes for commands that need clean JSON output."""
from __future__ import annotations

import sqlite3
from contextlib import redirect_stderr
from io import StringIO

from ..db.connect import connect_ro


def open_for_check(db_path: str) -> dict:
    stderr = StringIO()
    try:
        with redirect_stderr(stderr):
            conn = connect_ro(db_path)
    except SystemExit as exc:
        message = stderr.getvalue().strip()
        if not message and exc.code == 4:
            message = f"error: database not found: {db_path}"
        elif not message and exc.code == 3:
            message = "error: database is locked — another session-recall process may be running"
        return {"ok": False, "exit_code": exc.code, "message": message}
    except sqlite3.Error as exc:
        message = stderr.getvalue().strip() or f"error: could not open database at {db_path}: {exc}"
        return {"ok": False, "exit_code": 2, "message": message}
    return {"ok": True, "conn": conn}
