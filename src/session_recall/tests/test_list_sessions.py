"""Tests for commands/list_sessions.py — session listing logic."""
import json
from io import StringIO
import os
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from session_recall.util.resolve_scope import Scope


def _create_test_db() -> str:
    """Create temp DB with test sessions matching real schema."""
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
        title TEXT, overview TEXT, created_at TEXT)""")
    # Insert test data
    conn.execute("INSERT INTO sessions VALUES ('s1', '/workspace/project', 'owner/repo', 'main', 'Test session 1', datetime('now'), datetime('now'), 'local')")
    conn.execute("INSERT INTO sessions VALUES ('s2', '/workspace/project/subdir', 'owner/repo', 'main', 'Test session 2', datetime('now', '-1 day'), datetime('now'), 'local')")
    conn.execute("INSERT INTO sessions VALUES ('s3', '/workspace/other', 'other/repo', 'dev', 'Other repo', datetime('now'), datetime('now'), 'local')")
    conn.execute("INSERT INTO turns VALUES (1, 's1', 0, 'hello', 'hi', datetime('now'))")
    conn.execute("INSERT INTO turns VALUES (2, 's1', 1, 'q2', 'a2', datetime('now'))")
    conn.execute("INSERT INTO session_files VALUES (1, 's1', '/workspace/project/app.py', 'edit', 0, datetime('now'))")
    conn.execute("INSERT INTO session_files VALUES (2, 's2', '/workspace/project/notes.md', 'edit', 0, datetime('now', '-1 day'))")
    conn.execute("INSERT INTO session_files VALUES (3, 's2', '/workspace/project/config.json', 'edit', 0, datetime('now', '-1 day'))")
    conn.execute("INSERT INTO session_files VALUES (4, 's3', '/workspace/other/other.txt', 'edit', 0, datetime('now'))")
    conn.commit()
    conn.close()
    return path


def _create_turn_only_db() -> str:
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
        title TEXT, overview TEXT, created_at TEXT)""")
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/workspace/project', 'owner/repo', 'main', 'Turn fallback session', datetime('now'), datetime('now'), 'local')"
    )
    conn.execute(
        """INSERT INTO turns VALUES (
            1,
            's1',
            0,
            'Please update docs',
            'Touched `README.md` and `.github/skills/rubber-duck-gpt/SKILL.md`.',
            datetime('now')
        )"""
    )
    conn.commit()
    conn.close()
    return path


def test_list_filters_by_repo():
    """List should only return sessions for the specified repo."""
    path = _create_test_db()
    try:
        with patch("session_recall.commands.list_sessions.DB_PATH", path), \
             patch(
                 "session_recall.commands.list_sessions.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            from session_recall.commands.list_sessions import run
            args = SimpleNamespace(repo=None, limit=10, days=30, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            output = json.loads(buf.getvalue())
            assert code == 0
            assert output["count"] == 2  # s1 + s2, not s3
            assert all(s["repository"] == "owner/repo" for s in output["sessions"])
    finally:
        os.unlink(path)


def test_list_respects_limit():
    """List should respect --limit."""
    path = _create_test_db()
    try:
        with patch("session_recall.commands.list_sessions.DB_PATH", path), \
             patch(
                 "session_recall.commands.list_sessions.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            from session_recall.commands.list_sessions import run
            args = SimpleNamespace(repo=None, limit=1, days=30, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                run(args)
            output = json.loads(buf.getvalue())
            assert output["count"] == 1
    finally:
        os.unlink(path)


def test_list_json_shape():
    """JSON output must have repo, count, sessions keys."""
    path = _create_test_db()
    try:
        with patch("session_recall.commands.list_sessions.DB_PATH", path), \
             patch(
                 "session_recall.commands.list_sessions.resolve_scope",
                 return_value=Scope("all", "all", "all"),
             ):
            from session_recall.commands.list_sessions import run
            args = SimpleNamespace(repo="all", limit=10, days=30, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                run(args)
            output = json.loads(buf.getvalue())
            assert "repo" in output
            assert "count" in output
            assert "sessions" in output
            # Should include turns_count
            assert "turns_count" in output["sessions"][0]
    finally:
        os.unlink(path)


def test_list_path_scope_filters_by_workspace_prefix():
    """Path scope should include sessions from nested workspace directories."""
    path = _create_test_db()
    try:
        with patch("session_recall.commands.list_sessions.DB_PATH", path), \
             patch(
                 "session_recall.commands.list_sessions.resolve_scope",
                 return_value=Scope("path", "/workspace/project", "/workspace/project"),
             ):
            from session_recall.commands.list_sessions import run
            args = SimpleNamespace(repo=None, limit=10, days=30, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            output = json.loads(buf.getvalue())
            assert code == 0
            ids = {s["id_full"] for s in output["sessions"]}
            assert ids == {"s1", "s2"}
    finally:
        os.unlink(path)


def test_list_recent_files_include_non_markdown_entries():
    """Embedded recent_files should include code/config files, not just markdown."""
    path = _create_test_db()
    try:
        with patch("session_recall.commands.list_sessions.DB_PATH", path), \
             patch(
                 "session_recall.commands.list_sessions.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            from session_recall.commands.list_sessions import run
            args = SimpleNamespace(repo=None, limit=10, days=30, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            output = json.loads(buf.getvalue())
            assert code == 0
            recent_files = [f["full_path"] for f in output["recent_files"]]
            assert "/workspace/project/app.py" in recent_files
            assert "/workspace/project/config.json" in recent_files
    finally:
        os.unlink(path)


def test_list_recent_files_respect_days_window():
    """Embedded recent_files should respect the same days filter as sessions."""
    path = _create_test_db()
    try:
        with patch("session_recall.commands.list_sessions.DB_PATH", path), \
             patch(
                 "session_recall.commands.list_sessions.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            from session_recall.commands.list_sessions import run

            args = SimpleNamespace(repo=None, limit=10, days=0, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            output = json.loads(buf.getvalue())
            assert code == 0
            assert output["count"] == 1
            assert [f["full_path"] for f in output["recent_files"]] == [
                "/workspace/project/app.py"
            ]
    finally:
        os.unlink(path)


def test_list_recent_files_use_turn_fallback_when_session_files_are_missing():
    path = _create_turn_only_db()
    try:
        with patch("session_recall.commands.list_sessions.DB_PATH", path), \
             patch(
                 "session_recall.commands.list_sessions.resolve_scope",
                 return_value=Scope("repo", "owner/repo", "owner/repo"),
             ):
            from session_recall.commands.list_sessions import run

            args = SimpleNamespace(repo=None, limit=10, days=30, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            output = json.loads(buf.getvalue())
            assert code == 0
            assert [f["full_path"] for f in output["recent_files"]] == [
                "README.md",
                ".github/skills/rubber-duck-gpt/SKILL.md",
            ]
            assert all(f["source"] == "turn_fallback" for f in output["recent_files"])
    finally:
        os.unlink(path)


def test_list_path_scope_does_not_overmatch_wildcard_like_paths():
    """Path scope should treat _ and % literally, not as SQL LIKE wildcards."""
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
        title TEXT, overview TEXT, created_at TEXT)""")
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/workspace/foo_bar', NULL, 'main', 'Target', datetime('now'), datetime('now'), 'local')"
    )
    conn.execute(
        "INSERT INTO sessions VALUES ('s2', '/workspace/fooXbar', NULL, 'main', 'Sibling', datetime('now'), datetime('now'), 'local')"
    )
    conn.execute(
        "INSERT INTO session_files VALUES (1, 's1', '/workspace/foo_bar/app.py', 'edit', 0, datetime('now'))"
    )
    conn.execute(
        "INSERT INTO session_files VALUES (2, 's2', '/workspace/fooXbar/app.py', 'edit', 0, datetime('now'))"
    )
    conn.commit()
    conn.close()
    try:
        with patch("session_recall.commands.list_sessions.DB_PATH", path), \
             patch(
                 "session_recall.commands.list_sessions.resolve_scope",
                 return_value=Scope("path", "/workspace/foo_bar", "/workspace/foo_bar"),
             ):
            from session_recall.commands.list_sessions import run

            args = SimpleNamespace(repo=None, limit=10, days=30, json=True)
            buf = StringIO()
            with patch("sys.stdout", buf):
                code = run(args)
            output = json.loads(buf.getvalue())
            assert code == 0
            assert {s["id_full"] for s in output["sessions"]} == {"s1"}
            assert [f["full_path"] for f in output["recent_files"]] == [
                "/workspace/foo_bar/app.py"
            ]
    finally:
        os.unlink(path)


def test_list_path_scope_reports_schema_drift_when_cwd_missing():
    """Path-scoped list should fail cleanly if sessions.cwd is missing."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE sessions (
        id TEXT PRIMARY KEY, repository TEXT, branch TEXT,
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
        title TEXT, overview TEXT, created_at TEXT)""")
    conn.commit()
    conn.close()
    try:
        with patch("session_recall.commands.list_sessions.DB_PATH", path), \
             patch(
                 "session_recall.commands.list_sessions.resolve_scope",
                 return_value=Scope("path", "/workspace/project", "/workspace/project"),
             ):
            from session_recall.commands.list_sessions import run

            args = SimpleNamespace(repo=None, limit=10, days=30, json=True)
            out = StringIO()
            err = StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", err):
                code = run(args)
            assert code == 2
            assert "Schema drift" in err.getvalue()
            assert "cwd" in err.getvalue()
    finally:
        os.unlink(path)
