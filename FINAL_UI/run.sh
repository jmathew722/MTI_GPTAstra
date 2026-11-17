#!/usr/bin/env bash
# McAgent UI launcher (macOS / Linux).
#   ./run.sh                          auto-detect the pipeline repo
#   ./run.sh --repo /path/to/repo     explicit repo (or env MCAGENT_REPO)
#   PORT=8210 ./run.sh --repo ...     port (default 8200)
# Env: MCAGENT_REPO, MCAGENT_DATA (default FINAL_UI/data), MCAGENT_PYTHON
#      (reuse this interpreter, skip venv and installs), PORT, HOST.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8200}"
HOST="${HOST:-127.0.0.1}"
REPO="${MCAGENT_REPO:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)   REPO="${2:-}"; shift 2 ;;
    --repo=*) REPO="${1#--repo=}"; shift ;;
    --port)   PORT="${2:-}"; shift 2 ;;
    -h|--help) sed -n 2,7p "$0"; exit 0 ;;
    *) echo "Unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done

is_repo() { [ -f "$1/main.py" ] && [ -d "$1/pipeline" ]; }

if [ -z "$REPO" ]; then
  # Auto-detect: walk up from FINAL_UI; at each level test the directory itself
  # and its direct children. Several matches at one level is an error (never guess).
  dir="$(dirname "$HERE")"
  while :; do
    found=()
    if is_repo "$dir"; then found+=("$dir"); fi
    for c in "$dir"/*/; do c="${c%/}"; if [ "$c" != "$HERE" ] && is_repo "$c"; then found+=("$c"); fi; done
    if [ "${#found[@]}" -eq 1 ]; then REPO="${found[0]}"; echo "Auto-detected pipeline repo: $REPO"; break; fi
    if [ "${#found[@]}" -gt 1 ]; then
      echo "ERROR: several pipeline repos found; choose one with --repo <path>:" >&2
      printf '  %s\n' "${found[@]}" >&2; exit 1
    fi
    [ "$dir" = "/" ] && break
    dir="$(dirname "$dir")"
  done
  if [ -z "$REPO" ]; then
    cat >&2 <<MSG
ERROR: no pipeline repo found above $HERE.
A pipeline repo is a folder containing main.py and a pipeline/ package.
Point the UI at one:
  ./run.sh --repo /path/to/2D-3D-CAD-Test-Generation
  MCAGENT_REPO=/path/to/repo ./run.sh
MSG
    exit 1
  fi
fi

RESOLVED="$(cd "$REPO" 2>/dev/null && pwd)" || { echo "ERROR: repo path does not exist: $REPO" >&2; exit 1; }
REPO="$RESOLVED"
if ! is_repo "$REPO"; then
  echo "ERROR: $REPO is not a pipeline repo: it needs main.py and a pipeline/ package." >&2
  exit 1
fi
if ! grep -q -- '--no-export' "$REPO/main.py" 2>/dev/null; then
  echo "WARNING: $REPO/main.py has no --no-export flag. The UI drives main.py with --drawing/--from-json/--views-folder --output --no-export; runs and demos will fail on a repo whose CLI differs." >&2
fi
export MCAGENT_REPO="$REPO"
export MCAGENT_DATA="${MCAGENT_DATA:-$HERE/data}"

# ---- Python -----------------------------------------------------------------
if [ -n "${MCAGENT_PYTHON:-}" ]; then
  PY="$MCAGENT_PYTHON"
  "$PY" -c "import fastapi, uvicorn, dotenv" 2>/dev/null || {
    echo "ERROR: MCAGENT_PYTHON ($PY) lacks fastapi/uvicorn/python-dotenv. Install server/requirements-ui.txt and the repo requirements there." >&2; exit 1; }
else
  VENV="$HERE/.venv"
  if [ ! -x "$VENV/bin/python" ]; then
    BASE=""
    for c in python3.12 python3.11 python3.10; do
      if command -v "$c" >/dev/null 2>&1; then BASE="$c"; break; fi
    done
    if [ -z "$BASE" ] && command -v python3 >/dev/null 2>&1 &&
       python3 -c 'import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<(3,13) else 1)'; then BASE=python3; fi
    if [ -z "$BASE" ]; then
      echo "ERROR: Python 3.10-3.12 is required (3.13+ lacks pinned wheels such as numba). Install python3.12 or set MCAGENT_PYTHON." >&2; exit 1
    fi
    echo "Creating venv $VENV with $BASE ..."
    "$BASE" -m venv "$VENV"
  fi
  PY="$VENV/bin/python"
  REQ_REPO="$REPO/requirements.txt"
  STAMP="$VENV/.installed-$(cat "$REQ_REPO" "$HERE/server/requirements-ui.txt" 2>/dev/null | cksum | cut -d' ' -f1)"
  if [ ! -f "$STAMP" ]; then
    echo "Installing dependencies (repo + UI) ..."
    "$PY" -m pip install -q --upgrade pip
    if [ -f "$REQ_REPO" ]; then "$PY" -m pip install -q -r "$REQ_REPO"; fi
    "$PY" -m pip install -q -r "$HERE/server/requirements-ui.txt"
    touch "$STAMP"
  fi
fi

echo
echo "  McAgent UI  ->  http://$HOST:$PORT"
echo "  repo: $MCAGENT_REPO"
echo "  data: $MCAGENT_DATA"
echo "  (Ctrl+C to stop)"
echo
exec "$PY" -m uvicorn app:app --app-dir "$HERE/server" --host "$HOST" --port "$PORT"
