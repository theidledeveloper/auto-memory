"""Tests for files fallback and important_files parsing."""
import json
import os
import sqlite3
import tempfile
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from session_recall.util.parse_important_files import parse_important_files
from session_recall.util.resolve_scope import Scope


def _create_fallback_db() -> str:
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
        "INSERT INTO sessions VALUES ('s_old', '/workspace/project', 'owner/repo', 'main', 'Old session', datetime('now', '-10 days'), datetime('now', '-10 days'), 'local')"
    )
    conn.execute(
        "INSERT INTO sessions VALUES ('s_new', '/workspace/project', 'owner/repo', 'main', 'New session', datetime('now'), datetime('now'), 'local')"
    )
    conn.execute(
        "INSERT INTO session_files VALUES (1, 's_old', '/workspace/project/old.py', 'edit', 0, datetime('now', '-10 days'))"
    )
    conn.execute(
        """INSERT INTO checkpoints VALUES (
            1, 's_new', 1, 'Recent checkpoint', 'overview', '', '', '',
            '- `/workspace/project/new.py`\n- `/workspace/project/README.md`\n  - changed in latest run',
            '', datetime('now')
        )"""
    )
    conn.commit()
    conn.close()
    return path


def test_parse_important_files_extracts_conservative_paths():
    text = """- `/workspace/project/new.py`
- Core spec and source of truth
- AUTO-MEMORY-RECENT-FILES-ANALYSIS.md
  - explains why `session_files` is stale
- ./relative/path.txt
"""
    assert parse_important_files(text) == [
        "/workspace/project/new.py",
        "AUTO-MEMORY-RECENT-FILES-ANALYSIS.md",
        "./relative/path.txt",
    ]


def test_parse_important_files_rejects_route_and_descriptive_text():
    text = """- /settings
- Why it matters: core component for fullscreen barcode/card scan mode
- frontend/src/components/FullScreenCardView.jsx
- .env
- /Users/anthonyscata/.copilot/session-state/abc/plan.md
"""
    assert parse_important_files(text) == [
        "frontend/src/components/FullScreenCardView.jsx",
        ".env",
    ]


def test_parse_important_files_rejects_version_like_bullets():
    text = """- v1.2
- 1.2.3
- release-2026.04
- package.json
"""
    assert parse_important_files(text) == ["package.json"]


def test_files_uses_checkpoint_fallback_when_rows_are_stale():
    path = _create_fallback_db()
    try:
        with patch("session_recall.commands.files.DB_PATH", path), \
             patch(
                 "session_recall.commands.files.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            from session_recall.commands.files import run

            args = SimpleNamespace(repo=None, limit=10, days=7, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            out = json.loads(buf.getvalue())
            assert code == 0
            assert out["source"] == "checkpoint_fallback"
            assert "warning" in out
            assert [f["file_path"] for f in out["files"]] == [
                "/workspace/project/new.py",
                "/workspace/project/README.md",
            ]
            assert all(f["source"] == "checkpoint_fallback" for f in out["files"])
            assert out["files"][0]["checkpoint_title"] == "Recent checkpoint"
    finally:
        os.unlink(path)


def test_files_prefers_primary_rows_when_fresh():
    path = _create_fallback_db()
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO session_files VALUES (2, 's_new', '/workspace/project/live.py', 'edit', 0, datetime('now'))"
        )
        conn.commit()
        conn.close()
        with patch("session_recall.commands.files.DB_PATH", path), \
             patch(
                 "session_recall.commands.files.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            from session_recall.commands.files import run

            args = SimpleNamespace(repo=None, limit=10, days=7, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            out = json.loads(buf.getvalue())
            assert code == 0
            assert out["source"] == "session_files"
            assert "warning" not in out
            assert out["files"][0]["file_path"] == "/workspace/project/live.py"
            assert out["files"][0]["source"] == "session_files"
    finally:
        os.unlink(path)


def test_files_uses_updated_at_to_trigger_fallback_when_rows_are_stale():
    path = _create_fallback_db()
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE sessions SET created_at = datetime('now', '-10 days'), updated_at = datetime('now') WHERE id = 's_new'"
        )
        conn.execute(
            "UPDATE checkpoints SET created_at = datetime('now', '-2 days') WHERE id = 1"
        )
        conn.execute(
            "UPDATE session_files SET first_seen_at = datetime('now', '-2 days') WHERE id = 1"
        )
        conn.commit()
        conn.close()
        with patch("session_recall.commands.files.DB_PATH", path), \
             patch(
                 "session_recall.commands.files.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            from session_recall.commands.files import run

            args = SimpleNamespace(repo=None, limit=10, days=7, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            out = json.loads(buf.getvalue())
            assert code == 0
            assert out["source"] == "checkpoint_fallback"
            assert out["warning"].startswith("session_files rows lag latest activity")
            assert out["files"][0]["file_path"] == "/workspace/project/new.py"
    finally:
        os.unlink(path)


def test_files_uses_turn_timestamp_to_trigger_fallback_when_rows_are_stale():
    path = _create_fallback_db()
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE sessions SET created_at = datetime('now', '-10 days'), updated_at = datetime('now', '-10 days') WHERE id = 's_new'"
        )
        conn.execute(
            "UPDATE checkpoints SET created_at = datetime('now', '-2 days') WHERE id = 1"
        )
        conn.execute(
            "UPDATE session_files SET first_seen_at = datetime('now', '-2 days') WHERE id = 1"
        )
        conn.execute(
            "INSERT INTO turns VALUES (1, 's_new', 0, 'hello', 'hi', datetime('now'))"
        )
        conn.commit()
        conn.close()
        with patch("session_recall.commands.files.DB_PATH", path), \
             patch(
                 "session_recall.commands.files.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            from session_recall.commands.files import run

            args = SimpleNamespace(repo=None, limit=10, days=7, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            out = json.loads(buf.getvalue())
            assert code == 0
            assert out["source"] == "checkpoint_fallback"
            assert out["warning"].startswith("session_files rows lag latest activity")
            assert out["files"][0]["file_path"] == "/workspace/project/new.py"
    finally:
        os.unlink(path)
