"""List recent sessions for the current (or specified) repository."""
import os
import sys
import time

from ..config import DB_PATH
from ..db.schema_check import FILE_FALLBACK_SCHEMA, schema_check
from ..store.factory import open_store
from ..store.protocol import StoreSchemaError
from ..util import debug
from ..util.file_activity import latest_activity_timestamp, latest_file_timestamp
from ..util.file_hints import load_checkpoint_file_hints, load_turn_file_hints
from ..util.format_output import output
from ..util.resolve_scope import (
    file_scope_sql,
    resolve_scope,
    time_filter_sql,
)
_STALE_HOURS = 24


def run(args) -> int:
    """Execute the list subcommand. Returns exit code."""
    scope = resolve_scope(args.repo)
    debug.log(args, f"scope mode={scope.mode} display={scope.display}")
    store = open_store(args, meta=getattr(args, "_telemetry", None), db_path=DB_PATH)
    limit = args.limit or 10
    try:
        t0 = time.monotonic()
        sessions = store.list_sessions(scope, days=args.days, limit=limit)
        recent_files, _, _warning = store.recent_files(scope, days=args.days, limit=10)
        debug.log(args, f"session_rows={len(sessions)} ms={debug.elapsed_ms(t0):.1f}")
        data = {"repo": scope.display, "count": len(sessions), "sessions": sessions, "recent_files": recent_files}
        if getattr(args, "_telemetry", None) is not None:
            args._telemetry["rows"] = len(sessions)
        output(data, json_mode=args.json)
        return 0
    except StoreSchemaError as exc:
        print("❌ Schema drift:", file=sys.stderr)
        for problem in exc.problems:
            print(f"   - {problem}", file=sys.stderr)
        return 2
    finally:
        store.close()


_FILES_SQL = """SELECT sf.file_path, sf.tool_name, sf.first_seen_at, sf.session_id
FROM session_files sf JOIN sessions s ON s.id = sf.session_id
{where_clause}
ORDER BY sf.first_seen_at DESC LIMIT ?"""


def _format_recent_file(row: dict, cwd: str) -> dict:
    path = row["file_path"]
    return {
        "file_path": os.path.relpath(path, cwd) if os.path.isabs(path) and path.startswith(cwd) else path,
        "full_path": path,
        "tool_name": row["tool_name"],
        "date": row["date"],
        "session_id": row["session_id"],
        "source": row.get("source", "session_files"),
    }


def _recent_files(conn, scope, days=None, limit=10, debug_args=None):
    conditions = []
    params = []
    scope_clause, scope_params = file_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("sf.first_seen_at", days)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = _FILES_SQL.format(where_clause=where_clause)
    rows = conn.execute(sql, (*params, limit)).fetchall()
    cwd = os.getcwd()
    primary_files = [{
        "file_path": r["file_path"],
        "tool_name": r["tool_name"],
        "source": "session_files",
        "date": (r["first_seen_at"] or "")[:10],
        "session_id": r["session_id"][:8],
    } for r in rows]
    checkpoint_fallback_supported = not schema_check(conn, FILE_FALLBACK_SCHEMA)
    checkpoint_files = (
        load_checkpoint_file_hints(conn, scope, days, limit)
        if checkpoint_fallback_supported
        else []
    )
    turn_files = load_turn_file_hints(conn, scope, days, limit)
    fallback_files = checkpoint_files or turn_files
    latest_file = latest_file_timestamp(conn, scope)
    latest_activity = latest_activity_timestamp(conn, scope)
    file_rows_stale = latest_activity is not None and (
        latest_file is None or (latest_activity - latest_file).total_seconds() / 3600 > _STALE_HOURS
    )
    selected = fallback_files if fallback_files and (not primary_files or file_rows_stale) else primary_files
    debug.log(
        debug_args,
        "recent_files "
        f"primary={len(primary_files)} checkpoint={len(checkpoint_files)} turn={len(turn_files)} "
        f"selected_source={'fallback' if selected is fallback_files else 'session_files'} stale={file_rows_stale}",
    )
    return [_format_recent_file(row, cwd) for row in selected]
