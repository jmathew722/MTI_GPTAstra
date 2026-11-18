"""Glue between the progress engine and the event stream (Stage 1).

``RunTelemetry`` owns one run: a fresh ``run_id``, an attempt number, a
``ProgressEngine`` whose snapshots become ``progress.updated`` events, and the
terminal ``run.*`` events. ``NullTelemetry`` is the inert default so call sites
never need ``if telemetry``. Enabled for ordinary runs by ``GPTASTRA_STRUCTURED_EVENTS=1``.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from pipeline.progress import Op, Phase, ProgressEngine
from pipeline.run_events import EVENTS_NAME, RunEventEmitter


class NullTelemetry:
    run_id = ""
    attempt = 0

    def start(self, *a, **k): pass
    def plan(self, *a, **k): pass
    def begin(self, *a, **k): pass
    def complete(self, *a, **k): pass
    def complete_remaining(self, *a, **k): return 0
    def operation_failed(self, *a, **k): pass
    def cost(self, *a, **k): pass
    def finish(self, *a, **k): pass
    def fail(self, *a, **k): pass
    def cancel(self, *a, **k): pass
    def close(self, *a, **k): pass


def _prior_attempts(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines()
                   if '"kind":"run.started"' in line)
    except OSError:
        return 0


class RunTelemetry:
    def __init__(self, emitter: RunEventEmitter) -> None:
        self._em = emitter
        self.run_id, self.attempt = emitter.run_id, emitter.attempt
        self._engine = ProgressEngine(self._em.progress)
        self._ended = False

    @classmethod
    def create(cls, part_id: str, out_dir: Path, *,
               stdout: Optional[Callable[[str], None]] = None) -> "RunTelemetry":
        path = Path(out_dir) / EVENTS_NAME
        em = RunEventEmitter(run_id="run_" + uuid.uuid4().hex[:20], part_id=part_id,
                             attempt=_prior_attempts(path) + 1, stdout=stdout, jsonl_path=path)
        return cls(em)

    @classmethod
    def from_env(cls, part_id: str, out_dir: Path):
        if os.getenv("GPTASTRA_STRUCTURED_EVENTS") == "1":
            return cls.create(part_id, out_dir)
        return NullTelemetry()

    def start(self) -> None:
        self._em.emit("run.started", {})

    def plan(self, phase: Phase, units: int, weight_per_unit: float, unit: str) -> None:
        self._engine.plan(phase, units, weight_per_unit, unit)

    def begin(self, phase: Phase, op: Op, label: str = "") -> None:
        self._engine.begin(phase, op, label)

    def complete(self, phase: Phase, op: Op, *, unit_id: Optional[str] = None, label: str = "") -> None:
        self._engine.complete(phase, op, unit_id=unit_id, label=label)

    def complete_remaining(self, phase: Phase, op: Op, label: str = "") -> int:
        return self._engine.complete_remaining(phase, op, label)

    def operation_failed(self, phase: Phase, op: Op, unit_id: str, reason: str) -> None:
        self._em.emit("operation.failed", {"phase": phase.value, "operation": op.value,
                                           "unit_id": unit_id, "reason": reason[:300]})

    def cost(self, snapshot: Mapping[str, Any]) -> None:
        self._em.cost(snapshot)

    def finish(self) -> None:
        if self._ended:
            return
        try:
            self._engine.finish()
        except ValueError as e:     # work remained: the run did not truthfully finish
            self.fail(f"incomplete: {e}")
            return
        self._ended = True
        self._em.emit("run.completed", {})

    def fail(self, reason: str = "") -> None:
        if self._ended:
            return
        self._ended = True
        self._engine.fail(reason[:300])
        self._em.emit("run.failed", {"reason": reason[:300]})

    def cancel(self, reason: str = "") -> None:
        if self._ended:
            return
        self._ended = True
        self._engine.cancel(reason[:300])
        self._em.emit("run.cancelled", {"reason": reason[:300]})

    def close(self) -> None:
        self._em.close()
