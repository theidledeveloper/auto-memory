"""Tests for export and diff commands."""
from __future__ import annotations

import json
import sqlite3

from .helpers import create_session_store, run_session_recall


def test_export_writes_markdown_handoff(tmp_path):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_ids=["abcd1234-0000-0000-0000-000000000000"],
    )
    telemetry_path = tmp_path / "telemetry.json"

    result = run_session_recall(
        "export",
        "abcd1234",
        "--format",
        "md",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "# Session Export" in result.stdout
    assert "## Files" in result.stdout
    assert "Checkpoint 1" in result.stdout
    assert "Prompt for session 1" in result.stdout


def test_export_full_includes_all_turns(tmp_path):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_ids=["abcd1234-0000-0000-0000-000000000000"],
    )
    telemetry_path = tmp_path / "telemetry.json"
    conn = sqlite3.connect(db_path)
    for turn_index in range(1, 12):
        conn.execute(
            "INSERT INTO turns VALUES (?, ?, ?, ?, datetime('now'))",
            (
                "abcd1234-0000-0000-0000-000000000000",
                turn_index,
                f"Prompt {turn_index}",
                f"Response {turn_index}",
            ),
        )
    conn.commit()
    conn.close()

    result = run_session_recall(
        "export",
        "abcd1234",
        "--format",
        "md",
        "--full",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert result.stdout.count("### Turn ") == 12
    assert "### Turn 11" in result.stdout


def test_export_uses_longer_fence_than_turn_content(tmp_path):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_ids=["abcd1234-0000-0000-0000-000000000000"],
    )
    telemetry_path = tmp_path / "telemetry.json"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE turns SET user_message = ? WHERE session_id = ? AND turn_index = 0",
        (
            "safe line\n````\ninjected markdown",
            "abcd1234-0000-0000-0000-000000000000",
        ),
    )
    conn.commit()
    conn.close()

    result = run_session_recall(
        "export",
        "abcd1234",
        "--format",
        "md",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert "`````text\nsafe line\n````\ninjected markdown\n`````" in result.stdout


def test_export_escapes_markdown_in_non_turn_fields(tmp_path):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_ids=["abcd1234-0000-0000-0000-000000000000"],
    )
    telemetry_path = tmp_path / "telemetry.json"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE sessions SET summary = ? WHERE id = ?",
        (
            "# heading\n[link](https://example.com)",
            "abcd1234-0000-0000-0000-000000000000",
        ),
    )
    conn.execute(
        "UPDATE session_files SET file_path = ? WHERE session_id = ?",
        (
            "[evil](https://example.com)",
            "abcd1234-0000-0000-0000-000000000000",
        ),
    )
    conn.execute(
        "UPDATE checkpoints SET title = ?, overview = ? WHERE session_id = ?",
        (
            "`tick`",
            "<img src=x onerror=alert(1)>",
            "abcd1234-0000-0000-0000-000000000000",
        ),
    )
    conn.execute(
        "INSERT INTO session_refs VALUES (?, ?, ?, 0, datetime('now'))",
        (
            "abcd1234-0000-0000-0000-000000000000",
            "issue",
            "![alt](javascript:alert(1))",
        ),
    )
    conn.commit()
    conn.close()

    result = run_session_recall(
        "export",
        "abcd1234",
        "--format",
        "md",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert "## Summary\n\n````text\n# heading\n[link](https://example.com)\n````" in result.stdout
    assert r"\[evil\]\(https://example.com\)" in result.stdout
    assert r"- #1: \`tick\`" in result.stdout
    assert r"&lt;img src=x onerror=alert\(1\)&gt;" in result.stdout
    assert r"\!\[alt\]\(javascript:alert\(1\)\)" in result.stdout


def test_diff_returns_structured_metadata_first(tmp_path):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_count=2,
        session_ids=[
            "abcd1234-0000-0000-0000-000000000000",
            "beef5678-1111-1111-1111-111111111111",
        ],
    )
    telemetry_path = tmp_path / "telemetry.json"

    result = run_session_recall(
        "diff",
        "abcd1234",
        "beef5678",
        "--json",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["session_a"]["id"] == "abcd1234-0000-0000-0000-000000000000"
    assert payload["session_b"]["id"] == "beef5678-1111-1111-1111-111111111111"
    assert payload["summary"]["changed"] is True
    assert payload["files"]["added"] == ["/workspace/project/file-2.py"]
    assert payload["files"]["removed"] == ["/workspace/project/file-1.py"]
    assert payload["checkpoints"]["added"] == []
    assert payload["checkpoints"]["removed"] == []
    assert payload["checkpoints"]["changed"] == [
        {
            "n": 1,
            "from": {
                "n": 1,
                "title": "Checkpoint 1",
                "overview": "Overview 1",
            },
            "to": {
                "n": 1,
                "title": "Checkpoint 2",
                "overview": "Overview 2",
            },
        }
    ]
    assert payload["turns_compared"] is False


def test_diff_reports_checkpoint_metadata_changes(tmp_path):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_count=2,
        session_ids=[
            "abcd1234-0000-0000-0000-000000000000",
            "beef5678-1111-1111-1111-111111111111",
        ],
    )
    telemetry_path = tmp_path / "telemetry.json"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET title = ?, overview = ? WHERE session_id = ?",
        (
            "Checkpoint 1",
            "Updated overview",
            "beef5678-1111-1111-1111-111111111111",
        ),
    )
    conn.execute(
        "UPDATE sessions SET summary = ? WHERE id = ?",
        (
            "Session 1",
            "beef5678-1111-1111-1111-111111111111",
        ),
    )
    conn.execute(
        "DELETE FROM session_files WHERE session_id = ?",
        ("beef5678-1111-1111-1111-111111111111",),
    )
    conn.execute(
        "INSERT INTO session_files VALUES (?, ?, ?, 0, datetime('now'))",
        (
            "beef5678-1111-1111-1111-111111111111",
            "/workspace/project/file-1.py",
            "edit",
        ),
    )
    conn.commit()
    conn.close()

    result = run_session_recall(
        "diff",
        "abcd1234",
        "beef5678",
        "--json",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["changed"] is False
    assert payload["files"]["added"] == []
    assert payload["files"]["removed"] == []
    assert payload["checkpoints"]["added"] == []
    assert payload["checkpoints"]["removed"] == []
    assert payload["checkpoints"]["changed"] == [
        {
            "n": 1,
            "from": {
                "n": 1,
                "title": "Checkpoint 1",
                "overview": "Overview 1",
            },
            "to": {
                "n": 1,
                "title": "Checkpoint 1",
                "overview": "Updated overview",
            },
        }
    ]


def test_diff_human_output_surfaces_checkpoint_metadata_change(tmp_path):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_count=2,
        session_ids=[
            "abcd1234-0000-0000-0000-000000000000",
            "beef5678-1111-1111-1111-111111111111",
        ],
    )
    telemetry_path = tmp_path / "telemetry.json"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET overview = ? WHERE session_id = ?",
        (
            "Updated overview",
            "beef5678-1111-1111-1111-111111111111",
        ),
    )
    conn.execute(
        "UPDATE sessions SET summary = ? WHERE id = ?",
        (
            "Session 1",
            "beef5678-1111-1111-1111-111111111111",
        ),
    )
    conn.execute(
        "DELETE FROM session_files WHERE session_id = ?",
        ("beef5678-1111-1111-1111-111111111111",),
    )
    conn.execute(
        "INSERT INTO session_files VALUES (?, ?, ?, 0, datetime('now'))",
        (
            "beef5678-1111-1111-1111-111111111111",
            "/workspace/project/file-1.py",
            "edit",
        ),
    )
    conn.commit()
    conn.close()

    result = run_session_recall(
        "diff",
        "abcd1234",
        "beef5678",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert "Checkpoints" in result.stdout
    assert "~ #1:" in result.stdout
    assert "Overview 1 -> Updated overview" in result.stdout
