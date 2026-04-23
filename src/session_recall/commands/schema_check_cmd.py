"""Schema-check subcommand — validates session-store.db structure."""
import sys
from ..config import DB_PATH
from ..db.connect import connect_ro
from ..db.schema_check import FEATURE_SUPPORT_SCHEMA, schema_check
from ..util.format_output import fmt_json

def run(args) -> int:
    """Execute schema-check. Returns 0 if OK, 2 if drift."""
    conn = connect_ro(DB_PATH)
    problems = schema_check(conn, FEATURE_SUPPORT_SCHEMA)
    conn.close()
    json_mode = getattr(args, "json", False)
    if problems:
        if json_mode:
            print(fmt_json({"ok": False, "problems": problems}))
        else:
            print("❌ Schema drift. Copilot CLI may have been upgraded.", file=sys.stderr)
            for p in problems:
                print(f"   - {p}", file=sys.stderr)
        return 2
    print(fmt_json({"ok": True, "problems": []}) if json_mode else "✅ Schema OK")
    return 0
