#!/usr/bin/env bash
set -e

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

export $(grep -v '^#' .env | xargs)

python fetch_data.py
python baseline_fetch.py
python analyze.py
python compute_uniqueness.py
python generate_report.py

echo "Report ready: $OUTPUT_DIR/final_report.html"
