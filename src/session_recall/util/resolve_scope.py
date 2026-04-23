"""Resolve current query scope to repo, path, or all."""
import os
import subprocess
from dataclasses import dataclass

from .detect_repo import detect_repo


@dataclass(frozen=True)
class Scope:
    """Resolved scope for commands and scoped health checks."""
    mode: str
    value: str
    display: str


def _normalize_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(os.path.expanduser(path)))


def _path_prefix(path: str) -> str:
    return f"{path}{os.sep}"


def _is_explicit_relative_path(path: str) -> bool:
    expanded = os.path.expanduser(path)
    return (
        expanded in {".", ".."}
        or expanded.startswith(f".{os.sep}")
        or expanded.startswith(f"..{os.sep}")
    )


def _git_toplevel(cwd: str | None = None) -> str | None:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            cwd=cwd,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if res.returncode != 0:
        return None
    root = res.stdout.strip()
    return _normalize_path(root) if root else None


def resolve_scope(scope_arg: str | None = None, cwd: str | None = None) -> Scope:
    """Resolve explicit or inferred scope."""
    if scope_arg == "all":
        return Scope("all", "all", "all")
    if scope_arg:
        if os.path.isabs(os.path.expanduser(scope_arg)) or _is_explicit_relative_path(scope_arg):
            base = cwd or os.getcwd()
            path = _normalize_path(os.path.join(base, scope_arg))
            return Scope("path", path, path)
        return Scope("repo", scope_arg, scope_arg)
    repo = detect_repo(cwd=cwd)
    if repo:
        return Scope("repo", repo, repo)
    root = _git_toplevel(cwd=cwd)
    if root:
        return Scope("path", root, root)
    path = _normalize_path(cwd or os.getcwd())
    return Scope("path", path, path)


def session_scope_sql(
    scope: Scope,
    *,
    repo_col: str = "s.repository",
    cwd_col: str = "s.cwd",
) -> tuple[str, tuple[str, ...]]:
    """Return a WHERE-clause fragment and params for session-scoped queries."""
    if scope.mode == "all":
        return "", ()
    if scope.mode == "repo":
        return f"{repo_col} = ?", (scope.value,)
    return f"({cwd_col} = ? OR instr({cwd_col}, ?) = 1)", (
        scope.value,
        _path_prefix(scope.value),
    )


def file_scope_sql(
    scope: Scope,
    *,
    repo_col: str = "s.repository",
    file_col: str = "sf.file_path",
) -> tuple[str, tuple[str, ...]]:
    """Return a WHERE-clause fragment and params for file-scoped queries."""
    if scope.mode == "all":
        return "", ()
    if scope.mode == "repo":
        return f"{repo_col} = ?", (scope.value,)
    return f"instr({file_col}, ?) = 1", (_path_prefix(scope.value),)


def time_filter_sql(
    column: str,
    days: int | None,
    *,
    default_days: int | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Return a time-window filter for commands that accept --days."""
    effective_days = default_days if days is None else days
    if effective_days is None:
        return "", ()
    if effective_days == 0:
        return f"date({column}) >= date('now')", ()
    return f"{column} >= datetime('now', ?)", (f"-{effective_days} days",)
