"""Tests for shared session-detail query helpers."""
from __future__ import annotations

import sqlite3

import pytest

from session_recall.db.queries import (
    load_checkpoints,
    load_files,
    load_refs,
    load_session_detail,
    load_turns,
    resolve_session_id,
)


def _seed_conn(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY, repository TEXT, branch TEXT, summary TEXT,
            created_at TEXT, updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE turns (
            session_id TEXT, turn_index INTEGER, user_message TEXT,
            assistant_response TEXT, timestamp TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE session_files (
            session_id TEXT, file_path TEXT, tool_name TEXT, turn_index INTEGER,
            first_seen_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE session_refs (
            session_id TEXT, ref_type TEXT, ref_value TEXT, turn_index INTEGER,
            created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE checkpoints (
            session_id TEXT, checkpoint_number INTEGER, title TEXT,
            overview TEXT, created_at TEXT
        )"""
    )

    session_id = "abcd1234-0000-0000-0000-000000000000"
    conn.execute(
        "INSERT INTO sessions VALUES (?, 'repo', 'main', 'test session', '2026-04-17', '2026-04-17')",
        (session_id,),
    )
    long_text = "u" * 600
    assistant_text = "a" * 700
    conn.execute(
        "INSERT INTO turns VALUES (?, 0, ?, ?, '2026-04-17')",
        (session_id, long_text, assistant_text),
    )
    for index in range(1, 5):
        conn.execute(
            "INSERT INTO turns VALUES (?, ?, ?, ?, '2026-04-17')",
            (session_id, index, f"user msg {index}", f"assistant msg {index}"),
        )
    conn.execute(
        "INSERT INTO session_files VALUES (?, '/workspace/project/file.py', 'edit', 0, '2026-04-17')",
        (session_id,),
    )
    conn.execute(
        "INSERT INTO session_refs VALUES (?, 'issue', '42', 0, '2026-04-17')",
        (session_id,),
    )
    conn.execute(
        "INSERT INTO checkpoints VALUES (?, 1, 'Checkpoint 1', ?, '2026-04-17')",
        (session_id, "o" * 400),
    )
    conn.execute(
        "INSERT INTO checkpoints VALUES (?, 2, 'Checkpoint 2', 'short overview', '2026-04-17')",
        (session_id,),
    )
    conn.commit()


@pytest.fixture
def seeded_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed_conn(conn)
    yield conn
    conn.close()


def test_resolve_session_id_accepts_prefix(seeded_conn):
    row = resolve_session_id(seeded_conn, "abcd1234")

    assert row["id"] == "abcd1234-0000-0000-0000-000000000000"
    assert row["repository"] == "repo"


def test_resolve_session_id_accepts_full_id(seeded_conn):
    row = resolve_session_id(seeded_conn, "abcd1234-0000-0000-0000-000000000000")

    assert row["branch"] == "main"


def test_resolve_session_id_rejects_invalid_id(seeded_conn):
    with pytest.raises(ValueError, match="invalid session id"):
        resolve_session_id(seeded_conn, "abc")


def test_resolve_session_id_raises_for_missing_session(seeded_conn):
    with pytest.raises(LookupError, match="No session found matching 'ffff1234'"):
        resolve_session_id(seeded_conn, "ffff1234")


def test_resolve_session_id_rejects_ambiguous_prefix(seeded_conn):
    seeded_conn.execute(
        "INSERT INTO sessions VALUES (?, 'repo', 'main', 'other session', '2026-04-17', '2026-04-17')",
        ("abcd1234-1111-1111-1111-111111111111",),
    )
    seeded_conn.commit()

    with pytest.raises(ValueError, match="ambiguous session id"):
        resolve_session_id(seeded_conn, "abcd1234")


def test_load_row_helpers_return_expected_counts(seeded_conn):
    session_id = "abcd1234-0000-0000-0000-000000000000"

    assert len(load_turns(seeded_conn, session_id, limit=3)) == 3
    assert len(load_files(seeded_conn, session_id)) == 1
    assert len(load_refs(seeded_conn, session_id)) == 1
    assert len(load_checkpoints(seeded_conn, session_id)) == 2


def test_load_session_detail_matches_show_contract(seeded_conn):
    result = load_session_detail(
        seeded_conn,
        "abcd1234-0000-0000-0000-000000000000",
        turn_limit=3,
        truncate=500,
    )

    assert set(result) == {
        "id",
        "repository",
        "branch",
        "summary",
        "created_at",
        "turns_count",
        "turns",
        "files",
        "refs",
        "checkpoints",
    }
    assert result["turns_count"] == 3
    assert len(result["turns"]) == 3
    assert result["files"] == [
        {"file_path": "/workspace/project/file.py", "tool_name": "edit", "turn_index": 0}
    ]
    assert result["refs"] == [
        {"ref_type": "issue", "ref_value": "42", "turn_index": 0}
    ]
    assert result["checkpoints"][0]["n"] == 1
    assert result["checkpoints"][0]["title"] == "Checkpoint 1"


def test_load_session_detail_truncates_turns_but_not_full_mode(seeded_conn):
    session_id = "abcd1234-0000-0000-0000-000000000000"

    truncated = load_session_detail(seeded_conn, session_id, truncate=500)
    full = load_session_detail(seeded_conn, session_id, truncate=99999)

    assert len(truncated["turns"][0]["user"]) == 500
    assert len(truncated["turns"][0]["assistant"]) == 500
    assert len(full["turns"][0]["user"]) == 600
    assert len(full["turns"][0]["assistant"]) == 700


def test_load_session_detail_keeps_checkpoint_overview_at_300(seeded_conn):
    result = load_session_detail(
        seeded_conn,
        "abcd1234-0000-0000-0000-000000000000",
        truncate=99999,
    )

    assert len(result["checkpoints"][0]["overview"]) == 300
