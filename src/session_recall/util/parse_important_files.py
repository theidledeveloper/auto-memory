"""Parse conservative file-path hints from checkpoint important_files text."""
from __future__ import annotations

import os
import re

_BACKTICK_PATH_RE = re.compile(r"`([^`\n]+)`")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_TRAILING_PUNCT = ",.;:"
_KNOWN_FILE_NAMES = {
    "Dockerfile",
    "Makefile",
    "Procfile",
    "Gemfile",
    "Rakefile",
    "Brewfile",
    "README",
    "LICENSE",
}
_KNOWN_DOTFILES = {
    ".env",
    ".env.example",
    ".env.local",
    ".env.development",
    ".env.production",
    ".gitignore",
    ".gitattributes",
    ".npmrc",
    ".nvmrc",
    ".prettierrc",
    ".prettierignore",
    ".eslintrc",
    ".eslintignore",
    ".editorconfig",
    ".tool-versions",
    ".ruby-version",
    ".python-version",
    ".node-version",
    ".browserslistrc",
    ".dockerignore",
    ".terraform.lock.hcl",
}


def _clean_candidate(candidate: str) -> str:
    return candidate.strip().rstrip(_TRAILING_PUNCT).strip()


def _looks_like_path(candidate: str, *, allow_spaces: bool) -> bool:
    if not candidate or candidate.startswith(("http://", "https://")):
        return False
    if not allow_spaces and any(ch.isspace() for ch in candidate):
        return False
    if candidate.startswith(("~/.copilot/session-state/", "/Users/")) and "/.copilot/session-state/" in candidate:
        return False
    leaf = os.path.basename(candidate.rstrip("/"))
    if not leaf:
        return False
    if leaf in _KNOWN_FILE_NAMES:
        return True
    if leaf.startswith("."):
        return leaf in _KNOWN_DOTFILES
    if "." in leaf and leaf not in {".", ".."}:
        _, _, ext = leaf.rpartition(".")
        return any(ch.isalpha() for ch in ext)
    return False


def parse_important_files(text: str | None) -> list[str]:
    """Return de-duplicated file paths from structured checkpoint notes."""
    if not text:
        return []
    results: list[str] = []
    seen: set[str] = set()

    def add(candidate: str, *, allow_spaces: bool) -> None:
        cleaned = _clean_candidate(candidate)
        if not _looks_like_path(cleaned, allow_spaces=allow_spaces) or cleaned in seen:
            return
        seen.add(cleaned)
        results.append(cleaned)

    for match in _BACKTICK_PATH_RE.finditer(text):
        add(match.group(1), allow_spaces=True)

    for line in text.splitlines():
        match = _BULLET_RE.match(line)
        if not match:
            continue
        candidate = match.group(1)
        if candidate.startswith("`") and candidate.endswith("`"):
            continue
        add(candidate, allow_spaces=False)

    return results
