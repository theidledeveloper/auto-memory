"""Compose an approximate recall bundle from recent files, sessions, and checkpoints."""
from __future__ import annotations

import sys

from ..config import DB_PATH
from ..db.connect import connect_ro
from ..db.schema_check import PATH_SCOPE_SCHEMA, schema_check
from ..util import debug
from ..util.format_output import fmt_json, sanitize_for_terminal
from ..util.resolve_scope import resolve_scope, session_scope_sql
from .list_sessions import _recent_files

APPROX_CHARS_PER_TOKEN = 4
FILE_LIMIT = 10
SESSION_LIMIT = 5
CHECKPOINT_LIMIT = 5
_FILE_LINE_LIMIT = 96
_SESSION_LINE_LIMIT = 120
_CHECKPOINT_LINE_LIMIT = 140
_SELECTION_ORDER = ["files", "sessions", "checkpoints"]
_NOTE = "Approximate/experimental bundle using a 4 chars/token heuristic."


def _one_line(value: str | None) -> str:
    return sanitize_for_terminal(value).replace("\n", " ")


def _truncate(value: str | None, limit: int) -> str:
    text = _one_line(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _load_recent_sessions(conn, scope, limit: int) -> list[dict]:
    conditions = []
    params: list[str] = []
    scope_clause, scope_params = session_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    sql = (
        "SELECT s.id, s.summary, s.created_at "
        "FROM sessions s"
    )
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY s.created_at DESC LIMIT ?"
    rows = conn.execute(sql, (*params, limit)).fetchall()
    return [
        {
            "id_short": row["id"][:8],
            "summary": row["summary"] or "(untitled)",
            "date": (row["created_at"] or "")[:10],
        }
        for row in rows
    ]


def _load_recent_checkpoints(conn, scope, limit: int) -> list[dict]:
    conditions = []
    params: list[str] = []
    scope_clause, scope_params = session_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    sql = (
        "SELECT c.checkpoint_number, c.title, c.overview, c.created_at, c.session_id "
        "FROM checkpoints c "
        "JOIN sessions s ON s.id = c.session_id"
    )
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    rows = conn.execute(sql, (*params, limit)).fetchall()
    return [
        {
            "session_id": row["session_id"][:8],
            "checkpoint_number": row["checkpoint_number"],
            "title": row["title"] or "(untitled)",
            "overview": row["overview"] or "",
            "date": (row["created_at"] or "")[:10],
        }
        for row in rows
    ]


def _file_candidates(files: list[dict]) -> list[dict]:
    return [
        {
            "line": (
                f"- {_truncate(item.get('file_path'), _FILE_LINE_LIMIT)} "
                f"[{_truncate(item.get('tool_name'), 16)}] "
                f"{_truncate(item.get('source'), 18)}"
            ),
            "payload": item,
        }
        for item in files
    ]


def _session_candidates(sessions: list[dict]) -> list[dict]:
    return [
        {
            "line": (
                f"- {item['id_short']} {_truncate(item.get('date'), 10)} "
                f"{_truncate(item.get('summary'), _SESSION_LINE_LIMIT)}"
            ),
            "payload": item,
        }
        for item in sessions
    ]


def _checkpoint_candidates(checkpoints: list[dict]) -> list[dict]:
    return [
        {
            "line": (
                f"- {item['session_id']}#{item['checkpoint_number']} "
                f"{_truncate(item.get('title'), 44)}: "
                f"{_truncate(item.get('overview'), _CHECKPOINT_LINE_LIMIT)}"
            ),
            "payload": item,
        }
        for item in checkpoints
    ]


def _append_line(lines: list[str], line: str, used_chars: int, budget_chars: int) -> tuple[bool, int]:
    addition = len(line) if not lines else len(line) + 1
    if used_chars + addition > budget_chars:
        return False, used_chars
    lines.append(line)
    return True, used_chars + addition


def _fit_budget(scope_display: str, sections: list[tuple[str, list[dict]]], budget_chars: int) -> dict:
    lines: list[str] = []
    used_chars = 0
    selected = {name: [] for name, _ in sections}
    truncated = False

    ok, used_chars = _append_line(lines, f"Context for {_one_line(scope_display)}", used_chars, budget_chars)
    if not ok:
        return {"text": "", "used_chars": 0, "truncated": True, "selected": selected}

    for name, items in sections:
        if not items:
            continue
        start_len = len(lines)
        start_used = used_chars
        heading = f"{name.capitalize()}:"
        ok, used_chars = _append_line(lines, heading, used_chars, budget_chars)
        if not ok:
            truncated = True
            break
        added_any = False
        for item in items:
            ok, used_chars = _append_line(lines, item["line"], used_chars, budget_chars)
            if not ok:
                truncated = True
                break
            selected[name].append(item["payload"])
            added_any = True
        if not added_any:
            lines = lines[:start_len]
            used_chars = start_used
    return {
        "text": "\n".join(lines),
        "used_chars": used_chars,
        "truncated": truncated,
        "selected": selected,
    }


def run(args) -> int:
    scope = resolve_scope(getattr(args, "repo", None))
    budget_tokens = args.budget
    budget_chars = budget_tokens * APPROX_CHARS_PER_TOKEN
    debug.log(args, f"scope mode={scope.mode} display={scope.display} budget_tokens={budget_tokens}")

    conn = connect_ro(DB_PATH, meta=getattr(args, "_telemetry", None))
    try:
        problems = schema_check(conn, PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
        if problems:
            for problem in problems:
                print(f"   - {problem}", file=sys.stderr)
            return 2

        files = _recent_files(conn, scope, days=None, limit=FILE_LIMIT, debug_args=args)
        sessions = _load_recent_sessions(conn, scope, SESSION_LIMIT)
        checkpoints = _load_recent_checkpoints(conn, scope, CHECKPOINT_LIMIT)
        fitted = _fit_budget(
            scope.display,
            [
                ("files", _file_candidates(files)),
                ("sessions", _session_candidates(sessions)),
                ("checkpoints", _checkpoint_candidates(checkpoints)),
            ],
            budget_chars,
        )
        selected = fitted["selected"]
        included_rows = sum(len(selected[name]) for name in _SELECTION_ORDER)
        debug.log(
            args,
            "context "
            f"budget_chars={budget_chars} used_chars={fitted['used_chars']} "
            f"files={len(selected['files'])}/{len(files)} "
            f"sessions={len(selected['sessions'])}/{len(sessions)} "
            f"checkpoints={len(selected['checkpoints'])}/{len(checkpoints)} "
            f"truncated={fitted['truncated']}",
        )
        if getattr(args, "_telemetry", None) is not None:
            args._telemetry["rows"] = included_rows
        payload = {
            "scope": scope.display,
            "approximate": True,
            "experimental": True,
            "selection_order": _SELECTION_ORDER,
            "budget": {
                "tokens": budget_tokens,
                "approx_chars": budget_chars,
                "used_chars": fitted["used_chars"],
                "heuristic": "4 chars/token",
                "truncated": fitted["truncated"],
            },
            "note": _NOTE,
            "files": selected["files"],
            "sessions": selected["sessions"],
            "checkpoints": selected["checkpoints"],
            "text": fitted["text"],
        }
        if getattr(args, "json", False):
            print(fmt_json(payload))
        else:
            print(fitted["text"])
        return 0
    finally:
        conn.close()
