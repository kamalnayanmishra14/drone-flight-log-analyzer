#!/usr/bin/env python3
"""Analyze drone flight logs from CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REQUIRED_COLUMNS = [
    "timestamp",
    "latitude",
    "longitude",
    "altitude",
    "speed",
    "battery_percent",
]

EARTH_RADIUS_M = 6_371_000


@dataclass
class FlightRecord:
    timestamp: datetime
    latitude: float
    longitude: float
    altitude: float
    speed: float
    battery_percent: float


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in meters between two GPS points."""
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


def parse_timestamp(value: str) -> datetime:
    """Parse common timestamp formats from flight logs."""
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported timestamp format: {value!r}")


def load_flight_log(csv_path: Path) -> list[FlightRecord]:
    """Load and validate a flight log CSV file."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"File not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is empty or missing a header row.")

        missing = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        records: list[FlightRecord] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                records.append(
                    FlightRecord(
                        timestamp=parse_timestamp(row["timestamp"].strip()),
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                        altitude=float(row["altitude"]),
                        speed=float(row["speed"]),
                        battery_percent=float(row["battery_percent"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid data on row {row_number}: {exc}") from exc

    if not records:
        raise ValueError("CSV file contains no flight records.")

    return sorted(records, key=lambda record: record.timestamp)


def total_distance_m(records: list[FlightRecord]) -> float:
    """Sum segment distances between consecutive GPS readings."""
    if len(records) < 2:
        return 0.0

    distance = 0.0
    for previous, current in zip(records, records[1:]):
        distance += haversine_m(
            previous.latitude,
            previous.longitude,
            current.latitude,
            current.longitude,
        )
    return distance


def analyze_flight_log(records: list[FlightRecord]) -> dict[str, float | int | str]:
    """Compute basic flight statistics."""
    altitudes = [record.altitude for record in records]
    speeds = [record.speed for record in records]
    batteries = [record.battery_percent for record in records]

    duration = records[-1].timestamp - records[0].timestamp
    distance_m = total_distance_m(records)

    return {
        "records": len(records),
        "start_time": records[0].timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": records[-1].timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "flight_duration": str(duration),
        "max_altitude_m": max(altitudes),
        "min_altitude_m": min(altitudes),
        "avg_altitude_m": sum(altitudes) / len(altitudes),
        "max_speed_mps": max(speeds),
        "avg_speed_mps": sum(speeds) / len(speeds),
        "min_battery_percent": min(batteries),
        "max_battery_percent": max(batteries),
        "total_distance_m": distance_m,
        "total_distance_km": distance_m / 1000,
    }


def print_report(stats: dict[str, float | int | str]) -> None:
    """Print a formatted summary of flight statistics."""
    print("\n=== Drone Flight Log Summary ===")
    print(f"Records:              {stats['records']}")
    print(f"Start time:           {stats['start_time']}")
    print(f"End time:             {stats['end_time']}")
    print(f"Flight duration:      {stats['flight_duration']}")
    print(f"Max altitude:         {stats['max_altitude_m']:.2f} m")
    print(f"Min altitude:         {stats['min_altitude_m']:.2f} m")
    print(f"Avg altitude:         {stats['avg_altitude_m']:.2f} m")
    print(f"Max speed:            {stats['max_speed_mps']:.2f} m/s")
    print(f"Avg speed:            {stats['avg_speed_mps']:.2f} m/s")
    print(f"Min battery:          {stats['min_battery_percent']:.1f}%")
    print(f"Max battery:          {stats['max_battery_percent']:.1f}%")
    print(f"Total distance:       {stats['total_distance_m']:.2f} m")
    print(f"Total distance:       {stats['total_distance_km']:.3f} km")
    print("================================\n")


def save_json_report(stats: dict[str, float | int | str], output_path: Path) -> None:
    """Write flight statistics to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(stats, handle, indent=2)
        handle.write("\n")


def save_flight_plots(records: list[FlightRecord], output_path: Path) -> None:
    """Generate altitude, battery, speed, and flight path charts."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "Plotting requires matplotlib. Install it with: pip install matplotlib"
        ) from exc

    timestamps = [record.timestamp for record in records]
    altitudes = [record.altitude for record in records]
    batteries = [record.battery_percent for record in records]
    speeds = [record.speed for record in records]
    latitudes = [record.latitude for record in records]
    longitudes = [record.longitude for record in records]

    figure, axes = plt.subplots(2, 2, figsize=(12, 8))
    figure.suptitle("Drone Flight Log Analysis", fontsize=14, fontweight="bold")

    axes[0, 0].plot(timestamps, altitudes, color="#2563eb", linewidth=2)
    axes[0, 0].set_title("Altitude Over Time")
    axes[0, 0].set_ylabel("Altitude (m)")
    axes[0, 0].grid(True, alpha=0.3)

    axes[0, 1].plot(timestamps, batteries, color="#16a34a", linewidth=2)
    axes[0, 1].set_title("Battery Over Time")
    axes[0, 1].set_ylabel("Battery (%)")
    axes[0, 1].grid(True, alpha=0.3)

    axes[1, 0].plot(timestamps, speeds, color="#dc2626", linewidth=2)
    axes[1, 0].set_title("Speed Over Time")
    axes[1, 0].set_ylabel("Speed (m/s)")
    axes[1, 0].grid(True, alpha=0.3)

    axes[1, 1].plot(longitudes, latitudes, color="#7c3aed", linewidth=2, marker="o", markersize=3)
    axes[1, 1].scatter(longitudes[0], latitudes[0], color="#16a34a", s=60, label="Start", zorder=3)
    axes[1, 1].scatter(longitudes[-1], latitudes[-1], color="#dc2626", s=60, label="End", zorder=3)
    axes[1, 1].set_title("Flight Path")
    axes[1, 1].set_xlabel("Longitude")
    axes[1, 1].set_ylabel("Latitude")
    axes[1, 1].legend()
    axes[1, 1].grid(True, alpha=0.3)

    for axis in axes.flat:
        axis.tick_params(axis="x", rotation=25)

    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze drone flight logs from CSV files."
    )
    parser.add_argument(
        "csv_file",
        type=Path,
        help="Path to the flight log CSV file",
    )
    parser.add_argument(
        "--json",
        type=Path,
        metavar="PATH",
        help="Write statistics to a JSON file",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        metavar="PATH",
        help="Save flight charts to a PNG file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        records = load_flight_log(args.csv_file)
        stats = analyze_flight_log(records)
        print_report(stats)

        if args.json:
            save_json_report(stats, args.json)
            print(f"Saved JSON report to {args.json}")

        if args.plot:
            try:
                save_flight_plots(records, args.plot)
            except RuntimeError as exc:
                print(f"Warning: {exc}", file=sys.stderr)
                return 1
            print(f"Saved flight charts to {args.plot}")
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
