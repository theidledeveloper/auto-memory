"""Tests for health/dim_file_freshness.py."""
import os
import sqlite3
import tempfile
from unittest.mock import patch

from session_recall.util.resolve_scope import Scope


def _create_db(stale: bool) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE sessions (
        id TEXT PRIMARY KEY, cwd TEXT, repository TEXT, branch TEXT,
        summary TEXT, created_at TEXT, updated_at TEXT, host_type TEXT)""")
    conn.execute("""CREATE TABLE turns (
        id INTEGER PRIMARY KEY, session_id TEXT, turn_index INTEGER,
        user_message TEXT, assistant_response TEXT, timestamp TEXT)""")
    conn.execute("""CREATE TABLE session_files (
        id INTEGER PRIMARY KEY, session_id TEXT, file_path TEXT,
        tool_name TEXT, turn_index INTEGER, first_seen_at TEXT)""")
    conn.execute("""CREATE TABLE session_refs (
        id INTEGER PRIMARY KEY, session_id TEXT, ref_type TEXT,
        ref_value TEXT, turn_index INTEGER, created_at TEXT)""")
    conn.execute("""CREATE TABLE checkpoints (
        id INTEGER PRIMARY KEY, session_id TEXT, checkpoint_number INTEGER,
        title TEXT, overview TEXT, history TEXT, work_done TEXT,
        technical_details TEXT, important_files TEXT, next_steps TEXT,
        created_at TEXT)""")
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/workspace/project', 'owner/repo', 'main', 'Session', datetime('now'), datetime('now'), 'local')"
    )
    conn.execute(
        "INSERT INTO checkpoints VALUES (1, 's1', 1, 'Checkpoint', 'overview', '', '', '', '- `/workspace/project/app.py`', '', datetime('now'))"
    )
    file_age = "-10 days" if stale else "0 days"
    conn.execute(
        "INSERT INTO session_files VALUES (1, 's1', '/workspace/project/app.py', 'edit', 0, datetime('now', ?))",
        (file_age,),
    )
    conn.commit()
    conn.close()
    return path


def _create_turn_hint_db() -> str:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE sessions (
        id TEXT PRIMARY KEY, cwd TEXT, repository TEXT, branch TEXT,
        summary TEXT, created_at TEXT, updated_at TEXT, host_type TEXT)""")
    conn.execute("""CREATE TABLE turns (
        id INTEGER PRIMARY KEY, session_id TEXT, turn_index INTEGER,
        user_message TEXT, assistant_response TEXT, timestamp TEXT)""")
    conn.execute("""CREATE TABLE session_files (
        id INTEGER PRIMARY KEY, session_id TEXT, file_path TEXT,
        tool_name TEXT, turn_index INTEGER, first_seen_at TEXT)""")
    conn.execute("""CREATE TABLE session_refs (
        id INTEGER PRIMARY KEY, session_id TEXT, ref_type TEXT,
        ref_value TEXT, turn_index INTEGER, created_at TEXT)""")
    conn.execute("""CREATE TABLE checkpoints (
        id INTEGER PRIMARY KEY, session_id TEXT, checkpoint_number INTEGER,
        title TEXT, overview TEXT, history TEXT, work_done TEXT,
        technical_details TEXT, important_files TEXT, next_steps TEXT,
        created_at TEXT)""")
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/workspace/project', 'owner/repo', 'main', 'Session', datetime('now'), datetime('now'), 'local')"
    )
    conn.execute(
        """INSERT INTO turns VALUES (
            1,
            's1',
            0,
            'update docs',
            'Touched `README.md` during latest run.',
            datetime('now')
        )"""
    )
    conn.commit()
    conn.close()
    return path


def test_file_freshness_amber_when_checkpoint_fallback_is_current():
    path = _create_db(stale=True)
    try:
        from session_recall.health.dim_file_freshness import check

        with patch("session_recall.health.dim_file_freshness.DB_PATH", path), \
             patch(
                  "session_recall.health.dim_file_freshness.resolve_scope",
                  return_value=Scope("repo", "owner/repo", "owner/repo"),
              ):
            out = check()
        assert out["zone"] == "AMBER"
        assert out["detail"].startswith("session_files rows are stale; checkpoint fallback")
    finally:
        os.unlink(path)


def test_file_freshness_green_when_rows_are_current():
    path = _create_db(stale=False)
    try:
        from session_recall.health.dim_file_freshness import check

        with patch("session_recall.health.dim_file_freshness.DB_PATH", path), \
             patch(
                 "session_recall.health.dim_file_freshness.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            out = check()
        assert out["zone"] == "GREEN"
    finally:
        os.unlink(path)


def test_file_freshness_uses_updated_at_for_latest_activity():
    path = _create_db(stale=False)
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE sessions SET created_at = datetime('now', '-10 days'), updated_at = datetime('now') WHERE id = 's1'"
        )
        conn.execute(
            "UPDATE checkpoints SET created_at = datetime('now', '-10 days') WHERE id = 1"
        )
        conn.execute(
            "UPDATE session_files SET first_seen_at = datetime('now', '-10 days') WHERE id = 1"
        )
        conn.commit()
        conn.close()

        from session_recall.health.dim_file_freshness import check

        with patch("session_recall.health.dim_file_freshness.DB_PATH", path), \
             patch(
                 "session_recall.health.dim_file_freshness.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            out = check()
        assert out["zone"] == "RED"
    finally:
        os.unlink(path)


def test_file_freshness_uses_turn_timestamp_for_latest_activity():
    path = _create_db(stale=False)
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO turns VALUES (1, 's1', 0, 'hello', 'hi', datetime('now'))"
        )
        conn.execute(
            "UPDATE sessions SET created_at = datetime('now', '-10 days'), updated_at = datetime('now', '-10 days') WHERE id = 's1'"
        )
        conn.execute(
            "UPDATE checkpoints SET created_at = datetime('now', '-10 days') WHERE id = 1"
        )
        conn.execute(
            "UPDATE session_files SET first_seen_at = datetime('now', '-10 days') WHERE id = 1"
        )
        conn.commit()
        conn.close()

        from session_recall.health.dim_file_freshness import check

        with patch("session_recall.health.dim_file_freshness.DB_PATH", path), \
             patch(
                 "session_recall.health.dim_file_freshness.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            out = check()
        assert out["zone"] == "RED"
    finally:
        os.unlink(path)


def test_file_freshness_amber_when_turn_fallback_is_current():
    path = _create_turn_hint_db()
    try:
        from session_recall.health.dim_file_freshness import check

        with patch("session_recall.health.dim_file_freshness.DB_PATH", path), \
             patch(
                 "session_recall.health.dim_file_freshness.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            out = check()
        assert out["zone"] == "AMBER"
        assert out["detail"].startswith("no session_files rows in scope; turn fallback")
    finally:
        os.unlink(path)


def test_file_freshness_handles_mixed_timezone_formats():
    path = _create_db(stale=True)
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE session_files SET first_seen_at = '2026-04-01T10:00:00Z' WHERE id = 1"
        )
        conn.execute(
            "UPDATE checkpoints SET created_at = '2026-04-23 10:00:00' WHERE id = 1"
        )
        conn.execute(
            "UPDATE sessions SET created_at = '2026-04-23 10:00:00', updated_at = '2026-04-23 10:00:00' WHERE id = 's1'"
        )
        conn.commit()
        conn.close()

        from session_recall.health.dim_file_freshness import check

        with patch("session_recall.health.dim_file_freshness.DB_PATH", path), \
             patch(
                 "session_recall.health.dim_file_freshness.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            out = check()
        assert out["zone"] == "AMBER"
        assert "checkpoint fallback" in out["detail"]
    finally:
        os.unlink(path)


def test_file_freshness_ignores_stale_turn_fallback_outside_recent_window():
    path = _create_turn_hint_db()
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE turns SET timestamp = datetime('now', '-10 days') WHERE id = 1"
        )
        conn.execute(
            "UPDATE sessions SET updated_at = datetime('now') WHERE id = 's1'"
        )
        conn.commit()
        conn.close()

        from session_recall.health.dim_file_freshness import check

        with patch("session_recall.health.dim_file_freshness.DB_PATH", path), \
             patch(
                 "session_recall.health.dim_file_freshness.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            out = check()
        assert out["zone"] == "RED"
        assert out["detail"] == "no file rows for current scope"
    finally:
        os.unlink(path)
