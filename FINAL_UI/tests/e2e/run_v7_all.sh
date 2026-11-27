#!/bin/bash
# Reproducible v7 browser run on an ISOLATED throwaway server (never the user's live UI on 8200, never the real data).
#   usage: tests/e2e/run_v7_all.sh [port]      (run from FINAL_UI/tests/e2e; needs FINAL_UI/.venv and node_modules)
PORT="${1:-8253}"
UI="$(cd ../.. && pwd)"
REPO="$(cd ../../../2D-3D-CAD-Test-Generation && pwd)"
S="$(mktemp -d)"
export MCAGENT_REPO="$REPO" MCAGENT_DATA="$S/data" MCAGENT_FINAL_OUTPUTS="$S/final" PYTHONUTF8=1
mkdir -p "$S/data" "$S/final"
PY="$UI/.venv/Scripts/python.exe"; [ -f "$PY" ] || PY=python
"$PY" helpers/make_v7_fixture.py "$S/data" reset
( cd "$UI" && "$PY" -m uvicorn app:app --app-dir server --host 127.0.0.1 --port "$PORT" > "$S/server.log" 2>&1 & echo $! > "$S/pid" )
for i in $(seq 1 40); do curl -s -o /dev/null "http://127.0.0.1:$PORT/api/status" && break; sleep 1; done
export BASE_URL="http://127.0.0.1:$PORT"
for spec in ${SPECS:-34-v7-reverse-reference}; do
  echo "=== $spec"; timeout 1500 npx playwright test "tests/$spec.spec.ts" --reporter=list 2>&1 | grep -E "✓|✘|passed|failed|skipped|flaky|Error|expect|Received|Expected|at .*spec.ts" | head -60
done
kill "$(cat "$S/pid")" 2>/dev/null; taskkill //PID "$(cat "$S/pid")" //F >/dev/null 2>&1
echo "scratch: $S"
