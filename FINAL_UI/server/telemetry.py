"""Structured run telemetry on the server (Stage 1).

Pure functions so they can be tested without FastAPI. The server feeds every console
line to ``apply_line``; events are idempotent by ``(run_id, seq)``, stale runs cannot
overwrite the active attempt, and only bounded snapshots are exposed (the full stream
is served as the ``run_events.jsonl`` artifact).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

PREFIX = "[gptastra-event] "
EVENTS_NAME = "run_events.jsonl"
SCHEMA_VERSION = 1
_REQUIRED = ("schema_version", "event_id", "run_id", "attempt", "seq", "kind", "payload")
_TERMINAL = {"run.completed": "completed", "run.failed": "failed", "run.cancelled": "cancelled"}
_MAX_TEXT = 300

_PROGRESS_KEYS = ("phase", "operation", "label", "completed_units", "total_units", "unit",
                  "phase_completed_units", "phase_total_units", "overall_completed_weight",
                  "overall_total_weight", "percent", "indeterminate", "terminal")
_COST_KEYS = ("currency", "run_cost_usd", "part_total_cost_usd", "session_total_cost_usd",
              "input_tokens", "cached_input_tokens", "output_tokens", "api_calls", "unpriced_calls",
              "pricing_status", "part_pricing_status", "session_pricing_status", "pricing_source",
              "legacy_rows", "as_of")


def _blank(source: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "source": source, "run_id": None, "attempt": None,
            "progress": None, "cost": None, "last_seq": 0, "terminal": None}


def new_state() -> dict:
    return _blank("structured")


def legacy_state() -> dict:
    return _blank("legacy_log_parser")


def _pick(payload: dict, keys: tuple) -> dict:
    out = {}
    for k in keys:
        if k in payload:
            v = payload[k]
            if isinstance(v, str):
                v = v[:_MAX_TEXT]
            elif not (v is None or isinstance(v, (int, float, bool))):
                continue
            out[k] = v
    return out


def parse_line(line: str) -> Optional[dict]:
    try:
        if not isinstance(line, str) or not line.startswith(PREFIX):
            return None
        obj = json.loads(line[len(PREFIX):])
    except ValueError:
        return None
    if not isinstance(obj, dict) or any(k not in obj for k in _REQUIRED):
        return None
    if not isinstance(obj["run_id"], str) or not isinstance(obj["seq"], int) \
            or not isinstance(obj["attempt"], int) or not isinstance(obj["payload"], dict):
        return None
    return obj


def apply_line(state: dict, line: str) -> bool:
    """Fold one console line into ``state``. True only if the state changed."""
    ev = parse_line(line)
    if ev is None:
        return False
    run, seq, kind = ev["run_id"], ev["seq"], ev["kind"]
    if run != state["run_id"]:
        # With no active run (first event, or a reconnect mid-stream) adopt whichever run speaks;
        # afterwards only a *newer attempt's* run.started may take over.
        takes_over = state["run_id"] is None or (
            kind == "run.started" and ev["attempt"] > (state["attempt"] or 0))
        if not takes_over:
            return False        # stale (or out-of-band) run: never overwrites the active attempt
        state.update(run_id=run, attempt=ev["attempt"], progress=None, cost=None,
                     last_seq=0, terminal=None)
    if seq <= state["last_seq"]:
        return False            # duplicate or late
    payload = ev["payload"]
    if kind == "progress.updated":
        snap = _pick(payload, _PROGRESS_KEYS)
        new, old = snap.get("percent"), (state["progress"] or {}).get("percent")
        if new is not None and old is not None and new < old:
            return False        # the backend guarantees monotonic; refuse a regression
        state["progress"] = snap
    elif kind == "cost.updated":
        state["cost"] = _pick(payload, _COST_KEYS)
    elif kind in _TERMINAL:
        state["terminal"] = _TERMINAL[kind]
    state["last_seq"] = seq
    return True


def replay_file(path: Path) -> Optional[dict]:
    """Final state of a saved ``run_events.jsonl`` (the last attempt in it), or None."""
    state = new_state()
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    changed = False
    for line in text.splitlines():
        changed |= apply_line(state, PREFIX + line.strip()) if line.strip() else False
    return state if changed else None


def find_events_file(out: Path) -> Optional[Path]:
    """``run_events.jsonl`` in ``out`` or one level below (the pipeline writes <out>/<part>/)."""
    out = Path(out).resolve()
    direct = out / EVENTS_NAME
    if direct.is_file():
        return direct
    try:
        for child in sorted(out.iterdir()):
            cand = child / EVENTS_NAME
            if child.is_dir() and cand.is_file():
                return cand
    except OSError:
        pass
    return None
