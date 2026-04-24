"""Configuration constants for auto-memory CLI."""
import os
from pathlib import Path

DEFAULT_DB_PATH = str(Path.home() / ".copilot" / "session-store.db")
DEFAULT_TELEMETRY_PATH = str(Path.home() / ".copilot" / "scripts" / ".session-recall-stats.json")
INSTRUCTION_PATHS = [str(Path.home() / ".copilot" / "copilot-instructions.md")]
INSTRUCTION_MARKER = "## Progressive Session Recall — RUN FIRST ON EVERY PROMPT"
SOURCE_CHOICES = ("copilot", "claude")
DEFAULT_SOURCE = "copilot"


def get_db_path() -> str:
    return os.environ.get("SESSION_RECALL_DB", DEFAULT_DB_PATH)


def get_telemetry_path() -> str:
    return os.environ.get("SESSION_RECALL_TELEMETRY", DEFAULT_TELEMETRY_PATH)


def get_source() -> str:
    return os.environ.get("SESSION_RECALL_SOURCE", DEFAULT_SOURCE)


def normalize_source(value: str | None) -> str:
    source = DEFAULT_SOURCE if value is None else value.strip().lower()
    if source not in SOURCE_CHOICES:
        choices = ", ".join(SOURCE_CHOICES)
        raise ValueError(f"invalid session source '{value}' (expected one of: {choices})")
    return source


DB_PATH = get_db_path()
TELEMETRY_PATH = get_telemetry_path()

RETRY_DELAYS_MS = [50, 150, 450]
MAX_RETRIES = len(RETRY_DELAYS_MS)

EXPECTED_SCHEMA_VERSION = 1
