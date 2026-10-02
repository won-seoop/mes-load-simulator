#!/usr/bin/env bash
# EXP-011: reproduce SQLite `database is locked` write contention against an
# isolated server instance, and report how many occurrences showed up in the
# server log.
#
# PAR-014 (2026-09-28) found 2 real `database is locked` 500s buried in
# server.log during a routine 50 VU/3min daily run -- a very low frequency
# event (2 / 16208 requests). A single-endpoint, single-process thread-pool
# harness (the first version of this script) could not reproduce it at all,
# even at 9000 tight-loop requests: Python's sqlite3 driver already applies a
# 5s busy-timeout by default, which absorbs ordinary contention. The only
# combination that is known to have triggered it is the full daily pipeline:
# real uvicorn process + the autonomous simulation engine's background writer
# thread + Locust's full endpoint mix (equipment PATCH, lot advance,
# work-order/lot creation, inspections, quality disposition) running
# concurrently. This script reproduces exactly that combination, just at a
# higher user count / tighter ramp than the daily 50 VU baseline so the rare
# event is more likely to show up inside a short run.
#
# Usage:
#   scripts/repro_sqlite_lock.sh [port] [db_path] [users] [spawn_rate] [duration]
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-18301}"
DB_PATH="${2:-$(pwd)/experiments/EXP-011-sqlite-write-lock/repro_live.db}"
USERS="${3:-150}"
SPAWN_RATE="${4:-50}"
DURATION="${5:-60s}"
HOST="http://127.0.0.1:${PORT}"
# Raw per-run artifacts (server logs, locust CSVs, db files) are large and
# not reproducible byte-for-byte, so they live under raw/ which .gitignore
# excludes (same convention as reports/raw/) -- only experiment.md/config.yaml
# in the parent dir are meant to be committed.
LOG_DIR="$(pwd)/experiments/EXP-011-sqlite-write-lock/raw"
mkdir -p "$LOG_DIR"
SERVER_LOG="${LOG_DIR}/server_$(basename "$DB_PATH" .db).log"

rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm" "$DB_PATH-journal"
source .venv/bin/activate

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT already in use" >&2
  exit 1
fi

MES_DATABASE_URL="sqlite:///${DB_PATH}" uvicorn app.main:app --host 127.0.0.1 --port "$PORT" > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for i in $(seq 1 20); do
  if curl -sf "$HOST/health" > /dev/null; then break; fi
  sleep 0.5
done

curl -sf -X POST "$HOST/simulation/start" > /dev/null
sleep 3  # let the engine spawn some lots before Locust starts advancing them

set +e
locust -f load_test/locustfile.py --headless \
  -u "$USERS" -r "$SPAWN_RATE" -t "$DURATION" \
  --host "$HOST" \
  --csv "${LOG_DIR}/locust_$(basename "$DB_PATH" .db)" \
  --only-summary
set -e

sleep 1
kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true

LOCKED_COUNT=$(grep -c "database is locked" "$SERVER_LOG" || true)
TOTAL_5XX=$(grep -cE '"[A-Z]+ [^"]*" 5[0-9][0-9] ' "$SERVER_LOG" || true)
echo "=== $SERVER_LOG ==="
echo "database_is_locked_occurrences=${LOCKED_COUNT}"
echo "total_server_5xx_lines=${TOTAL_5XX}"
