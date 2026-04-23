"""Dim 7: File-row freshness — how far file rows lag recent session activity."""
from __future__ import annotations

from ..config import DB_PATH
from ..db.connect import connect_ro
from ..db.schema_check import FILE_FALLBACK_SCHEMA, PATH_SCOPE_SCHEMA, schema_check
from ..util.file_activity import format_gap, latest_activity_timestamp, latest_file_timestamp
from ..util.file_hints import latest_checkpoint_hint_timestamp, latest_turn_hint_timestamp
from ..util.resolve_scope import resolve_scope
from .scoring import score_dim

HINT = "Use `session-recall files --days 7` — checkpoint and turn fallback can surface newer changes"
_FALLBACK_LOOKBACK_DAYS = 7
_GREEN_HOURS = 24
_AMBER_HOURS = 72


def _fallback_result(prefix: str, label: str, gap_hours: float) -> dict:
    result = score_dim(
        gap_hours,
        green_threshold=_GREEN_HOURS,
        amber_threshold=_AMBER_HOURS,
        higher_is_better=False,
    )
    if result["zone"] == "GREEN":
        result["zone"] = "AMBER"
        result["score"] = min(result["score"], 6.5)
    result.update({
        "name": "File Row Freshness",
        "detail": f"{prefix}; {label} {format_gap(gap_hours)} behind latest activity",
        "hint": HINT,
    })
    return result


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
        checkpoint_supported = not schema_check(conn, FILE_FALLBACK_SCHEMA)
        checkpoint_hint_ts = (
            latest_checkpoint_hint_timestamp(conn, scope, cutoff_days=_FALLBACK_LOOKBACK_DAYS)
            if checkpoint_supported else None
        )
        turn_hint_ts = latest_turn_hint_timestamp(
            conn,
            scope,
            cutoff_days=_FALLBACK_LOOKBACK_DAYS,
        )
        conn.close()
    except Exception as e:
        return {"name": "File Row Freshness", "score": 0, "zone": "RED",
                "detail": str(e), "hint": HINT}

    if latest_activity is None:
        return {"name": "File Row Freshness", "score": 5, "zone": "AMBER",
                "detail": f"0 sessions for {scope.display}", "hint": HINT}
    hint_candidates = []
    if checkpoint_hint_ts is not None:
        hint_candidates.append((checkpoint_hint_ts, "checkpoint fallback"))
    if turn_hint_ts is not None:
        hint_candidates.append((turn_hint_ts, "turn fallback"))
    latest_hint_ts, latest_hint_label = (
        max(hint_candidates, key=lambda item: item[0])
        if hint_candidates
        else (None, None)
    )
    if latest_file_ts is None:
        if latest_hint_ts is not None and latest_hint_label is not None:
            gap_hours = max(0.0, (latest_activity - latest_hint_ts).total_seconds() / 3600)
            return _fallback_result("no session_files rows in scope", latest_hint_label, gap_hours)
        return {"name": "File Row Freshness", "score": 0, "zone": "RED",
                "detail": "no file rows for current scope", "hint": HINT}
    if latest_hint_ts is not None and latest_hint_ts > latest_file_ts:
        gap_hours = max(0.0, (latest_activity - latest_hint_ts).total_seconds() / 3600)
        return _fallback_result("session_files rows are stale", latest_hint_label, gap_hours)

    gap_hours = max(0.0, (latest_activity - latest_file_ts).total_seconds() / 3600)
    result = score_dim(gap_hours, green_threshold=_GREEN_HOURS, amber_threshold=_AMBER_HOURS,
                       higher_is_better=False)
    result.update({
        "name": "File Row Freshness",
        "detail": f"{format_gap(gap_hours)} behind latest activity",
        "hint": HINT,
    })
    return result
