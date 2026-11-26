"""v5: 3D -> 2D HTTP API (server/reverse_api.py) over the real ReverseService.

TEST-ONLY FAKE ENGINE: reverse.engine.PartRunner.run and reverse.worker.CadSession are replaced by stand-ins that write clearly labelled
fixture artifacts ("demo": true). SOLIDWORKS is never started. These tests prove the API, validation, queue behaviour, safety and audit
rules. They are explicitly NOT evidence that SOLIDWORKS produced a native drawing.
"""
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pythoncom")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation"
_TMP = tempfile.mkdtemp(prefix="mcagent_v5r_")
os.environ.setdefault("MCAGENT_REPO", str(REPO))
os.environ.setdefault("MCAGENT_DATA", os.path.join(_TMP, "data"))
os.environ.setdefault("MCAGENT_FINAL_OUTPUTS", os.path.join(_TMP, "final"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO))
import app as appmod  # noqa: E402
import reverse_api as rapi  # noqa: E402
import reverse_fixtures as fx  # noqa: E402
from reverse import engine, state, worker  # noqa: E402

client = TestClient(appmod.app)
GATE = threading.Event()
ATTEMPTS: dict = {}


class FakeSession:
    """TEST ONLY: no COM, no SOLIDWORKS."""
    def __init__(self, *a, **k):
        self.info = worker.SwInfo(revision="TEST-FAKE", major=0, service_pack="", is_2025=False)

    def connect(self):
        return self.info

    def close_all_owned(self):
        pass


def fake_run(self):
    p = self.part
    p.started = state.now()
    p.attempts += 1
    ATTEMPTS[p.part_id] = ATTEMPTS.get(p.part_id, 0) + 1
    name = p.name.lower()
    for stage in state.STAGES:
        if self.cancel():
            state.finish(p, "canceled")
            self.store.save(self.job)
            return
        state.begin_stage(p, stage)
        self.store.save(self.job)
        if "slow" in name and stage == "mesh_export":
            for _ in range(100):
                if GATE.is_set() or self.cancel():
                    break
                time.sleep(0.05)
            if self.cancel():
                state.end_stage(p, stage, "failed", errors=["canceled"])
                state.finish(p, "canceled")
                self.store.save(self.job)
                return
        if "fail" in name and stage == "planning" or ("flaky" in name and ATTEMPTS[p.part_id] == 1 and stage == "planning"):
            state.end_stage(p, stage, "failed", errors=["boom"])
            state.finish(p, "failed", f"RuntimeError: layout failed for {self.src}")      # an absolute path on purpose: the API must scrub it
            self.store.save(self.job)
            return
        state.end_stage(p, stage)
        self.store.save(self.job)
        if stage == "mesh_export":
            fx.write_part_files(self.store.dir(self.job.job_id), p, pdf=False, qa=False)
            self.store.save(self.job)
    fx.write_part_files(self.store.dir(self.job.job_id), p, issues=[])
    state.finish(p, "completed")
    self.store.save(self.job)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="mcagent_v5r_iso_"))
    (root / "data").mkdir()
    monkeypatch.setattr(appmod, "DATA_DIR", root / "data")
    monkeypatch.setattr(engine.PartRunner, "run", fake_run)
    monkeypatch.setattr(worker, "CadSession", FakeSession)
    monkeypatch.setattr(rapi, "_sw_process_running", lambda: False)
    monkeypatch.delenv("SOLIDFLOW_REVERSE_ROOTS", raising=False)
    monkeypatch.delenv("SOLIDFLOW_STOCK_TEMPLATE", raising=False)
    GATE.clear()
    ATTEMPTS.clear()
    rapi.set_service(None)
    svc = rapi.service()
    tpl = root / "default.drwdot"
    tpl.write_bytes(b"TEST FIXTURE template")
    svc.templates.register({"id": "solidflow-ansi-b", "name": "Generated default (test fixture)", "path": str(tpl), "sha256": "ab" * 32, "own_sheet_format": True,
                            "source": "generated", "paper": "ANSI B", "validation": {"ok": True, "errors": [], "views": 0}})
    yield root
    try:
        svc.stop()
    except Exception:
        pass
    rapi.set_service(None)


def sld(name, data=b"SLDPRT-test-bytes" * 8):
    return ("files", (name, data, "application/octet-stream"))


def wait_done(job_id, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/reverse/jobs/{job_id}").json()
        if j["summary_state"] not in ("running", "queued"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish: " + json.dumps(client.get(f"/api/reverse/jobs/{job_id}").json()["summary_state"]))


def submit(files, **form):
    r = client.post("/api/reverse/jobs", files=files, data=form)
    return r


def assert_no_abs_paths(text, root):
    assert str(root) not in text and str(root).replace("\\", "/") not in text and str(root).replace("\\", "\\\\") not in text
    assert not re.search(r"[A-Za-z]:[\\/]", text.replace("\\\\", "\\")), text[:300]


# ------------------------------------------------------------------ catalog / info

def test_profiles_and_templates_expose_no_paths(isolated):
    p = client.get("/api/reverse/profiles").json()["profiles"]
    assert any(x["id"] == "us_third_angle_inch" for x in p)
    t = client.get("/api/reverse/templates").json()
    assert t["default_id"] == "solidflow-ansi-b"
    assert all("path" not in x for x in t["templates"])
    assert_no_abs_paths(json.dumps(t), isolated)


def _wait_task(timeout=5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = client.get("/api/reverse/templates").json()["task"]
        if t and t["state"] != "running":
            return t
        time.sleep(0.05)
    raise AssertionError("template task did not finish")


def test_template_upload_is_a_background_task_polled_through_the_listing(isolated, monkeypatch):
    r = client.post("/api/reverse/templates", files={"file": ("x.txt", b"abc")})
    assert r.status_code == 400 and ".drwdot" in r.json()["detail"]
    assert client.post("/api/reverse/templates", files={"file": ("x.slddrt", b"abc")}).status_code == 400
    svc = rapi.service()
    seen = {}
    release = threading.Event()

    def fake_validate(path, name=None):                       # TEST ONLY: stands in for the CAD-worker validation
        seen["bytes"] = Path(path).read_bytes()
        release.wait(3)
        return svc.templates.register({"id": "user-ok", "name": name, "path": str(path), "sha256": "cd" * 32, "own_sheet_format": False, "source": "uploaded",
                                       "paper": "ANSI B", "validation": {"ok": True, "errors": [], "views": 0}})
    monkeypatch.setattr(svc, "validate_template_async", fake_validate)
    r = client.post("/api/reverse/templates", files={"file": ("ok.drwdot", b"abc")})
    assert r.status_code == 202 and r.json()["task"]["state"] == "running"
    # a second template task is refused while one occupies the CAD worker
    assert client.post("/api/reverse/templates", files={"file": ("two.drwdot", b"abc")}).status_code == 409
    assert client.post("/api/reverse/templates/generate", json={}).status_code == 409
    release.set()
    t = _wait_task()
    assert t["state"] == "done", t
    assert t["template_id"] == "user-ok" and seen["bytes"] == b"abc"
    lst = client.get("/api/reverse/templates").json()["templates"]
    assert any(x["id"] == "user-ok" and x["source"] == "uploaded" for x in lst) and all("path" not in x for x in lst)


def test_template_task_failure_message_is_scrubbed_and_generate_validates_key(isolated, monkeypatch):
    svc = rapi.service()
    def boom(key):
        raise ValueError(f"SOLIDWORKS rejected {isolated}/x.drwdot")
    monkeypatch.setattr(svc, "generate_template_async", boom)
    assert client.post("/api/reverse/templates/generate", json={"key": "nope"}).status_code == 400
    assert client.post("/api/reverse/templates/generate", json={"key": "solidflow-ansi-c"}).status_code == 202
    t = _wait_task()
    assert t["state"] == "failed" and "rejected" in t["error"]
    assert_no_abs_paths(json.dumps(t), isolated)


def test_template_preview_served_only_when_present(isolated):
    svc = rapi.service()
    pv = isolated / "pv.pdf"
    pv.write_bytes(fx.tiny_pdf())
    svc.templates.register({"id": "gen-pv", "name": "g", "path": str(isolated / "default.drwdot"), "sha256": "", "source": "generated", "preview_pdf": str(pv), "paper": "B"})
    r = client.get("/api/reverse/templates/gen-pv/preview")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert client.get("/api/reverse/templates/solidflow-ansi-b/preview").status_code == 404
    assert client.get("/api/reverse/templates/bad id/preview").status_code == 400
    lst = {x["id"]: x for x in client.get("/api/reverse/templates").json()["templates"]}
    assert lst["gen-pv"]["has_preview"] is True and lst["solidflow-ansi-b"]["has_preview"] is False


def test_estimate_not_enough_data_then_range(isolated):
    e = client.get("/api/reverse/estimate?parts=3").json()
    assert e["available"] is False and "at least 3" in e["basis"]
    assert client.get("/api/reverse/estimate?parts=0").status_code == 422
    fx.write_job(isolated / "data", "r3d_" + "1" * 16, [("a.SLDPRT", "completed"), ("b.SLDPRT", "completed"), ("c.SLDPRT", "review")])
    e = client.get("/api/reverse/estimate?parts=2").json()
    assert e["available"] is True and e["low_s"] <= e["high_s"] and "percentile" in e["basis"]


def test_status_reports_detected_revision_only_when_a_job_connected(isolated):
    s = client.get("/api/reverse/status").json()
    assert s["solidworks"]["detected"] is False and s["solidworks"]["revision"] == "" and s["queue_length"] == 0
    rapi._PROBE.update(t=0, v=None)
    fx.write_job(isolated / "data", "r3d_" + "2" * 16, [("a.SLDPRT", "completed")])
    s = client.get("/api/reverse/status").json()["solidworks"]
    assert s["detected"] is True and s["revision"] == "33.5.0" and s["source"] == "last_job" and s["is_2025"] is True


# ------------------------------------------------------------------ submission / validation

def test_submit_rejects_bad_files_with_reasons_and_runs_the_rest(isolated):
    r = submit([sld("good.SLDPRT"), sld("asm.SLDASM"), sld("mesh.stl"), sld("notes.txt"), sld("empty.SLDPRT", b""), sld("~$lock.SLDPRT")])
    assert r.status_code == 200, r.text
    j = r.json()
    names = {x["name"]: x["reason"] for x in j["rejected"]}
    assert "assembly" in names["asm.sldasm"] and "mesh" in names["mesh.stl"] and "not a SOLIDWORKS part" in names["notes.txt"]
    assert "empty" in names["empty.sldprt"] and "lock file" in names["lock.sldprt"]
    assert [p["name"] for p in j["parts"]] == ["good.sldprt"]
    assert_no_abs_paths(r.text, isolated)
    done = wait_done(j["job_id"])
    assert done["parts"][0]["state"] == "completed"
    assert done["options"]["rejected"], "rejections stay visible on the job"


def test_submit_with_only_bad_files_is_400(isolated):
    r = submit([sld("a.stp"), sld("b.txt")])
    assert r.status_code == 400
    assert "No valid" in r.json()["detail"]
    assert client.post("/api/reverse/jobs", data={}).status_code in (400, 422)
    assert client.post("/api/reverse/jobs", json={"nope": 1}).status_code == 400


def test_submit_unknown_template_and_profile_are_400(isolated):
    assert submit([sld("a.SLDPRT")], template_id="nope").status_code == 400
    assert submit([sld("a.SLDPRT")], profile="nope").status_code == 400
    assert submit([sld("a.SLDPRT")], config="x" * 200).status_code == 400


def test_duplicate_names_get_distinct_part_ids(isolated):
    r = submit([sld("same.SLDPRT"), sld("same.SLDPRT", b"different-bytes" * 5)])
    ids = [p["part_id"] for p in r.json()["parts"]]
    assert len(set(ids)) == 2
    wait_done(r.json()["job_id"])


def test_uploaded_name_cannot_escape_the_upload_folder(isolated):
    r = submit([("files", ("..\\..\\evil.SLDPRT", b"x" * 40, "application/octet-stream")), ("files", ("../../evil2.SLDPRT", b"x" * 40, "application/octet-stream"))])
    assert r.status_code == 200
    wait_done(r.json()["job_id"])
    up = rapi._upload_root()
    for f in up.rglob("*.sldprt"):
        assert str(f.resolve()).startswith(str(up.resolve()))
    assert not (isolated / "evil.sldprt").exists() and not (isolated / "data" / "evil.sldprt").exists()


def test_folder_mode_only_inside_authorized_roots(isolated, monkeypatch):
    outside = isolated / "outside"
    outside.mkdir()
    (outside / "p.SLDPRT").write_bytes(b"x" * 50)
    r = client.post("/api/reverse/jobs", json={"folder": str(outside)})
    assert r.status_code == 400 and "authorized" in r.json()["detail"]
    assert client.post("/api/reverse/jobs", json={"folder": "relative/dir"}).status_code == 400
    monkeypatch.setenv("SOLIDFLOW_REVERSE_ROOTS", str(outside))
    (outside / "sub").mkdir()
    (outside / "sub" / "q.sldprt").write_bytes(b"x" * 50)
    r = client.post("/api/reverse/jobs", json={"folder": str(outside), "recursive": False})
    assert r.status_code == 200 and [p["name"] for p in r.json()["parts"]] == ["p.SLDPRT"]
    wait_done(r.json()["job_id"])
    r = client.post("/api/reverse/jobs", json={"folder": str(outside), "recursive": True})
    assert sorted(p["name"].lower() for p in r.json()["parts"]) == ["p.sldprt", "q.sldprt"]
    assert_no_abs_paths(r.text, isolated)
    wait_done(r.json()["job_id"])


# ------------------------------------------------------------------ queue behaviour

def test_batch_isolation_one_failing_part_does_not_stop_the_rest(isolated):
    r = submit([sld("ok1.SLDPRT"), sld("fail.SLDPRT"), sld("ok2.SLDPRT")])
    done = wait_done(r.json()["job_id"])
    st = {p["name"]: p["state"] for p in done["parts"]}
    assert st == {"ok1.sldprt": "completed", "fail.sldprt": "failed", "ok2.sldprt": "completed"}
    assert done["summary_state"] == "completed_with_failures"
    failed = next(p for p in done["parts"] if p["name"] == "fail.sldprt")
    assert "drawing.pdf" not in failed["files"], "a failed part never advertises a drawing"
    assert "model.stl" in failed["files"], "but the STL it did produce is listed"
    assert done["progress"]["parts_done"] == 3
    assert_no_abs_paths(json.dumps(done), isolated)         # the fake failure message carried an absolute path


def test_retry_runs_only_failed_parts(isolated):
    r = submit([sld("ok.SLDPRT"), sld("flaky.SLDPRT")])
    jid = r.json()["job_id"]
    done = wait_done(jid)
    assert {p["name"]: p["state"] for p in done["parts"]} == {"ok.sldprt": "completed", "flaky.sldprt": "failed"}
    assert client.post(f"/api/reverse/jobs/{jid}/retry", json={"part_ids": ["nope"]}).status_code == 404
    assert client.post(f"/api/reverse/jobs/{jid}/retry").status_code == 200
    done = wait_done(jid)
    assert all(p["state"] == "completed" for p in done["parts"])
    assert ATTEMPTS["ok"] == 1, "the completed part was not run again"
    assert client.post(f"/api/reverse/jobs/{jid}/retry").status_code == 409      # nothing left to retry


def test_cancel_stops_the_running_part_and_the_queued_ones(isolated):
    r = submit([sld("slow.SLDPRT"), sld("second.SLDPRT")])
    jid = r.json()["job_id"]
    for _ in range(100):
        if client.get(f"/api/reverse/jobs/{jid}").json()["parts"][0]["state"] == "mesh_export":
            break
        time.sleep(0.05)
    assert client.post(f"/api/reverse/jobs/{jid}/cancel").status_code == 200
    done = wait_done(jid)
    assert [p["state"] for p in done["parts"]] == ["canceled", "canceled"]
    assert done["summary_state"] == "canceled"
    assert client.post(f"/api/reverse/jobs/{jid}/cancel").status_code == 409      # already finished


def test_cannot_delete_or_review_a_running_job_but_can_delete_a_finished_one(isolated):
    r = submit([sld("slow.SLDPRT")])
    jid = r.json()["job_id"]
    for _ in range(100):
        if client.get(f"/api/reverse/jobs/{jid}").json()["parts"][0]["state"] == "mesh_export":
            break
        time.sleep(0.05)
    assert client.delete(f"/api/reverse/jobs/{jid}").status_code == 409
    assert client.post(f"/api/reverse/jobs/{jid}/parts/slow/review", json={"issue_id": "x", "action": "accept", "note": "n"}).status_code == 409
    GATE.set()
    wait_done(jid)
    assert client.delete(f"/api/reverse/jobs/{jid}").status_code == 200
    assert client.get(f"/api/reverse/jobs/{jid}").status_code == 404
    assert not list(rapi._upload_root().rglob("*.sldprt")), "the uploaded copy goes with the job"


# ------------------------------------------------------------------ reads, events, artifacts

def job_with_files(isolated, kind="review", jid="r3d_" + "a" * 16, name="bracket.SLDPRT"):
    fx.write_job(isolated / "data", jid, [(name, kind)])
    return jid, name.rsplit(".", 1)[0]


def test_job_views_list_and_thumbnail(isolated):
    jid, pid = job_with_files(isolated)
    lst = client.get("/api/reverse/jobs").json()["jobs"]
    row = next(x for x in lst if x["job_id"] == jid)
    assert row["kind"] == "reverse" and row["thumb"]["url_path"].endswith("preview/page-001.png") and row["state"] == "review_required"
    v = client.get(f"/api/reverse/jobs/{jid}").json()
    p = v["parts"][0]
    assert "source" not in p and "output_root" not in v
    assert p["files"]["drawing.pdf"]["bytes"] > 0 and p["stages"]["verification"]["status"] == "warning"
    assert_no_abs_paths(json.dumps(v) + json.dumps(lst), isolated)


def test_events_after_cursor(isolated):
    jid, _ = job_with_files(isolated)
    e = client.get(f"/api/reverse/jobs/{jid}/events").json()
    assert len(e["events"]) >= 2 and e["next"] == e["events"][-1]["seq"] + 1
    assert client.get(f"/api/reverse/jobs/{jid}/events?after={e['next']}").json()["events"] == []
    assert client.get(f"/api/reverse/jobs/{jid}/events?after=-1").status_code == 422


def test_invalid_and_unknown_ids(isolated):
    assert client.get("/api/reverse/jobs/r3d_" + "f" * 16).status_code == 404
    assert client.get("/api/reverse/jobs/..%5C..%5Cx").status_code in (400, 404)
    assert client.get("/api/reverse/jobs/bad id!").status_code == 400
    jid, _ = job_with_files(isolated)
    assert client.post(f"/api/reverse/jobs/{jid}/parts/nope/review", json={}).status_code == 404
    assert client.post(f"/api/reverse/jobs/{jid}/parts/bad%20id/review", json={}).status_code == 400


def test_artifact_download_media_types_and_dispositions(isolated):
    jid, pid = job_with_files(isolated)
    base = f"/api/reverse/jobs/{jid}/files/{pid}/active/"
    r = client.get(base + "drawing.pdf")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf") and r.headers["content-disposition"].startswith("inline")
    assert r.content.startswith(b"%PDF")
    r = client.get(base + "model.stl")
    assert r.status_code == 200 and r.headers["content-type"].startswith("model/stl") and r.headers["content-disposition"].startswith("inline")
    r = client.get(base + "preview/page-001.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content.startswith(b"\x89PNG")
    r = client.get(base + "qa.json")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment") and r.headers["x-content-type-options"] == "nosniff"
    r = client.get(base + "drawing.slddrw")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")


def test_artifact_download_refuses_traversal_and_unlisted_files(isolated):
    jid, pid = job_with_files(isolated)
    other, _ = job_with_files(isolated, "completed", "r3d_" + "b" * 16, "other.SLDPRT")
    h = f"/api/reverse/jobs/{jid}/files/"
    bad = ["job.json", "events.jsonl", f"{pid}/active/../../job.json", f"{pid}/active/..%2f..%2fjob.json", "..%2f" + other + "%2fjob.json", f"..%2f{other}%2fother%2factive%2fmodel.stl",
           "%2fetc%2fpasswd", "C:%5CWindows%5Cwin.ini", f"{pid}%5Cactive%5Cmodel.stl", f"{pid}/active/_staging/x", f"{pid}/active/nothere.pdf", "other/active/model.stl"]
    for rel in bad:
        r = client.get(h + rel)
        assert r.status_code in (400, 404), (rel, r.status_code)
    assert client.get(h).status_code in (400, 404, 405)
    # a file that exists on disk but is not a listed artifact must not be served
    (isolated / "data" / "outputs" / "3d-to-2d" / jid / pid / "active" / "secret.txt").write_text("nope")
    assert client.get(h + f"{pid}/active/secret.txt").status_code == 404


def test_artifact_listing_skips_files_that_do_not_exist(isolated):
    jid, pid = job_with_files(isolated, "completed")
    (isolated / "data" / "outputs" / "3d-to-2d" / jid / pid / "active" / "drawing.pdf").unlink()
    v = client.get(f"/api/reverse/jobs/{jid}").json()
    assert "drawing.pdf" not in v["parts"][0]["files"] and "model.stl" in v["parts"][0]["files"]
    assert client.get(f"/api/reverse/jobs/{jid}/files/{pid}/active/drawing.pdf").status_code == 404


# ------------------------------------------------------------------ audited review

def test_review_requires_a_note_to_accept_or_reject_and_is_audited(isolated):
    jid, pid = job_with_files(isolated)
    url = f"/api/reverse/jobs/{jid}/parts/{pid}/review"
    iss = client.get(f"/api/reverse/jobs/{jid}").json()["parts"][0]["issues"]
    assert len(iss) == 3
    hi = next(i for i in iss if i["severity"] == "high")
    assert client.post(url, json={"issue_id": hi["id"], "action": "accept", "note": "  "}).status_code == 400
    assert client.post(url, json={"issue_id": hi["id"], "action": "reject"}).status_code == 400
    assert client.post(url, json={"issue_id": "nope", "action": "accept", "note": "n"}).status_code == 404
    assert client.post(url, json={"issue_id": hi["id"], "action": "approve", "note": "n"}).status_code == 400
    assert client.post(url, data="not json", headers={"content-type": "application/json"}).status_code == 400
    r = client.post(url, json={"issue_id": hi["id"], "action": "reject", "note": "Wrong hole size on the drawing", "user": "A. Engineer"})
    assert r.status_code == 200 and r.json()["issue"]["disposition"] == "rejected"
    hist = r.json()["issue"]["history"][-1]
    assert hist["user"] == "A. Engineer" and hist["action"] == "reject" and hist["note"].startswith("Wrong hole") and hist["at"]
    r = client.post(url, json={"issue_id": hi["id"], "action": "reopen"})
    assert r.status_code == 200 and r.json()["issue"]["disposition"] == "open" and len(r.json()["issue"]["history"]) == 2
    qa = json.loads((isolated / "data" / "outputs" / "3d-to-2d" / jid / pid / "active" / "qa.json").read_text())
    assert any(i["history"] for i in qa["issues"]), "the audit trail is written next to the artifacts"
    r = client.post(url, json={"issue_id": hi["id"], "action": "accept", "note": "Reviewed with the designer"})
    med = next(i for i in iss if i["severity"] == "medium")
    r = client.post(url, json={"issue_id": med["id"], "action": "accept", "note": "Fillets noted by hand"})
    assert r.json()["review_status"] == "resolved" and r.json()["part_state"] == "completed"


def test_review_user_defaults_to_the_os_user_never_blank(isolated):
    jid, pid = job_with_files(isolated)
    iss = client.get(f"/api/reverse/jobs/{jid}").json()["parts"][0]["issues"]
    r = client.post(f"/api/reverse/jobs/{jid}/parts/{pid}/review", json={"issue_id": iss[0]["id"], "action": "accept", "note": "ok"})
    assert r.json()["issue"]["history"][-1]["user"].strip()
