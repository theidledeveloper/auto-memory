"""Telemetry-backed stats and usage summary."""
from __future__ import annotations

import sys

from ..config import DB_PATH
from ..db.connect import connect_ro
from ..db.schema_check import PATH_SCOPE_SCHEMA, schema_check
from ..health import dim_disclosure
from ..util import debug
from ..util.format_output import fmt_json, sanitize_for_terminal
from ..util.resolve_scope import resolve_scope, session_scope_sql
from ..util.telemetry_report import explain, summarize


def _safe_line(value) -> str:
    return sanitize_for_terminal(str(value)).replace("\n", " ")


def _store_summary(conn, scope) -> dict:
    conditions = []
    params: list[str] = []
    scope_clause, scope_params = session_scope_sql(scope, cwd_col="s.cwd")
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS sessions,
               COALESCE(AVG(turn_count), 0) AS avg_turns,
               COALESCE(AVG(file_count), 0) AS avg_files
        FROM (
            SELECT s.id,
                   COUNT(DISTINCT t.turn_index) AS turn_count,
                   COUNT(DISTINCT sf.file_path) AS file_count
            FROM sessions s
            LEFT JOIN turns t ON t.session_id = s.id
            LEFT JOIN session_files sf ON sf.session_id = s.id
            {where_clause}
            GROUP BY s.id
        )
        """,
        tuple(params),
    ).fetchone()

    top_repos = conn.execute(
        f"""
        SELECT s.repository, COUNT(*) AS sessions
        FROM sessions s
        {where_clause}
        GROUP BY s.repository
        ORDER BY sessions DESC, s.repository ASC
        LIMIT 5
        """,
        tuple(params),
    ).fetchall()

    return {
        "sessions": int(row["sessions"] or 0),
        "avg_turns_per_session": round(float(row["avg_turns"] or 0.0), 2),
        "avg_files_per_session": round(float(row["avg_files"] or 0.0), 2),
        "busiest_repos": [
            {"repository": repo["repository"], "sessions": int(repo["sessions"] or 0)}
            for repo in top_repos
            if repo["repository"]
        ],
    }


def _render_human(scope, telemetry_summary: dict, store_summary: dict, what_it_means: str) -> str:
    commands = ", ".join(
        f"{_safe_line(item['command'])}={item['count']}" for item in telemetry_summary["top_commands"]
    ) or "none yet"
    tiers = telemetry_summary["tier_distribution"]
    lines = [
        f"Session recall stats ({_safe_line(scope.display)})",
        "",
        "Telemetry",
        f"  Entries: {telemetry_summary['entries']}",
        f"  Commands: {commands}",
        (
            "  Tier usage: "
            f"T1={tiers['tier1_pct']:.1f}% "
            f"T2={tiers['tier2_pct']:.1f}% "
            f"T3={tiers['tier3_pct']:.1f}% "
            f"meta={tiers['meta_entries']} "
            f"legacy={tiers['legacy_entries']}"
        ),
        (
            "  Latency: "
            f"avg={telemetry_summary['latency_ms']['avg']:.1f}ms "
            f"p95={telemetry_summary['latency_ms']['p95']:.1f}ms"
        ),
        (
            "  Busy hits: "
            f"{telemetry_summary['busy']['busy_hit_rate_pct']:.1f}% "
            f"(avg_attempts={telemetry_summary['busy']['avg_attempts']:.2f})"
        ),
        "",
        "Session store",
        f"  Sessions: {store_summary['sessions']}",
        f"  Avg session length: {store_summary['avg_turns_per_session']:.2f} turns",
        f"  Avg files/session: {store_summary['avg_files_per_session']:.2f}",
    ]
    if store_summary["busiest_repos"]:
        lines.append("  Busiest repos:")
        for repo in store_summary["busiest_repos"]:
            lines.append(f"    - {_safe_line(repo['repository'])} ({repo['sessions']})")
    lines.extend(["", f"What this means: {_safe_line(what_it_means)}"])
    return "\n".join(lines)


def run(args) -> int:
    scope = resolve_scope(getattr(args, "repo", None) or "all")
    debug.log(args, f"scope mode={scope.mode} display={scope.display}")

    connect_meta = getattr(args, "_telemetry", None)
    conn = connect_ro(DB_PATH, meta=connect_meta)
    try:
        problems = schema_check(conn, PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
        if problems:
            for problem in problems:
                print(f"   - {problem}", file=sys.stderr)
            return 2

        store_timer = debug.start_timer()
        store = _store_summary(conn, scope)
        debug.log(
            args,
            f"store_summary sessions={store['sessions']} repos={len(store['busiest_repos'])} ms={debug.elapsed_ms(store_timer):.1f}",
        )

        telemetry_summary = summarize()
        disclosure = dim_disclosure.check()
        what_it_means = explain(telemetry_summary, disclosure)
        if connect_meta is not None:
            connect_meta["rows"] = store["sessions"]

        payload = {
            "scope": scope.display,
            "telemetry": telemetry_summary,
            "session_store": store,
            "what_it_means": what_it_means,
        }
        if getattr(args, "json", False):
            print(fmt_json(payload))
        else:
            print(_render_human(scope, telemetry_summary, store, what_it_means))
        return 0
    finally:
        conn.close()
