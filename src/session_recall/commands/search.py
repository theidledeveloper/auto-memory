"""Full-text search across session turns and summaries."""
import re
import sys
import time
from ..db.connect import connect_ro
from ..db.schema_check import PATH_SCOPE_SCHEMA, SEARCH_INDEX_SCHEMA, schema_check
from ..config import DB_PATH
from ..util import debug
from ..util import telemetry
from ..util.format_output import output
from ..util.resolve_scope import (
    file_scope_sql,
    resolve_scope,
    session_scope_sql,
    time_filter_sql,
)

_SQL = """SELECT si.content, si.session_id, si.source_type,
        s.summary, s.created_at, s.repository
 FROM search_index si JOIN sessions s ON s.id = si.session_id
 WHERE search_index MATCH ?{extra_filters} ORDER BY rank LIMIT ?"""

_FILE_SQL = """SELECT sf.file_path, sf.session_id, sf.tool_name, sf.first_seen_at,
        s.summary, s.created_at, s.repository
 FROM session_files sf JOIN sessions s ON s.id = sf.session_id
 WHERE sf.file_path LIKE ?{extra_filters}
 ORDER BY sf.first_seen_at DESC LIMIT ?"""

# FTS5 special chars that cause syntax errors when unquoted
_FTS5_SPECIAL = re.compile(r'[.\-(){}[\]^~*:"+/\\@#$%&!?<>=|]')


def sanitize_fts5_query(raw: str) -> str | None:
    """Escape FTS5 special characters and add prefix matching.

    Returns None for empty/whitespace-only queries.
    Strategy: split on whitespace, quote each token that contains
    special chars, append * for prefix matching on every token.
    """
    stripped = raw.strip()
    if not stripped:
        return None
    tokens = stripped.split()
    safe_tokens = []
    for tok in tokens:
        # Escape internal double quotes
        escaped = tok.replace('"', '""')
        if _FTS5_SPECIAL.search(tok):
            # Quote the whole token to treat special chars as literals
            safe_tokens.append(f'"{escaped}"')
        else:
            # Bare token with prefix wildcard for partial matching
            safe_tokens.append(f'{escaped}*')
    return " ".join(safe_tokens)


def run(args) -> int:
    query_len = len((args.query or "").strip())
    query_fingerprint = telemetry.query_hash(args.query or "") if query_len else "none"
    debug.log(args, f"query_len={query_len} query_hash={query_fingerprint}")
    conn = connect_ro(DB_PATH, meta=getattr(args, "_telemetry", None))
    problems = schema_check(conn)
    if problems:
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        conn.close()
        return 2
    raw_query = args.query
    scope = resolve_scope(getattr(args, 'repo', None))
    debug.log(args, f"scope mode={scope.mode} display={scope.display}")
    problems = schema_check(conn, PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
    if problems:
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        conn.close()
        return 2
    problems = schema_check(conn, SEARCH_INDEX_SCHEMA)
    if problems:
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        conn.close()
        return 2
    limit = getattr(args, 'limit', None) or 5
    days = getattr(args, 'days', None)

    fts_query = sanitize_fts5_query(raw_query)
    debug.log(args, f"fts_ready={fts_query is not None}")
    if fts_query is None:
        data = {"query": raw_query, "repo": scope.display, "count": 0, "results": [],
                "warning": "Empty query — nothing to search"}
        output(data, json_mode=getattr(args, 'json', False))
        conn.close()
        return 0

    conditions = []
    params = []
    scope_clause, scope_params = session_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("s.created_at", days)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    extra_filters = "".join(f" AND {condition}" for condition in conditions)
    sql = _SQL.format(extra_filters=extra_filters)
    t0 = time.monotonic()
    rows = conn.execute(sql, (fts_query, *params, limit)).fetchall()
    results = [{"session_id": r["session_id"][:8], "session_id_full": r["session_id"],
                "source_type": r["source_type"], "summary": r["summary"],
                "date": (r["created_at"] or "")[:10], "excerpt": (r["content"] or "")[:200]}
               for r in rows]
    seen = {(r["session_id_full"], r["source_type"]) for r in results}
    like_pat = f"%{raw_query}%"
    file_conditions = []
    file_params = []
    file_scope_clause, file_scope_params = file_scope_sql(scope)
    if file_scope_clause:
        file_conditions.append(file_scope_clause)
        file_params.extend(file_scope_params)
    file_days_clause, file_days_params = time_filter_sql("s.created_at", days)
    if file_days_clause:
        file_conditions.append(file_days_clause)
        file_params.extend(file_days_params)
    fsql = _FILE_SQL.format(
        extra_filters="".join(f" AND {condition}" for condition in file_conditions)
    )
    frows = conn.execute(fsql, (like_pat, *file_params, limit)).fetchall()
    for r in frows:
        if (r["session_id"], "file") in seen:
            continue
        seen.add((r["session_id"], "file"))
        results.append({"session_id": r["session_id"][:8], "session_id_full": r["session_id"],
                         "source_type": "file", "summary": r["summary"],
                         "date": (r["created_at"] or "")[:10],
                         "excerpt": f"{r['file_path']} ({r['tool_name']})"})
    results = results[:limit]
    debug.log(
        args,
        f"fts_rows={len(rows)} file_rows={len(frows)} final_rows={len(results)} ms={debug.elapsed_ms(t0):.1f}",
    )
    data = {"query": raw_query, "repo": scope.display, "count": len(results), "results": results}
    if getattr(args, "_telemetry", None) is not None:
        args._telemetry["rows"] = len(results)
    output(data, json_mode=getattr(args, 'json', False))
    conn.close()
    return 0
