"""Dim 6: Repo coverage — sessions exist for the current repo."""
from ..db.connect import connect_ro
from ..db.schema_check import PATH_SCOPE_SCHEMA, schema_check
from ..config import DB_PATH
from ..util.resolve_scope import resolve_scope, session_scope_sql

HINT = "Run from the project workspace"


def check() -> dict:
    scope = resolve_scope()
    clause, params = session_scope_sql(scope, repo_col="repository", cwd_col="cwd")
    try:
        conn = connect_ro(DB_PATH)
        problems = schema_check(conn, PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
        if problems:
            conn.close()
            return {"name": "Repo Coverage", "score": 0, "zone": "RED",
                    "detail": "; ".join(problems), "hint": HINT}
        sql = "SELECT COUNT(*) FROM sessions"
        if clause:
            sql += f" WHERE {clause}"
        count = conn.execute(sql, params).fetchone()[0]
        conn.close()
    except Exception as e:
        return {"name": "Repo Coverage", "score": 0, "zone": "RED",
                "detail": str(e), "hint": HINT}
    if count >= 1:
        return {"name": "Repo Coverage", "score": 10, "zone": "GREEN",
                "detail": f"{count} sessions for {scope.display}", "hint": ""}
    return {"name": "Repo Coverage", "score": 5, "zone": "AMBER",
            "detail": f"0 sessions for {scope.display}", "hint": HINT}
