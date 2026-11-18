"""Progress from observable work (Stage 1).

Progress is completed weight / planned weight. Nothing here reads a clock. Until a
phase publishes its unit total the run is indeterminate; the reported percent never
moves backward; it is held below 100 until ``finish()`` (artifact finalization).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Optional


class Phase(str, Enum):
    INGEST = "ingest"
    EXTRACTION = "extraction"
    RESOLUTION = "resolution"
    BUILD_PLAN = "build_plan"
    REFERENCE_BUILD = "reference_build"
    SOLIDWORKS_GENERATION = "solidworks_generation"
    VERIFICATION = "verification"
    ARTIFACT_FINALIZATION = "artifact_finalization"


class Op(str, Enum):
    INGEST_DRAWING = "ingest_drawing"
    EXTRACT_VIEW = "extract_view"
    RESOLVE_AMBIGUITY = "resolve_ambiguity"
    BUILD_PLAN = "build_plan"
    REFERENCE_FEATURE = "reference_feature"
    CREATE_FEATURE = "create_feature"
    VERIFY_CHECK = "verify_check"
    FINALIZE_ARTIFACT = "finalize_artifact"


_NOT_100 = 99.9


class _PhaseState:
    def __init__(self, units: int, weight: float, unit: str) -> None:
        self.total, self.weight, self.unit = units, weight, unit
        self.done = 0
        self.seen: set[str] = set()


class ProgressEngine:
    def __init__(self, sink: Optional[Callable[[dict], Any]] = None) -> None:
        self._sink = sink or (lambda payload: None)
        self._phases: dict[Phase, _PhaseState] = {}
        self._active: Optional[tuple[Phase, Op]] = None
        self._label = ""
        self._high = 0.0
        self.terminal: Optional[str] = None

    # -- planning ---------------------------------------------------------- #
    def plan(self, phase: Phase, units: int, weight_per_unit: float, unit: str) -> None:
        if units < 0 or weight_per_unit <= 0:
            raise ValueError("units must be >= 0 and weight_per_unit > 0")
        st = self._phases.get(phase)
        if st is None:
            self._phases[phase] = _PhaseState(units, weight_per_unit, unit)
        else:
            if units < st.done:
                raise ValueError("cannot plan fewer units than already completed")
            st.total, st.weight, st.unit = units, weight_per_unit, unit
        self._publish()

    def begin(self, phase: Phase, op: Op, label: str = "") -> None:
        self._active, self._label = (phase, op), label
        self._publish()

    # -- work -------------------------------------------------------------- #
    def complete(self, phase: Phase, op: Op, *, unit_id: Optional[str] = None, label: str = "") -> None:
        st = self._phases.get(phase)
        if st is None:
            raise ValueError(f"{phase.value}: no unit total published")
        if unit_id is not None:
            if unit_id in st.seen:
                return  # idempotent
        if st.done >= st.total:
            raise ValueError(f"{phase.value}: completion exceeds planned {st.total} {st.unit}")
        if unit_id is not None:
            st.seen.add(unit_id)
        st.done += 1
        self._active, self._label = (phase, op), label
        self._publish()

    def complete_remaining(self, phase: Phase, op: Op, label: str = "") -> int:
        """Account for units that were merged or skipped (a hole + its pattern built as one
        feature). Returns how many were closed out."""
        st = self._phases.get(phase)
        if st is None or st.done >= st.total:
            return 0
        n = st.total - st.done
        st.done = st.total
        self._active, self._label = (phase, op), label
        self._publish()
        return n

    def finish(self) -> None:
        if any(s.done < s.total for s in self._phases.values()):
            raise ValueError("cannot finish: planned work remains")
        if not self._phases:
            raise ValueError("cannot finish: no work was planned")
        self.terminal = "completed"
        self._publish()

    def fail(self, reason: str = "") -> None:
        self.terminal, self._label = "failed", reason
        self._publish()

    def cancel(self, reason: str = "") -> None:
        self.terminal, self._label = "cancelled", reason
        self._publish()

    # -- reporting --------------------------------------------------------- #
    def _weights(self) -> tuple[float, float]:
        total = sum(s.total * s.weight for s in self._phases.values())
        done = sum(s.done * s.weight for s in self._phases.values())
        return done, total

    def snapshot(self) -> dict:
        done, total = self._weights()
        determinate = total > 0
        if self.terminal == "completed":
            pct: Optional[float] = 100.0
        elif determinate:
            pct = round(min(done / total * 100.0, _NOT_100), 1)
            pct = max(pct, self._high)
            self._high = pct
        else:
            pct = None
        phase, op = self._active if self._active else (None, None)
        st = self._phases.get(phase) if phase else None
        return {
            "phase": phase.value if phase else None,
            "operation": op.value if op else None,
            "label": self._label,
            "completed_units": st.done if st else 0,
            "total_units": st.total if st else None,
            "unit": st.unit if st else None,
            "phase_completed_units": st.done if st else 0,
            "phase_total_units": st.total if st else None,
            "overall_completed_weight": done,
            "overall_total_weight": total,
            "percent": pct,
            "indeterminate": pct is None,
            "terminal": self.terminal,
        }

    def _publish(self) -> None:
        self._sink(self.snapshot())
