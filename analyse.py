#!/usr/bin/env python3
"""
analyse.py  ·  Flight Analysis Pipeline & Safety Scoring
────────────────────────────────────────────────────────────────
Part of  : drone-flight-log-analyzer  |  Phase 1
Author   : Kamal Nayan Mishra (@kamalnayanmishra14)
────────────────────────────────────────────────────────────────
Safety Score — weighted algorithm (100 pts total)

  Component           Weight   Max    Scoring logic
  ──────────────────────────────────────────────────
  Battery             30 %      30    min_battery × 0.6 (cap 30),
                                      −5 per critical event,
                                      −drain-rate penalty
  Speed               25 %      25    full at ≤ 40 km/h, linear decay
                                      to 0 at 120 km/h, −3 per spike
  GPS Continuity      25 %      25    start at 25, −8 per time-gap,
                                      −12 per coordinate jump
  Altitude Stability  20 %      20    pstdev of |Δalt/Δt| (m/s):
                                      ≤ 1 m/s → 20, ≥ 4 m/s → 0

  Grade   Score
  ─────────────
  A       85 – 100
  B       70 – 84
  C       55 – 69
  D       40 – 54
  F        0 – 39
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

from ingest import (
    FlightRecord,
    haversine_m,
    load_flight_log,
    print_anomaly_summary,
    run_anomaly_detection,
    save_anomaly_report,
)

# ── Grade table ────────────────────────────────────────────────────────────────
_GRADE_TABLE = [
    (85, "A", "Excellent — Mission-Safe"),
    (70, "B", "Good — Minor Deviations"),
    (55, "C", "Fair — Review Recommended"),
    (40, "D", "Poor — Action Required"),
    ( 0, "F", "Fail — Unsafe Flight Profile"),
]

def _assign_grade(score: float) -> tuple[str, str]:
    for threshold, letter, label in _GRADE_TABLE:
        if score >= threshold:
            return letter, label
    return "F", "Fail — Unsafe Flight Profile"


# ── Component scorer: Battery (30 pts) ────────────────────────────────────────
def _score_battery(
    records   : list[FlightRecord],
    anomalies : list[dict],
) -> tuple[float, str]:
    """
    Base score  : min(30,  min_battery_pct × 0.60)
                  → full 30 pts when minimum battery ≥ 50 %
                  → 0 pts at 0 %  (linear between)
    Penalty A   : −5 pts per reading below 20 % (critical event)
    Penalty B   : −2 pts per % / min above 5 % / min drain rate,
                  capped at −10 pts
    """
    batteries = [r.battery_percent for r in records]
    min_b     = min(batteries)
    base      = min(30.0, min_b * 0.60)

    crit_count = sum(1 for a in anomalies if a.get("kind") == "battery")
    anomaly_p  = crit_count * 5.0

    drain_p = 0.0
    if len(records) >= 2:
        elapsed_s   = (records[-1].timestamp - records[0].timestamp).total_seconds()
        total_drain = max(0.0, batteries[0] - batteries[-1])
        if elapsed_s > 0:
            rate    = (total_drain / elapsed_s) * 60          # % per minute
            drain_p = min(10.0, max(0.0, (rate - 5.0) * 2.0))

    score = max(0.0, min(30.0, base - anomaly_p - drain_p))
    note  = (
        f"Min battery {min_b:.1f}%  |  "
        f"{crit_count} critical event(s)  |  "
        f"Drain penalty {drain_p:.1f} pt(s)"
    )
    return round(score, 2), note


# ── Component scorer: Speed (25 pts) ──────────────────────────────────────────
def _score_speed(
    records   : list[FlightRecord],
    anomalies : list[dict],
) -> tuple[float, str]:
    """
    Base score  : 25 pts when max_speed ≤ 40 km/h.
                  Linear decay to 0 at 120 km/h.
    Penalty     : −3 pts per speed spike event above 60 km/h.
    """
    max_kmh = max(r.speed * 3.6 for r in records)
    if max_kmh <= 40.0:
        base = 25.0
    elif max_kmh >= 120.0:
        base = 0.0
    else:
        base = 25.0 * (1.0 - (max_kmh - 40.0) / 80.0)

    spikes = sum(1 for a in anomalies if a.get("kind") == "speed")
    score  = max(0.0, min(25.0, base - spikes * 3.0))
    note   = f"Max speed {max_kmh:.1f} km/h  |  {spikes} spike event(s)"
    return round(score, 2), note


# ── Component scorer: GPS Continuity (25 pts) ─────────────────────────────────
def _score_gps(anomalies: list[dict]) -> tuple[float, str]:
    """
    Start at 25 pts.
    −8 pts per time-gap event (gps_gap).
    −12 pts per coordinate-jump event (gps_jump).
    Minimum 0.
    """
    gaps   = sum(1 for a in anomalies if a.get("kind") == "gps_gap")
    jumps  = sum(1 for a in anomalies if a.get("kind") == "gps_jump")
    score  = max(0.0, 25.0 - gaps * 8.0 - jumps * 12.0)
    note   = f"{gaps} time gap(s)  |  {jumps} coordinate jump(s)"
    return round(score, 2), note


# ── Component scorer: Altitude Stability (20 pts) ─────────────────────────────
def _score_altitude(records: list[FlightRecord]) -> tuple[float, str]:
    """
    Compute the population std-dev of |Δaltitude / Δt| (m/s) across
    all consecutive record pairs.

    std ≤ 1.0 m/s → 20 pts  (very smooth climb/descent profile)
    std ≥ 4.0 m/s →  0 pts  (erratic altitude changes)
    Linear interpolation between the two bounds.
    """
    if len(records) < 3:
        return 20.0, "Insufficient records for stability analysis"

    rates: list[float] = []
    for prev, curr in zip(records, records[1:]):
        dt = (curr.timestamp - prev.timestamp).total_seconds()
        if dt > 0:
            rates.append(abs(curr.altitude - prev.altitude) / dt)

    if not rates:
        return 20.0, "No altitude deltas computed"

    std = statistics.pstdev(rates)
    if std <= 1.0:
        score = 20.0
    elif std >= 4.0:
        score = 0.0
    else:
        score = 20.0 * (1.0 - (std - 1.0) / 3.0)

    note = f"Altitude rate std-dev {std:.2f} m/s"
    return round(score, 2), note


# ── Score aggregator ───────────────────────────────────────────────────────────
def calculate_flight_score(
    records        : list[FlightRecord],
    anomaly_report : dict,
) -> dict:
    """Return the complete safety-score breakdown as a serialisable dict."""
    flat_anomalies = (
        anomaly_report["anomalies"]["battery"]
        + anomaly_report["anomalies"]["speed"]
        + anomaly_report["anomalies"]["gps"]
    )

    b_s,  b_n  = _score_battery(records, flat_anomalies)
    sp_s, sp_n = _score_speed(records, flat_anomalies)
    g_s,  g_n  = _score_gps(flat_anomalies)
    a_s,  a_n  = _score_altitude(records)

    total = b_s + sp_s + g_s + a_s
    grade, label = _assign_grade(total)

    return {
        "score"       : round(total, 2),
        "max_score"   : 100,
        "grade"       : grade,
        "grade_label" : label,
        "components"  : {
            "battery"            : {"score": b_s,  "max": 30, "weight": "30%", "note": b_n},
            "speed"              : {"score": sp_s, "max": 25, "weight": "25%", "note": sp_n},
            "gps_continuity"     : {"score": g_s,  "max": 25, "weight": "25%", "note": g_n},
            "altitude_stability" : {"score": a_s,  "max": 20, "weight": "20%", "note": a_n},
        },
    }


# ── Flight statistics ──────────────────────────────────────────────────────────
def compute_flight_stats(records: list[FlightRecord]) -> dict:
    """Compute basic flight statistics (mirrors flight_log_analyzer.py output)."""
    alts   = [r.altitude        for r in records]
    speeds = [r.speed           for r in records]
    batts  = [r.battery_percent for r in records]
    dist_m = sum(
        haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
        for a, b in zip(records, records[1:])
    )
    dur = records[-1].timestamp - records[0].timestamp
    return {
        "records"          : len(records),
        "start_time"       : records[0].timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time"         : records[-1].timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "flight_duration"  : str(dur),
        "max_altitude_m"   : max(alts),
        "avg_altitude_m"   : round(sum(alts) / len(alts), 2),
        "max_speed_kmh"    : round(max(speeds) * 3.6, 2),
        "avg_speed_kmh"    : round(sum(speeds) / len(speeds) * 3.6, 2),
        "min_battery_pct"  : min(batts),
        "max_battery_pct"  : max(batts),
        "total_distance_m" : round(dist_m, 2),
        "total_distance_km": round(dist_m / 1000, 3),
    }


# ── Full report builder ────────────────────────────────────────────────────────
def build_full_report(
    records        : list[FlightRecord],
    anomaly_report : dict,
    score_report   : dict,
    csv_path       : Path,
) -> dict:
    """Assemble the complete JSON report consumed by debrief.py."""
    return {
        "source_file"     : str(csv_path),
        "generated_at"    : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "flight_stats"    : compute_flight_stats(records),
        "anomaly_summary" : anomaly_report["summary"],
        "anomalies"       : anomaly_report["anomalies"],
        "safety_score"    : score_report,
    }


# ── Terminal output ────────────────────────────────────────────────────────────
def print_score_report(s: dict) -> None:
    total    = s["score"]
    filled   = int(total / 2)
    bar      = "█" * filled + "░" * (50 - filled)

    print("══ FLIGHT SAFETY SCORE " + "═" * 39)
    print(f"   {total:.1f} / 100   Grade: {s['grade']}  —  {s['grade_label']}")
    print(f"   [{bar}]")
    print()
    print("── Component Breakdown " + "─" * 39)
    for name, comp in s["components"].items():
        label = name.replace("_", " ").title()
        pct   = comp["score"] / comp["max"] if comp["max"] else 0
        cb    = "█" * int(pct * 20) + "░" * (20 - int(pct * 20))
        print(
            f"   {label:<24}  {comp['score']:>5.1f} / {comp['max']:<2}  "
            f"[{cb}]  {comp['weight']}"
        )
        print(f"    └─ {comp['note']}")
    print("═" * 62 + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Full drone flight analysis pipeline with weighted safety score.",
    )
    ap.add_argument("csv_file",    type=Path,           help="Path to flight log CSV")
    ap.add_argument("--json",      type=Path, metavar="PATH",
                    help="Save full report to JSON (required by debrief.py)")
    ap.add_argument("--anomalies", type=Path, metavar="PATH",
                    help="Save anomaly-only JSON report")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    try:
        records        = load_flight_log(args.csv_file)
        anomaly_report = run_anomaly_detection(records)
        score_report   = calculate_flight_score(records, anomaly_report)
        full_report    = build_full_report(records, anomaly_report, score_report, args.csv_file)

        print_anomaly_summary(anomaly_report)
        print_score_report(score_report)

        if args.anomalies:
            save_anomaly_report(anomaly_report, args.anomalies)
            print(f"Anomaly report → {args.anomalies}")

        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            with args.json.open("w", encoding="utf-8") as fh:
                json.dump(full_report, fh, indent=2)
                fh.write("\n")
            print(f"Full report    → {args.json}")

    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
