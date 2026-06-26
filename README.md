# Drone Flight Log Analyzer

A Python tool that reads drone flight telemetry from CSV files and computes key flight statistics such as max altitude, min battery, and total distance traveled.

## Features

- Parse and validate flight log CSV files
- Compute flight statistics (altitude, speed, battery, distance)
- Calculate total distance using the Haversine formula between GPS points
- Export statistics to JSON
- Generate charts for altitude, battery, speed, and flight path

## CSV Format

Your CSV file must include these columns:

| Column | Description |
|--------|-------------|
| `timestamp` | Flight time (`YYYY-MM-DD HH:MM:SS`) |
| `latitude` | GPS latitude in decimal degrees |
| `longitude` | GPS longitude in decimal degrees |
| `altitude` | Altitude in meters |
| `speed` | Speed in meters per second |
| `battery_percent` | Battery level (0–100) |

## Usage

Print a summary to the terminal:

```bash
python3 flight_log_analyzer.py sample_flight_log.csv
```

Export statistics to JSON:

```bash
python3 flight_log_analyzer.py sample_flight_log.csv --json output/report.json
```

Generate flight charts (requires matplotlib):

```bash
pip install -r requirements.txt
python3 flight_log_analyzer.py sample_flight_log.csv --plot output/flight_charts.png
```

Run everything at once:

```bash
python3 flight_log_analyzer.py sample_flight_log.csv \
  --json output/report.json \
  --plot output/flight_charts.png
```

## Example Output

```
=== Drone Flight Log Summary ===
Records:              14
Start time:           2025-06-26 10:00:00
End time:             2025-06-26 10:02:10
Flight duration:      0:02:10
Max altitude:         92.00 m
Min battery:          91.8%
Total distance:       564.49 m
Total distance:       0.564 km
================================
```

## Project Structure

```
.
├── flight_log_analyzer.py   # Main analysis script
├── sample_flight_log.csv    # Sample data
├── requirements.txt         # Optional dependencies for plotting
└── README.md
```

## License

MIT
