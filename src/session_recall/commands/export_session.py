"""Export a session as a portable markdown artifact."""
from __future__ import annotations

import html
import re
import sys
import time

from ..config import DB_PATH
from ..store.factory import open_store
from ..store.protocol import StoreSchemaError
from ..util import debug
from ..util.format_output import sanitize_for_terminal


_MD_SPECIALS_RE = re.compile(r"([\\`*_{}\[\]()#+!|])")


def _code_fence(text: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    return "`" * max(4, longest + 1)


def _escape_markdown_line(value: str | None) -> str:
    text = sanitize_for_terminal(value).replace("\n", " ") if value else ""
    text = html.escape(text, quote=False)
    return _MD_SPECIALS_RE.sub(r"\\\1", text)


def _render_text_block(value: str) -> list[str]:
    content = sanitize_for_terminal(value)
    fence = _code_fence(content)
    return [f"{fence}text", content, fence, ""]


def _render_turn_block(label: str, value: str) -> list[str]:
    return [
        f"**{label}**",
        *_render_text_block(value),
    ]


def render_markdown(detail: dict) -> str:
    """Render show-style session detail as markdown."""
    lines = [
        "# Session Export",
        "",
        f"- Session: {_escape_markdown_line(detail.get('id') or '')}",
        f"- Repo: {_escape_markdown_line(detail.get('repository') or '(unknown)')}",
        f"- Branch: {_escape_markdown_line(detail.get('branch') or '(unknown)')}",
        f"- Created: {_escape_markdown_line(detail.get('created_at') or '(unknown)')}",
        "",
        "## Summary",
        "",
        *_render_text_block(detail.get("summary") or "(untitled)"),
        "## Files",
    ]

    files = detail.get("files", [])
    if files:
        for item in files:
            lines.append(
                f"- {_escape_markdown_line(item.get('file_path') or '')} "
                f"[{_escape_markdown_line(item.get('tool_name') or '?')}]"
            )
    else:
        lines.append("_No files recorded._")

    lines.extend(["", "## Checkpoints"])
    checkpoints = detail.get("checkpoints", [])
    if checkpoints:
        for item in checkpoints:
            lines.append(
                f"- #{item.get('n', '?')}: {_escape_markdown_line(item.get('title') or '(untitled)')}"
            )
            overview = _escape_markdown_line(item.get("overview") or "")
            if overview:
                lines.append(f"  - {overview}")
    else:
        lines.append("_No checkpoints recorded._")

    refs = detail.get("refs", [])
    if refs:
        lines.extend(["", "## Refs"])
        for item in refs:
            lines.append(
                f"- {_escape_markdown_line(item.get('ref_type') or '?')}: "
                f"{_escape_markdown_line(item.get('ref_value') or '')}"
            )

    lines.extend(["", "## Selected Turns"])
    turns = detail.get("turns", [])
    if turns:
        for turn in turns:
            lines.extend(
                [
                    f"### Turn {turn.get('idx', '?')}",
                    "",
                    *_render_turn_block("User", turn.get("user") or ""),
                    *_render_turn_block("Assistant", turn.get("assistant") or ""),
                ]
            )
    else:
        lines.append("_No turns selected._")

    return "\n".join(lines).rstrip() + "\n"


def run(args) -> int:
    store = open_store(args, meta=getattr(args, "_telemetry", None), db_path=DB_PATH)
    try:
        try:
            session_row = store.resolve_session_id(args.session_id)
            turn_limit = None if getattr(args, "full", False) else getattr(args, "turns", 10)
            debug.log(args, f"resolved_session={session_row['id']} turn_limit={turn_limit}")
            t0 = time.monotonic()
            detail = store.load_session_detail(
                session_row["id"],
                turn_limit=turn_limit,
                truncate=99999 if getattr(args, "full", False) else 500,
            )
            debug.log(
                args,
                f"rows turns={len(detail['turns'])} files={len(detail['files'])} refs={len(detail['refs'])} checkpoints={len(detail['checkpoints'])} ms={debug.elapsed_ms(t0):.1f}",
            )
            if getattr(args, "_telemetry", None) is not None:
                args._telemetry["rows"] = len(detail["turns"])
            print(render_markdown(detail), end="")
            return 0
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except LookupError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except StoreSchemaError as exc:
            for problem in exc.problems:
                print(f"   - {problem}", file=sys.stderr)
            return 2
    finally:
        store.close()
