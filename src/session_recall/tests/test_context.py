"""Tests for the context bundle command."""
from session_recall.commands.context import _fit_budget


def test_fit_budget_prefers_files_before_sessions_and_checkpoints():
    sections = [
        (
            "files",
            [
                {"line": "- file-a.py [edit] session_files", "payload": {"file_path": "file-a.py"}},
                {"line": "- file-b.py [edit] session_files", "payload": {"file_path": "file-b.py"}},
            ],
        ),
        (
            "sessions",
            [{"line": "- s1 2026-04-24 Session one", "payload": {"id_short": "s1"}}],
        ),
        (
            "checkpoints",
            [{"line": "- s1#1 Checkpoint one: Overview", "payload": {"session_id": "s1"}}],
        ),
    ]

    result = _fit_budget("owner/repo", sections, budget_chars=95)

    assert result["selected"]["files"]
    assert result["selected"]["sessions"] == []
    assert result["selected"]["checkpoints"] == []
    assert "Files:" in result["text"]
    assert "Sessions:" not in result["text"]


def test_fit_budget_stays_within_declared_character_budget():
    sections = [
        ("files", [{"line": "- file-a.py [edit] session_files", "payload": {"file_path": "file-a.py"}}]),
        ("sessions", [{"line": "- s1 2026-04-24 Session one", "payload": {"id_short": "s1"}}]),
    ]

    result = _fit_budget("owner/repo", sections, budget_chars=80)

    assert result["used_chars"] <= 80
    assert len(result["text"]) <= 80
