#!/bin/bash
# Wrapper used by launchd to run the daily signal script with the venv.
set -e

BACKEND_DIR="/Users/cristovao/Documents/Projects/Cristopher/backend"
cd "$BACKEND_DIR"

source venv/bin/activate
python scripts/daily_signal.py
