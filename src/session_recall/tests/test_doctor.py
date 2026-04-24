"""Tests for the doctor command."""
from __future__ import annotations

import json
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
    conn.execute("INSERT INTO sessions VALUES ('s1', '/tmp', 'owner/repo', 'main', 'seed', datetime('now'), datetime('now'))")
    conn.commit()
    conn.close()


def test_doctor_reports_ready_with_env_overrides(tmp_path, monkeypatch, capsys):
    instructions = tmp_path / "copilot-instructions.md"
    instructions.write_text("## Progressive Session Recall — RUN FIRST ON EVERY PROMPT\n")
    db_path = tmp_path / "session-store.db"
    telemetry_path = tmp_path / "telemetry.json"
    _create_db(db_path)

    monkeypatch.setenv("SESSION_RECALL_DB", str(db_path))
    monkeypatch.setenv("SESSION_RECALL_TELEMETRY", str(telemetry_path))
    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions)])
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/session-recall")

    from session_recall.commands.doctor import run

    rc = run(SimpleNamespace(json=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert out["paths"]["db"] == str(db_path)
    assert out["paths"]["telemetry"] == str(telemetry_path)
    telemetry_check = next(check for check in out["checks"] if check["name"] == "telemetry")
    assert telemetry_check["ok"] is True


def test_doctor_reports_missing_instruction_block(tmp_path, monkeypatch, capsys):
    instructions = tmp_path / "copilot-instructions.md"
    instructions.write_text("# empty\n")
    db_path = tmp_path / "session-store.db"
    _create_db(db_path)

    monkeypatch.setenv("SESSION_RECALL_DB", str(db_path))
    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions)])
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/session-recall")

    from session_recall.commands.doctor import run

    rc = run(SimpleNamespace(json=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["ok"] is False
    instruction_check = next(check for check in out["checks"] if check["name"] == "instructions")
    assert "missing" in instruction_check["detail"].lower()


def test_doctor_reports_directory_instruction_target(tmp_path, monkeypatch, capsys):
    instructions_dir = tmp_path / "copilot-instructions.md"
    instructions_dir.mkdir()
    db_path = tmp_path / "session-store.db"
    _create_db(db_path)

    monkeypatch.setenv("SESSION_RECALL_DB", str(db_path))
    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions_dir)])
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/session-recall")

    from session_recall.commands.doctor import run

    rc = run(SimpleNamespace(json=True))
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert rc == 1
    assert captured.err == ""
    instruction_check = next(check for check in out["checks"] if check["name"] == "instructions")
    assert "not a regular file" in instruction_check["detail"].lower()


def test_doctor_json_keeps_stderr_clean_for_missing_db(tmp_path, monkeypatch, capsys):
    instructions = tmp_path / "copilot-instructions.md"
    instructions.write_text("## Progressive Session Recall — RUN FIRST ON EVERY PROMPT\n")
    missing_db = tmp_path / "missing.db"

    monkeypatch.setenv("SESSION_RECALL_DB", str(missing_db))
    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions)])
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/session-recall")

    from session_recall.commands.doctor import run

    rc = run(SimpleNamespace(json=True))
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert rc == 1
    assert captured.err == ""
    db_check = next(check for check in out["checks"] if check["name"] == "db_path")
    assert "not found" in db_check["detail"].lower()


def test_doctor_human_ready_message_does_not_tell_user_to_rerun_init(
    tmp_path, monkeypatch, capsys
):
    instructions = tmp_path / "copilot-instructions.md"
    instructions.write_text("## Progressive Session Recall — RUN FIRST ON EVERY PROMPT\n")
    db_path = tmp_path / "session-store.db"
    _create_db(db_path)

    monkeypatch.setenv("SESSION_RECALL_DB", str(db_path))
    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions)])
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/session-recall")

    from session_recall.commands.doctor import run

    rc = run(SimpleNamespace(json=False))
    rendered = capsys.readouterr().out
    assert rc == 0
    assert "Ready. Init block, schema, and active DB wiring all look good." in rendered


def test_doctor_json_handles_existing_directory_db_path(tmp_path, monkeypatch, capsys):
    instructions = tmp_path / "copilot-instructions.md"
    instructions.write_text("## Progressive Session Recall — RUN FIRST ON EVERY PROMPT\n")
    db_dir = tmp_path / "db-dir"
    db_dir.mkdir()

    monkeypatch.setenv("SESSION_RECALL_DB", str(db_dir))
    monkeypatch.setattr("session_recall.util.instructions.INSTRUCTION_PATHS", [str(instructions)])
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/session-recall")

    from session_recall.commands.doctor import run

    rc = run(SimpleNamespace(json=True))
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert rc == 1
    assert captured.err == ""
    db_check = next(check for check in out["checks"] if check["name"] == "db_path")
    assert "could not open database" in db_check["detail"].lower()
