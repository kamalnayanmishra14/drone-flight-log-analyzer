#!/usr/bin/env python3
"""
debrief.py  ·  AI Pilot Debrief via Ollama (qwen2.5-coder:14b)
────────────────────────────────────────────────────────────────
Part of  : drone-flight-log-analyzer  |  Phase 1
Author   : Kamal Nayan Mishra (@kamalnayanmishra14)

Reads the full analysis JSON produced by analyse.py, sends it to
a local Ollama model, and receives a 3-paragraph professional
pilot debrief:
  Para 1 — Mission Overview
  Para 2 — Anomaly Analysis
  Para 3 — Recommendations & Next Steps

Zero external dependencies — uses only stdlib urllib.
────────────────────────────────────────────────────────────────
Usage:
  # Run the analysis pipeline first:
  python3 analyse.py sample_flight_log.csv --json output/report.json

  # Then generate the debrief:
  python3 debrief.py output/report.json
  python3 debrief.py output/report.json --out output/debrief.txt
  python3 debrief.py output/report.json --model gemma3:12b
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

OLLAMA_BASE    = "http://localhost:11434"
OLLAMA_GENERATE = f"{OLLAMA_BASE}/api/generate"
DEFAULT_MODEL  = "qwen2.5-coder:14b"


# ── Report loader ──────────────────────────────────────────────────────────────
def load_report(path: Path) -> dict:
    """Load the full analysis JSON report from analyse.py."""
    if not path.is_file():
        raise FileNotFoundError(f"Report not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ── Prompt builder ─────────────────────────────────────────────────────────────
def build_prompt(report: dict) -> str:
    """
    Construct a structured, data-rich prompt from the analysis report.
    The model receives all flight stats, component scores, and anomaly
    details in a single context block.
    """
    stats   = report.get("flight_stats", {})
    score   = report.get("safety_score", {})
    summary = report.get("anomaly_summary", {})
    anomaly_data = report.get("anomalies", {})

    # Serialise all anomaly detail lines
    detail_lines: list[str] = []
    for kind, items in anomaly_data.items():
        for item in items:
            sev  = item.get("severity", "info").upper()
            ts   = item.get("timestamp", "?")
            txt  = item.get("detail", "")
            detail_lines.append(f"  [{sev}] {ts}  {txt}")
    anomaly_block = "\n".join(detail_lines) if detail_lines else "  None detected."

    # Component score lines
    comps = score.get("components", {})
    comp_block = "\n".join(
        f"  {k.replace('_', ' ').title():<24}: {v['score']}/{v['max']}  ({v['weight']})  — {v.get('note', '')}"
        for k, v in comps.items()
    )

    grade       = score.get("grade", "?")
    grade_label = score.get("grade_label", "N/A")

    return f"""You are an expert UAV flight operations analyst writing an official post-mission debrief report for a DGCA-regulated drone operation in India.

════════════════════ TELEMETRY REPORT ════════════════════════

FLIGHT STATISTICS
  Duration        : {stats.get("flight_duration", "N/A")}
  Max Altitude    : {stats.get("max_altitude_m", "N/A")} m
  Avg Altitude    : {stats.get("avg_altitude_m", "N/A")} m
  Max Speed       : {stats.get("max_speed_kmh", "N/A")} km/h
  Avg Speed       : {stats.get("avg_speed_kmh", "N/A")} km/h
  Total Distance  : {stats.get("total_distance_km", "N/A")} km
  Min Battery     : {stats.get("min_battery_pct", "N/A")}%
  Max Battery     : {stats.get("max_battery_pct", "N/A")}%
  Data Records    : {stats.get("records", "N/A")}

SAFETY SCORE
  Total Score     : {score.get("score", "N/A")} / 100
  Grade           : {grade}  —  {grade_label}
{comp_block}

ANOMALY SUMMARY
  Total           : {summary.get("total_anomalies", 0)}
  Critical        : {summary.get("critical_count", 0)}
  Warnings        : {summary.get("warning_count", 0)}

ANOMALY DETAILS
{anomaly_block}

══════════════════════════════════════════════════════════════

Write a professional pilot debrief in EXACTLY 3 paragraphs. Requirements:
  - No bullet points, no headers, no markdown, no numbering
  - Continuous formal prose only
  - Aviation/UAV operations language appropriate for DGCA India
  - Reference specific values from the telemetry (altitude, speed, distance, score)

PARAGRAPH 1 — MISSION OVERVIEW
Summarise the flight envelope: total duration, maximum altitude reached, distance covered, and peak speed recorded. State whether the mission profile was nominal or irregular. Provide a concise overall operational assessment based on the aggregate safety score.

PARAGRAPH 2 — ANOMALY ANALYSIS
Describe every detected anomaly precisely, citing its category (battery / speed / GPS), severity level, and the timestamp at which it occurred. If the safety score indicates a clean flight, confirm the absence of anomalies and commend the operational discipline demonstrated. Do not fabricate anomalies that are not in the data.

PARAGRAPH 3 — RECOMMENDATIONS & NEXT STEPS
Provide exactly three specific, actionable recommendations for the pilot, referencing the safety score grade ({grade} — {grade_label}). Address at least one of the following areas as appropriate: pre-flight battery management, speed discipline during operations, GPS signal verification procedure, or altitude profile optimisation. Close with a single sentence on readiness for the next mission.

Output only the three paragraphs. No preamble, no sign-off, no metadata."""


# ── Ollama API caller ──────────────────────────────────────────────────────────
def call_ollama(
    prompt  : str,
    model   : str = DEFAULT_MODEL,
    timeout : int = 120,
) -> str:
    """
    POST to Ollama /api/generate (non-streaming) and return response text.
    Uses only stdlib urllib — no third-party dependencies required.
    """
    payload = json.dumps({
        "model"   : model,
        "prompt"  : prompt,
        "stream"  : False,
        "options" : {
            "temperature" : 0.35,    # low temp → precise, factual language
            "top_p"       : 0.90,
            "num_predict" : 700,     # ~3 solid paragraphs
        },
    }).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_GENERATE,
        data    = payload,
        headers = {"Content-Type": "application/json"},
        method  = "POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = json.loads(resp.read())
            return body.get("response", "").strip()
    except urllib.error.URLError as exc:
        raise ConnectionError(
            f"Cannot reach Ollama at {OLLAMA_GENERATE}\n"
            f"  1. Start Ollama:           ollama serve\n"
            f"  2. Pull model if needed:   ollama pull {model}\n"
            f"  3. Verify it's running:    curl {OLLAMA_BASE}/api/tags\n"
            f"Details: {exc}"
        ) from exc


# ── Output helpers ─────────────────────────────────────────────────────────────
def _build_header(report: dict) -> str:
    score = report.get("safety_score", {})
    return (
        "\n" + "═" * 62 + "\n"
        "  DRONE FLIGHT DEBRIEF — AI ANALYST REPORT\n"
        f"  Source   : {report.get('source_file', 'unknown')}\n"
        f"  Analysed : {report.get('generated_at', '?')}\n"
        f"  Debriefed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"  Safety   : {score.get('score', '?')}/100  "
        f"Grade {score.get('grade', '?')} — {score.get('grade_label', '')}\n"
        + "═" * 62
    )


def print_debrief(text: str, report: dict) -> None:
    print(_build_header(report))
    print()
    print(text)
    print("\n" + "═" * 62 + "\n")


def save_debrief(text: str, path: Path, report: dict) -> None:
    """Write the debrief to a plain-text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(_build_header(report).strip() + "\n\n")
        fh.write(text + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Generate a professional AI pilot debrief from a flight analysis report "
            "using a local Ollama model."
        ),
    )
    ap.add_argument(
        "report_json",
        type=Path,
        help="Full analysis report JSON produced by analyse.py (--json flag)",
    )
    ap.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model name (default: {DEFAULT_MODEL})",
    )
    ap.add_argument(
        "--out",
        type=Path,
        metavar="PATH",
        help="Save debrief to a .txt file",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Ollama request timeout in seconds (default: 120)",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    try:
        print(f"\n  Loading report : {args.report_json}")
        report = load_report(args.report_json)

        print(f"  Model          : {args.model}")
        print(f"  Endpoint       : {OLLAMA_GENERATE}")
        print("  Generating debrief — please wait…\n")

        prompt = build_prompt(report)
        text   = call_ollama(prompt, model=args.model, timeout=args.timeout)

        print_debrief(text, report)

        if args.out:
            save_debrief(text, args.out, report)
            print(f"  Saved → {args.out}\n")

    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ConnectionError as exc:
        print(f"\nOllama connection error:\n{exc}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"Report parse error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
