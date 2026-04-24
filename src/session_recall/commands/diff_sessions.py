"""Compare two sessions using compact metadata-first output."""
from __future__ import annotations

import sys
import time

from ..config import DB_PATH
from ..store.factory import open_store
from ..store.protocol import StoreSchemaError
from ..util import debug
from ..util.format_output import fmt_json, sanitize_for_terminal


def _session_meta(row) -> dict:
    return {
        "id": row["id"],
        "short_id": row["id"][:8],
        "repository": row["repository"],
        "branch": row["branch"],
        "summary": row["summary"],
        "created_at": row["created_at"],
    }


def _file_paths(rows) -> list[str]:
    return sorted({row["file_path"] for row in rows})


def _checkpoint_meta(rows) -> list[dict]:
    return [
        {
            "n": row["checkpoint_number"],
            "title": row["title"],
            "overview": row["overview"],
        }
        for row in rows
    ]


def _build_diff(session_a, session_b, files_a, files_b, checkpoints_a, checkpoints_b) -> dict:
    file_set_a = set(files_a)
    file_set_b = set(files_b)
    checkpoint_map_a = {item["n"]: item for item in checkpoints_a}
    checkpoint_map_b = {item["n"]: item for item in checkpoints_b}
    checkpoint_nums_a = set(checkpoint_map_a)
    checkpoint_nums_b = set(checkpoint_map_b)

    return {
        "session_a": _session_meta(session_a),
        "session_b": _session_meta(session_b),
        "summary": {
            "changed": session_a["summary"] != session_b["summary"],
            "from": session_a["summary"],
            "to": session_b["summary"],
        },
        "files": {
            "added": sorted(file_set_b - file_set_a),
            "removed": sorted(file_set_a - file_set_b),
        },
        "checkpoints": {
            "added": [
                checkpoint_map_b[n]
                for n in sorted(checkpoint_nums_b - checkpoint_nums_a)
            ],
            "removed": [
                checkpoint_map_a[n]
                for n in sorted(checkpoint_nums_a - checkpoint_nums_b)
            ],
            "changed": [
                {
                    "n": n,
                    "from": checkpoint_map_a[n],
                    "to": checkpoint_map_b[n],
                }
                for n in sorted(checkpoint_nums_a & checkpoint_nums_b)
                if checkpoint_map_a[n] != checkpoint_map_b[n]
            ],
        },
        "turns_compared": False,
    }


def _render_section(title: str, added, removed, changed, formatter, changed_formatter) -> list[str]:
    lines = [title]
    if not added and not removed and not changed:
        lines.append("  no changes")
        return lines
    for item in added:
        lines.append(f"  + {formatter(item)}")
    for item in removed:
        lines.append(f"  - {formatter(item)}")
    for item in changed:
        lines.append(f"  ~ {changed_formatter(item)}")
    return lines


def _render_human(data: dict) -> str:
    lines = []
    warning = data.get("warning")
    if warning:
        lines.extend([f"Warning: {sanitize_for_terminal(warning)}", ""])
    lines.extend(
        [
            f"Session diff: {sanitize_for_terminal(data['session_a']['short_id'])} -> "
            f"{sanitize_for_terminal(data['session_b']['short_id'])}",
            "",
        ]
    )
    summary = data["summary"]
    if summary["changed"]:
        lines.extend(
            [
                "Summary",
                f"  from: {sanitize_for_terminal(summary['from'] or '(untitled)')}",
                f"  to:   {sanitize_for_terminal(summary['to'] or '(untitled)')}",
                "",
            ]
        )
    else:
        lines.extend(["Summary", "  unchanged", ""])

    lines.extend(
        _render_section(
            "Files",
            data["files"]["added"],
            data["files"]["removed"],
            [],
            lambda item: sanitize_for_terminal(item),
            lambda item: sanitize_for_terminal(item),
        )
    )
    lines.append("")
    lines.extend(
        _render_section(
            "Checkpoints",
            data["checkpoints"]["added"],
            data["checkpoints"]["removed"],
            data["checkpoints"]["changed"],
            lambda item: (
                f"#{item['n']}: {sanitize_for_terminal(item['title'] or '(untitled)')}"
            ),
            lambda item: (
                f"#{item['n']}: "
                f"{sanitize_for_terminal(item['from'].get('title') or '(untitled)')} "
                f"-> {sanitize_for_terminal(item['to'].get('title') or '(untitled)')}"
                f" | {sanitize_for_terminal(item['from'].get('overview') or '')} "
                f"-> {sanitize_for_terminal(item['to'].get('overview') or '')}"
            ),
        )
    )
    lines.extend(["", "Turns", "  not compared yet"])
    return "\n".join(lines)


def run(args) -> int:
    store = open_store(args, meta=getattr(args, "_telemetry", None), db_path=DB_PATH)
    try:
        try:
            session_a = store.resolve_session_id(args.session_a)
            session_b = store.resolve_session_id(args.session_b)
            debug.log(args, f"resolved_sessions={session_a['id']} -> {session_b['id']}")
            t0 = time.monotonic()
            data = _build_diff(
                session_a,
                session_b,
                _file_paths(store.load_files(session_a["id"])),
                _file_paths(store.load_files(session_b["id"])),
                _checkpoint_meta(store.load_checkpoints(session_a["id"])),
                _checkpoint_meta(store.load_checkpoints(session_b["id"])),
            )
            if getattr(args, "source", "copilot") == "claude":
                data["warning"] = "Claude source currently compares summary only; file and checkpoint metadata are not yet available."
            changed_count = len(data["checkpoints"]["changed"])
            debug.log(
                args,
                f"files +{len(data['files']['added'])} -{len(data['files']['removed'])} checkpoints +{len(data['checkpoints']['added'])} -{len(data['checkpoints']['removed'])} ~{changed_count} ms={debug.elapsed_ms(t0):.1f}",
            )
            if getattr(args, "_telemetry", None) is not None:
                args._telemetry["rows"] = (
                    len(data["files"]["added"]) +
                    len(data["files"]["removed"]) +
                    len(data["checkpoints"]["added"]) +
                    len(data["checkpoints"]["removed"]) +
                    changed_count
                )
            if getattr(args, "json", False):
                print(fmt_json(data))
            else:
                print(_render_human(data))
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
