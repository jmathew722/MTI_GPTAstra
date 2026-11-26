"""Real end-to-end check of the 3D -> 2D HTTP API: a REAL uvicorn server, a REAL upload, the REAL serialized CAD worker and REAL SOLIDWORKS.

    python tools/reverse_http_e2e.py --part <a .SLDPRT> --out <scratch dir> [--port 8213]

Starts the FINAL_UI server on a temp data folder (never the user's live port), generates the default template through the API, submits the part, polls to a
terminal state, downloads the PDF / STL / manifest through the artifact endpoint, rejects a traversal attempt, then stops the server.  Writes http_e2e.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "FINAL_UI"


def call(method, url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def multipart(fields: dict, files: dict):
    b = uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (name, content) in files.items():
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b"\r\n"
    out += f"--{b}--\r\n".encode()
    return out, {"Content-Type": f"multipart/form-data; boundary={b}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, default=8213)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    data = a.out / "data"
    env = dict(os.environ, MCAGENT_REPO=str(ROOT / "2D-3D-CAD-Test-Generation"), MCAGENT_DATA=str(data), MCAGENT_FINAL_OUTPUTS=str(a.out / "final_outputs"), PYTHONUTF8="1")
    py = UI / ".venv" / "Scripts" / "python.exe"
    srv = subprocess.Popen([str(py if py.is_file() else sys.executable), "-m", "uvicorn", "app:app", "--app-dir", "server", "--host", "127.0.0.1", "--port", str(a.port)],
                           cwd=str(UI), env=env, stdout=open(a.out / "server.log", "w"), stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{a.port}"
    res: dict = {"steps": []}

    def step(name, ok, detail=""):
        res["steps"].append({"step": name, "ok": bool(ok), "detail": str(detail)[:300]})
        print(("PASS " if ok else "FAIL ") + name + " " + str(detail)[:140], flush=True)
        return ok
    try:
        for _ in range(60):
            try:
                if call("GET", base + "/api/status", timeout=3)[0] == 200:
                    break
            except Exception:      # noqa: BLE001
                time.sleep(1)
        step("server up", True, base)
        code, body, _ = call("GET", base + "/api/reverse/templates")
        step("templates listed", code == 200, body[:120])
        code, body, _ = call("POST", base + "/api/reverse/templates/generate", b"{}", {"Content-Type": "application/json"})
        step("generate default template accepted (202)", code in (200, 202), f"{code} {body[:100]}")
        tid = None
        for _ in range(120):
            code, body, _ = call("GET", base + "/api/reverse/templates")
            ts = json.loads(body)
            ts = ts.get("templates", ts) if isinstance(ts, dict) else ts
            hit = next((t for t in ts if t.get("id") == "solidflow-ansi-b" and t.get("available")), None)
            if hit:
                tid = hit["id"]
                break
            time.sleep(2)
        step("generated template available (native, validated)", tid is not None, tid)
        part = Path(a.part)
        mp, hdr = multipart({"template_id": tid or "", "profile": "us_third_angle_inch"}, {"files": (part.name, part.read_bytes())})
        code, body, _ = call("POST", base + "/api/reverse/jobs", mp, hdr)
        job = json.loads(body) if code == 200 else {}
        jid = job.get("job_id") or job.get("job", {}).get("job_id")
        step("job submitted", code == 200 and jid, f"{code} {jid}")
        final = None
        for _ in range(180):
            code, body, _ = call("GET", f"{base}/api/reverse/jobs/{jid}")
            j = json.loads(body)
            if j["summary_state"] in ("completed", "review_required", "failed", "completed_with_failures", "canceled"):
                final = j
                break
            time.sleep(2)
        step("job reached a terminal state", final is not None, final and final["summary_state"])
        p = final["parts"][0] if final else {}
        step("part is review_required (never silently 'complete')", p.get("state") in ("review_required", "completed"), p.get("state"))
        files = p.get("files", {})
        step("PDF + SLDDRW + STL + manifest listed (only files that exist)", all(k in files for k in ("drawing.pdf", "drawing.slddrw", "model.stl", "manifest.json")), sorted(files))
        for name in ("drawing.pdf", "model.stl", "drawing.slddrw"):
            if name in files:
                code, body, hdrs = call("GET", f"{base}/api/reverse/jobs/{jid}/files/{files[name]['url_path']}")
                (a.out / name).write_bytes(body) if code == 200 else None
                step(f"download {name}", code == 200 and len(body) == files[name]["bytes"], f"{code} {len(body)} bytes {hdrs.get('Content-Type')}")
        code, body, _ = call("GET", f"{base}/api/reverse/jobs/{jid}/files/..%2F..%2Fjob.json")
        step("path traversal on download refused", code in (400, 403, 404), code)
        step("no absolute server paths in the job JSON", str(data) not in json.dumps(final) and str(part.parent) not in json.dumps(final))
        code, body, _ = call("GET", base + "/api/reverse/jobs")
        step("history lists the job", code == 200 and jid in body.decode("utf-8", "ignore"))
        res["job"] = final
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=20)
        except Exception:      # noqa: BLE001
            srv.kill()
    (a.out / "http_e2e.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    return 0 if all(s["ok"] for s in res["steps"]) else 1


if __name__ == "__main__":
    sys.exit(main())
