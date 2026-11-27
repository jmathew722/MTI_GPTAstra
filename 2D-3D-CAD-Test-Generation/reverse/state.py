"""Durable job and per-part state for 3D -> 2D drawing generation.

State machine (architecture spec, section "Stages and state"):
    queued -> preflight -> mesh_export -> inventory -> planning -> drawing -> dimensioning -> verification -> publishing
           -> completed | review_required | failed | canceled
Progress is measured stage completion, never a time guess.  The job file is rewritten atomically, so a restart never reads a half-written
file, and ``events.jsonl`` is append-only.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# v7 vocabulary (docs/solidflow-upgrades/V7_CONTRACT.md). ``stl_export`` includes the geometry inventory (same open document).
STAGES = ("preflight", "stl_export", "reference_resolution", "extraction", "view_planning", "native_drawing", "dimensioning_layout", "comparison_correction",
          "verification", "publish")
# stages that only exist in reference-match mode; Standard mode records them as ``not_applicable``
REFERENCE_STAGES = ("reference_resolution", "extraction", "comparison_correction")
LEGACY_STAGES = ("mesh_export", "inventory", "planning", "drawing", "dimensioning", "publishing")      # jobs created before v7 keep these keys
TERMINAL = ("completed", "review_required", "failed", "canceled")
STATES = ("queued",) + STAGES + LEGACY_STAGES + TERMINAL
STAGE_LABEL = {"preflight": "Preflight", "stl_export": "STL export", "reference_resolution": "Reference resolution", "extraction": "Reference extraction",
               "view_planning": "View planning", "native_drawing": "Native drawing", "dimensioning_layout": "Dimensions and layout",
               "comparison_correction": "Comparison and correction", "verification": "Verification", "publish": "Publish",
               # legacy vocabulary (read-only; old jobs)
               "mesh_export": "STL export", "inventory": "Geometry inventory", "planning": "View planning", "drawing": "Native drawing",
               "dimensioning": "Dimensions", "publishing": "Publish"}
DONE_STATUSES = ("succeeded", "warning", "skipped", "not_applicable")


class StateError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def can_move(cur: str, nxt: str) -> bool:
    if cur in TERMINAL:
        return False
    if nxt in ("failed", "canceled", "review_required", "completed"):
        return nxt != "completed" or cur in ("publish", "publishing", "verification")
    if cur == "queued":
        return nxt == "preflight"
    return cur in STAGES and nxt in STAGES and STAGES.index(nxt) >= STAGES.index(cur)


@dataclass
class PartState:
    part_id: str
    source: str                      # server-side path of the SLDPRT as copied/authorized (never shown to other users)
    name: str
    config: str = ""                 # requested configuration ('' = active saved one)
    state: str = "queued"
    stages: dict = field(default_factory=dict)       # stage -> {status, started, ended, warnings[], errors[], seconds}
    review_status: str = "none"      # none | required | resolved
    issues: list = field(default_factory=list)       # engineering review issues
    artifacts: dict = field(default_factory=dict)    # name -> relative path (only files that EXIST are listed)
    error: str = ""
    attempts: int = 0
    started: Optional[str] = None
    ended: Optional[str] = None
    seconds: Optional[float] = None
    coverage_pct: Optional[float] = None
    material: dict = field(default_factory=dict)
    reference: dict = field(default_factory=dict)        # v7: mode, status, source, extraction cache, usage (keys starting with "_" are server-private)
    verification: dict = field(default_factory=dict)     # v7: QA gate result (coverage, collisions, comparison, iterations, standards)


@dataclass
class Job:
    job_id: str
    template_id: str
    profile: str = "us_third_angle_inch"
    output_root: str = ""
    options: dict = field(default_factory=dict)
    state: str = "queued"
    created: str = field(default_factory=now)
    updated: str = field(default_factory=now)
    parts: list[PartState] = field(default_factory=list)
    solidworks: dict = field(default_factory=dict)   # revision / service pack actually detected
    cancel_requested: bool = False
    actual_api_cost_usd: float = 0.0                 # measured model/API spend; CAD automation is not an LLM charge
    kind: str = "drawing_generation"

    def part(self, part_id: str) -> PartState:
        for p in self.parts:
            if p.part_id == part_id:
                return p
        raise KeyError(part_id)

    def summary_state(self) -> str:
        if not self.parts:
            return self.state
        sts = [p.state for p in self.parts]
        if any(s not in TERMINAL for s in sts):
            return "running" if any(s != "queued" for s in sts) else "queued"
        if all(s == "canceled" for s in sts):
            return "canceled"
        if any(s == "failed" for s in sts):
            return "completed_with_failures" if any(s in ("completed", "review_required") for s in sts) else "failed"
        return "review_required" if any(s == "review_required" for s in sts) else "completed"


class JobStore:
    """Files under ``<root>/<job_id>/``: job.json (atomic), events.jsonl (append-only). Thread-safe within one process."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def dir(self, job_id: str) -> Path:
        return self.root / job_id

    def _flag(self, job_id: str) -> Path:
        return self.dir(job_id) / "cancel.flag"

    def clear_cancel(self, job_id: str) -> None:
        with self._lock:
            self._flag(job_id).unlink(missing_ok=True)

    def save(self, job: Job) -> None:
        """Atomic write. A cancel request is stored as its own flag file and is NEVER cleared by a save: a worker holding a stale in-memory Job (with
        cancel_requested False) must not be able to erase a cancel that arrived while it was running (clear it explicitly with clear_cancel)."""
        with self._lock:
            d = self.dir(job.job_id)
            d.mkdir(parents=True, exist_ok=True)
            if job.cancel_requested:
                self._flag(job.job_id).write_text("1", encoding="utf-8")
            job.updated = now()
            tmp = d / "job.json.tmp"
            tmp.write_text(json.dumps(_to_json(job), indent=2), encoding="utf-8")
            for attempt in range(8):       # a concurrent reader can hold the file for a moment on Windows
                try:
                    os.replace(tmp, d / "job.json")
                    break
                except PermissionError:
                    if attempt == 7:
                        raise
                    time.sleep(0.05)

    def load(self, job_id: str) -> Job:
        p = self.dir(job_id) / "job.json"
        with self._lock:                  # never read while the matching save is replacing the file
            if not p.is_file():
                raise KeyError(job_id)
            last: Optional[Exception] = None
            for _ in range(8):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    break
                except (PermissionError, json.JSONDecodeError) as e:
                    last = e
                    time.sleep(0.05)
            else:
                raise last  # type: ignore[misc]
            j = _from_json(data)
            j.cancel_requested = self._flag(job_id).exists()
            return j

    def list(self) -> list[Job]:
        out = []
        for d in sorted(self.root.iterdir() if self.root.is_dir() else []):
            try:
                if (d / "job.json").is_file():
                    out.append(self.load(d.name))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(out, key=lambda j: j.created, reverse=True)

    def event(self, job_id: str, kind: str, part_id: str = "", **data) -> dict:
        ev = {"t": now(), "ts": time.time(), "job": job_id, "part": part_id, "kind": kind, **data}
        with self._lock:
            d = self.dir(job_id)
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, default=str) + "\n")
        return ev

    def events(self, job_id: str, after: int = 0) -> list[dict]:
        p = self.dir(job_id) / "events.jsonl"
        if not p.is_file():
            return []
        out = []
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if i < after or not line.strip():
                continue
            try:
                e = json.loads(line)
                e["seq"] = i
                out.append(e)
            except json.JSONDecodeError:
                continue
        return out

    def recover(self) -> list[str]:
        """After a restart, a job that was mid-run cannot continue (its COM session is gone): mark non-terminal parts failed with a clear reason
        and keep every artifact already published. Returns the recovered job ids."""
        fixed = []
        for j in self.list():
            changed = False
            for p in j.parts:
                if p.state not in TERMINAL and p.state != "queued":
                    p.state, p.error, p.ended = "failed", "Interrupted: the server restarted while this part was running. Retry to run it again.", now()
                    changed = True
            if changed:
                j.state = j.summary_state()
                self.save(j)
                self.event(j.job_id, "recovered", note="interrupted by restart")
                fixed.append(j.job_id)
        return fixed


_PART_MONO: dict = {}      # (id(part)) -> monotonic start, in-process only (durations must not follow wall-clock adjustments)


def mark_started(part: "PartState") -> None:
    part.started = now()
    _PART_MONO[id(part)] = time.monotonic()


def begin_stage(part: PartState, stage: str) -> None:
    if not can_move(part.state, stage):
        raise StateError(f"cannot move {part.part_id} from {part.state} to {stage}")
    part.state = stage
    part.stages[stage] = {"status": "running", "started": now(), "t0": time.monotonic(), "warnings": [], "errors": []}


def mark_not_applicable(part: PartState, stage: str, why: str = "") -> None:
    """A stage that does not apply to this part (Standard mode has no reference): recorded so the UI can render it, counted as done."""
    part.stages[stage] = {"status": "not_applicable", "started": now(), "ended": now(), "seconds": 0.0, "warnings": [], "errors": [], "note": why}


def end_stage(part: PartState, stage: str, status: str = "succeeded", *, warnings=(), errors=()) -> None:
    st = part.stages.setdefault(stage, {"started": now(), "t0": time.monotonic(), "warnings": [], "errors": []})
    st["status"] = status
    st["ended"] = now()
    st["seconds"] = round(time.monotonic() - st.pop("t0", time.monotonic()), 2)
    st["warnings"] = list(st.get("warnings", [])) + list(warnings)
    st["errors"] = list(st.get("errors", [])) + list(errors)


def finish(part: PartState, state: str, error: str = "") -> None:
    if part.state in TERMINAL:
        return
    part.state = state
    part.error = error
    part.ended = now()
    t0m = _PART_MONO.pop(id(part), None)
    if t0m is not None:
        part.seconds = round(time.monotonic() - t0m, 1)
    elif part.started:
        try:
            part.seconds = round((datetime.fromisoformat(part.ended) - datetime.fromisoformat(part.started)).total_seconds(), 1)
        except ValueError:
            pass


def progress(job: Job) -> dict:
    """Measured completion: finished stages / total stages across parts. Never a guess of elapsed time."""
    total = len(job.parts) * len(STAGES)
    done = 0
    for p in job.parts:
        if p.state in TERMINAL and p.state in ("completed", "review_required"):
            done += len(STAGES)
        else:
            legacy = any(k in p.stages for k in LEGACY_STAGES)
            names = ("preflight", "mesh_export", "inventory", "planning", "drawing", "dimensioning", "verification", "publishing") if legacy else STAGES
            done += min(len(STAGES), sum(1 for s in names if (p.stages.get(s) or {}).get("status") in DONE_STATUSES))
    return {"stages_done": done, "stages_total": total, "fraction": (done / total) if total else 0.0,
            "parts_done": sum(1 for p in job.parts if p.state in TERMINAL), "parts_total": len(job.parts)}


def _to_json(job: Job) -> dict:
    d = {k: v for k, v in job.__dict__.items() if k != "parts"}
    d["parts"] = [dict(p.__dict__) for p in job.parts]
    return d


def _from_json(d: dict) -> Job:
    parts = [PartState(**p) for p in d.pop("parts", [])]
    j = Job(**d)
    j.parts = parts
    return j
