"""Analyze telemetry and recommend disclosure thresholds."""
from __future__ import annotations

import sys

from ..health import dim_disclosure
from ..util import debug
from ..util.format_output import fmt_json
from ..util.telemetry_report import load_entries


def _render_human(data: dict) -> str:
    sample = data["sample"]
    dist = data["distribution"]
    rec = data["recommendation"]
    lines = [
        "Progressive disclosure calibration",
        "",
        (
            "Sample: "
            f"{sample['scored_entries']} scored, {sample['meta_entries']} meta, {sample['unknown_entries']} legacy, "
            f"{sample['age_days']}d since first"
        ),
        (
            "Distribution: "
            f"T1={dist['tier1_pct']:.1f}% "
            f"T2={dist['tier2_pct']:.1f}% "
            f"T3={dist['tier3_pct']:.1f}% "
            f"avg={dist['avg_tier']:.2f} "
            f"sigma={dist['sigma']:.2f}"
        ),
        (
            "Transitions: "
            f"healthy={data['transitions']['healthy']} "
            f"neutral={data['transitions']['neutral']} "
            f"suspicious={data['transitions']['suspicious']} "
            f"repetition={data['transitions']['repetition']}"
        ),
        "",
        "Recommended thresholds (copy into health/dim_disclosure.py)",
        f"  GREEN_AVG_LOW  = {rec['green_avg_low']:.2f}",
        f"  GREEN_AVG_HIGH = {rec['green_avg_high']:.2f}",
        f"  AMBER_AVG_LOW  = {rec['amber_avg_low']:.2f}",
        f"  AMBER_AVG_HIGH = {rec['amber_avg_high']:.2f}",
        f"  T3_POLICY_FLOOR = {rec['t3_policy_floor']:.2f}",
        "",
        f"Readiness: {data['readiness']}",
        f"Next step: {data['next_step']}",
    ]
    return "\n".join(lines)


def run(args) -> int:
    if not getattr(args, "analyze", False):
        print("error: calibrate currently requires --analyze", file=sys.stderr)
        return 2

    entries = load_entries()
    debug.log(args, f"telemetry_entries={len(entries)}")
    analysis = dim_disclosure.analyze(entries)
    if getattr(args, "_telemetry", None) is not None:
        args._telemetry["rows"] = analysis["sample"]["scored_entries"]
    if getattr(args, "json", False):
        print(fmt_json(analysis))
    else:
        print(_render_human(analysis))
    return 0
