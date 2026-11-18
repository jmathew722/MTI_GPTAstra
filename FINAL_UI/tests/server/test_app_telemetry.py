"""FastAPI wiring for structured telemetry (Stage 1, task 1.5)."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

os.environ["MCAGENT_REPO"] = str(Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation")
os.environ["MCAGENT_DATA"] = tempfile.mkdtemp(prefix="mcagent_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
import app as appmod  # noqa: E402

P = "[gptastra-event] "


def _ev(seq, kind, payload, run="run_live", attempt=1):
    return P + json.dumps({"schema_version": 1, "event_id": f"e{run}{seq}", "run_id": run, "attempt": attempt,
                           "part_id": "P1", "seq": seq, "occurred_at": "2026-11-18T00:00:00.000Z",
                           "kind": kind, "payload": payload})


def _wait(rid, timeout=15):
    t0 = time.time()
    while not appmod.RUNS[rid]["done"] and time.time() - t0 < timeout:
        time.sleep(0.05)
    assert appmod.RUNS[rid]["done"]


def test_live_subprocess_events_reach_the_snapshot_endpoint(tmp_path):
    prog = {"phase": "extraction", "operation": "extract_view", "label": "Reading", "percent": 25.0,
            "indeterminate": False, "completed_units": 1, "total_units": 4, "unit": "views", "terminal": None}
    stale = {"percent": 99.0}
    script = "\n".join([
        "print('[stage] extraction: reading 1 image(s) for P1')",
        f"print({_ev(1, 'run.started', {})!r})",
        f"print({_ev(2, 'progress.updated', prog)!r})",
        f"print({_ev(7, 'progress.updated', stale, run='run_old')!r})",     # stale run
        f"print({_ev(3, 'cost.updated', {'run_cost_usd': '0.5', 'pricing_status': 'priced'})!r})",
        f"print({_ev(3, 'cost.updated', {'run_cost_usd': '9.9'})!r})",      # duplicate seq
    ])
    rid = appmod._start_run([sys.executable, "-c", script], tmp_path)
    _wait(rid)
    c = TestClient(appmod.app)
    snap = c.get(f"/api/runs/{rid}/telemetry").json()
    assert snap["source"] == "structured" and snap["run_id"] == "run_live" and snap["last_seq"] == 3
    assert snap["progress"]["percent"] == 25.0 and snap["cost"]["run_cost_usd"] == "0.5"
    assert snap["events_artifact"] == "run_events.jsonl"
    assert "events" not in snap
    # ordinary log lines are still streamed untouched
    assert any(l.startswith("[stage] extraction") for l in appmod.RUNS[rid]["lines"])


def test_child_process_receives_the_structured_events_flag(tmp_path):
    rid = appmod._start_run([sys.executable, "-c",
                             "import os;print('FLAG='+os.environ.get('GPTASTRA_STRUCTURED_EVENTS',''))"], tmp_path)
    _wait(rid)
    assert "FLAG=1" in appmod.RUNS[rid]["lines"]


def test_unknown_run_is_404():
    assert TestClient(appmod.app).get("/api/runs/nope/telemetry").status_code == 404


def test_saved_events_are_replayed_and_old_runs_are_labeled_legacy(tmp_path):
    saved = tmp_path / "saved" / "P1"
    saved.mkdir(parents=True)
    (saved / "run_events.jsonl").write_text(
        _ev(1, "run.started", {})[len(P):] + "\n" + _ev(2, "run.failed", {"reason": "x"})[len(P):] + "\n",
        encoding="utf-8")
    snap = appmod._telemetry_for(tmp_path / "saved")
    assert snap["source"] == "structured" and snap["terminal"] == "failed"
    old = tmp_path / "old"
    old.mkdir()
    assert appmod._telemetry_for(old)["source"] == "legacy_log_parser"


def test_outputs_payload_carries_telemetry(tmp_path):
    cats = appmod._categorize_output(tmp_path)
    assert cats["categories"]["telemetry"]["source"] == "legacy_log_parser"
