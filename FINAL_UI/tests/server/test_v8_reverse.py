"""v8: the validation-report export kind, the replication-aware draft / verified status, and the pre-run estimate route (server/reverse_v7.py).

TEST-ONLY FAKES: ReverseService.estimate_run is replaced by a stand-in on the real service object (the backend agent's implementation is not needed to prove
the HTTP layer); artifacts are the labelled fixtures from tests/server/reverse_fixtures.py. SOLIDWORKS is never started and no model call is made.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pythoncom")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation"
_TMP = tempfile.mkdtemp(prefix="mcagent_v8r_")
os.environ.setdefault("MCAGENT_REPO", str(REPO))
os.environ.setdefault("MCAGENT_DATA", os.path.join(_TMP, "data"))
os.environ.setdefault("MCAGENT_FINAL_OUTPUTS", os.path.join(_TMP, "final"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO))
import app as appmod  # noqa: E402
import reverse_api as rapi  # noqa: E402
import reverse_v7 as v7  # noqa: E402
import reverse_fixtures as fx  # noqa: E402
from reverse import state  # noqa: E402

client = TestClient(appmod.app)
JOB = "r3d_00000000000000bb"


@pytest.fixture()
def env(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="mcagent_v8r_iso_"))
    (root / "data").mkdir()
    monkeypatch.setattr(appmod, "DATA_DIR", root / "data")
    monkeypatch.setattr(rapi, "_sw_process_running", lambda: False)
    monkeypatch.delenv("SOLIDFLOW_REVERSE_ROOTS", raising=False)
    rapi.set_service(None)
    svc = rapi.service()
    monkeypatch.setattr(svc, "start", lambda: None)
    yield root, svc
    rapi.set_service(None)


def seed(root, parts=None):
    return fx.write_job(root / "data", JOB, parts or [("flange.SLDPRT", "completed"), ("bracket.SLDPRT", "review"), ("broken.SLDPRT", "failed"), ("gone.SLDPRT", "canceled")])


def dl(part, kind, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return client.get(f"/api/reverse/jobs/{JOB}/parts/{part}/export/{kind}" + ("?" + qs if qs else ""))


def part_dir(root, pid):
    return root / "data/outputs/3d-to-2d" / JOB / pid / "active"


# ------------------------------------------------------------------ validation report export

def test_report_is_an_export_kind_bound_to_the_part_with_real_bytes(env):
    root, _ = env
    seed(root)
    info = client.get(f"/api/reverse/jobs/{JOB}/parts/flange/export").json()
    rep = info["downloads"]["report"]
    assert rep["available"] is True and rep["filename"] == "flange-validation-report.json" and rep["bytes"] == (part_dir(root, "flange") / "qa.json").stat().st_size
    r = dl("flange", "report", ack=1, expect=rep["bytes"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.content == (part_dir(root, "flange") / "qa.json").read_bytes()
    assert r.headers["content-disposition"].startswith("attachment") and "flange-validation-report.json" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff" and int(r.headers["content-length"]) == len(r.content)
    # the bracket's report is its own file, not the flange's
    rb = dl("bracket", "report", ack=1)
    assert rb.status_code == 200 and rb.content == (part_dir(root, "bracket") / "qa.json").read_bytes() and rb.content != r.content


def test_report_follows_the_same_ack_stale_missing_and_canceled_rules(env):
    root, _ = env
    seed(root)
    assert dl("bracket", "report").status_code == 409 and "acknowledge" in dl("bracket", "report").json()["detail"].lower()
    size = client.get(f"/api/reverse/jobs/{JOB}/parts/bracket/export").json()["downloads"]["report"]["bytes"]
    stale = dl("bracket", "report", ack=1, expect=size + 1)
    assert stale.status_code == 409 and "changed" in stale.json()["detail"].lower()
    broken = client.get(f"/api/reverse/jobs/{JOB}/parts/broken/export").json()["downloads"]["report"]            # a failed part never wrote qa.json
    assert broken["available"] is False and "report" in broken["reason"].lower()
    assert dl("broken", "report", ack=1).status_code == 404
    gone = client.get(f"/api/reverse/jobs/{JOB}/parts/gone/export").json()["downloads"]["report"]
    assert gone["available"] is False and "canceled" in gone["reason"]
    assert dl("gone", "report", ack=1).status_code == 409
    assert dl("flange", "nope").status_code == 404
    assert dl("flange", "../../etc").status_code in (404, 400, 422)


def test_replication_report_is_preferred_over_the_qa_record_and_zip_is_unchanged(env):
    root, _ = env
    job = seed(root, parts=[("flange.SLDPRT", "completed")])
    p = job.part("flange")
    f = part_dir(root, "flange") / "replication" / "report.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"schema": "replication-report/1", "status": "verified"}), encoding="utf-8")
    p.artifacts["replication/report.json"] = "flange/active/replication/report.json"
    state.JobStore(root / "data/outputs/3d-to-2d").save(job)
    r = dl("flange", "report", ack=1)
    assert r.status_code == 200 and json.loads(r.content)["schema"] == "replication-report/1"
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(dl("flange", "zip", ack=1).content))
    assert sorted(z.namelist()) == ["flange-drawing.pdf", "flange-drawing.slddrw"]          # the ZIP still holds only the two drawing files


def test_a_report_outside_the_job_is_never_served(env):
    root, _ = env
    job = seed(root, parts=[("flange.SLDPRT", "completed")])
    secret = root / "secret.json"
    secret.write_text("{}", encoding="utf-8")
    job.part("flange").artifacts["qa.json"] = "../../../../secret.json"
    state.JobStore(root / "data/outputs/3d-to-2d").save(job)
    assert dl("flange", "report", ack=1).status_code == 404
    assert client.get(f"/api/reverse/jobs/{JOB}/parts/flange/export").json()["downloads"]["report"]["available"] is False


# ------------------------------------------------------------------ draft vs verified status

def test_export_status_pure_rules():
    s = v7.export_status("completed", "none", {"status": "passed"})
    assert s["key"] == "draft" and s["requires_ack"] is False and s["replication"] is None
    s = v7.export_status("completed", "none", {"status": "passed"}, {"status": "verified"})
    assert s["key"] == "verified" and s["tone"] == "green" and s["requires_ack"] is False and "not an engineering approval" in s["label"]
    s = v7.export_status("review_required", "required", {"status": "review_required"}, {"status": "needs_review", "reason": "2 annotations are missing"})
    assert s["key"] == "review_required" and s["requires_ack"] is True and any("2 annotations are missing" in r for r in s["reasons"])
    s = v7.export_status("completed", "none", {"status": "passed"}, {"status": "blocked", "reason": "no source PDF"})
    assert s["key"] == "review_required" and any("blocked" in r for r in s["reasons"]) and s["requires_ack"]
    s = v7.export_status("completed", "none", {"status": "passed"}, {"status": "failed", "reason": "run error"})
    assert s["key"] == "failed" and s["tone"] == "red"
    s = v7.export_status("completed", "none", {"status": "passed"}, {"status": "pending"})
    assert s["requires_ack"] is True
    # a verified replication never relaxes a v7 verification that did not pass
    s = v7.export_status("completed", "none", {"status": "not_run"}, {"status": "verified"})
    assert s["key"] != "verified" and s["requires_ack"] is True
    assert "approved" not in v7.export_status("completed", "none", {"status": "passed"}, {"status": "verified"})["label"].lower().replace("not an engineering approval", "")


def test_export_state_reports_verified_and_needs_ack_for_a_replication_status(env, monkeypatch):
    root, svc = env
    seed(root, parts=[("flange.SLDPRT", "completed")])
    orig = svc.job_view
    box = {"rep": {"status": "verified", "status_label": "Verified"}}

    def jv(job_id):
        v = orig(job_id)
        for p in v["parts"]:
            p["verification"] = {"status": "passed"}
            p["replication"] = box["rep"]
        return v
    monkeypatch.setattr(svc, "job_view", jv)
    st = client.get(f"/api/reverse/jobs/{JOB}/parts/flange/export").json()["status"]
    assert st["key"] == "verified" and st["requires_ack"] is False
    r = dl("flange", "pdf")                                      # a verified drawing downloads without an acknowledgement
    assert r.status_code == 200 and r.headers["x-drawing-status"] == "verified"
    box["rep"] = {"status": "needs_review", "reason": "scale of view V1 differs"}
    st = client.get(f"/api/reverse/jobs/{JOB}/parts/flange/export").json()["status"]
    assert st["key"] == "review_required" and st["requires_ack"] is True
    assert dl("flange", "pdf").status_code == 409 and dl("flange", "report").status_code == 409
    assert dl("flange", "pdf", ack=1).status_code == 200


# ------------------------------------------------------------------ pre-run estimate

def est_obj(expected=0.21, model="gpt-6-astra"):
    return {"duration": {"low_s": 90, "expected_s": 150, "high_s": 330, "source": "history", "basis": "median of 7"},
            "cost": {"low": 0.04, "expected": expected, "high": 0.62, "currency": "USD", "rate_version": "2026-11-27", "model": model, "unavailable_reason": None},
            "tokens": {"input": {"low": 0, "expected": 20000, "high": 0}, "output": {"low": 0, "expected": 4000, "high": 0}, "cached_input": 0},
            "by_stage": {}, "assumptions": ["1 page, no tiling"], "labels": []}


def test_capabilities_report_the_estimate_and_report_flags(env, monkeypatch):
    _, svc = env
    caps = client.get("/api/reverse/capabilities").json()
    assert caps["report"] is True and "estimate" in caps
    monkeypatch.setattr(svc, "estimate_run", lambda paths, reference=None, options=None: {}, raising=False)
    assert client.get("/api/reverse/capabilities").json()["estimate"] is True


def test_estimate_without_a_backend_estimator_is_history_only_and_never_zero_for_match(env):
    root, svc = env
    r = client.post("/api/reverse/estimate", json={"count": 2})
    assert r.status_code == 200
    j = r.json()
    assert j["source"] == "history" and j["mode"] == "standard"
    assert j["total"]["cost"] == {"low": 0, "expected": 0, "high": 0, "currency": "USD", "rate_version": None, "model": None, "unavailable_reason": None}      # Standard: no model call exists
    assert j["total"]["duration"] is None and "no_duration_history" in j["total"]["labels"]                         # no history: unknown, not a made-up number
    m = client.post("/api/reverse/estimate", json={"count": 1, "reference": {"mode": "match"}}).json()
    assert m["mode"] == "match" and m["total"]["cost"]["expected"] is None and m["total"]["cost"]["low"] is None and m["total"]["cost"]["unavailable_reason"]
    # history makes a duration range, but never an invented "expected"
    for i in range(4):
        fx.write_job(root / "data", f"r3d_00000000000000a{i}", [("p.SLDPRT", "completed")])
    for k in range(4):
        j2 = svc.store.load(f"r3d_00000000000000a{k}")
        j2.parts[0].seconds = 40.0 + 10 * k
        svc.store.save(j2)
    d = client.post("/api/reverse/estimate", json={"count": 2}).json()["total"]["duration"]
    assert d["source"] == "history" and d["low_s"] > 0 and d["high_s"] >= d["low_s"] and d["expected_s"] is None


def test_estimate_validates_its_input(env):
    assert client.post("/api/reverse/estimate", json={"count": "x"}).status_code == 400
    assert client.post("/api/reverse/estimate", json={"count": 1, "reference": {"mode": "wild"}}).status_code == 400
    assert client.post("/api/reverse/estimate", json={"count": 1, "reference": [1]}).status_code == 400
    assert client.post("/api/reverse/estimate", json=[1]).status_code == 400
    assert client.post("/api/reverse/estimate", json={"count": 1, "stage_id": "s_000000000000", "reference": {"mode": "match"}}).status_code in (200, 404)
    big = client.post("/api/reverse/estimate", json={"count": 99999}).json()
    assert big["count"] == 1000                                                      # clamped, never a huge loop


class FakeEst:
    def __init__(self, svc):
        self.calls = []
        self.fail = False
        svc.estimate_run = self.estimate_run
        svc.reference_candidates = lambda part, config="": {"part": {}, "selected": None, "candidates": []}
        svc.save_reference_pdf = lambda tmp: {"ok": False, "error": "x"}

    def estimate_run(self, part_paths, reference=None, options=None):
        self.calls.append({"paths": [Path(p) for p in part_paths], "reference": reference})
        if self.fail:
            raise RuntimeError(f"pricing file not readable at {part_paths[0]}")
        parts = [{"part": str(p), "name": Path(p).name, "reference": {"status": "resolved", "pages": 1, "extraction_cache": "hit" if i == 0 else "fresh"}, "estimate": est_obj()} for i, p in enumerate(part_paths)]
        return {"schema_version": 1, "mode": (reference or {}).get("mode", "standard"), "model": "gpt-6-astra", "parts": parts, "total": est_obj(0.42),
                "budget": {"cap_usd": 20.0, "spent_usd": 16.2, "remaining_usd": 3.8, "would_block": False, "note": "n"}}


def stage(names):
    r = client.post("/api/reverse/stage", files=[("files", (n, b"SLDPRT" + n.encode(), "application/octet-stream")) for n in names])
    assert r.status_code == 200, r.text
    return r.json()


def test_estimate_run_is_used_for_staged_parts_and_never_leaks_paths(env):
    root, svc = env
    fe = FakeEst(svc)
    st = stage(["a.SLDPRT", "b.SLDPRT"])
    body = {"count": 2, "stage_id": st["stage_id"], "keys": ["p0", "p1"], "reference": {"mode": "match", "per_part": {"p0": {"source": "auto"}, "p1": {"source": "none"}}}}
    r = client.post("/api/reverse/estimate", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["source"] == "estimate_run" and j["model"] == "gpt-6-astra" and j["total"]["cost"]["expected"] == 0.42 and j["budget"]["remaining_usd"] == 3.8
    assert [p["part"] for p in j["parts"]] == ["p0", "p1"] and j["parts"][0]["reference"]["extraction_cache"] == "hit"
    assert len(fe.calls) == 1 and [p.name for p in fe.calls[0]["paths"]] == ["a.sldprt", "b.sldprt"]
    ref = fe.calls[0]["reference"]
    assert ref["mode"] == "match" and set(ref["per_part"]) == {str(p) for p in fe.calls[0]["paths"]}                 # translated to server paths on the server only
    blob = r.text
    assert str(root) not in blob and not re.search(r"[A-Za-z]:[\\/]", blob) and "uploads" not in blob
    # a subset of the staged parts
    r2 = client.post("/api/reverse/estimate", json={"count": 1, "stage_id": st["stage_id"], "keys": ["p1"], "reference": {"mode": "match"}}).json()
    assert [p["part"] for p in r2["parts"]] == ["p1"] and len(fe.calls[1]["paths"]) == 1
    # standard mode on a stage is still estimated by the backend (it knows there is no model call)
    r3 = client.post("/api/reverse/estimate", json={"count": 2, "stage_id": st["stage_id"], "keys": ["p0", "p1"]}).json()
    assert r3["source"] == "estimate_run" and fe.calls[2]["reference"] is None


def test_estimate_run_failure_falls_back_to_history_and_says_so_without_paths(env):
    root, svc = env
    fe = FakeEst(svc)
    fe.fail = True
    st = stage(["a.SLDPRT"])
    j = client.post("/api/reverse/estimate", json={"count": 1, "stage_id": st["stage_id"], "keys": ["p0"], "reference": {"mode": "match"}}).json()
    assert j["source"] == "history" and "error" in j and "<path>/" in j["error"] and str(root) not in json.dumps(j)
    assert j["total"]["cost"]["expected"] is None                                    # match mode with no backend answer: unavailable, never $0
    assert client.post("/api/reverse/estimate", json={"count": 1, "stage_id": "bad id", "reference": {"mode": "match"}}).status_code == 400


def test_estimate_route_makes_no_run_and_starts_no_worker(env, monkeypatch):
    root, svc = env
    FakeEst(svc)
    started = []
    monkeypatch.setattr(svc, "start", lambda: started.append(1))
    monkeypatch.setattr(svc, "submit", lambda *, part_paths, template_id=None, profile="x", configs=None, reference=None, options=None, authorized=True: started.append("submit"))
    st = stage(["a.SLDPRT"])
    client.post("/api/reverse/estimate", json={"count": 1, "stage_id": st["stage_id"], "keys": ["p0"], "reference": {"mode": "match"}})
    assert started == []
    assert not list((root / "data/outputs/3d-to-2d").glob("r3d_*")) if (root / "data/outputs/3d-to-2d").exists() else True
