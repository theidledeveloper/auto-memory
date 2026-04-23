"""Dim 7: File-row freshness — how far file rows lag recent session activity."""
from __future__ import annotations

from ..config import DB_PATH
from ..db.connect import connect_ro
from ..db.schema_check import PATH_SCOPE_SCHEMA, schema_check
from ..util.file_activity import format_gap, latest_activity_timestamp, latest_file_timestamp
from ..util.resolve_scope import resolve_scope
from .scoring import score_dim

HINT = "Use `session-recall files --days 7` — checkpoint fallback can surface newer changes"
_GREEN_HOURS = 24
_AMBER_HOURS = 72


def check() -> dict:
    scope = resolve_scope()
    try:
        conn = connect_ro(DB_PATH)
        problems = schema_check(conn, PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
        if problems:
            conn.close()
            return {"name": "File Row Freshness", "score": 0, "zone": "RED",
                    "detail": "; ".join(problems), "hint": HINT}

        latest_file_ts = latest_file_timestamp(conn, scope)
        latest_activity = latest_activity_timestamp(conn, scope)
        conn.close()
    except Exception as e:
        return {"name": "File Row Freshness", "score": 0, "zone": "RED",
                "detail": str(e), "hint": HINT}

    if latest_activity is None:
        return {"name": "File Row Freshness", "score": 5, "zone": "AMBER",
                "detail": f"0 sessions for {scope.display}", "hint": HINT}
    if latest_file_ts is None:
        return {"name": "File Row Freshness", "score": 0, "zone": "RED",
                "detail": "no file rows for current scope", "hint": HINT}

    gap_hours = max(0.0, (latest_activity - latest_file_ts).total_seconds() / 3600)
    result = score_dim(gap_hours, green_threshold=_GREEN_HOURS, amber_threshold=_AMBER_HOURS,
                       higher_is_better=False)
    result.update({
        "name": "File Row Freshness",
        "detail": f"{format_gap(gap_hours)} behind latest activity",
        "hint": HINT,
    })
    return result
