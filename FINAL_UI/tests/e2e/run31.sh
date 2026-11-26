#!/bin/bash
# usage: run31.sh [playwright args]
# Needs the server on :8212 started with MCAGENT_DATA / MCAGENT_FINAL_OUTPUTS pointing at the SAME isolated folders exported here
# (never the real data), e.g.:
#   S=<scratch>; MCAGENT_REPO=<repo> MCAGENT_DATA=$S/rvdata MCAGENT_FINAL_OUTPUTS=$S/rvfinal python -m uvicorn app:app --app-dir server --port 8212
S="${RV_SCRATCH:-C:\Users\joeka\AppData\Local\Temp\claude\886e9dc1611e638d\e39c4065-9e2b-42d3-9530-a7bc60802011\scratchpad}"
MCAGENT_FINAL_OUTPUTS="$S\rvfinal" MCAGENT_DATA="$S\rvdata" BASE_URL=http://127.0.0.1:8212 timeout 900 npx playwright test "$@" 2>&1
