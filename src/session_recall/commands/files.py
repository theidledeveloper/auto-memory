"""List recently touched files with session attribution."""
from __future__ import annotations

import sys
import time

from ..db.connect import connect_ro
from ..db.schema_check import FILE_FALLBACK_SCHEMA, PATH_SCOPE_SCHEMA, schema_check
from ..config import DB_PATH
from ..util import debug
from ..util.file_activity import format_gap, latest_activity_timestamp, latest_file_timestamp
from ..util.file_hints import load_checkpoint_file_hints, load_turn_file_hints
from ..util.format_output import output
from ..util.resolve_scope import file_scope_sql, resolve_scope, time_filter_sql

_BASE = """SELECT sf.file_path, sf.tool_name, sf.first_seen_at,
             sf.session_id, s.summary FROM session_files sf
            JOIN sessions s ON s.id = sf.session_id"""
_STALE_HOURS = 24


def _load_primary_files(conn, scope, days: int | None, limit: int) -> list[dict]:
    conditions = []
    params: list[str] = []
    scope_clause, scope_params = file_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("sf.first_seen_at", days)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    sql = _BASE
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY sf.first_seen_at DESC LIMIT ?"
    rows = conn.execute(sql, (*params, limit)).fetchall()
    return [{
        "file_path": r["file_path"],
        "tool_name": r["tool_name"],
        "source": "session_files",
        "date": (r["first_seen_at"] or "")[:10],
        "session_id": r["session_id"][:8],
        "session_summary": r["summary"],
    } for r in rows]


def _warning_for_fallback(latest_file, latest_activity, fallback_label: str) -> str:
    if latest_activity is None:
        return f"Using {fallback_label} for files"
    if latest_file is None:
        return f"No session_files rows in scope, using {fallback_label}"
    gap_hours = max(0.0, (latest_activity - latest_file).total_seconds() / 3600)
    return f"session_files rows lag latest activity by {format_gap(gap_hours)}, using {fallback_label}"


def run(args) -> int:
    scope = resolve_scope(getattr(args, 'repo', None))
    debug.log(args, f"scope mode={scope.mode} display={scope.display}")
    conn = connect_ro(DB_PATH, meta=getattr(args, "_telemetry", None))
    problems = schema_check(conn, PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
    if problems:
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        conn.close()
        return 2
    limit = getattr(args, 'limit', None) or 10
    days = getattr(args, 'days', None)
    checkpoint_fallback_supported = not schema_check(conn, FILE_FALLBACK_SCHEMA)
    t0 = time.monotonic()
    primary_files = _load_primary_files(conn, scope, days, limit)
    checkpoint_files = (
        load_checkpoint_file_hints(conn, scope, days, limit)
        if checkpoint_fallback_supported
        else []
    )
    turn_files = load_turn_file_hints(conn, scope, days, limit)
    fallback_files = checkpoint_files or turn_files
    fallback_source = "checkpoint_fallback" if checkpoint_files else "turn_fallback"
    fallback_label = "checkpoint fallback" if checkpoint_files else "turn fallback"
    latest_file = latest_file_timestamp(conn, scope)
    latest_activity = latest_activity_timestamp(conn, scope)
    file_rows_stale = latest_activity is not None and (
        latest_file is None or (latest_activity - latest_file).total_seconds() / 3600 > _STALE_HOURS
    )

    use_fallback = bool(fallback_files) and (not primary_files or file_rows_stale)
    files = fallback_files if use_fallback else primary_files
    debug.log(
        args,
        "rows="
        f"{len(files)} primary={len(primary_files)} checkpoint={len(checkpoint_files)} turn={len(turn_files)} "
        f"selected_source={fallback_source if use_fallback else 'session_files'} "
        f"stale={file_rows_stale} ms={debug.elapsed_ms(t0):.1f}",
    )
    data = {
        "repo": scope.display,
        "count": len(files),
        "files": files,
        "source": fallback_source if use_fallback else "session_files",
    }
    if getattr(args, "_telemetry", None) is not None:
        args._telemetry["rows"] = len(files)
    if use_fallback:
        data["warning"] = _warning_for_fallback(latest_file, latest_activity, fallback_label)
    elif file_rows_stale:
        if latest_file is None:
            data["warning"] = "No session_files rows in scope and no checkpoint or turn fallback entries found"
        else:
            gap_hours = max(0.0, (latest_activity - latest_file).total_seconds() / 3600)
            data["warning"] = (
                f"session_files rows lag latest activity by {format_gap(gap_hours)} "
                "and no checkpoint or turn fallback entries were found"
            )
    output(data, json_mode=getattr(args, 'json', False))
    conn.close()
    return 0
