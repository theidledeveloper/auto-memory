"""Tests for search command schema validation."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace


def _create_db(path):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE sessions (
        id TEXT PRIMARY KEY, cwd TEXT, repository TEXT, branch TEXT,
        summary TEXT, created_at TEXT, updated_at TEXT)""")
    conn.execute("""CREATE TABLE turns (
        session_id TEXT, turn_index INTEGER, user_message TEXT,
        assistant_response TEXT, timestamp TEXT)""")
    conn.execute("""CREATE TABLE session_files (
        session_id TEXT, file_path TEXT, tool_name TEXT, turn_index INTEGER,
        first_seen_at TEXT)""")
    conn.execute("""CREATE TABLE session_refs (
        session_id TEXT, ref_type TEXT, ref_value TEXT, turn_index INTEGER,
        created_at TEXT)""")
    conn.execute("""CREATE TABLE checkpoints (
        session_id TEXT, checkpoint_number INTEGER, title TEXT,
        overview TEXT, important_files TEXT, created_at TEXT)""")
    conn.commit()
    conn.close()


def test_search_reports_missing_search_index_schema(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "session-store.db"
    _create_db(db_path)
    monkeypatch.setenv("SESSION_RECALL_DB", str(db_path))
    monkeypatch.setattr("session_recall.commands.search.DB_PATH", str(db_path))

    from session_recall.commands.search import run

    rc = run(SimpleNamespace(query="memory", repo=None, limit=5, days=None, json=True))
    captured = capsys.readouterr()

    assert rc == 2
    assert "search_index" in captured.err
    assert captured.out == ""
