"""Direct tests for under-covered health dimensions."""
from __future__ import annotations

import os
import time

from session_recall.health import dim_corpus, dim_e2e, dim_freshness, dim_latency
from session_recall.health import dim_schema, dim_summary_coverage

from .helpers import create_session_store


def test_db_freshness_tracks_file_mtime(tmp_path, monkeypatch):
    db_path = create_session_store(tmp_path / "session-store.db")
    monkeypatch.setattr(dim_freshness, "DB_PATH", str(db_path))

    fresh = dim_freshness.check()
    assert fresh["zone"] == "GREEN"
    assert "h old" in fresh["detail"]

    stale_seconds = time.time() - (10 * 24 * 3600)
    os.utime(db_path, (stale_seconds, stale_seconds))
    stale = dim_freshness.check()
    assert stale["zone"] == "RED"
    assert stale["detail"].endswith("h old")


def test_schema_integrity_and_core_health_dimensions(tmp_path, monkeypatch):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        session_count=12,
        ghost_sessions=1,
        include_important_files=True,
    )
    db_path = str(db_path)

    for module in (dim_schema, dim_latency, dim_corpus, dim_summary_coverage, dim_e2e):
        monkeypatch.setattr(module, "DB_PATH", db_path)

    schema = dim_schema.check()
    assert schema["zone"] == "GREEN"
    assert schema["detail"] == "All tables/columns OK"

    latency = dim_latency.check()
    assert latency["zone"] == "GREEN"
    assert latency["detail"].endswith("ms")

    corpus = dim_corpus.check()
    assert corpus["zone"] == "AMBER"
    assert corpus["detail"] == "13 sessions"

    summary = dim_summary_coverage.check()
    assert summary["zone"] == "GREEN"
    assert "ghost sessions excluded" in summary["detail"]

    e2e = dim_e2e.check()
    assert e2e["zone"] == "GREEN"
    assert "list→show OK" in e2e["detail"]


def test_schema_integrity_flags_missing_feature_columns(tmp_path, monkeypatch):
    db_path = create_session_store(
        tmp_path / "session-store.db",
        include_important_files=False,
    )
    monkeypatch.setattr(dim_schema, "DB_PATH", str(db_path))

    schema = dim_schema.check()
    assert schema["zone"] == "AMBER"
    assert "missing columns" in schema["detail"]
