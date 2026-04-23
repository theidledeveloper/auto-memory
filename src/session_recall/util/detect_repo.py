import re
import subprocess


def _parse_remote_url(url: str) -> str | None:
    """Return 'owner/repo' from a git remote URL."""
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    # Handle SSH: git@github.com:owner/repo.git
    m = re.match(r"git@[^:]+:(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1)
    # Handle HTTPS: https://github.com/owner/repo.git
    m = re.match(r"https?://[^/]+/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1)
    return None


def _git_output(args: list[str], cwd: str | None = None) -> str:
    """Return stdout for a git command or empty string on failure."""
    try:
        res = subprocess.run(
            ["git", *args],
            capture_output=True,
            cwd=cwd,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    if res.returncode != 0:
        return ""
    return res.stdout.strip()


def detect_repo(cwd: str | None = None) -> str | None:
    """Return 'owner/repo' from git remotes, preferring origin."""
    repo = _parse_remote_url(_git_output(["remote", "get-url", "origin"], cwd=cwd))
    if repo:
        return repo
    remotes = _git_output(["remote"], cwd=cwd)
    if not remotes:
        return None
    for remote in remotes.splitlines():
        repo = _parse_remote_url(_git_output(["remote", "get-url", remote], cwd=cwd))
        if repo:
            return repo
    return None
