"""FastAPI exposure of the SolidWorks build recording ("Record Pipeline Run")."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("imageio_ffmpeg")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation"
os.environ.setdefault("MCAGENT_REPO", str(REPO))
os.environ.setdefault("MCAGENT_DATA", tempfile.mkdtemp(prefix="mcagent_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
sys.path.insert(0, str(REPO))
import app as appmod  # noqa: E402
from pipeline import solidworks_recorder as rec  # noqa: E402

SESSION = "t" + "8" * 11
client = TestClient(appmod.app)


class Src(rec.FrameSource):
    name = "fake"

    def latest(self):
        return np.full((120, 200, 3), 130, np.uint8), False


def _part(name, *, record=True, sha=""):
    """A part whose recording was produced by the REAL recorder (synthetic frames)."""
    sdir = appmod._session_dir(SESSION)
    (sdir / appmod.ORIGINALS_DIRNAME).mkdir(parents=True, exist_ok=True)
    out = sdir / name / "output"
    out.mkdir(parents=True, exist_ok=True)
    (sdir / appmod.ORIGINALS_DIRNAME / f"{name}.pdf").write_bytes(b"%PDF-1.4 test")
    if record:
        r = rec.SolidWorksRecorder(out, part=name, run_id="run_r", source_sha256=sha, fps=10, paced=False, hold_s=0,
                                   source_factory=lambda h: Src())
        r.start()
        time.sleep(0.3)
        r.after_feature("F001", "prism", "built")
        time.sleep(0.4)
        r.stop()
    return out


def test_recording_is_in_the_part_payload_without_absolute_paths():
    out = _part("ZZREC1")
    cat = appmod._categorize_output(out, session=SESSION)["categories"]["recording"]
    assert cat["present"] and cat["status"] == "ready" and cat["has_video"] and cat["has_poster"]
    assert cat["media_type"] in ("video/mp4", "video/webm") and cat["chapters"][0]["id"] == "F001"
    blob = json.dumps(cat)
    assert str(out) not in blob and ":\\" not in blob and "/Users" not in blob


def test_not_recorded_part_has_no_recording():
    out = _part("ZZREC2", record=False)
    cat = appmod._categorize_output(out, session=SESSION)["categories"]["recording"]
    assert cat == {"present": False, "status": "none"}
    assert client.get(f"/api/parts/{SESSION}/ZZREC2/recording.video").status_code == 404


def test_manifest_etag_video_range_download_and_poster():
    _part("ZZREC3")
    base = f"/api/parts/{SESSION}/ZZREC3"
    r = client.get(f"{base}/recording")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    etag = r.headers["etag"]
    assert client.get(f"{base}/recording", headers={"If-None-Match": etag}).status_code == 304
    v = client.get(f"{base}/recording.video")
    assert v.status_code == 200 and v.headers["content-type"] in ("video/mp4", "video/webm") and len(v.content) > 500
    assert v.headers["content-disposition"].startswith("inline")
    part = client.get(f"{base}/recording.video", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100          # seeking works
    d = client.get(f"{base}/recording.video?download=true")
    assert d.headers["content-disposition"].startswith("attachment")
    p = client.get(f"{base}/recording-poster.jpg")
    assert p.status_code == 200 and p.headers["content-type"] == "image/jpeg" and p.content[:2] == b"\xff\xd8"


def test_failed_recording_reports_its_code_and_serves_no_video():
    out = _part("ZZREC4", record=False)
    rec.write_skipped(out, run_id="r", part="ZZREC4", reason="Extraction failed")
    cat = client.get(f"/api/parts/{SESSION}/ZZREC4/recording").json()
    assert cat["status"] == "skipped" and cat["code"] == "REC_NOT_REACHED" and not cat["has_video"]
    assert client.get(f"/api/parts/{SESSION}/ZZREC4/recording.video").status_code == 404
    assert client.get(f"/api/parts/{SESSION}/ZZREC4/recording-poster.jpg").status_code == 404


def test_recording_for_another_drawing_revision_is_stale_and_withheld():
    _part("ZZREC5", sha="a" * 64)
    # the current drawing's hash differs from the one the recording was made for
    cat = appmod._categorize_output(appmod._session_dir(SESSION) / "ZZREC5" / "output", session=SESSION)["categories"]["recording"]
    assert cat["status"] == "stale" and cat["has_video"] is False
    assert client.get(f"/api/parts/{SESSION}/ZZREC5/recording.video").status_code == 404


def test_unfinished_recording_with_no_live_run_is_interrupted():
    out = _part("ZZREC6", record=False)
    rec.write_manifest(out, {"status": "recording", "run_id": "r", "part": "ZZREC6", "frames": 3})
    cat = client.get(f"/api/parts/{SESSION}/ZZREC6/recording").json()
    assert cat["status"] == "interrupted" and cat["code"] == "REC_INTERRUPTED"


def test_a_manifest_cannot_point_the_server_at_another_file():
    out = _part("ZZREC7")
    m = json.loads((out / rec.MANIFEST).read_text())
    m["video"] = "../../etc/passwd"
    (out / rec.MANIFEST).write_text(json.dumps(m))
    assert client.get(f"/api/parts/{SESSION}/ZZREC7/recording.video").status_code == 404
    m["video"] = "ir_report.json"
    (out / rec.MANIFEST).write_text(json.dumps(m))
    assert client.get(f"/api/parts/{SESSION}/ZZREC7/recording.video").status_code == 404


def test_capability_endpoint_shape():
    c = client.get("/api/recording/capability").json()
    assert set(c) == {"available", "backend", "encoder", "reason"}
    assert c["available"] is True or c["reason"]


@pytest.mark.parametrize("record,available,expect_flag", [(True, True, True), (False, True, False), (True, False, False)])
def test_run_part_passes_record_only_when_asked_and_possible(monkeypatch, record, available, expect_flag):
    _part("ZZREC8", record=False)
    seen = {}
    monkeypatch.setattr(appmod, "_has_api_key", lambda: True)
    monkeypatch.setattr(appmod, "_recording_capability",
                        lambda: {"available": available, "backend": "wgc", "encoder": "h264", "reason": "" if available else "no"})
    monkeypatch.setattr(appmod, "_start_run", lambda cmd, out, **kw: seen.setdefault("cmd", cmd) and "rid123")
    form = {"session": SESSION, "part": "ZZREC8"}
    if record:
        form["record"] = "true"
    r = client.post("/api/run-part", data=form)
    assert r.status_code == 200 and r.json()["id"] == "rid123"
    assert ("--record-solidworks" in seen["cmd"]) is expect_flag
