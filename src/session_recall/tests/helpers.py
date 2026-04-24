"""Shared test builders and subprocess helpers."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from itertools import zip_longest
from pathlib import Path


def create_session_store(
    path: Path,
    *,
    session_count: int = 1,
    session_ids: list[str] | None = None,
    ghost_sessions: int = 0,
    include_important_files: bool = True,
    include_search_index: bool = False,
) -> Path:
    """Create a small SQLite store that mirrors the production schema."""
    if session_ids is not None and len(session_ids) != session_count:
        raise ValueError("session_ids length must match session_count")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY, cwd TEXT, repository TEXT, branch TEXT,
            summary TEXT, created_at TEXT, updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE turns (
            session_id TEXT, turn_index INTEGER, user_message TEXT,
            assistant_response TEXT, timestamp TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE session_files (
            session_id TEXT, file_path TEXT, tool_name TEXT, turn_index INTEGER,
            first_seen_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE session_refs (
            session_id TEXT, ref_type TEXT, ref_value TEXT, turn_index INTEGER,
            created_at TEXT
        )"""
    )
    if include_important_files:
        conn.execute(
            """CREATE TABLE checkpoints (
                session_id TEXT, checkpoint_number INTEGER, title TEXT,
                overview TEXT, history TEXT, work_done TEXT,
                technical_details TEXT, important_files TEXT, next_steps TEXT,
                created_at TEXT
            )"""
        )
    else:
        conn.execute(
            """CREATE TABLE checkpoints (
                session_id TEXT, checkpoint_number INTEGER, title TEXT,
                overview TEXT, history TEXT, work_done TEXT,
                technical_details TEXT, next_steps TEXT, created_at TEXT
            )"""
        )
    if include_search_index:
        conn.execute(
            """CREATE VIRTUAL TABLE search_index USING fts5(
                content, session_id UNINDEXED, source_type UNINDEXED, source_id UNINDEXED
            )"""
        )

    for index in range(session_count):
        session_id = session_ids[index] if session_ids is not None else f"s{index + 1}"
        age = f"-{index} days" if index else "0 days"
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, datetime('now', ?), datetime('now', ?))",
            (
                session_id,
                "/workspace/project",
                "owner/repo",
                "main",
                f"Session {index + 1}",
                age,
                age,
            ),
        )
        conn.execute(
            "INSERT INTO turns VALUES (?, 0, ?, ?, datetime('now', ?))",
            (
                session_id,
                f"Prompt for session {index + 1}",
                f"Response for session {index + 1}",
                age,
            ),
        )
        conn.execute(
            "INSERT INTO session_files VALUES (?, ?, ?, 0, datetime('now', ?))",
            (
                session_id,
                f"/workspace/project/file-{index + 1}.py",
                "edit",
                age,
            ),
        )
        if include_important_files:
            conn.execute(
                """INSERT INTO checkpoints VALUES (
                    ?, 1, ?, ?, '', '', '',
                    ?, '', datetime('now', ?)
                )""",
                (
                    session_id,
                    f"Checkpoint {index + 1}",
                    f"Overview {index + 1}",
                    f"- `/workspace/project/file-{index + 1}.py`",
                    age,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO checkpoints VALUES (
                    ?, 1, ?, ?, '', '', '',
                    '', datetime('now', ?)
                )""",
                (
                    session_id,
                    f"Checkpoint {index + 1}",
                    f"Overview {index + 1}",
                    age,
                ),
            )
        if include_search_index:
            conn.execute(
                "INSERT INTO search_index (content, session_id, source_type, source_id) VALUES (?, ?, 'turn', '1')",
                (f"content about session {index + 1}", session_id),
            )

    for index in range(ghost_sessions):
        session_id = f"ghost-{index + 1}"
        age = f"-{session_count + index} days"
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, datetime('now', ?), datetime('now', ?))",
            (
                session_id,
                "/workspace/project",
                "owner/repo",
                "main",
                None,
                age,
                age,
            ),
        )

    conn.commit()
    conn.close()
    return path


def run_session_recall(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run the real module entrypoint in a subprocess."""
    repo_root = Path(__file__).resolve().parents[3]
    child_env = os.environ.copy()
    pythonpath = str(repo_root / "src")
    if child_env.get("PYTHONPATH"):
        pythonpath = os.pathsep.join((pythonpath, child_env["PYTHONPATH"]))
    child_env["PYTHONPATH"] = pythonpath
    if env:
        child_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "session_recall", *args],
        cwd=repo_root,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )


def create_claude_history(root: Path, *, sessions: list[dict]) -> Path:
    """Create a small Claude Code projects tree for adapter tests."""
    root = root.resolve()
    projects_root = root / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)

    for index, spec in enumerate(sessions):
        cwd = Path(spec["cwd"]).resolve()
        cwd.mkdir(parents=True, exist_ok=True)
        session_id = spec["session_id"]
        branch = spec.get("branch", "main")
        base_time = spec.get("base_time", f"2026-04-{10 + index:02d}T12:00:00Z")
        user_messages = spec.get("user_messages", [f"Prompt for {session_id}"])
        assistant_messages = spec.get("assistant_messages", [f"Response for {session_id}"])
        project_dir = projects_root / _normalize_claude_project_dir(str(cwd))
        project_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = project_dir / f"{session_id}.jsonl"
        records: list[dict] = []
        for turn_index, (user_text, assistant_text) in enumerate(
            zip_longest(user_messages, assistant_messages, fillvalue="")
        ):
            user_ts = _offset_timestamp(base_time, turn_index * 2)
            assistant_ts = _offset_timestamp(base_time, turn_index * 2 + 1)
            if user_text:
                records.append(
                    {
                        "sessionId": session_id,
                        "cwd": str(cwd),
                        "gitBranch": branch,
                        "type": "user",
                        "timestamp": user_ts,
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": user_text}],
                        },
                    }
                )
            if assistant_text:
                records.append(
                    {
                        "sessionId": session_id,
                        "cwd": str(cwd),
                        "gitBranch": branch,
                        "type": "assistant",
                        "timestamp": assistant_ts,
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": assistant_text}],
                        },
                    }
                )
        transcript_path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )

    return root


def _normalize_claude_project_dir(project_path: str) -> str:
    normalized = project_path.replace("\\", "/").replace("/", "-").replace(".", "-").replace("_", "-")
    normalized = normalized[1:] if normalized.startswith("-") else normalized
    return f"-{normalized}"


def _offset_timestamp(base: str, minutes: int) -> str:
    hour = 12 + ((minutes // 60) % 10)
    minute = minutes % 60
    date = base.split("T", 1)[0]
    return f"{date}T{hour:02d}:{minute:02d}:00Z"
