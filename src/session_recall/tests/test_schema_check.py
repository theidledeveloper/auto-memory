"""Tests for db/schema_check.py — schema drift detection."""
import sqlite3
import tempfile
import os
from session_recall.db.schema_check import (
    FEATURE_SUPPORT_SCHEMA,
    FILE_FALLBACK_SCHEMA,
    PATH_SCOPE_SCHEMA,
    EXPECTED_SCHEMA,
    schema_check,
)


def _create_db(tables: dict[str, list[str]]) -> str:
    """Create a temp DB with specified tables/columns."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    for table, cols in tables.items():
        col_defs = ", ".join(f"{c} TEXT" for c in cols)
        conn.execute(f"CREATE TABLE {table} ({col_defs})")
    conn.close()
    return path


def test_correct_schema():
    """All expected tables and columns → no problems."""
    tables = {t: list(cols) for t, cols in EXPECTED_SCHEMA.items() if cols}
    path = _create_db(tables)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        assert schema_check(conn) == []
        conn.close()
    finally:
        os.unlink(path)


def test_missing_column():
    """Missing column in sessions table → reported."""
    tables = {t: list(cols) for t, cols in EXPECTED_SCHEMA.items() if cols}
    tables["sessions"] = [c for c in tables["sessions"] if c != "summary"]
    path = _create_db(tables)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        problems = schema_check(conn)
        assert len(problems) == 1
        assert "summary" in problems[0]
        conn.close()
    finally:
        os.unlink(path)


def test_sessions_cwd_required():
    """Path scope depends on sessions.cwd, so schema drift must flag it."""
    tables = {t: list(cols) for t, cols in EXPECTED_SCHEMA.items() if cols}
    path = _create_db(tables)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        problems = schema_check(conn, PATH_SCOPE_SCHEMA)
        assert any("cwd" in problem for problem in problems)
        conn.close()
    finally:
        os.unlink(path)


def test_checkpoints_important_files_required_for_fallback():
    """Files fallback depends on checkpoints.important_files being present."""
    tables = {t: list(cols) for t, cols in EXPECTED_SCHEMA.items() if cols}
    path = _create_db(tables)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        problems = schema_check(conn, FILE_FALLBACK_SCHEMA)
        assert any("important_files" in problem for problem in problems)
        conn.close()
    finally:
        os.unlink(path)


def test_feature_support_schema_requires_cwd_and_important_files():
    tables = {t: list(cols) for t, cols in EXPECTED_SCHEMA.items() if cols}
    path = _create_db(tables)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        problems = schema_check(conn, FEATURE_SUPPORT_SCHEMA)
        assert any("cwd" in problem for problem in problems)
        assert any("important_files" in problem for problem in problems)
        conn.close()
    finally:
        os.unlink(path)


def test_missing_table():
    """Missing table entirely → reported as MISSING TABLE."""
    tables = {t: list(cols) for t, cols in EXPECTED_SCHEMA.items() if cols and t != "checkpoints"}
    path = _create_db(tables)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        problems = schema_check(conn)
        assert any("MISSING TABLE: checkpoints" in p for p in problems)
        conn.close()
    finally:
        os.unlink(path)


def test_extra_columns_ok():
    """Extra columns beyond expected → no problems (we only check for missing)."""
    tables = {t: list(cols) + ["extra_col"] for t, cols in EXPECTED_SCHEMA.items() if cols}
    path = _create_db(tables)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        assert schema_check(conn) == []
        conn.close()
    finally:
        os.unlink(path)
