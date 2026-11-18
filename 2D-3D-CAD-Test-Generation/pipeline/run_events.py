"""Versioned, structured run-event stream (Stage 1).

One-line UTF-8 JSON events, prefixed on stdout with ``[gptastra-event] `` so ordinary
log lines stay readable, and appended to a durable ``run_events.jsonl``. Ordering is
by ``(run_id, seq)``; timestamps are informational only.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

SCHEMA_VERSION = 1
EVENT_PREFIX = "[gptastra-event] "
EVENTS_NAME = "run_events.jsonl"
_REQUIRED = ("schema_version", "event_id", "run_id", "attempt", "seq", "kind", "payload")


def _check_json(value: Any, path: str = "payload") -> None:
    """Only plain JSON values: arbitrary objects (which could carry secrets) are refused."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(f"{path}: non-string key {k!r}")
            _check_json(v, f"{path}.{k}")
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check_json(v, f"{path}[{i}]")
        return
    raise TypeError(f"{path}: {type(value).__name__} is not JSON-safe; pass explicit mappings")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RunEventEmitter:
    def __init__(self, run_id: str, part_id: str, attempt: int = 1, *,
                 stdout: Optional[Callable[[str], None]] = None,
                 jsonl_path: Optional[Path] = None) -> None:
        self.run_id, self.part_id, self.attempt = run_id, part_id, attempt
        self._stdout = stdout if stdout is not None else (lambda s: print(s, flush=True))
        self._path = Path(jsonl_path) if jsonl_path else None
        self._fh = None
        self._seq = 0
        self._lock = threading.Lock()
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8")

    def emit(self, kind: str, payload: Mapping[str, Any]) -> dict:
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        _check_json(payload)
        with self._lock:
            self._seq += 1
            event = {
                "schema_version": SCHEMA_VERSION,
                "event_id": "evt_" + uuid.uuid4().hex,
                "run_id": self.run_id,
                "attempt": self.attempt,
                "part_id": self.part_id,
                "seq": self._seq,
                "occurred_at": _now(),
                "kind": kind,
                "payload": dict(payload),
            }
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            if self._fh:
                self._fh.write(line + "\n")
                self._fh.flush()
            self._stdout(EVENT_PREFIX + line)
        return event

    def progress(self, snapshot: Mapping[str, Any]) -> dict:
        return self.emit("progress.updated", snapshot)

    def cost(self, snapshot: Mapping[str, Any]) -> dict:
        return self.emit("cost.updated", snapshot)

    def close(self) -> None:
        with self._lock:
            if self._fh:
                self._fh.close()
                self._fh = None


def parse_event_line(line: str) -> Optional[dict]:
    """Return the event dict for a prefixed line, else None. Never raises."""
    try:
        if not isinstance(line, str) or not line.startswith(EVENT_PREFIX):
            return None
        obj = json.loads(line[len(EVENT_PREFIX):])
        if not isinstance(obj, dict) or any(k not in obj for k in _REQUIRED):
            return None
        return obj
    except (ValueError, TypeError):
        return None


class SequenceGuard:
    """Idempotent ordering: accept an event only if its seq exceeds the last for that run."""

    def __init__(self) -> None:
        self._last: dict[str, int] = {}

    def accept(self, event: Mapping[str, Any]) -> bool:
        run, seq = event["run_id"], event["seq"]
        if seq <= self._last.get(run, 0):
            return False
        self._last[run] = seq
        return True
