#!/bin/bash
echo "=== Drone Flight Log Analyzer — Demo ==="
python3 analyse.py sample_flight_log.csv --json output/report.json
python3 debrief.py output/report.json --out output/debrief.txt
echo "=== Done. Check output/ folder ==="
