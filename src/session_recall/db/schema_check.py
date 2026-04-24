"""Schema validation against expected Copilot CLI session-store.db structure."""

EXPECTED_SCHEMA: dict[str, set[str]] = {
    "sessions": {"id", "repository", "branch", "summary", "created_at", "updated_at"},
    "turns": {"session_id", "turn_index", "user_message", "assistant_response", "timestamp"},
    "session_files": {"session_id", "file_path", "tool_name", "turn_index", "first_seen_at"},
    "session_refs": {"session_id", "ref_type", "ref_value", "turn_index", "created_at"},
    "checkpoints": {"session_id", "checkpoint_number", "title", "overview", "created_at"},
}

PATH_SCOPE_SCHEMA: dict[str, set[str]] = {"sessions": {"cwd"}}
FILE_FALLBACK_SCHEMA: dict[str, set[str]] = {"checkpoints": {"important_files"}}
SEARCH_INDEX_SCHEMA: dict[str, set[str]] = {
    "search_index": {"content", "session_id", "source_type", "source_id"}
}
FEATURE_SUPPORT_SCHEMA: dict[str, set[str]] = {
    "sessions": {"cwd"},
    "checkpoints": {"important_files"},
}


def schema_check(conn, extra_expected: dict[str, set[str]] | None = None) -> list[str]:
    """Validate DB schema. Returns list of problems (empty = OK)."""
    problems: list[str] = []
    merged_schema = {table: set(cols) for table, cols in EXPECTED_SCHEMA.items()}
    for table, cols in (extra_expected or {}).items():
        merged_schema.setdefault(table, set()).update(cols)
    for table, expected_cols in merged_schema.items():
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            problems.append(f"MISSING TABLE: {table}")
            continue
        actual = {r[1] if isinstance(r, tuple) else r["name"] for r in rows}
        missing = expected_cols - actual
        if missing:
            problems.append(f"{table}: missing columns {missing}")
    return problems
