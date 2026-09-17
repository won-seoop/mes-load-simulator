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

echo "Running test suite before load test..."
pytest tests/ -v

uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$RAW_DIR/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for i in $(seq 1 20); do
  if curl -sf http://localhost:8000/health > /dev/null; then
    break
  fi
  sleep 0.5
done

set +e
locust -f load_test/locustfile.py --headless \
  -u 50 -r 5 -t 3m \
  --host http://localhost:8000 \
  --csv "$RAW_DIR/locust" \
  --only-summary
LOCUST_EXIT=$?
set -e
# Locust exits non-zero whenever any request failed during the run, which is
# expected under load (a small failure rate is normal) — only treat exit
# codes other than 0/1 as a real crash worth aborting the pipeline for.
if [ "$LOCUST_EXIT" -gt 1 ]; then
  echo "locust exited with unexpected code $LOCUST_EXIT" >&2
  exit "$LOCUST_EXIT"
fi

curl -s http://localhost:8000/metrics -o "$RAW_DIR/mes_metrics.json"

kill "$SERVER_PID" 2>/dev/null || true
trap - EXIT

python scripts/summarize.py "$RUN_DATE"
