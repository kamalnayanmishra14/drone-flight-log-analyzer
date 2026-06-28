# Drone Flight Log Analyzer

A Python pipeline that ingests drone telemetry CSV files, detects flight anomalies, computes a weighted safety score, and generates an AI-written pilot debrief using a local Ollama model — no cloud, no API key, zero cost.

> Built by [Kamal Nayan Mishra](https://github.com/kamalnayanmishra14) · DGCA Remote Pilot · BCA + Drone Technology Diploma

---

## Pipeline Overview

```
flight_log.csv
      │
      ▼
 ingest.py          →  anomaly detection (battery / speed / GPS)
      │
      ▼
 analyse.py         →  safety score 0–100  ·  grade A / B / C / D / F
      │
      ▼
 report.json
      │
      ▼
 debrief.py         →  Ollama (qwen2.5-coder:14b)  →  3-paragraph pilot debrief
```

---

## Features

**Phase 0 — Flight Statistics** (`flight_log_analyzer.py`)
- Parse and validate flight log CSV files
- Compute altitude, speed, battery, and distance statistics
- Calculate total distance using the Haversine formula
- Export statistics to JSON
- Generate charts for altitude, battery, speed, and flight path

**Phase 1 — Anomaly Detection + AI Debrief**
- Detect battery drops below 20% (critical)
- Detect speed spikes above 60 km/h (DGCA limit)
- Detect GPS time gaps and coordinate jumps
- Compute weighted Flight Safety Score (100 pts)
- Generate professional pilot debrief via local Ollama model

---

## Safety Score Algorithm

| Component | Weight | Scoring Logic |
|---|---|---|
| Battery | 30% | Full score at ≥ 50% reserve · −5 per critical event |
| Speed | 25% | Full at ≤ 40 km/h · linear decay to 0 at 120 km/h |
| GPS Continuity | 25% | −8 per time gap · −12 per coordinate jump |
| Altitude Stability | 20% | Std-dev of rate-of-change · ≤ 1 m/s = full score |

| Grade | Score |
|---|---|
| A | 85 – 100 |
| B | 70 – 84 |
| C | 55 – 69 |
| D | 40 – 54 |
| F | 0 – 39 |

---

## CSV Format

Your CSV file must include these columns:

| Column | Description |
|---|---|
| `timestamp` | Flight time (`YYYY-MM-DD HH:MM:SS`) |
| `latitude` | GPS latitude in decimal degrees |
| `longitude` | GPS longitude in decimal degrees |
| `altitude` | Altitude in metres |
| `speed` | Speed in metres per second |
| `battery_percent` | Battery level (0–100) |

---

## Usage

### Phase 0 — Basic Statistics

```bash
python3 flight_log_analyzer.py sample_flight_log.csv
```

With JSON export and charts:
```bash
pip install -r requirements.txt
python3 flight_log_analyzer.py sample_flight_log.csv \
  --json output/report.json \
  --plot output/flight_charts.png
```

### Phase 1 — Full Pipeline

**Step 1 — Anomaly detection only:**
```bash
python3 ingest.py sample_flight_log.csv
```

**Step 2 — Full analysis + safety score:**
```bash
python3 analyse.py sample_flight_log.csv --json output/report.json
```

**Step 3 — AI pilot debrief (requires Ollama):**
```bash
python3 debrief.py output/report.json --out output/debrief.txt
```

**Run everything at once:**
```bash
python3 analyse.py sample_flight_log.csv --json output/report.json && \
python3 debrief.py output/report.json --out output/debrief.txt
```

---

## Example Output

### Safety Score
```
══ FLIGHT SAFETY SCORE ════════════════════════════════════
   100.0 / 100   Grade: A  —  Excellent — Mission-Safe
   [██████████████████████████████████████████████████]

── Component Breakdown ────────────────────────────────────
   Battery                    30.0 / 30  [████████████████████]  30%
    └─ Min battery 91.8%  |  0 critical event(s)
   Speed                      25.0 / 25  [████████████████████]  25%
    └─ Max speed 29.2 km/h  |  0 spike event(s)
   Gps Continuity             25.0 / 25  [████████████████████]  25%
    └─ 0 time gap(s)  |  0 coordinate jump(s)
   Altitude Stability         20.0 / 20  [████████████████████]  20%
    └─ Altitude rate std-dev 0.84 m/s
```

### AI Debrief (generated locally by qwen2.5-coder:14b)
```
DRONE FLIGHT DEBRIEF — AI ANALYST REPORT
Safety : 100.0/100  Grade A — Excellent — Mission-Safe

The flight operation conducted today was executed within nominal
parameters... The aggregate safety score of 100.0/100, graded as
A — Excellent — Mission-Safe, reflects a high standard of operational
discipline and adherence to flight parameters.

The telemetry data did not reveal any anomalies during the flight
operation. Battery performance was exemplary, GPS continuity was
flawless, speed remained within safe limits throughout the mission.

Based on the excellent performance, it is recommended that the pilot
continue to maintain rigorous pre-flight battery management practices...
```

---

## Project Structure

```
drone-flight-log-analyzer/
├── flight_log_analyzer.py   # Phase 0 — statistics & charts
├── ingest.py                # Phase 1 — CSV loader + anomaly detection
├── analyse.py               # Phase 1 — safety score pipeline
├── debrief.py               # Phase 1 — Ollama AI debrief
├── sample_flight_log.csv    # Sample flight data
├── requirements.txt         # matplotlib (optional, for charts)
└── README.md
```

---

## Requirements

**Phase 0 charts only:**
```bash
pip install -r requirements.txt   # matplotlib>=3.8.0
```

**Phase 1 debrief:**
- [Ollama](https://ollama.com) installed and running locally
- Model pulled: `ollama pull qwen2.5-coder:14b`
- No other dependencies — Phase 1 uses Python stdlib only

---

## Local AI Setup

```bash
# Install Ollama (macOS)
brew install ollama

# Pull the model
ollama pull qwen2.5-coder:14b

# Start the server
ollama serve
```

---

## License

MIT
