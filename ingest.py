#!/usr/bin/env python3
"""
ingest.py  ·  Drone Telemetry Ingestion & Anomaly Detection
────────────────────────────────────────────────────────────────
Part of  : drone-flight-log-analyzer  |  Phase 1
Author   : Kamal Nayan Mishra (@kamalnayanmishra14)
Inherits : CSV schema from flight_log_analyzer.py
────────────────────────────────────────────────────────────────
Anomaly thresholds
  · Battery   < 20 %                    → CRITICAL
  · Speed     > 60 km/h (16.67 m/s)    → WARNING / CRITICAL
  · GPS gap   > 3× median interval      → WARNING
  · GPS jump  implied velocity > 50 m/s → CRITICAL
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────
REQUIRED_COLUMNS = (
    "timestamp", "latitude", "longitude",
    "altitude", "speed", "battery_percent",
)
EARTH_RADIUS_M = 6_371_000

BATTERY_CRITICAL_PCT        = 20.0
SPEED_LIMIT_KMH             = 60.0
SPEED_LIMIT_MPS             = SPEED_LIMIT_KMH / 3.6   # ≈ 16.667 m/s
GPS_GAP_MULTIPLIER          = 3.0
GPS_IMPOSSIBLE_VELOCITY_MPS = 50.0


# ── Data models ────────────────────────────────────────────────────────────────
@dataclass
class FlightRecord:
    timestamp       : datetime
    latitude        : float
    longitude       : float
    altitude        : float
    speed           : float
    battery_percent : float


@dataclass
class Anomaly:
    kind      : str   # battery | speed | gps_gap | gps_jump
    row_index : int   # 0-based index into records list
    timestamp : str   # formatted string for serialisation
    field     : str
    value     : float
    threshold : float
    severity  : str   # warning | critical
    detail    : str


# ── Geometry ───────────────────────────────────────────────────────────────────
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres between two GPS coordinates."""
    rl1, ro1 = math.radians(lat1), math.radians(lon1)
    rl2, ro2 = math.radians(lat2), math.radians(lon2)
    dlat = rl2 - rl1
    dlon = ro2 - ro1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rl1) * math.cos(rl2) * math.sin(dlon / 2) ** 2
    )
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Timestamp parsing ──────────────────────────────────────────────────────────
_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
)

def parse_timestamp(value: str) -> datetime:
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported timestamp format: {value!r}")


# ── CSV loader ─────────────────────────────────────────────────────────────────
def load_flight_log(csv_path: Path) -> list[FlightRecord]:
    """Load, validate, and sort flight records from a CSV file."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"File not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("CSV is empty or missing a header row.")
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        records: list[FlightRecord] = []
        for line_no, row in enumerate(reader, start=2):
            try:
                records.append(FlightRecord(
                    timestamp       = parse_timestamp(row["timestamp"]),
                    latitude        = float(row["latitude"]),
                    longitude       = float(row["longitude"]),
                    altitude        = float(row["altitude"]),
                    speed           = float(row["speed"]),
                    battery_percent = float(row["battery_percent"]),
                ))
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Invalid data on row {line_no}: {exc}") from exc

    if not records:
        raise ValueError("No flight records found in CSV.")
    return sorted(records, key=lambda r: r.timestamp)


# ── Anomaly detectors ──────────────────────────────────────────────────────────
def detect_battery_anomalies(records: list[FlightRecord]) -> list[Anomaly]:
    """Flag every reading where battery_percent falls below BATTERY_CRITICAL_PCT (20%)."""
    anomalies: list[Anomaly] = []
    for idx, rec in enumerate(records):
        if rec.battery_percent < BATTERY_CRITICAL_PCT:
            anomalies.append(Anomaly(
                kind      = "battery",
                row_index = idx,
                timestamp = rec.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                field     = "battery_percent",
                value     = rec.battery_percent,
                threshold = BATTERY_CRITICAL_PCT,
                severity  = "critical",
                detail    = (
                    f"Battery at {rec.battery_percent:.1f}% — "
                    f"below critical threshold of {BATTERY_CRITICAL_PCT:.0f}%"
                ),
            ))
    return anomalies


def detect_speed_anomalies(records: list[FlightRecord]) -> list[Anomaly]:
    """Flag readings exceeding 60 km/h (DGCA BVLOS / safe operations limit)."""
    anomalies: list[Anomaly] = []
    for idx, rec in enumerate(records):
        if rec.speed > SPEED_LIMIT_MPS:
            speed_kmh = rec.speed * 3.6
            # Escalate to critical if > 25 % above the limit (75 km/h)
            severity = "critical" if speed_kmh >= SPEED_LIMIT_KMH * 1.25 else "warning"
            anomalies.append(Anomaly(
                kind      = "speed",
                row_index = idx,
                timestamp = rec.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                field     = "speed",
                value     = rec.speed,
                threshold = SPEED_LIMIT_MPS,
                severity  = severity,
                detail    = (
                    f"Speed {speed_kmh:.1f} km/h — "
                    f"exceeds limit of {SPEED_LIMIT_KMH:.0f} km/h"
                ),
            ))
    return anomalies


def detect_gps_gaps(records: list[FlightRecord]) -> list[Anomaly]:
    """
    Detect two categories of GPS anomaly:

    gps_gap  — time interval between consecutive records > 3× the median interval.
               Indicates a logging break or satellite loss.

    gps_jump — the haversine distance between two consecutive points implies a
               velocity exceeding GPS_IMPOSSIBLE_VELOCITY_MPS (50 m/s / 180 km/h),
               which is physically impossible for a commercial UAS. Indicates a
               corrupt or spoofed coordinate.
    """
    if len(records) < 2:
        return []

    intervals = [
        (records[i + 1].timestamp - records[i].timestamp).total_seconds()
        for i in range(len(records) - 1)
    ]
    median_gap    = statistics.median(intervals)
    gap_threshold = GPS_GAP_MULTIPLIER * median_gap

    anomalies: list[Anomaly] = []
    for i, (prev, curr) in enumerate(zip(records, records[1:])):
        elapsed   = (curr.timestamp - prev.timestamp).total_seconds()
        dist_m    = haversine_m(prev.latitude, prev.longitude, curr.latitude, curr.longitude)
        implied_v = dist_m / elapsed if elapsed > 0 else 0.0

        if elapsed > gap_threshold:
            anomalies.append(Anomaly(
                kind      = "gps_gap",
                row_index = i + 1,
                timestamp = curr.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                field     = "timestamp",
                value     = elapsed,
                threshold = gap_threshold,
                severity  = "warning",
                detail    = (
                    f"Time gap {elapsed:.0f}s between consecutive records "
                    f"(threshold {gap_threshold:.0f}s; median {median_gap:.0f}s)"
                ),
            ))

        if implied_v > GPS_IMPOSSIBLE_VELOCITY_MPS:
            anomalies.append(Anomaly(
                kind      = "gps_jump",
                row_index = i + 1,
                timestamp = curr.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                field     = "latitude,longitude",
                value     = implied_v,
                threshold = GPS_IMPOSSIBLE_VELOCITY_MPS,
                severity  = "critical",
                detail    = (
                    f"Implied velocity {implied_v:.1f} m/s "
                    f"({implied_v * 3.6:.0f} km/h) — GPS coordinate jump suspected"
                ),
            ))

    return anomalies


# ── Orchestrator ───────────────────────────────────────────────────────────────
def run_anomaly_detection(records: list[FlightRecord]) -> dict:
    """Run all detectors and return a structured anomaly report dictionary."""
    battery = detect_battery_anomalies(records)
    speed   = detect_speed_anomalies(records)
    gps     = detect_gps_gaps(records)
    all_a   = battery + speed + gps

    return {
        "summary": {
            "total_records"         : len(records),
            "total_anomalies"       : len(all_a),
            "critical_count"        : sum(1 for a in all_a if a.severity == "critical"),
            "warning_count"         : sum(1 for a in all_a if a.severity == "warning"),
            "battery_anomaly_count" : len(battery),
            "speed_anomaly_count"   : len(speed),
            "gps_anomaly_count"     : len(gps),
        },
        "anomalies": {
            "battery" : [asdict(a) for a in battery],
            "speed"   : [asdict(a) for a in speed],
            "gps"     : [asdict(a) for a in gps],
        },
    }


def save_anomaly_report(report: dict, path: Path) -> None:
    """Serialise anomaly report to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")


# ── Terminal output ────────────────────────────────────────────────────────────
def print_anomaly_summary(report: dict) -> None:
    s = report["summary"]
    print("══ ANOMALY DETECTION " + "═" * 41)
    print(f"   Records scanned   : {s['total_records']}")
    print(
        f"   Total anomalies   : {s['total_anomalies']}  "
        f"(● Critical: {s['critical_count']}   ○ Warning: {s['warning_count']})"
    )
    print(
        f"   Battery: {s['battery_anomaly_count']}   "
        f"Speed: {s['speed_anomaly_count']}   "
        f"GPS: {s['gps_anomaly_count']}"
    )

    if s["total_anomalies"] == 0:
        print("   ✓ Clean flight — no anomalies detected.")
    else:
        for kind, items in report["anomalies"].items():
            if items:
                print(f"\n   [{kind.upper()}]")
                for a in items:
                    marker = "●" if a["severity"] == "critical" else "○"
                    print(f"     {marker} [{a['timestamp']}]  {a['detail']}")
    print("═" * 62 + "\n")


# ── Entry point (standalone usage) ────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Ingest flight log CSV and detect anomalies.",
    )
    ap.add_argument("csv_file", type=Path, help="Path to flight log CSV")
    ap.add_argument("--json", type=Path, metavar="PATH", help="Save anomaly report to JSON")
    args = ap.parse_args()

    try:
        records = load_flight_log(args.csv_file)
        report  = run_anomaly_detection(records)
        print_anomaly_summary(report)
        if args.json:
            save_anomaly_report(report, args.json)
            print(f"Saved → {args.json}")
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
