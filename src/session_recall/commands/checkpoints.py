"""List recent checkpoints with session context."""
import sys
from ..db.connect import connect_ro
from ..db.schema_check import PATH_SCOPE_SCHEMA, schema_check
from ..config import DB_PATH
from ..util.format_output import output
from ..util.resolve_scope import resolve_scope, session_scope_sql, time_filter_sql

_BASE = """SELECT c.checkpoint_number, c.title, c.overview, c.created_at,
            c.session_id, s.summary as session_summary FROM checkpoints c
           JOIN sessions s ON s.id = c.session_id"""


def run(args) -> int:
    conn = connect_ro(DB_PATH)
    problems = schema_check(conn)
    if problems:
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        conn.close()
        return 2
    scope = resolve_scope(getattr(args, 'repo', None))
    problems = schema_check(conn, PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
    if problems:
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        conn.close()
        return 2
    limit = getattr(args, 'limit', None) or 5
    days = getattr(args, 'days', None)
    conditions = []
    params = []
    scope_clause, scope_params = session_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("c.created_at", days)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    sql = _BASE
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    rows = conn.execute(sql, (*params, limit)).fetchall()
    checkpoints = [{
        "checkpoint_number": r["checkpoint_number"], "title": r["title"],
        "overview": (r["overview"] or "")[:300], "date": (r["created_at"] or "")[:10],
        "session_id": r["session_id"][:8], "session_summary": r["session_summary"],
    } for r in rows]
    output({"repo": scope.display, "count": len(checkpoints), "checkpoints": checkpoints},
           json_mode=getattr(args, 'json', False))
    conn.close()
    return 0
