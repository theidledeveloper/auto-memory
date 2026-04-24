"""Shared session-detail query helpers."""
from __future__ import annotations

import re
import sqlite3

_SID_RE = re.compile(r"^[0-9a-fA-F-]{4,}$")


def resolve_session_id(conn: sqlite3.Connection, raw_id: str) -> sqlite3.Row:
    """Resolve a full session row from an exact or prefix ID match."""
    sid = raw_id.strip()
    if not _SID_RE.match(sid) or not sid.replace("-", ""):
        raise ValueError(f"invalid session id '{raw_id}' (expected hex, 4+ chars)")
    sid = sid.lower()
    row = conn.execute(
        "SELECT id, repository, branch, summary, created_at "
        "FROM sessions WHERE id = ?",
        (sid,),
    ).fetchone()
    if row is not None:
        return row
    rows = conn.execute(
        "SELECT id, repository, branch, summary, created_at "
        "FROM sessions WHERE id LIKE ? ORDER BY id LIMIT 2",
        (f"{sid}%",),
    ).fetchall()
    if len(rows) > 1:
        raise ValueError(f"ambiguous session id '{raw_id}' (matches multiple sessions)")
    row = rows[0] if rows else None
    if row is None:
        raise LookupError(f"No session found matching '{sid}'")
    return row


def load_turns(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Load ordered turns for a session."""
    sql = (
        "SELECT turn_index, user_message, assistant_response, timestamp "
        "FROM turns WHERE session_id = ? ORDER BY turn_index"
    )
    params: tuple[str, ...] | tuple[str, int] = (session_id,)
    if limit is not None:
        sql += " LIMIT ?"
        params = (session_id, limit)
    return conn.execute(sql, params).fetchall()


def load_files(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    """Load session_files rows for a session."""
    return conn.execute(
        "SELECT file_path, tool_name, turn_index "
        "FROM session_files WHERE session_id = ?",
        (session_id,),
    ).fetchall()


def load_refs(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    """Load session_refs rows for a session."""
    return conn.execute(
        "SELECT ref_type, ref_value, turn_index "
        "FROM session_refs WHERE session_id = ?",
        (session_id,),
    ).fetchall()


def load_checkpoints(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    """Load ordered checkpoint rows for a session."""
    return conn.execute(
        "SELECT checkpoint_number, title, overview "
        "FROM checkpoints WHERE session_id = ? ORDER BY checkpoint_number",
        (session_id,),
    ).fetchall()


def load_session_detail(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    turn_limit: int | None = None,
    truncate: int = 500,
) -> dict:
    """Load session detail matching the show-command response shape."""
    row = conn.execute(
        "SELECT id, repository, branch, summary, created_at "
        "FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No session found matching '{session_id}'")

    turns_rows = load_turns(conn, session_id, limit=turn_limit)
    turns = [
        {
            "idx": turn["turn_index"],
            "user": (turn["user_message"] or "")[:truncate],
            "assistant": (turn["assistant_response"] or "")[:truncate],
            "timestamp": turn["timestamp"],
        }
        for turn in turns_rows
    ]
    files = [dict(file_row) for file_row in load_files(conn, session_id)]
    refs = [dict(ref_row) for ref_row in load_refs(conn, session_id)]
    checkpoints = [
        {
            "n": checkpoint["checkpoint_number"],
            "title": checkpoint["title"],
            "overview": (checkpoint["overview"] or "")[:300],
        }
        for checkpoint in load_checkpoints(conn, session_id)
    ]
    return {
        "id": row["id"],
        "repository": row["repository"],
        "branch": row["branch"],
        "summary": row["summary"],
        "created_at": row["created_at"],
        "turns_count": len(turns_rows),
        "turns": turns,
        "files": files,
        "refs": refs,
        "checkpoints": checkpoints,
    }
