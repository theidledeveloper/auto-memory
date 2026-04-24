"""Telemetry summaries for stats, health, and calibration surfaces."""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

from ..config import TELEMETRY_PATH


def load_entries(path: str = TELEMETRY_PATH) -> list[dict]:
    try:
        telemetry_path = Path(path)
        if not telemetry_path.exists():
            return []
        return json.loads(telemetry_path.read_text()).get("entries", [])
    except Exception:
        return []


def _p95(values: list[int | float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(len(ordered) * 0.95)
    return float(ordered[min(idx, len(ordered) - 1)])


def summarize(entries: list[dict] | None = None) -> dict:
    entries = list(entries or load_entries())
    command_counts = Counter(e.get("cmd", "unknown") for e in entries if e.get("cmd"))
    durations = [
        int(e.get("duration_ms", 0))
        for e in entries
        if isinstance(e.get("duration_ms", 0), (int, float))
    ]
    total_busy = sum(int(e.get("busy_hits", 0) or 0) for e in entries)
    avg_attempts = (
        sum(float(e.get("attempts", 1) or 1) for e in entries) / len(entries)
        if entries
        else 0.0
    )

    tier_counts = Counter()
    scored_tiers: list[int] = []
    for entry in entries:
        tier = entry.get("tier")
        if tier in (0, 1, 2, 3):
            tier_counts[tier] += 1
            if tier in (1, 2, 3):
                scored_tiers.append(tier)
        else:
            tier_counts["legacy"] += 1

    scored_n = len(scored_tiers)
    t1 = tier_counts[1]
    t2 = tier_counts[2]
    t3 = tier_counts[3]
    avg_tier = round(statistics.mean(scored_tiers), 2) if scored_tiers else None

    return {
        "entries": len(entries),
        "command_counts": dict(sorted(command_counts.items())),
        "top_commands": [
            {"command": command, "count": count}
            for command, count in command_counts.most_common(5)
        ],
        "latency_ms": {
            "avg": round(sum(durations) / len(durations), 1) if durations else 0.0,
            "p95": round(_p95(durations), 1) if durations else 0.0,
        },
        "busy": {
            "busy_hits_total": total_busy,
            "busy_hit_rate_pct": round((total_busy / len(entries)) * 100, 1) if entries else 0.0,
            "avg_attempts": round(avg_attempts, 2) if entries else 0.0,
        },
        "tier_distribution": {
            "legacy_entries": tier_counts["legacy"],
            "meta_entries": tier_counts[0],
            "tier1": t1,
            "tier2": t2,
            "tier3": t3,
            "scored_entries": scored_n,
            "tier1_pct": round((t1 / scored_n) * 100, 1) if scored_n else 0.0,
            "tier2_pct": round((t2 / scored_n) * 100, 1) if scored_n else 0.0,
            "tier3_pct": round((t3 / scored_n) * 100, 1) if scored_n else 0.0,
            "avg_tier": avg_tier,
        },
    }


def explain(summary: dict, disclosure: dict | None = None) -> str:
    if summary["entries"] == 0:
        return "No telemetry yet. Run session-recall a few times first."

    tiers = summary["tier_distribution"]
    t3_pct = tiers["tier3_pct"]
    t1_t2_pct = tiers["tier1_pct"] + tiers["tier2_pct"]
    if disclosure and disclosure.get("zone") == "CALIBRATING":
        return disclosure.get("hint") or "Progressive disclosure is still calibrating."
    transitions = disclosure.get("transitions", {}) if disclosure else {}
    if transitions.get("suspicious", 0) > transitions.get("healthy", 0):
        return "You are jumping into deep recall too often. Start with list/files, then search, then show."
    if transitions.get("repetition", 0) >= 2:
        return "You are repeating the same searches. Narrow terms sooner or jump to show once the session is obvious."
    if t3_pct > 30:
        return "Deep recall is doing too much work. Cheap tiers are not carrying enough of the load."
    if t1_t2_pct >= 80:
        return "Most recall stays in cheap tiers. Deep dives look targeted."
    return "Recall usage is mixed. There is room to stay in Tier 1/2 more often."
