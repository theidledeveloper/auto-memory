"""Dim 9: Progressive Disclosure — analyzes tier usage patterns from telemetry.

Stage 1 behavior (this file at checkout): returns score=None, zone="CALIBRATING".
Stage 2 (after operator runs `calibrate --analyze` and hand-edits thresholds):
  operator fills in concrete GREEN/AMBER/RED thresholds below and flips SCORING_ACTIVE=True.
"""
from __future__ import annotations
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from ..config import TELEMETRY_PATH

# ---- Stage-2 gate. Operator flips this to True after hand-editing thresholds. ----
SCORING_ACTIVE = False

# Placeholders — operator replaces with observed μ±σ from `calibrate --analyze`.
GREEN_AVG_LOW, GREEN_AVG_HIGH = 1.15, 2.63   # μ ± 1σ band (example)
AMBER_AVG_LOW, AMBER_AVG_HIGH = 0.41, 3.37   # μ ± 2σ band (example)
T3_POLICY_FLOOR = 0.30                        # T3 > 30% is always suspicious

MIN_SAMPLE_SIZE = 200
MIN_SAMPLE_DAYS = 7
UNKNOWN_CEILING = 0.5   # if unknown_count / total > 0.5, force CALIBRATING

SWEEP_WINDOW_MIN = 5  # minutes; T3→T3 within this is drill-down, beyond is suspicious


def _load_entries() -> list[dict]:
    try:
        path = Path(TELEMETRY_PATH)
        if not path.exists():
            return []
        return json.loads(path.read_text()).get("entries", [])
    except Exception:
        return []


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None


def analyze(entries: list[dict] | None = None) -> dict:
    entries = list(entries or _load_entries())
    total = len(entries)
    unknown_count = sum(1 for e in entries if "tier" not in e)
    meta_count = sum(1 for e in entries if e.get("tier") == 0)
    scored = [e for e in entries if e.get("tier") in (1, 2, 3)]
    scored_n = len(scored)
    parsed = [_parse_ts(e.get("ts", "")) for e in entries]
    parsed = [ts for ts in parsed if ts is not None]
    first_ts = min(parsed) if parsed else None
    age_days = ((datetime.now(timezone.utc).replace(tzinfo=None) - first_ts).days if first_ts else 0)

    tiers = [e["tier"] for e in scored]
    transitions = _classify_transitions(scored) if scored else {
        "healthy": 0,
        "neutral": 0,
        "suspicious": 0,
        "repetition": 0,
    }
    esc_rate = _escalation_rate(transitions)
    avg = statistics.mean(tiers) if tiers else 0.0
    sigma = statistics.pstdev(tiers) if len(tiers) > 1 else 0.0
    t1 = sum(1 for t in tiers if t == 1)
    t2 = sum(1 for t in tiers if t == 2)
    t3 = sum(1 for t in tiers if t == 3)
    sample_ready = scored_n > 0 and not (
        scored_n < MIN_SAMPLE_SIZE and age_days < MIN_SAMPLE_DAYS
    )
    return {
        "sample": {
            "total_entries": total,
            "unknown_entries": unknown_count,
            "meta_entries": meta_count,
            "scored_entries": scored_n,
            "age_days": age_days,
            "sample_ready": sample_ready,
        },
        "distribution": {
            "tier1": t1,
            "tier2": t2,
            "tier3": t3,
            "tier1_pct": round((t1 / scored_n) * 100, 1) if scored_n else 0.0,
            "tier2_pct": round((t2 / scored_n) * 100, 1) if scored_n else 0.0,
            "tier3_pct": round((t3 / scored_n) * 100, 1) if scored_n else 0.0,
            "avg_tier": round(avg, 2),
            "sigma": round(sigma, 2),
            "escalation_rate_pct": round((esc_rate or 0.0) * 100, 1),
        },
        "transitions": transitions,
        "recommendation": {
            "green_avg_low": round(max(1.0, avg - sigma), 2) if tiers else GREEN_AVG_LOW,
            "green_avg_high": round(min(3.0, avg + sigma), 2) if tiers else GREEN_AVG_HIGH,
            "amber_avg_low": round(max(1.0, avg - (2 * sigma)), 2) if tiers else AMBER_AVG_LOW,
            "amber_avg_high": round(min(3.0, avg + (2 * sigma)), 2) if tiers else AMBER_AVG_HIGH,
            "t3_policy_floor": T3_POLICY_FLOOR,
            "scoring_active": SCORING_ACTIVE,
        },
        "readiness": (
            "ready for operator review"
            if sample_ready
            else f"collect more data ({scored_n}/{MIN_SAMPLE_SIZE} scored entries, {age_days}/{MIN_SAMPLE_DAYS} days)"
        ),
        "next_step": (
            "Review thresholds, hand-edit dim_disclosure.py, then flip SCORING_ACTIVE=True when comfortable."
            if tiers
            else "No scored telemetry yet. Run session-recall commands that hit tiers 1-3 first."
        ),
    }


def _classify_transitions(scored: list[dict]) -> dict:
    """Returns {healthy, neutral, suspicious, repetition} counts over adjacent pairs."""
    healthy = neutral = suspicious = repetition = 0
    sorted_e = sorted(scored, key=lambda e: e.get("ts") or "")
    for prev, curr in zip(sorted_e, sorted_e[1:]):
        pt, ct = prev.get("tier"), curr.get("tier")
        if pt is None or ct is None:
            continue
        pts, cts = _parse_ts(prev.get("ts", "")), _parse_ts(curr.get("ts", ""))
        gap_min = ((cts - pts).total_seconds() / 60) if (pts and cts) else 0

        if pt == 1 and ct in (2, 3):
            healthy += 1
        elif pt == 2 and ct == 3:
            healthy += 1
        elif pt == 3 and ct == 3:
            if gap_min <= SWEEP_WINDOW_MIN:
                neutral += 1
            else:
                suspicious += 1
        elif pt == 2 and ct == 2 and prev.get("query_hash") and prev.get("query_hash") == curr.get("query_hash"):
            repetition += 1
    # Cold-start T3: a T3 with no T1/T2 in the preceding SWEEP_WINDOW_MIN
    for i, e in enumerate(sorted_e):
        if e.get("tier") != 3:
            continue
        ets = _parse_ts(e.get("ts", ""))
        if not ets:
            continue
        window_start = ets - timedelta(minutes=SWEEP_WINDOW_MIN)
        preceded = any(
            p.get("tier") in (1, 2) and (_parse_ts(p.get("ts", "")) or datetime.min) >= window_start
            for p in sorted_e[:i]
        )
        if not preceded:
            suspicious += 1
    return {"healthy": healthy, "neutral": neutral,
            "suspicious": suspicious, "repetition": repetition}


def _escalation_rate(t: dict) -> float | None:
    denom = t["healthy"] + t["suspicious"]
    if denom == 0:
        return None
    return t["healthy"] / denom


def check() -> dict:
    entries = _load_entries()
    analysis = analyze(entries)
    total = len(entries)
    unknown_count = sum(1 for e in entries if "tier" not in e)
    meta_count = sum(1 for e in entries if e.get("tier") == 0)
    scored = [e for e in entries if e.get("tier") in (1, 2, 3)]
    scored_n = len(scored)

    base = {"name": "Progressive Disclosure",
            "unknown_entries": unknown_count,
            "meta_entries": meta_count,
            "scored_entries": scored_n}

    # Guard 1: mixed-schema drain
    if total > 0 and unknown_count / total > UNKNOWN_CEILING:
        return {**base, "score": None, "zone": "CALIBRATING",
                "detail": f"unknown={unknown_count}/{total} (>{int(UNKNOWN_CEILING*100)}%) — legacy entries draining",
                "hint": "mixed-schema telemetry — waiting for legacy entries to drain"}

    # Guard 2: insufficient sample
    age_days = analysis["sample"]["age_days"]
    if scored_n == 0:
        return {**base, "score": None, "zone": "CALIBRATING",
                "detail": f"0/{MIN_SAMPLE_SIZE} non-meta entries, {age_days}d since first",
                "hint": "No scored telemetry yet. Run session-recall commands that hit tiers 1-3 first."}
    if scored_n < MIN_SAMPLE_SIZE and age_days < MIN_SAMPLE_DAYS:
        return {**base, "score": None, "zone": "CALIBRATING",
                "detail": f"{scored_n}/{MIN_SAMPLE_SIZE} non-meta entries, {age_days}d since first",
                "hint": f"Collecting baseline. Score activates at {MIN_SAMPLE_SIZE} entries or {MIN_SAMPLE_DAYS} days."}

    # Distribution
    tiers = [e["tier"] for e in scored]
    t1 = sum(1 for t in tiers if t == 1) / scored_n
    t2 = sum(1 for t in tiers if t == 2) / scored_n
    t3 = sum(1 for t in tiers if t == 3) / scored_n
    avg = statistics.mean(tiers)
    transitions = analysis["transitions"]
    esc_rate = _escalation_rate(transitions)

    detail = (f"T1={t1:.0%} T2={t2:.0%} T3={t3:.0%} avg={avg:.2f} "
              f"esc_rate={esc_rate:.0%} " if esc_rate is not None else
              f"T1={t1:.0%} T2={t2:.0%} T3={t3:.0%} avg={avg:.2f} ")
    detail += f"(n={scored_n}, meta={meta_count}, unknown={unknown_count})"

    if not SCORING_ACTIVE:
        return {**base, "score": None, "zone": "CALIBRATING",
                "detail": detail,
                "hint": "Baseline collected. Run `session-recall calibrate --analyze`, then hand-edit thresholds + flip SCORING_ACTIVE=True.",
                "transitions": transitions}

    # Stage 2 scoring (only reached after operator activates)
    if t3 > T3_POLICY_FLOOR:
        zone, score = "RED", 2.0
        hint = f"T3={t3:.0%} > policy floor {T3_POLICY_FLOOR:.0%} — agent skipping ladder"
        if transitions["suspicious"] > transitions["healthy"]:
            hint += "; too many direct deep dives"
    elif GREEN_AVG_LOW <= avg <= GREEN_AVG_HIGH:
        zone, score = "GREEN", 8.0
        hint = "Mostly staying in cheap tiers before deep recall." if transitions["healthy"] else ""
    elif AMBER_AVG_LOW <= avg <= AMBER_AVG_HIGH:
        zone, score = "AMBER", 5.0
        hint = f"avg_tier={avg:.2f} outside 1σ band"
        if transitions["repetition"] >= 2:
            hint += "; repeated search patterns suggest narrowing queries sooner"
    else:
        zone, score = "RED", 2.0
        hint = f"avg_tier={avg:.2f} outside 2σ band"
        if transitions["suspicious"] > transitions["healthy"]:
            hint += "; start with list/files before show"

    return {**base, "score": score, "zone": zone, "detail": detail, "hint": hint,
            "transitions": transitions}
