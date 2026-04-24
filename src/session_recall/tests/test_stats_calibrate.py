"""Tests for stats/calibrate surfaces and debug output."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from .helpers import create_session_store, run_session_recall


def _seed_telemetry(path):
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {"ts": "2026-04-20T00:00:00Z", "cmd": "list", "duration_ms": 20, "busy_hits": 0, "attempts": 1, "tier": 1},
                    {"ts": "2026-04-20T00:01:00Z", "cmd": "search", "duration_ms": 50, "busy_hits": 1, "attempts": 2, "tier": 2, "query_hash": "abcd1234"},
                    {"ts": "2026-04-20T00:02:00Z", "cmd": "show", "duration_ms": 80, "busy_hits": 0, "attempts": 1, "tier": 3, "session_id_prefix": "abcd1234"},
                    {"ts": "2026-04-20T00:03:00Z", "cmd": "health", "duration_ms": 25, "busy_hits": 0, "attempts": 1, "tier": 0},
                ]
            }
        )
    )


def test_stats_reports_telemetry_and_store_summary(tmp_path):
    db_path = create_session_store(tmp_path / "session-store.db", session_count=3)
    telemetry_path = tmp_path / "telemetry.json"
    _seed_telemetry(telemetry_path)

    result = run_session_recall(
        "stats",
        "--json",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["telemetry"]["entries"] == 4
    assert payload["telemetry"]["command_counts"]["list"] == 1
    assert payload["telemetry"]["tier_distribution"]["tier3"] == 1
    assert payload["session_store"]["sessions"] == 3
    assert payload["session_store"]["busiest_repos"][0]["repository"] == "owner/repo"
    assert payload["what_it_means"]


def test_calibrate_analyze_emits_threshold_recommendation(tmp_path):
    db_path = create_session_store(tmp_path / "session-store.db", session_count=1)
    telemetry_path = tmp_path / "telemetry.json"
    telemetry_path.write_text(
        json.dumps(
            {
                "entries": [
                    {"ts": f"2026-04-{day:02d}T00:00:00Z", "cmd": "list", "duration_ms": 20, "tier": 1}
                    for day in range(1, 9)
                ]
                + [
                    {"ts": "2026-04-09T00:00:00Z", "cmd": "search", "duration_ms": 30, "tier": 2, "query_hash": "abcd1234"},
                    {"ts": "2026-04-10T00:00:00Z", "cmd": "show", "duration_ms": 40, "tier": 3, "session_id_prefix": "abcd1234"},
                ]
            }
        )
    )

    result = run_session_recall(
        "calibrate",
        "--analyze",
        "--json",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["sample"]["scored_entries"] == 10
    assert payload["recommendation"]["green_avg_low"] <= payload["recommendation"]["green_avg_high"]
    assert payload["recommendation"]["t3_policy_floor"] == 0.3
    assert "hand-edit dim_disclosure.py" in payload["next_step"]


def test_debug_stderr_stays_off_stdout_for_files(tmp_path):
    db_path = create_session_store(tmp_path / "session-store.db", session_count=1)
    telemetry_path = tmp_path / "telemetry.json"

    result = run_session_recall(
        "--debug",
        "files",
        "--json",
        "--repo",
        "owner/repo",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["count"] == 1
    assert "[debug] scope mode=" in result.stderr
    assert "selected_source=session_files" in result.stderr


def test_health_json_includes_activity_summary(tmp_path):
    db_path = create_session_store(tmp_path / "session-store.db", session_count=2)
    telemetry_path = tmp_path / "telemetry.json"
    _seed_telemetry(telemetry_path)

    result = run_session_recall(
        "health",
        "--json",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["activity_summary"]["entries"] == 4
    assert payload["what_it_means"]


def test_search_debug_does_not_log_raw_query(tmp_path):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_count=1,
        include_search_index=True,
    )
    telemetry_path = tmp_path / "telemetry.json"

    result = run_session_recall(
        "--debug",
        "search",
        "supersecret\x1b[31m",
        "--json",
        "--repo",
        "owner/repo",
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert "supersecret" not in result.stderr
    assert "\x1b" not in result.stderr
    assert "query_hash=" in result.stderr


def test_stats_human_sanitizes_scope_and_repo_names(tmp_path):
    db_path = create_session_store(tmp_path / "session-store.db", session_count=1)
    telemetry_path = tmp_path / "telemetry.json"
    _seed_telemetry(telemetry_path)
    malicious_repo = "owner/\x1b[31mrepo"
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE sessions SET repository = ?", (malicious_repo,))
    conn.commit()
    conn.close()

    result = run_session_recall(
        "stats",
        "--repo",
        malicious_repo,
        env={
            "SESSION_RECALL_DB": str(db_path),
            "SESSION_RECALL_TELEMETRY": str(telemetry_path),
        },
    )

    assert result.returncode == 0
    assert "\x1b" not in result.stdout
    assert "owner/repo" in result.stdout


def test_health_human_sanitizes_detail_and_hint(monkeypatch, capsys):
    from session_recall.commands import health as health_cmd

    class FakeDim:
        @staticmethod
        def check():
            return {
                "name": "Repo\x1b[31m",
                "score": 5.0,
                "zone": "AMBER",
                "detail": "bad\x1b[31mline\nnext",
                "hint": "hint\x1b[31m\nnext",
            }

    monkeypatch.setattr(health_cmd, "DIMS", [FakeDim])
    rc = health_cmd.run(SimpleNamespace(json=False))
    rendered = capsys.readouterr().out

    assert rc == 0
    assert "\x1b" not in rendered
    assert "badline next" in rendered
    assert "hint next" in rendered
