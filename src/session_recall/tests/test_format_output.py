"""Human-readable formatter tests."""
from session_recall.util.format_output import output


def test_output_formats_files_human_readably(capsys):
    output(
        {
            "repo": "owner/repo",
            "count": 1,
            "files": [
                {
                    "file_path": "src/app.py",
                    "tool_name": "edit",
                    "source": "session_files",
                    "date": "2026-04-23",
                }
            ],
        },
        json_mode=False,
    )
    rendered = capsys.readouterr().out
    assert "src/app.py" in rendered
    assert "session_files" in rendered
    assert "Date" in rendered


def test_output_formats_checkpoints_human_readably(capsys):
    output(
        {
            "repo": "owner/repo",
            "count": 1,
            "checkpoints": [
                {
                    "checkpoint_number": 2,
                    "title": "Checkpoint title",
                    "overview": "Checkpoint overview",
                    "date": "2026-04-23",
                    "session_id": "abcd1234",
                }
            ],
        },
        json_mode=False,
    )
    rendered = capsys.readouterr().out
    assert "Checkpoint title" in rendered
    assert "Checkpoint overview" in rendered
    assert "#" in rendered


def test_output_formats_search_human_readably(capsys):
    output(
        {
            "query": "memory",
            "count": 1,
            "results": [
                {
                    "session_id": "abcd1234",
                    "date": "2026-04-23",
                    "source_type": "turn",
                    "summary": "Memory fix session",
                    "excerpt": "Investigated memory issue",
                }
            ],
        },
        json_mode=False,
    )
    rendered = capsys.readouterr().out
    assert "Results for 'memory'" in rendered
    assert "Memory fix session" in rendered
    assert "Investigated memory issue" in rendered


def test_output_formats_show_human_readably(capsys):
    output(
        {
            "id": "abcd1234-0000-0000-0000-000000000000",
            "repository": "owner/repo",
            "branch": "main",
            "summary": "Session summary",
            "created_at": "2026-04-23T12:00:00Z",
            "turns_count": 2,
            "files": [{"file_path": "src/app.py", "tool_name": "edit"}],
            "checkpoints": [{"n": 1, "title": "Checkpoint title"}],
            "turns": [{"idx": 0, "user": "How did this break?"}],
        },
        json_mode=False,
    )
    rendered = capsys.readouterr().out
    assert "Session: abcd1234-0000-0000-0000-000000000000" in rendered
    assert "Files:" in rendered
    assert "Checkpoint title" in rendered


def test_output_does_not_misroute_non_show_dicts(capsys):
    output(
        {
            "id": "run-123",
            "turns": [{"idx": 0, "user": "hello"}],
            "files": [{"file_path": "src/app.py", "tool_name": "edit"}],
        },
        json_mode=False,
    )
    rendered = capsys.readouterr().out
    assert "Session:" not in rendered
    assert "src/app.py" in rendered


def test_output_preserves_file_warning_when_empty(capsys):
    output(
        {
            "warning": "Falling back to recent turn mentions because session_files is stale.",
            "files": [],
        },
        json_mode=False,
    )
    rendered = capsys.readouterr().out
    assert "Warning:" in rendered
    assert "session_files is stale" in rendered
    assert "No files found." in rendered


def test_output_preserves_search_warning_when_empty(capsys):
    output(
        {
            "query": "",
            "warning": "Empty query.",
            "results": [],
        },
        json_mode=False,
    )
    rendered = capsys.readouterr().out
    assert "Warning: Empty query." in rendered
    assert "No results found for ''." in rendered


def test_output_strips_carriage_returns_from_terminal_content(capsys):
    output(
        {
            "id": "abcd1234-0000-0000-0000-000000000000",
            "repository": "owner/repo",
            "branch": "main",
            "summary": "before\rafter",
            "created_at": "2026-04-23T12:00:00Z",
            "turns_count": 0,
            "files": [],
            "checkpoints": [],
            "turns": [],
        },
        json_mode=False,
    )
    rendered = capsys.readouterr().out
    assert "\r" not in rendered
    assert "beforeafter" in rendered


def test_output_collapses_newlines_in_search_query_and_excerpt(capsys):
    output(
        {
            "query": "foo\nfake line",
            "count": 1,
            "results": [
                {
                    "session_id": "abcd1234",
                    "date": "2026-04-23",
                    "source_type": "turn",
                    "summary": "Line one\nline two",
                    "excerpt": "Investigated\nmemory issue",
                }
            ],
        },
        json_mode=False,
    )
    rendered = capsys.readouterr().out
    assert "Results for 'foo fake line'" in rendered
    assert "Line one line two" in rendered
    assert "Investigated memory issue" in rendered
