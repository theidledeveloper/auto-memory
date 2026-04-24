"""Adapter coverage for Claude-backed session recall."""

from __future__ import annotations

import json
from pathlib import Path

from .helpers import create_claude_history, run_session_recall


SESSION_A = "11111111-1111-1111-1111-111111111111"
SESSION_B = "22222222-2222-2222-2222-222222222222"


def _claude_env(tmp_path) -> dict[str, str]:
    claude_root = create_claude_history(
        tmp_path / ".claude",
        sessions=[
            {
                "session_id": SESSION_A,
                "cwd": tmp_path / "workspace" / "owner" / "repo-a",
                "branch": "main",
                "base_time": "2026-04-10T12:00:00Z",
                "user_messages": [
                    "Investigate adapter boundary",
                    "Wire list and show first",
                ],
                "assistant_messages": [
                    "Use a query-result seam.",
                    "Keep Cursor out for now.",
                ],
            },
            {
                "session_id": SESSION_B,
                "cwd": tmp_path / "workspace" / "owner" / "repo-b",
                "branch": "feature/claude",
                "base_time": "2026-04-11T12:00:00Z",
                "user_messages": ["Export this conversation as markdown"],
                "assistant_messages": ["Markdown export is ready."],
            },
        ],
    )
    return {
        "CLAUDE_CONFIG_DIR": str(claude_root),
        "SESSION_RECALL_TELEMETRY": str(tmp_path / "telemetry.json"),
    }


def _transcript_path(claude_root: Path, session_id: str) -> Path:
    return next((claude_root / "projects").rglob(f"{session_id}.jsonl"))


def test_list_supports_claude_source(tmp_path):
    result = run_session_recall(
        "list",
        "--source",
        "claude",
        "--json",
        "--repo",
        "all",
        env=_claude_env(tmp_path),
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["count"] == 2
    assert [session["id_full"] for session in payload["sessions"]] == [SESSION_B, SESSION_A]
    assert payload["recent_files"] == []
    assert payload["sessions"][0]["summary"] == "Export this conversation as markdown"


def test_show_uses_env_default_source_for_claude(tmp_path):
    env = _claude_env(tmp_path)
    env["SESSION_RECALL_SOURCE"] = "claude"
    result = run_session_recall(
        "show",
        SESSION_A[:8],
        "--json",
        "--turns",
        "1",
        env=env,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["id"] == SESSION_A
    assert payload["branch"] == "main"
    assert payload["summary"] == "Investigate adapter boundary"
    assert payload["turns_count"] == 2
    assert payload["turns"][0]["user"] == "Investigate adapter boundary"
    assert payload["turns"][0]["assistant"] == "Use a query-result seam."


def test_invalid_env_default_source_fails_fast(tmp_path):
    env = _claude_env(tmp_path)
    env["SESSION_RECALL_SOURCE"] = "bogus"
    result = run_session_recall(
        "list",
        "--json",
        "--repo",
        "all",
        env=env,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid session source 'bogus'" in result.stderr


def test_export_supports_claude_source(tmp_path):
    result = run_session_recall(
        "export",
        SESSION_A[:8],
        "--source",
        "claude",
        "--format",
        "md",
        env=_claude_env(tmp_path),
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "# Session Export" in result.stdout
    assert "Investigate adapter boundary" in result.stdout
    assert "Use a query-result seam." in result.stdout
    assert "_No files recorded._" in result.stdout


def test_export_preserves_multiline_turn_content(tmp_path):
    claude_root = create_claude_history(
        tmp_path / ".claude",
        sessions=[
            {
                "session_id": SESSION_A,
                "cwd": tmp_path / "workspace" / "owner" / "repo-a",
                "branch": "main",
                "base_time": "2026-04-10T12:00:00Z",
                "user_messages": ["Fix this:\n\ndef foo(x):\n    return x + 1\n\nIt should multiply."],
                "assistant_messages": ["Try this instead:\n\ndef foo(x):\n    return x * 2"],
            },
        ],
    )
    result = run_session_recall(
        "export",
        SESSION_A[:8],
        "--source",
        "claude",
        "--format",
        "md",
        env={
            "CLAUDE_CONFIG_DIR": str(claude_root),
            "SESSION_RECALL_TELEMETRY": str(tmp_path / "telemetry.json"),
        },
    )

    assert result.returncode == 0
    assert "Fix this:\n\ndef foo(x):\n    return x + 1\n\nIt should multiply." in result.stdout
    assert "Try this instead:\n\ndef foo(x):\n    return x * 2" in result.stdout


def test_list_ignores_transcript_when_record_session_id_mismatches_filename(tmp_path):
    env = _claude_env(tmp_path)
    transcript = _transcript_path(Path(env["CLAUDE_CONFIG_DIR"]), SESSION_A)
    records = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()]
    for record in records:
        record["sessionId"] = SESSION_B
    transcript.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    result = run_session_recall(
        "list",
        "--source",
        "claude",
        "--json",
        "--repo",
        "all",
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert [session["id_full"] for session in payload["sessions"]] == [SESSION_B]


def test_duplicate_claude_session_ids_are_rejected(tmp_path):
    claude_root = create_claude_history(
        tmp_path / ".claude",
        sessions=[
            {
                "session_id": SESSION_A,
                "cwd": tmp_path / "workspace" / "owner" / "repo-a",
                "branch": "main",
                "base_time": "2026-04-10T12:00:00Z",
                "user_messages": ["first copy"],
                "assistant_messages": ["first response"],
            },
            {
                "session_id": SESSION_A,
                "cwd": tmp_path / "workspace" / "owner" / "repo-b",
                "branch": "feature/dup",
                "base_time": "2026-04-11T12:00:00Z",
                "user_messages": ["second copy"],
                "assistant_messages": ["second response"],
            },
        ],
    )
    result = run_session_recall(
        "list",
        "--source",
        "claude",
        "--json",
        "--repo",
        "all",
        env={
            "CLAUDE_CONFIG_DIR": str(claude_root),
            "SESSION_RECALL_TELEMETRY": str(tmp_path / "telemetry.json"),
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["count"] == 0
    assert payload["sessions"] == []


def test_diff_claude_warns_when_only_summary_is_compared(tmp_path):
    result = run_session_recall(
        "diff",
        SESSION_A[:8],
        SESSION_B[:8],
        "--source",
        "claude",
        "--json",
        env=_claude_env(tmp_path),
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["summary"]["changed"] is True
    assert payload["files"]["added"] == []
    assert payload["files"]["removed"] == []
    assert payload["checkpoints"]["changed"] == []
    assert "summary only" in payload["warning"]
