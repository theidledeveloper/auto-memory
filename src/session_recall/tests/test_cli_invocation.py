"""End-to-end CLI invocation coverage."""
from __future__ import annotations

import json

from .helpers import create_session_store, run_session_recall


def test_module_entrypoint_list_honors_db_override(tmp_path):
    db_path = create_session_store(tmp_path / "session-store.db", session_count=3)
    telemetry_path = tmp_path / "telemetry.json"
    result = run_session_recall(
        "list",
        "--json",
        "--repo",
        "owner/repo",
        "--limit",
        "1",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["repo"] == "owner/repo"
    assert payload["count"] == 1
    assert payload["sessions"][0]["id_full"].startswith("s")
    assert payload["recent_files"][0]["source"] == "session_files"


def test_module_entrypoint_health_reports_all_dimensions(tmp_path):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_count=12,
        ghost_sessions=1,
    )
    telemetry_path = tmp_path / "telemetry.json"
    result = run_session_recall(
        "health",
        "--json",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert len(payload["dims"]) == 10
    assert any(dim["name"] == "E2E Probe" for dim in payload["dims"])
    assert payload["overall_score"] >= 0
    assert "activity_summary" in payload


def test_module_entrypoint_context_emits_budgeted_bundle(tmp_path):
    db_path = create_session_store(tmp_path / "session-store.db", session_count=3)
    telemetry_path = tmp_path / "telemetry.json"
    result = run_session_recall(
        "context",
        "--budget",
        "120",
        "--json",
        "--repo",
        "owner/repo",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["approximate"] is True
    assert payload["experimental"] is True
    assert payload["selection_order"] == ["files", "sessions", "checkpoints"]
    assert payload["budget"]["tokens"] == 120
    assert payload["budget"]["used_chars"] <= payload["budget"]["approx_chars"]
    assert payload["files"]
    assert payload["text"].startswith("Context for owner/repo")
