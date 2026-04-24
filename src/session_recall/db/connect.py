"""Read-only SQLite connection with exponential backoff retry."""
from __future__ import annotations

import sqlite3
import pathlib
import random
import sys
import time

RETRY_DELAYS_MS = [50, 150, 450]


def connect_ro(db_path: str, meta: dict | None = None) -> sqlite3.Connection:
    """Open read-only connection with busy timeout and retry on SQLITE_BUSY."""
    if not pathlib.Path(db_path).exists():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        sys.exit(4)
    busy_hits = 0
    attempts = 0
    for delay in [0] + RETRY_DELAYS_MS:
        attempts += 1
        if delay:
            busy_hits += 1
            time.sleep(delay * random.uniform(0.8, 1.2) / 1000)
        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro",
                uri=True,
                timeout=0.5,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 500")
            conn.execute("PRAGMA query_only = ON")
            if meta is not None:
                meta["busy_hits"] = busy_hits
                meta["attempts"] = attempts
            return conn
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
    print("error: database is locked — another session-recall process may be running", file=sys.stderr)
    raise SystemExit(3)
