"""Health check orchestrator — run all 10 dimensions and report."""
from ..health.scoring import overall_score
from ..health import (dim_freshness, dim_schema, dim_latency, dim_corpus,
                      dim_summary_coverage, dim_repo_coverage, dim_file_freshness, dim_concurrency,
                      dim_e2e, dim_disclosure)
from ..util.telemetry_report import explain, summarize
from ..util.format_output import fmt_json, sanitize_for_terminal

DIMS = [dim_freshness, dim_schema, dim_latency, dim_corpus,
        dim_summary_coverage, dim_repo_coverage, dim_file_freshness, dim_concurrency, dim_e2e,
        dim_disclosure]

ZONE_ICON = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}
ZONE_ICON["CALIBRATING"] = "⚪"


def run(args) -> int:
    results = [d.check() for d in DIMS]
    score = overall_score(results)
    hints = [r["hint"] for r in results if r["zone"] != "GREEN" and r.get("hint")]
    disclosure = next((r for r in results if r["name"] == "Progressive Disclosure"), None)
    activity_summary = summarize()
    what_it_means = explain(activity_summary, disclosure)

    if getattr(args, "json", False):
        print(
            fmt_json(
                {
                    "overall_score": score,
                    "dims": results,
                    "top_hints": hints[:3],
                    "activity_summary": activity_summary,
                    "what_it_means": what_it_means,
                }
            )
        )
    else:
        print(f"\n{'Dim':<3s} {'Name':<22s} {'Zone':<8s} {'Score':>5s}  Detail")
        print("-" * 70)
        for i, r in enumerate(results, 1):
            icon = ZONE_ICON.get(r["zone"], "?")
            score_str = f"{r['score']:5.1f}" if r.get("score") is not None else "  -  "
            name = sanitize_for_terminal(str(r["name"])).replace("\n", " ")
            detail = sanitize_for_terminal(str(r["detail"])).replace("\n", " ")
            print(f" {i:<2d} {name:<22s} {icon} {r['zone']:<5s} {score_str}  {detail}")
        print("-" * 70)
        print(f"    {'Overall':<22s}        {score:5.1f}")
        print(
            "\n📈 Activity:"
            f" entries={activity_summary['entries']}"
            f" T1={activity_summary['tier_distribution']['tier1_pct']:.1f}%"
            f" T2={activity_summary['tier_distribution']['tier2_pct']:.1f}%"
            f" T3={activity_summary['tier_distribution']['tier3_pct']:.1f}%"
            f" p95={activity_summary['latency_ms']['p95']:.1f}ms"
            f" busy={activity_summary['busy']['busy_hit_rate_pct']:.1f}%"
        )
        safe_meaning = sanitize_for_terminal(what_it_means).replace("\n", " ")
        print(f"🧭 What this means: {safe_meaning}")
        if hints:
            print("\n💡 Hints:")
            for h in hints[:3]:
                safe_hint = sanitize_for_terminal(h).replace("\n", " ")
                print(f"   • {safe_hint}")
        print()
    return 0
