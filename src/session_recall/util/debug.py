"""Lightweight stderr-only debug helpers."""
from __future__ import annotations

import sys
import time

from .format_output import sanitize_for_terminal


def enabled(args) -> bool:
    return bool(getattr(args, "debug", False))


def log(args, message: str) -> None:
    if enabled(args):
        safe = sanitize_for_terminal(message).replace("\n", " ")
        print(f"[debug] {safe}", file=sys.stderr)


def start_timer() -> float:
    return time.monotonic()


def elapsed_ms(started_at: float) -> float:
    return (time.monotonic() - started_at) * 1000
