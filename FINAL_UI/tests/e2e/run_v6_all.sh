#!/bin/bash
# Reproducible v6 browser regression on an ISOLATED throwaway server (never the user's live UI, never the real data).
#   usage: tests/e2e/run_v6_all.sh [port]      (run from FINAL_UI/tests/e2e; needs FINAL_UI/.venv and node_modules)
PORT="${1:-8239}"
UI="$(cd ../.. && pwd)"
REPO="$(cd ../../../2D-3D-CAD-Test-Generation && pwd)"
S="$(mktemp -d)"
export MCAGENT_REPO="$REPO" MCAGENT_DATA="$S/data" MCAGENT_FINAL_OUTPUTS="$S/final" PYTHONUTF8=1
mkdir -p "$S/data" "$S/final"
PY="$UI/.venv/Scripts/python.exe"; [ -f "$PY" ] || PY=python
"$PY" helpers/make_scored_part.py "$S/final" V6SeedA good >/dev/null 2>&1
"$PY" helpers/make_scored_part.py "$S/final" V6SeedB badhole >/dev/null 2>&1
( cd "$UI" && "$PY" -m uvicorn app:app --app-dir server --host 127.0.0.1 --port "$PORT" > "$S/server.log" 2>&1 & echo $! > "$S/pid" )
for i in $(seq 1 40); do curl -s -o /dev/null "http://127.0.0.1:$PORT/api/status" && break; sleep 1; done
export MCAGENT_FINAL_OUTPUTS="$S/final" MCAGENT_DATA="$S/data"
export BASE_URL="http://127.0.0.1:$PORT" STAGE2_OUT="$S/final"
"$PY" helpers/seed_session_part.py "http://127.0.0.1:$PORT" "$S/final" V5Audit
for spec in ${SPECS:-25-v4-scoring-projects-estimates-batch 27-v4-grade-spectrum 28-v4-buttons-and-number-colour 29-v4-layout-audit 30-v5-materials 31-v5-reverse 32-v5-results-drawer-layout 33-v6-workspace-collapsibles}; do
  echo "=== $spec"; timeout 900 npx playwright test "tests/$spec.spec.ts" --reporter=list 2>&1 | grep -E "✓|✘|passed|failed|skipped|flaky|Error|expect|Received|Expected|at .*spec.ts" | head -30
done
kill "$(cat "$S/pid")" 2>/dev/null; taskkill //PID "$(cat "$S/pid")" //F >/dev/null 2>&1
echo "scratch: $S"
