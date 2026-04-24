"""Output formatting for human-readable and JSON modes."""
import json
import re

_CONTROL_RE = re.compile(
    r'\x1b\[[0-?]*[ -/]*[@-~]'             # CSI sequences (colors, cursor moves)
    r'|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)'  # OSC sequences (title, clipboard, hyperlinks)
    r'|\x1b[@-Z\\-_]'                       # other ESC-prefixed (Fp, Fe, Fs)
    r'|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]'  # C0 controls (except TAB \x09, LF \x0a, CR \x0d) + DEL
    r'|[\x80-\x9f]'                         # C1 controls
)


def sanitize_for_terminal(s: str | None) -> str:
    """Strip ANSI/OSC/control sequences so session content can't hijack the terminal."""
    if not s:
        return ''
    return _CONTROL_RE.sub('', s.replace('\r', ''))


def _single_line(value: str | None) -> str:
    return sanitize_for_terminal(value).replace('\n', ' ')


def fmt_json(data: dict | list) -> str:
    """Return compact JSON string."""
    return json.dumps(data, indent=2, default=str)


def fmt_human_sessions(sessions: list[dict]) -> str:
    """Format session list as human-readable table."""
    if not sessions:
        return "No sessions found."
    lines = []
    lines.append(f"{'ID':8s}  {'Date':10s}  {'Turns':>5s}  {'Summary'}")
    lines.append("-" * 60)
    for s in sessions:
        sid = _single_line(s.get("id_short", s.get("id", "?")[:8]))
        date = _single_line(s.get("date", s.get("created_at", "?"))[:10])
        turns = str(s.get("turns_count", s.get("turns", "?")))
        summary = _single_line((s.get("summary") or "(untitled)")[:40])
        lines.append(f"{sid:8s}  {date:10s}  {turns:>5s}  {summary}")
    return "\n".join(lines)


def _truncate(value: str | None, limit: int) -> str:
    text = _single_line(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def fmt_human_files(data: dict) -> str:
    files = data.get("files", [])
    lines = []
    warning = data.get("warning")
    if warning:
        lines.append(f"Warning: {_single_line(warning)}")
        lines.append("")
    if not files:
        lines.append("No files found.")
        return "\n".join(lines)
    lines.append(f"{'Date':10s}  {'Source':19s}  {'Tool':20s}  File")
    lines.append("-" * 95)
    for item in files:
        lines.append(
            f"{_truncate(item.get('date'), 10):10s}  "
            f"{_truncate(item.get('source'), 19):19s}  "
            f"{_truncate(item.get('tool_name'), 20):20s}  "
            f"{_single_line(item.get('file_path') or '')}"
        )
    return "\n".join(lines)


def fmt_human_checkpoints(data: dict) -> str:
    checkpoints = data.get("checkpoints", [])
    if not checkpoints:
        return "No checkpoints found."
    lines = []
    lines.append(f"{'#':>2s}  {'Date':10s}  {'Session':8s}  {'Title':28s}  Overview")
    lines.append("-" * 100)
    for item in checkpoints:
        lines.append(
            f"{str(item.get('checkpoint_number', '?')):>2s}  "
            f"{_truncate(item.get('date'), 10):10s}  "
            f"{_truncate(item.get('session_id'), 8):8s}  "
            f"{_truncate(item.get('title'), 28):28s}  "
            f"{_truncate(item.get('overview'), 45)}"
        )
    return "\n".join(lines)


def fmt_human_search(data: dict) -> str:
    results = data.get("results", [])
    query = _single_line(data.get("query") or "")
    lines = []
    warning = data.get("warning")
    if warning:
        lines.append(f"Warning: {_single_line(warning)}")
        lines.append("")
    if not results:
        lines.append(f"No results found for '{query}'.")
        return "\n".join(lines)
    lines.extend([f"Results for '{query}'", ""])
    lines.append(f"{'Session':8s}  {'Date':10s}  {'Source':11s}  {'Summary':28s}  Excerpt")
    lines.append("-" * 110)
    for item in results:
        lines.append(
            f"{_truncate(item.get('session_id'), 8):8s}  "
            f"{_truncate(item.get('date'), 10):10s}  "
            f"{_truncate(item.get('source_type'), 11):11s}  "
            f"{_truncate(item.get('summary'), 28):28s}  "
            f"{_truncate(item.get('excerpt'), 50)}"
        )
    return "\n".join(lines)


def fmt_human_show(data: dict) -> str:
    lines = [
        f"Session: {_single_line(data.get('id') or '')}",
        f"Repo:    {_single_line(data.get('repository') or '(unknown)')}",
        f"Branch:  {_single_line(data.get('branch') or '(unknown)')}",
        f"Created: {_single_line(data.get('created_at') or '(unknown)')}",
        f"Summary: {_single_line(data.get('summary') or '(untitled)')}",
        "",
        f"Turns: {data.get('turns_count', 0)}",
    ]
    files = data.get("files", [])
    if files:
        lines.append("Files:")
        for item in files[:10]:
            lines.append(
                f"  - {_single_line(item.get('file_path') or '')} "
                f"[{_single_line(item.get('tool_name') or '?')}]"
            )
    checkpoints = data.get("checkpoints", [])
    if checkpoints:
        lines.append("Checkpoints:")
        for item in checkpoints[:10]:
            lines.append(
                f"  - #{item.get('n', '?')}: {_truncate(item.get('title'), 50)}"
            )
    turns = data.get("turns", [])
    if turns:
        lines.append("Recent turns:")
        for turn in turns[:3]:
            lines.append(f"  - [{turn.get('idx', '?')}] {_truncate(turn.get('user'), 80)}")
    return "\n".join(lines)


def fmt_human_session_bundle(data: dict) -> str:
    lines = [fmt_human_sessions(data.get("sessions", []))]
    recent_files = data.get("recent_files", [])
    if recent_files:
        lines.append("")
        lines.append("Recent files:")
        for item in recent_files[:10]:
            lines.append(
                f"  - {_single_line(item.get('file_path') or '')} "
                f"[{_single_line(item.get('source') or '?')}]"
            )
    return "\n".join(lines)


def output(data, json_mode: bool = False) -> None:
    """Print data in requested format to stdout."""
    if json_mode:
        print(fmt_json(data))
    elif isinstance(data, list):
        print(fmt_human_sessions(data))
    elif isinstance(data, dict) and "sessions" in data:
        print(fmt_human_session_bundle(data))
    elif isinstance(data, dict) and "turns" in data and "turns_count" in data and "created_at" in data:
        print(fmt_human_show(data))
    elif isinstance(data, dict) and "files" in data:
        print(fmt_human_files(data))
    elif isinstance(data, dict) and "checkpoints" in data:
        print(fmt_human_checkpoints(data))
    elif isinstance(data, dict) and "results" in data:
        print(fmt_human_search(data))
    else:
        print(fmt_json(data))
