#!/bin/bash
# Reproducible v8 browser run on an ISOLATED throwaway server (never the user's live UI on 8200, never the real data).
#   usage: tests/e2e/run_v8_all.sh [port]      (run from FINAL_UI/tests/e2e; needs FINAL_UI/.venv and node_modules)
PORT="${1:-8261}"
UI="$(cd ../.. && pwd)"
REPO="$(cd ../../../2D-3D-CAD-Test-Generation && pwd)"
if netstat -ano | grep -qE "127.0.0.1:$PORT .*LISTENING"; then echo "port $PORT is already in use (a stale server?): refusing to test it"; exit 2; fi
S="$(mktemp -d)"
export MCAGENT_REPO="$REPO" MCAGENT_DATA="$S/data" MCAGENT_FINAL_OUTPUTS="$S/final" PYTHONUTF8=1
mkdir -p "$S/data" "$S/final"
PY="$UI/.venv/Scripts/python.exe"; [ -f "$PY" ] || PY=python
"$PY" helpers/make_v8_fixture.py "$S/data" reset
"$PY" helpers/make_scored_part.py "$S/final" V8SeedA good >/dev/null 2>&1
"$PY" helpers/make_scored_part.py "$S/final" V8SeedB badhole >/dev/null 2>&1
( cd "$UI" && "$PY" -m uvicorn app:app --app-dir server --host 127.0.0.1 --port "$PORT" > "$S/server.log" 2>&1 & echo $! > "$S/pid" )
for i in $(seq 1 40); do curl -s -o /dev/null "http://127.0.0.1:$PORT/api/status" && break; sleep 1; done
export MCAGENT_FINAL_OUTPUTS="$S/final" MCAGENT_DATA="$S/data" BASE_URL="http://127.0.0.1:$PORT" STAGE2_OUT="$S/final"
"$PY" helpers/seed_session_part.py "http://127.0.0.1:$PORT" "$S/final" V8Audit     # a part that belongs to a session, for the 2D -> 3D workspace tests
for spec in ${SPECS:-35-v8-comparison-cost}; do
  echo "=== $spec"; timeout 1500 npx playwright test "tests/$spec.spec.ts" --reporter=list 2>&1 | grep -E "✓|✘|passed|failed|skipped|flaky|Error|expect|Received|Expected|at .*spec.ts" | head -60
done
# stop the server by PORT: $! is an MSYS pid, so killing it by pid leaves the Windows python server running (and a later run on the same port would silently test it)
for pid in $(netstat -ano | grep -E "127.0.0.1:$PORT .*LISTENING" | awk '{print $5}' | sort -u); do taskkill //PID "$pid" //F >/dev/null 2>&1; done
echo "scratch: $S"
