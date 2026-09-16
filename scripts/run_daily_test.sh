#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_DATE=$(date -u +%Y-%m-%d)
RAW_DIR="reports/raw/${RUN_DATE}"
mkdir -p "$RAW_DIR"

rm -f mes.db
python -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$RAW_DIR/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for i in $(seq 1 20); do
  if curl -sf http://localhost:8000/health > /dev/null; then
    break
  fi
  sleep 0.5
done

locust -f load_test/locustfile.py --headless \
  -u 50 -r 5 -t 3m \
  --host http://localhost:8000 \
  --csv "$RAW_DIR/locust" \
  --only-summary

curl -s http://localhost:8000/metrics -o "$RAW_DIR/mes_metrics.json"

kill "$SERVER_PID" 2>/dev/null || true
trap - EXIT

python scripts/summarize.py "$RUN_DATE"
