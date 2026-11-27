"""v7: reference-drawing routes and run/part/artifact-bound export downloads (server/reverse_v7.py).

TEST-ONLY FAKES: the reference backend (reference_candidates / save_reference_pdf / confirm_reference_link / submit(reference=...)) is replaced
by stand-ins on the real service object so the HTTP layer can be proved independently of the backend agent's work; the export tests use REAL
files written by tests/server/reverse_fixtures.py into an isolated data dir (labelled fixtures, not SOLIDWORKS output). SOLIDWORKS is never started.
"""
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pythoncom")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation"
_TMP = tempfile.mkdtemp(prefix="mcagent_v7r_")
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
from reverse import state, worker  # noqa: E402

client = TestClient(appmod.app)


@pytest.fixture()
def env(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="mcagent_v7r_iso_"))
    (root / "data").mkdir()
    monkeypatch.setattr(appmod, "DATA_DIR", root / "data")
    monkeypatch.setattr(rapi, "_sw_process_running", lambda: False)
    monkeypatch.delenv("SOLIDFLOW_REVERSE_ROOTS", raising=False)
    rapi.set_service(None)
    svc = rapi.service()
    monkeypatch.setattr(svc, "start", lambda: None)               # the CAD worker is never started here
    yield root, svc
    rapi.set_service(None)


def seed(root, job_id="r3d_00000000000000aa", parts=None):
    parts = parts or [("flange.SLDPRT", "completed"), ("bracket.SLDPRT", "review"), ("broken.SLDPRT", "failed"), ("gone.SLDPRT", "canceled"), ("busy.SLDPRT", "processing")]
    return fx.write_job(root / "data", job_id, parts)


def dl(job, part, kind, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return client.get(f"/api/reverse/jobs/{job}/parts/{part}/export/{kind}" + ("?" + qs if qs else ""))


JOB = "r3d_00000000000000aa"


# ------------------------------------------------------------------ export

def test_export_state_reports_only_real_artifacts_and_draft_status(env):
    root, _ = env
    seed(root)
    ok = client.get(f"/api/reverse/jobs/{JOB}/parts/flange/export").json()
    assert ok["downloads"]["slddrw"]["available"] and ok["downloads"]["pdf"]["available"] and ok["downloads"]["zip"]["available"]
    assert ok["downloads"]["pdf"]["filename"] == "flange-drawing.pdf"
    assert ok["status"]["requires_ack"] is True and "not approved" in ok["status"]["label"].lower() or ok["status"]["key"] in ("review_required", "draft")
    assert "approved" not in ok["status"]["label"].lower().replace("not approved", "")
    failed = client.get(f"/api/reverse/jobs/{JOB}/parts/broken/export").json()
    assert failed["downloads"]["slddrw"]["available"] is False and failed["downloads"]["pdf"]["available"] is False and failed["downloads"]["zip"]["available"] is False
    canceled = client.get(f"/api/reverse/jobs/{JOB}/parts/gone/export").json()
    assert not any(v["available"] for v in canceled["downloads"].values()) and "canceled" in canceled["downloads"]["pdf"]["reason"]
    busy = client.get(f"/api/reverse/jobs/{JOB}/parts/busy/export").json()
    assert not any(v["available"] for v in busy["downloads"].values())
    blob = json.dumps(ok)
    assert str(root) not in blob and not re.search(r"[A-Za-z]:[\\/]", blob)


def test_download_headers_signature_length_and_sanitised_filename(env):
    root, _ = env
    seed(root, parts=[("flange.SLDPRT", "completed")])
    jj = root / "data/outputs/3d-to-2d" / JOB / "job.json"
    d = json.loads(jj.read_text())
    d["parts"][0]["name"] = 'we ird;na"me' + chr(92) + '..' + chr(92) + 'x.SLDPRT'     # a display name with quote, semicolon and path separators
    jj.write_text(json.dumps(d))
    pid = "flange"
    r = dl(JOB, pid, "pdf", ack=1)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF-")
    assert int(r.headers["content-length"]) == len(r.content)
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment") and "filename=" in cd and '"' not in cd.split("filename=")[1].strip('"') and ";" not in cd.split("filename=")[1]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-drawing-status"] in ("draft", "review_required")
    s = dl(JOB, pid, "slddrw", ack=1)
    assert s.status_code == 200 and s.headers["content-type"] == "application/octet-stream" and ".slddrw" in s.headers["content-disposition"]
    assert s.content == (root / "data/outputs/3d-to-2d" / JOB / pid / "active" / "drawing.slddrw").read_bytes()


def test_acknowledgement_is_required_for_unapproved_drawings(env, monkeypatch):
    root, svc = env
    seed(root)
    r = dl(JOB, "bracket", "pdf")
    assert r.status_code == 409 and "acknowledge" in r.json()["detail"].lower()
    assert dl(JOB, "bracket", "pdf", ack=0).status_code == 409
    assert dl(JOB, "bracket", "pdf", ack=1).status_code == 200
    # a verified drawing (backend says passed) needs no acknowledgement but is still a draft
    orig = svc.job_view

    def jv(job_id):
        v = orig(job_id)
        for p in v["parts"]:
            if p["part_id"] == "flange":
                p["verification"] = {"status": "passed"}
        return v
    monkeypatch.setattr(svc, "job_view", jv)
    info = client.get(f"/api/reverse/jobs/{JOB}/parts/flange/export").json()
    assert info["status"]["requires_ack"] is False and info["status"]["key"] == "draft" and "not approved" in info["status"]["label"].lower()
    assert dl(JOB, "flange", "pdf").status_code == 200


def test_missing_stale_cancelled_wrong_part_and_traversal(env):
    root, _ = env
    seed(root)
    assert dl(JOB, "broken", "pdf", ack=1).status_code == 404                    # failed before a drawing existed
    assert dl(JOB, "gone", "pdf", ack=1).status_code == 409                      # canceled
    assert dl(JOB, "busy", "slddrw", ack=1).status_code == 409                   # still running
    assert dl(JOB, "nope", "pdf", ack=1).status_code == 404                      # wrong part
    assert dl("r3d_00000000000000bb", "flange", "pdf", ack=1).status_code == 404  # stale / unknown job
    assert dl(JOB, "flange", "exe", ack=1).status_code == 404
    for bad in ("..%2F..%2Fjob", "%2e%2e", "a%5Cb", "a%00b"):
        assert client.get(f"/api/reverse/jobs/{JOB}/parts/{bad}/export/pdf").status_code in (400, 404, 405)
    for bad in ("..%2Fx", "%2e%2e", "x%00"):
        assert client.get(f"/api/reverse/jobs/{bad}/parts/flange/export/pdf").status_code in (400, 404, 405)
    # stale: the size the page saw no longer matches
    size = len(dl(JOB, "flange", "pdf", ack=1).content)
    assert dl(JOB, "flange", "pdf", ack=1, expect=size).status_code == 200
    assert dl(JOB, "flange", "pdf", ack=1, expect=size + 1).status_code == 409
    # the file vanished from disk after the page listed it
    (root / "data/outputs/3d-to-2d" / JOB / "flange" / "active" / "drawing.pdf").unlink()
    assert dl(JOB, "flange", "pdf", ack=1).status_code == 404
    assert dl(JOB, "flange", "zip", ack=1).status_code == 404                    # a zip needs BOTH


def test_artifact_not_listed_for_the_part_is_never_served(env):
    root, _ = env
    seed(root)
    other = root / "data/outputs/3d-to-2d" / JOB / "flange" / "active" / "drawing.pdf"
    j = root / "data/outputs/3d-to-2d" / JOB / "job.json"
    d = json.loads(j.read_text())
    for p in d["parts"]:
        if p["part_id"] == "bracket":
            p["artifacts"]["drawing.pdf"] = "flange/active/drawing.pdf"        # points into another part's folder: still inside the job
        if p["part_id"] == "flange":
            p["artifacts"]["drawing.slddrw"] = "../../../../outside.slddrw"      # escapes the job folder
    j.write_text(json.dumps(d))
    (root / "data/outside.slddrw").write_bytes(b"secret")
    assert dl(JOB, "flange", "slddrw", ack=1).status_code == 404
    assert other.exists()


def test_zip_contains_only_validated_artifacts_and_no_server_paths(env):
    root, _ = env
    seed(root)
    r = dl(JOB, "flange", "zip", ack=1)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert int(r.headers["content-length"]) == len(r.content)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == ["flange-drawing.pdf", "flange-drawing.slddrw"] and z.testzip() is None
    assert z.read("flange-drawing.pdf").startswith(b"%PDF-")
    assert str(root).encode() not in r.content and dl(JOB, "flange", "zip").status_code == 409
    assert not list((root / "data" / "tmp").glob("export_*.zip"))                    # the temp archive is removed after sending


# ------------------------------------------------------------------ reference: capabilities and honest 501

def test_capabilities_are_reported_and_501_when_missing(env, monkeypatch):
    root, svc = env
    caps = client.get("/api/reverse/capabilities").json()
    assert set(caps) >= {"reference", "candidates", "upload", "confirm", "export"} and caps["export"] is True
    def old_submit(*, part_paths, template_id=None, profile="x", configs=None):       # a backend without the reference parameter
        raise AssertionError("not called")
    monkeypatch.setattr(svc, "submit", old_submit)
    assert client.get("/api/reverse/capabilities").json()["reference"] is False
    assert client.post("/api/reverse/stage", files=[("files", ("a.SLDPRT", b"x", "application/octet-stream"))]).status_code == 501
    assert client.post("/api/reverse/reference/upload", files={"file": ("a.pdf", b"%PDF-1.4 x")}).status_code == 501
    r = client.post("/api/reverse/jobs", files=[("files", ("a.SLDPRT", b"x", "application/octet-stream"))], data={"reference": json.dumps({"mode": "match"})})
    assert r.status_code == 501 and "Standard" in r.json()["detail"]


# ------------------------------------------------------------------ reference: stage, candidates, confirm, upload, submit

class FakeBackend:
    """TEST ONLY stand-ins for the v7 backend methods, installed on the real service object."""

    def __init__(self, root, svc):
        self.root, self.svc, self.calls, self.submitted = root, svc, [], []
        self.cands = {}
        svc.reference_candidates = self.reference_candidates
        svc.save_reference_pdf = self.save_reference_pdf
        svc.confirm_reference_link = self.confirm_reference_link
        svc.submit = self.submit
        self.confirmed = []

    def reference_candidates(self, part, config=""):
        self.calls.append(("cand", Path(part).name, config))
        name = Path(part).stem.lower()
        if "ambig" in name:
            c = [{"artifact_id": "pdf_aaaa1111", "filename": "A.pdf", "project": "proj", "run": "r1", "date": "2026-11-01", "pages": 1, "confidence": 0.5, "reasons": ["same part number"], "needs_confirmation": True, "link": None, "path": "C:/secret/a.pdf"},
                 {"artifact_id": "pdf_bbbb2222", "filename": "B.pdf", "project": "proj", "run": "r2", "date": "2026-11-02", "pages": 2, "confidence": 0.5, "reasons": ["same part number"], "needs_confirmation": True, "link": None}]
            return {"part": {"filename": Path(part).name, "sha256": "f" * 64}, "selected": None, "candidates": c}
        if "none" in name:
            return {"part": {}, "selected": None, "candidates": [], "error": f"nothing near {part}"}
        c = {"artifact_id": "pdf_cccc3333", "filename": "C.pdf", "project": "proj", "run": "r9", "date": "2026-11-20", "pages": 1, "confidence": 0.98, "reasons": ["hash"], "needs_confirmation": False, "link": "part_hash"}
        return {"part": {}, "selected": c, "candidates": [c]}

    def confirm_reference_link(self, part, artifact_id, config="", user=""):
        self.confirmed.append((Path(part).name, artifact_id, user))

    def save_reference_pdf(self, tmp):
        data = Path(tmp).read_bytes()
        if b"BADPDF" in data:
            return {"ok": False, "error": f"cannot open {tmp}"}
        sha = hashlib.sha256(data).hexdigest()
        dest = self.root / "data" / "uploads" / "3d-to-2d" / "reference" / f"{sha}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return {"ok": True, "sha256": sha, "pages": 2, "size": len(data), "pdf_path": str(dest), "artifact_id": "pdf_" + sha[:8], "filename": "x.pdf"}

    def submit(self, *, part_paths, template_id=None, profile="us_third_angle_inch", configs=None, reference=None, options=None, authorized=True):
        self.submitted.append({"paths": [Path(p) for p in part_paths], "reference": reference, "configs": configs})
        return fx.write_job(self.root / "data", "r3d_00000000000000cc", [(Path(p).name, "queued") for p in part_paths])


def stage_parts(names):
    r = client.post("/api/reverse/stage", files=[("files", (n, b"SLDPRT" + n.encode(), "application/octet-stream")) for n in names] + [("files", ("notes.txt", b"x", "text/plain"))])
    assert r.status_code == 200, r.text
    return r.json()


def test_stage_candidates_filter_fields_scrub_paths_and_never_return_server_paths(env):
    root, svc = env
    fb = FakeBackend(root, svc)
    st = stage_parts(["good.SLDPRT", "ambig.SLDPRT", "none.SLDPRT"])
    assert [p["key"] for p in st["parts"]] == ["p0", "p1", "p2"]                 # the .txt was skipped, keys follow the file order
    res = client.post("/api/reverse/reference/candidates", json={"stage_id": st["stage_id"]}).json()
    rows = {r["name"]: r for r in res["rows"]}
    assert rows["good.sldprt"]["selected"]["artifact_id"] == "pdf_cccc3333"
    assert len(rows["ambig.sldprt"]["candidates"]) == 2 and rows["ambig.sldprt"]["selected"] is None
    assert all(c["needs_confirmation"] for c in rows["ambig.sldprt"]["candidates"])
    assert rows["none.sldprt"]["candidates"] == [] and "error" in rows["none.sldprt"]
    blob = json.dumps(res)
    assert '"path"' not in blob and "<path>/none.sldprt" in blob and "C:/secret" not in blob and str(root) not in blob and not re.search(r"[A-Za-z]:[\\/]", blob)
    assert client.post("/api/reverse/reference/candidates", json={"stage_id": "s_000000000000"}).status_code == 404
    assert client.post("/api/reverse/reference/candidates", json={"stage_id": "../x"}).status_code == 400


def test_confirm_requires_an_offered_candidate_and_submit_requires_confirmation(env):
    root, svc = env
    fb = FakeBackend(root, svc)
    st = stage_parts(["ambig.SLDPRT", "good.SLDPRT"])
    sid = st["stage_id"]
    client.post("/api/reverse/reference/candidates", json={"stage_id": sid})
    ref = {"mode": "match", "per_part": {"p0": {"source": "artifact", "artifact_id": "pdf_aaaa1111"}, "p1": {"source": "auto"}}}
    # not confirmed yet: refused, nothing is submitted
    r = client.post("/api/reverse/jobs", json={"stage_id": sid, "keys": ["p0", "p1"], "reference": ref})
    assert r.status_code == 409 and "confirm" in r.json()["detail"].lower() and not fb.submitted
    assert client.post("/api/reverse/reference/confirm", json={"stage_id": sid, "key": "p0", "artifact_id": "pdf_zzzz9999"}).status_code == 409
    assert client.post("/api/reverse/reference/confirm", json={"stage_id": sid, "key": "p9", "artifact_id": "pdf_aaaa1111"}).status_code == 404
    ok = client.post("/api/reverse/reference/confirm", json={"stage_id": sid, "key": "p0", "artifact_id": "pdf_aaaa1111"})
    assert ok.status_code == 200 and ok.json()["persisted"] is True and fb.confirmed[0][:2] == ("ambig.sldprt", "pdf_aaaa1111")
    r = client.post("/api/reverse/jobs", json={"stage_id": sid, "keys": ["p0", "p1"], "reference": ref, "profile": "us_third_angle_inch"})
    assert r.status_code == 200, r.text
    sub = fb.submitted[0]
    keys = {p.name: str(p) for p in sub["paths"]}
    pp = sub["reference"]["per_part"]
    assert sub["reference"]["mode"] == "match" and sub["reference"]["fallback_standard"] is False
    assert pp[keys["ambig.sldprt"]] == {"source": "artifact", "artifact_id": "pdf_aaaa1111"}
    assert pp[keys["good.sldprt"]] == {"source": "auto"}
    # the stage is consumed by the job
    assert client.post("/api/reverse/reference/candidates", json={"stage_id": sid}).status_code == 404


def test_submit_only_the_checked_parts_of_a_stage_and_fallback_flag(env):
    root, svc = env
    fb = FakeBackend(root, svc)
    st = stage_parts(["a.SLDPRT", "b.SLDPRT", "c.SLDPRT"])
    ref = {"mode": "match", "fallback_standard": True, "per_part": {"p1": {"source": "none"}}}
    r = client.post("/api/reverse/jobs", json={"stage_id": st["stage_id"], "keys": ["p1", "p2"], "reference": ref})
    assert r.status_code == 200, r.text
    sub = fb.submitted[0]
    assert [p.name for p in sub["paths"]] == ["b.sldprt", "c.sldprt"] and sub["reference"]["fallback_standard"] is True
    pp = sub["reference"]["per_part"]
    assert sorted(v["source"] for v in pp.values()) == ["auto", "none"]            # a missing per_part entry means auto


def test_artifact_must_have_been_offered_for_that_part(env):
    root, svc = env
    FakeBackend(root, svc)
    st = stage_parts(["good.SLDPRT"])
    sid = st["stage_id"]
    ref = {"mode": "match", "per_part": {"p0": {"source": "artifact", "artifact_id": "pdf_cccc3333"}}}
    assert client.post("/api/reverse/jobs", json={"stage_id": sid, "reference": ref}).status_code == 409   # no lookup yet
    client.post("/api/reverse/reference/candidates", json={"stage_id": sid})
    assert client.post("/api/reverse/jobs", json={"stage_id": sid, "reference": ref}).status_code == 200     # offered and not needing confirmation


def test_reference_upload_policies_and_submit_with_uploaded_pdf(env, monkeypatch):
    root, svc = env
    fb = FakeBackend(root, svc)
    up = lambda name, data: client.post("/api/reverse/reference/upload", files={"file": (name, data, "application/pdf")})
    assert up("x.txt", b"%PDF-1.4").status_code == 400
    assert up("x.pdf", b"not a pdf at all").status_code == 400
    assert up("x.pdf", b"").status_code == 400
    r = up("x.pdf", b"%PDF-1.4 BADPDF")
    assert r.status_code == 400 and str(root) not in r.text and "C:" not in r.text
    monkeypatch.setattr(v7, "MAX_REFERENCE_BYTES", 64)
    assert up("big.pdf", b"%PDF-1.4" + b"0" * 200).status_code == 413
    monkeypatch.setattr(v7, "MAX_REFERENCE_BYTES", 50 * 1024 * 1024)
    data = b"%PDF-1.4 good reference"
    r = up("../../etc/My Ref;x.pdf", data)
    assert r.status_code == 200, r.text
    j = r.json()
    sha = hashlib.sha256(data).hexdigest()
    assert j["upload_id"] == sha and j["pages"] == 2 and j["filename"].endswith(".pdf") and "/" not in j["filename"] and ";" not in j["filename"]
    assert "path" not in j and str(root) not in json.dumps(j)
    st = stage_parts(["good.SLDPRT", "other.SLDPRT"])
    ref = {"mode": "match", "per_part": {"p0": {"source": "upload", "upload_id": sha}, "p1": {"source": "upload", "upload_id": "../../x"}}}
    assert client.post("/api/reverse/jobs", json={"stage_id": st["stage_id"], "reference": ref}).status_code == 400
    ref["per_part"]["p1"] = {"source": "upload", "upload_id": "0" * 64}
    assert client.post("/api/reverse/jobs", json={"stage_id": st["stage_id"], "reference": ref}).status_code == 409   # not on the server
    ref["per_part"]["p1"] = {"source": "none"}
    r = client.post("/api/reverse/jobs", json={"stage_id": st["stage_id"], "reference": ref})
    assert r.status_code == 200, r.text
    got = fb.submitted[-1]["reference"]["per_part"]
    assert sorted(v["source"] for v in got.values()) == ["none", "upload"]
    assert [v["pdf_path"] for v in got.values() if v["source"] == "upload"][0].endswith(sha + ".pdf")
    assert str(root) not in r.text                                                    # the response never carries the path


def test_bad_reference_payloads_are_rejected_and_standard_mode_is_unchanged(env):
    root, svc = env
    fb = FakeBackend(root, svc)
    f = [("files", ("a.SLDPRT", b"x", "application/octet-stream"))]
    for bad in ('{"mode":"weird"}', "not json", '["x"]', '{"mode":"match","per_part":{"p0":{"source":"hack"}}}', '{"mode":"match","per_part":[1]}'):
        assert client.post("/api/reverse/jobs", files=f, data={"reference": bad}).status_code == 400, bad
    r = client.post("/api/reverse/jobs", files=f, data={"reference": json.dumps({"mode": "standard", "per_part": {"p0": {"source": "upload"}}})})
    assert r.status_code == 200 and fb.submitted[-1]["reference"] is None            # standard sends no reference payload at all
    r = client.post("/api/reverse/jobs", files=f)
    assert r.status_code == 200 and fb.submitted[-1]["reference"] is None


def test_stage_drop_and_stale_stage_submit(env):
    root, svc = env
    FakeBackend(root, svc)
    st = stage_parts(["a.SLDPRT"])
    assert client.delete(f"/api/reverse/stage/{st['stage_id']}").json() == {"ok": True}
    assert client.delete(f"/api/reverse/stage/{st['stage_id']}").status_code == 404
    assert client.post("/api/reverse/jobs", json={"stage_id": st["stage_id"]}).status_code == 404
