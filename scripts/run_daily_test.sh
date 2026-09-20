#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# The scheduler runs at 07:00 KST; using UTC here would mislabel every run
# between KST 00:00-08:59 with the previous KST day (see ROADMAP.md).
CALENDAR_DATE=$(TZ=Asia/Seoul date +%Y-%m-%d)
# Daily automation uses the KST date. Named experiments can set MES_RUN_ID so
# they do not overwrite the canonical daily report produced on the same day.
RUN_ID="${MES_RUN_ID:-$CALENDAR_DATE}"
RAW_DIR="reports/raw/${RUN_ID}"
LOAD_PORT="${MES_LOAD_TEST_PORT:-18080}"
LOAD_HOST="http://127.0.0.1:${LOAD_PORT}"
mkdir -p "$RAW_DIR"

rm -f mes.db
python -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt

echo "Running test suite before load test..."
python -m pytest tests/ -v

if lsof -nP -iTCP:"$LOAD_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "load-test port $LOAD_PORT is already in use" >&2
  exit 1
fi

uvicorn app.main:app --host 127.0.0.1 --port "$LOAD_PORT" > "$RAW_DIR/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

SERVER_READY=0
for i in $(seq 1 20); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "load-test server exited before becoming ready" >&2
    cat "$RAW_DIR/server.log" >&2
    exit 1
  fi
  if curl -sf "$LOAD_HOST/health" > /dev/null; then
    SERVER_READY=1
    break
  fi
  sleep 0.5
done
if [ "$SERVER_READY" -ne 1 ]; then
  echo "load-test server did not become ready at $LOAD_HOST" >&2
  exit 1
fi

set +e
locust -f load_test/locustfile.py --headless \
  -u 50 -r 5 -t 3m \
  --host "$LOAD_HOST" \
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

curl -s "$LOAD_HOST/metrics" -o "$RAW_DIR/mes_metrics.json"
curl -s "$LOAD_HOST/quality/metrics" -o "$RAW_DIR/quality_metrics.json"
curl -s "$LOAD_HOST/quality/anomalies" -o "$RAW_DIR/quality_anomalies.json"

kill "$SERVER_PID" 2>/dev/null || true
trap - EXIT

python scripts/summarize.py "$RUN_ID"
