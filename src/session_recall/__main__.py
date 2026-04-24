"""auto-memory CLI — progressive session disclosure for Copilot CLI."""
import argparse
import sys
import time
from importlib.metadata import PackageNotFoundError, version

from .config import SOURCE_CHOICES, TELEMETRY_PATH, get_source, normalize_source
from .util import debug as debug_util
from .util import telemetry
from . import __version__


def _non_negative_int(v):
    """Argparse type: non-negative integer."""
    i = int(v)
    if i < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {v}")
    return i


def _positive_int(v):
    """Argparse type: positive integer."""
    i = int(v)
    if i <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {v}")
    return i


TIER_MAP = {
    "list": 1, "files": 1, "checkpoints": 1,   # Tier 1 — cheap scan
    "context": 1,
    "search": 2, "diff": 2,                       # Tier 2 — focused search
    "show": 3, "export": 3,                       # Tier 3 — deep dive / artifact
    "health": 0, "stats": 0, "schema-check": 0,  # Tier 0 — meta/ops
    "init": 0, "doctor": 0,
    "calibrate": 0,                               # Tier 0 — meta (Phase 4)
}


def _package_version() -> str:
    try:
        return version("auto-memory")
    except PackageNotFoundError:
        return __version__


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Print scope/query details to stderr",
    )
    source_common = argparse.ArgumentParser(add_help=False)
    source_common.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        default=get_source(),
        help="Session source backend (env: SESSION_RECALL_SOURCE)",
    )
    parser = argparse.ArgumentParser(
        prog="session-recall",
        description="Query GitHub Copilot CLI session history (install package: auto-memory)",
        parents=[common],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_package_version()}",
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="Recent sessions", parents=[common, source_common])
    p_list.add_argument("--repo", default=None)
    p_list.add_argument("--limit", type=int, default=None)
    p_list.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only include sessions from last N days (all time by default)",
    )
    p_list.add_argument("--json", action="store_true")

    p_schema = sub.add_parser("schema-check", help="Validate DB schema", parents=[common])
    p_schema.add_argument("--json", action="store_true")

    p_init = sub.add_parser("init", help="Wire session-recall into Copilot instructions", parents=[common])
    p_init.add_argument("--json", action="store_true")

    p_doctor = sub.add_parser("doctor", help="Verify setup and active paths", parents=[common])
    p_doctor.add_argument("--json", action="store_true")

    p_files = sub.add_parser("files", help="Recently touched files", parents=[common])
    p_files.add_argument("--json", action="store_true")
    p_files.add_argument("--repo", default=None)
    p_files.add_argument("--limit", type=int, default=None)
    p_files.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only include files from last N days (all time by default)",
    )

    p_cp = sub.add_parser("checkpoints", help="Recent checkpoints", parents=[common])
    p_cp.add_argument("--json", action="store_true")
    p_cp.add_argument("--repo", default=None)
    p_cp.add_argument("--limit", type=int, default=None)
    p_cp.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only include checkpoints from last N days (all time by default)",
    )

    p_context = sub.add_parser(
        "context",
        help="Approximate recall bundle",
        description="Approximate recall bundle from files, session summaries, and checkpoints",
        parents=[common],
    )
    p_context.add_argument(
        "--budget",
        type=_positive_int,
        required=True,
        help="Approximate token budget for the rendered bundle",
    )
    p_context.add_argument("--repo", default=None, help="Scope to a repo or path (defaults to inferred scope)")
    p_context.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="Show session details", parents=[common, source_common])
    p_show.add_argument("session_id")
    p_show.add_argument("--json", action="store_true")
    p_show.add_argument("--turns", type=_non_negative_int, default=None)
    p_show.add_argument("--full", action="store_true")

    p_export = sub.add_parser(
        "export",
        help="Export session as markdown",
        description="Export session as markdown",
        parents=[common, source_common],
    )
    p_export.add_argument("session_id")
    p_export.add_argument("--format", choices=["md"], default="md")
    p_export.add_argument("--turns", type=_non_negative_int, default=10)
    p_export.add_argument("--full", action="store_true")

    p_diff = sub.add_parser(
        "diff",
        help="Compare two sessions",
        description="Compare two sessions",
        parents=[common, source_common],
    )
    p_diff.add_argument("session_a")
    p_diff.add_argument("session_b")
    p_diff.add_argument("--json", action="store_true")

    p_search = sub.add_parser("search", help="Full-text search", parents=[common])
    p_search.add_argument("query")
    p_search.add_argument("--json", action="store_true")
    p_search.add_argument("--repo", default=None)
    p_search.add_argument("--limit", type=int, default=None)
    p_search.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only include sessions from last N days (all time by default)",
    )

    p_stats = sub.add_parser("stats", help="Usage and telemetry summary", parents=[common])
    p_stats.add_argument("--json", action="store_true")
    p_stats.add_argument("--repo", default=None, help="Scope to a repo or path (defaults to all)")

    p_calibrate = sub.add_parser("calibrate", help="Analyze disclosure telemetry", parents=[common])
    p_calibrate.add_argument("--analyze", action="store_true")
    p_calibrate.add_argument("--json", action="store_true")

    p_health = sub.add_parser("health", help="Health check (10 dimensions)", parents=[common])
    p_health.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    telemetry.init(TELEMETRY_PATH)
    t0 = time.monotonic()
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "debug"):
        args.debug = False
    if not args.command:
        parser.print_help(sys.stderr)
        sys.exit(1)
    if hasattr(args, "source"):
        try:
            args.source = normalize_source(args.source)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)
    args._telemetry = {}

    exit_code = 1
    if args.command == "list":
        from .commands.list_sessions import run
        exit_code = run(args)
    elif args.command == "schema-check":
        from .commands.schema_check_cmd import run
        exit_code = run(args)
    elif args.command == "init":
        from .commands.init import run
        exit_code = run(args)
    elif args.command == "doctor":
        from .commands.doctor import run
        exit_code = run(args)
    elif args.command == "files":
        from .commands.files import run
        exit_code = run(args)
    elif args.command == "checkpoints":
        from .commands.checkpoints import run
        exit_code = run(args)
    elif args.command == "context":
        from .commands.context import run
        exit_code = run(args)
    elif args.command == "show":
        from .commands.show_session import run
        exit_code = run(args)
    elif args.command == "export":
        from .commands.export_session import run
        exit_code = run(args)
    elif args.command == "diff":
        from .commands.diff_sessions import run
        exit_code = run(args)
    elif args.command == "search":
        from .commands.search import run
        exit_code = run(args)
    elif args.command == "stats":
        from .commands.stats import run
        exit_code = run(args)
    elif args.command == "calibrate":
        from .commands.calibrate import run
        exit_code = run(args)
    elif args.command == "health":
        from .commands.health import run
        exit_code = run(args)
    else:
        print(f"'{args.command}' not yet implemented. Coming in Phase 2.", file=sys.stderr)

    duration_ms = int((time.monotonic() - t0) * 1000)
    tier = TIER_MAP.get(args.command)  # None if command unknown
    qhash = None
    sid_prefix = None
    wtier = None  # Phase 4 will populate this
    if args.command == "search":
        qhash = telemetry.query_hash(getattr(args, "query", "") or "")
    elif args.command in {"show", "export"}:
        sid = getattr(args, "session_id", "") or ""
        sid_prefix = sid[:8] if sid else None
    telemetry.record(cmd=args.command, duration_ms=duration_ms, exit_code=exit_code,
                     tier=tier, query_hash=qhash, session_id_prefix=sid_prefix,
                     window_tier=wtier,
                     busy_hits=args._telemetry.get("busy_hits", 0),
                     attempts=args._telemetry.get("attempts", 1),
                     rows=args._telemetry.get("rows", 0))
    if getattr(args, "debug", False):
        debug_util.log(args, f"command={args.command} exit_code={exit_code} duration_ms={duration_ms}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
