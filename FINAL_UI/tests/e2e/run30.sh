#!/bin/bash
# usage: run30.sh [playwright args]  (env: SCR path of scratchpad)
S="C:\Users\joeka\AppData\Local\Temp\claude\886e9dc1611e638d\e39c4065-9e2b-42d3-9530-a7bc60802011\scratchpad"
MCAGENT_FINAL_OUTPUTS="$S\v5final" MCAGENT_DATA="$S\v5data" BASE_URL=http://127.0.0.1:8211 timeout 900 npx playwright test "$@" 2>&1
