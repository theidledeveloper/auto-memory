"""Show detailed info for a single session."""
import sys
import time

from ..config import DB_PATH
from ..store.factory import open_store
from ..store.protocol import StoreSchemaError
from ..util import debug
from ..util.format_output import output


def run(args) -> int:
    store = open_store(args, meta=getattr(args, "_telemetry", None), db_path=DB_PATH)
    try:
        try:
            session_row = store.resolve_session_id(args.session_id)
            debug.log(args, f"resolved_session={session_row['id']}")
            t0 = time.monotonic()
            result = store.load_session_detail(
                session_row["id"],
                turn_limit=getattr(args, "turns", None),
                truncate=99999 if getattr(args, "full", False) else 500,
            )
            debug.log(
                args,
                f"rows turns={len(result['turns'])} files={len(result['files'])} refs={len(result['refs'])} checkpoints={len(result['checkpoints'])} ms={debug.elapsed_ms(t0):.1f}",
            )
            if getattr(args, "_telemetry", None) is not None:
                args._telemetry["rows"] = len(result["turns"])
            output(result, json_mode=getattr(args, "json", False))
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
