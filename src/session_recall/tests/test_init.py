"""Tests for the init command."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from session_recall.util.instructions import INSTRUCTION_MARKER


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
    conn.execute("INSERT INTO sessions VALUES ('s1', '/tmp', 'owner/repo', 'main', 'seed', datetime('now'), datetime('now'))")
    conn.commit()
    conn.close()


def test_init_writes_block_once_and_is_idempotent(tmp_path, monkeypatch, capsys):
    instructions = tmp_path / "copilot-instructions.md"
    db_path = tmp_path / "session-store.db"
    _create_db(db_path)

    monkeypatch.setenv("SESSION_RECALL_DB", str(db_path))
    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions)])

    from session_recall.commands.init import run

    args = SimpleNamespace(json=True)
    first = run(args)
    first_out = json.loads(capsys.readouterr().out)
    second = run(args)
    second_out = json.loads(capsys.readouterr().out)

    content = instructions.read_text()
    assert first == 0
    assert second == 0
    assert first_out["changed"] is True
    assert second_out["changed"] is False
    assert content.count(INSTRUCTION_MARKER) == 1
    assert first_out["verification"]["schema_ok"] is True


def test_init_refuses_symlink(tmp_path, monkeypatch, capsys):
    real_file = tmp_path / "real.md"
    real_file.write_text("hello\n")
    symlink = tmp_path / "copilot-instructions.md"
    symlink.symlink_to(real_file)

    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(symlink)])

    from session_recall.commands.init import run

    rc = run(SimpleNamespace(json=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["ok"] is False
    assert "symlink" in out["message"].lower()


def test_init_refuses_directory_instruction_target(tmp_path, monkeypatch, capsys):
    instructions_dir = tmp_path / "copilot-instructions.md"
    instructions_dir.mkdir()

    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions_dir)])

    from session_recall.commands.init import run

    rc = run(SimpleNamespace(json=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["ok"] is False
    assert "not a regular file" in out["message"].lower()


def test_init_reports_locked_db_without_claiming_missing(tmp_path, monkeypatch, capsys):
    instructions = tmp_path / "copilot-instructions.md"
    db_path = tmp_path / "session-store.db"
    db_path.write_text("")

    monkeypatch.setenv("SESSION_RECALL_DB", str(db_path))
    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions)])

    def fail_locked(_):
        raise SystemExit(3)

    monkeypatch.setattr("session_recall.util.db_probe.connect_ro", fail_locked)

    from session_recall.commands.init import run

    rc = run(SimpleNamespace(json=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["verification"]["db_exists"] is True
    assert out["verification"]["connection_ok"] is False
    assert "locked" in out["verification"]["connection_error"].lower()


def test_init_json_handles_existing_directory_db_path(tmp_path, monkeypatch, capsys):
    instructions = tmp_path / "copilot-instructions.md"
    db_dir = tmp_path / "db-dir"
    db_dir.mkdir()

    monkeypatch.setenv("SESSION_RECALL_DB", str(db_dir))
    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions)])

    from session_recall.commands.init import run

    rc = run(SimpleNamespace(json=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["verification"]["db_exists"] is True
    assert out["verification"]["connection_ok"] is False
    assert "could not open database" in out["verification"]["connection_error"].lower()
