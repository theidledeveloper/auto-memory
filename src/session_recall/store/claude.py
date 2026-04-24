"""Claude Code JSONL-backed store implementation."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..util.detect_repo import detect_repo
from ..util.resolve_scope import Scope

_SID_RE = re.compile(r"^[0-9a-fA-F-]{4,}$")
_UUID_JSONL_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.jsonl$"
)


@dataclass(frozen=True)
class _ClaudeSession:
    id: str
    file_path: Path
    cwd: str
    repository: str
    branch: str
    summary: str
    created_at: str
    updated_at: str


class ClaudeStore:
    """Read Claude Code transcripts from ~/.claude/projects."""

    source = "claude"

    def __init__(self):
        root = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()
        self.projects_root = root / "projects"
        self._sessions: list[_ClaudeSession] | None = None

    def close(self) -> None:
        return None

    def list_sessions(self, scope: Scope, *, days: int | None, limit: int) -> list[dict]:
        sessions = [item for item in self._load_sessions() if _matches_scope(item, scope) and _matches_days(item, days)]
        sessions.sort(key=lambda item: item.created_at, reverse=True)
        selected = sessions[:limit]
        results: list[dict] = []
        for item in selected:
            turns = _pair_turns(_load_message_events(item.file_path), truncate=0)
            results.append(
                {
                    "id_short": item.id[:8],
                    "id_full": item.id,
                    "repository": item.repository,
                    "branch": item.branch,
                    "summary": item.summary,
                    "date": item.created_at[:10] if item.created_at else None,
                    "created_at": item.created_at,
                    "turns_count": len(turns),
                    "files_count": 0,
                }
            )
        return results

    def recent_files(
        self,
        scope: Scope,
        *,
        days: int | None,
        limit: int,
    ) -> tuple[list[dict], str, str | None]:
        del scope, days, limit
        return [], "claude_unavailable", None

    def resolve_session_id(self, raw_id: str) -> dict:
        sid = raw_id.strip()
        if not _SID_RE.match(sid) or not sid.replace("-", ""):
            raise ValueError(f"invalid session id '{raw_id}' (expected hex, 4+ chars)")
        sid = sid.lower()
        exact = [item for item in self._load_sessions() if item.id.lower() == sid]
        if exact:
            return _session_row(exact[0])
        prefix = [item for item in self._load_sessions() if item.id.lower().startswith(sid)]
        if len(prefix) > 1:
            raise ValueError(f"ambiguous session id '{raw_id}' (matches multiple sessions)")
        if not prefix:
            raise LookupError(f"No session found matching '{sid}'")
        return _session_row(prefix[0])

    def load_session_detail(
        self,
        session_id: str,
        *,
        turn_limit: int | None,
        truncate: int,
    ) -> dict:
        item = self._session_by_id(session_id)
        turns = _pair_turns(_load_message_events(item.file_path), truncate=truncate)
        selected_turns = turns if turn_limit is None else turns[:turn_limit]
        return {
            "id": item.id,
            "repository": item.repository,
            "branch": item.branch,
            "summary": item.summary,
            "created_at": item.created_at,
            "turns_count": len(turns),
            "turns": selected_turns,
            "files": [],
            "refs": [],
            "checkpoints": [],
        }

    def load_files(self, session_id: str) -> list[dict]:
        self._session_by_id(session_id)
        return []

    def load_checkpoints(self, session_id: str) -> list[dict]:
        self._session_by_id(session_id)
        return []

    def _session_by_id(self, session_id: str) -> _ClaudeSession:
        for item in self._load_sessions():
            if item.id == session_id:
                return item
        raise LookupError(f"No session found matching '{session_id}'")

    def _load_sessions(self) -> list[_ClaudeSession]:
        if self._sessions is not None:
            return self._sessions
        if not self.projects_root.exists():
            self._sessions = []
            return self._sessions
        sessions_by_id: dict[str, _ClaudeSession] = {}
        duplicate_ids: set[str] = set()
        for path in sorted(self.projects_root.rglob("*.jsonl")):
            if not _UUID_JSONL_RE.match(path.name) or "debug" in path.name:
                continue
            session = _parse_session_head(path)
            if session is not None:
                if session.id in duplicate_ids:
                    continue
                if session.id in sessions_by_id:
                    duplicate_ids.add(session.id)
                    del sessions_by_id[session.id]
                    continue
                sessions_by_id[session.id] = session
        self._sessions = list(sessions_by_id.values())
        return self._sessions


def _parse_session_head(path: Path) -> _ClaudeSession | None:
    session_id = path.stem
    cwd = ""
    branch = ""
    first_user = ""
    first_timestamp = ""
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle):
                if line_number >= 80:
                    break
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                record_session_id = record.get("sessionId")
                if record_session_id is not None:
                    candidate = str(record_session_id).strip()
                    if candidate and candidate.lower() != session_id.lower():
                        return None
                cwd = str(record.get("cwd") or cwd)
                branch = str(record.get("gitBranch") or branch)
                timestamp = record.get("timestamp")
                if isinstance(timestamp, str) and not first_timestamp:
                    first_timestamp = timestamp
                if not first_user and _message_role(record) == "user":
                    message = record.get("message") if isinstance(record.get("message"), dict) else {}
                    first_user = _clean_summary(_extract_full_text(message.get("content")))
                if cwd and branch and first_user and first_timestamp:
                    break
    except OSError:
        return None

    try:
        stat = path.stat()
    except OSError:
        return None
    created_at = first_timestamp or _iso_from_epoch(stat.st_ctime)
    updated_at = _iso_from_epoch(stat.st_mtime)
    repository = _detect_repository(cwd)
    summary = first_user or "(untitled)"
    return _ClaudeSession(
        id=session_id,
        file_path=path,
        cwd=cwd,
        repository=repository,
        branch=branch or "(unknown)",
        summary=summary,
        created_at=created_at,
        updated_at=updated_at,
    )


def _load_message_events(path: Path) -> list[dict]:
    events: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                role = _message_role(record)
                if role not in {"user", "assistant"}:
                    continue
                message = record.get("message") if isinstance(record.get("message"), dict) else {}
                content = _extract_full_text(message.get("content"))
                if not content:
                    continue
                events.append(
                    {
                        "role": role,
                        "content": content,
                        "timestamp": record.get("timestamp") or "",
                    }
                )
    except OSError:
        return []
    return events


def _pair_turns(events: list[dict], *, truncate: int) -> list[dict]:
    turns: list[dict] = []
    pending: dict | None = None
    for event in events:
        if event["role"] == "user":
            if pending is not None:
                turns.append(pending)
            pending = {
                "idx": len(turns),
                "user": _truncate(event["content"], truncate),
                "assistant": "",
                "timestamp": event["timestamp"],
            }
            continue
        if pending is None:
            continue
        if pending["assistant"]:
            turns.append(pending)
            pending = {
                "idx": len(turns),
                "user": "",
                "assistant": _truncate(event["content"], truncate),
                "timestamp": event["timestamp"],
            }
            continue
        pending["assistant"] = _truncate(event["content"], truncate)
    if pending is not None:
        turns.append(pending)
    return turns


def _message_role(record: dict) -> str:
    top_level = record.get("type")
    if isinstance(top_level, str) and top_level in {"user", "assistant"}:
        return top_level
    message = record.get("message")
    if isinstance(message, dict):
        role = message.get("role")
        if isinstance(role, str):
            return role
    return ""


def _extract_full_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            text = block.strip()
            if text:
                parts.append(text)
            continue
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        text = block.get("text")
        if isinstance(text, str) and (block_type in {None, "text"}):
            cleaned = text.strip()
            if cleaned:
                parts.append(cleaned)
    return "\n\n".join(parts)


def _clean_summary(value: str) -> str:
    return " ".join(value.split())


def _truncate(value: str, limit: int) -> str:
    if limit <= 0:
        return value
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _detect_repository(cwd: str) -> str:
    if cwd:
        detected = detect_repo(cwd=cwd) if os.path.isdir(cwd) else None
        if detected:
            return detected
        parts = [part for part in Path(cwd).parts if part not in {os.sep, ""}]
        if len(parts) >= 2:
            return "/".join(parts[-2:])
        if parts:
            return parts[-1]
    return "(unknown)"


def _matches_scope(session: _ClaudeSession, scope: Scope) -> bool:
    if scope.mode == "all":
        return True
    if scope.mode == "repo":
        if session.repository == scope.value:
            return True
        return Path(session.cwd).name == scope.value.split("/")[-1]
    if not session.cwd:
        return False
    session_path = os.path.normpath(session.cwd)
    scope_path = os.path.normpath(scope.value)
    return session_path == scope_path or session_path.startswith(f"{scope_path}{os.sep}")


def _matches_days(session: _ClaudeSession, days: int | None) -> bool:
    if days is None:
        return True
    created = _parse_dt(session.created_at)
    if created is None:
        return True
    now = datetime.now(timezone.utc)
    if days == 0:
        return created.date() >= now.date()
    return created >= now.replace(microsecond=0) - timedelta(days=days)


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iso_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _session_row(session: _ClaudeSession) -> dict:
    return {
        "id": session.id,
        "repository": session.repository,
        "branch": session.branch,
        "summary": session.summary,
        "created_at": session.created_at,
    }
