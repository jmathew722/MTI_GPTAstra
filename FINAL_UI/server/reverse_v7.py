"""v7 additions to the 3D -> 2D HTTP surface: reference-drawing routes (stage parts, find / confirm / upload a reference PDF), the reference
payload carried by job submission, and run/part/artifact-bound export downloads (SLDDRW, PDF, ZIP).

Owns NO CAD logic and no reference matching: everything is asked of reverse.service.ReverseService (see docs/solidflow-upgrades/V7_CONTRACT.md).
A capability the running backend does not have is reported by GET /api/reverse/capabilities and answered with 501, never faked.

Safety rules (same as reverse_api): ids are validated, the server resolves every path, an absolute path or the OpenAI key never reaches the browser,
uploads are size capped and signature checked, and a download is served only for an artifact that the job lists for that part.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

MAX_REFERENCE_BYTES = 50 * 1024 * 1024
STAGE_TTL_S = 6 * 3600
MAX_STAGE_PARTS = 200
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
KEY_RE = re.compile(r"^p\d{1,4}$")
ARTIFACT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,99}$")
SOURCES = ("auto", "upload", "artifact", "none")
CANDIDATE_KEYS = ("artifact_id", "filename", "project", "run", "date", "pages", "confidence", "reasons", "needs_confirmation", "link")

_STAGES: dict[str, dict] = {}            # stage_id -> {created, parts: {key: {name, path, size, owned, config, candidates, confirmed}}}
_SLOCK = threading.RLock()


# ------------------------------------------------------------------ capabilities

def capabilities(svc) -> dict:
    sig = None
    try:
        sig = inspect.signature(svc.submit).parameters
    except (TypeError, ValueError):
        pass
    submit_ref = bool(sig and "reference" in sig)
    cand = callable(getattr(svc, "reference_candidates", None))
    up = callable(getattr(svc, "save_reference_pdf", None))
    return {
        "reference": submit_ref,                 # submit() accepts a reference payload
        "candidates": submit_ref and cand,       # auto-find / saved-source lookup
        "upload": submit_ref and up,             # manual reference PDF upload
        "confirm": callable(getattr(svc, "confirm_reference_link", None)),
        "export": True,
        "report": True,                          # v8: the validation report (JSON) is an export kind
        "estimate": callable(getattr(svc, "estimate_run", None)),     # v8: pre-run estimate with cost (ReverseService.estimate_run)
        "limits": {"reference_pdf_bytes": MAX_REFERENCE_BYTES, "reference_pdf_pages": 20},
    }


def _need(svc, key: str, what: str) -> None:
    caps = capabilities(svc)
    if not caps.get(key):
        raise HTTPException(501, f"{what} is not available in this backend build.")


# ------------------------------------------------------------------ staging

def _sweep(api) -> None:
    now = time.time()
    with _SLOCK:
        for sid in [s for s, v in _STAGES.items() if now - v["created"] > STAGE_TTL_S]:
            _drop_stage(sid)


def _drop_stage(sid: str) -> None:
    st = _STAGES.pop(sid, None)
    if st and st.get("dir"):
        shutil.rmtree(st["dir"], ignore_errors=True)


def _stage_or_404(sid: str) -> dict:
    if not isinstance(sid, str) or not re.match(r"^s_[0-9a-f]{12}$", sid):
        raise HTTPException(400, "Invalid stage id.")
    with _SLOCK:
        st = _STAGES.get(sid)
    if st is None:
        raise HTTPException(404, "That part selection has expired. Choose the parts again.")
    return st


def _public_cand(c: dict) -> dict:
    return {k: c.get(k) for k in CANDIDATE_KEYS if k in c}


def _lookup(api, svc, st: dict, key: str) -> dict:
    info = st["parts"].get(key)
    if info is None:
        raise HTTPException(404, "Unknown part in this selection.")
    res = svc.reference_candidates(Path(info["path"]), info.get("config") or "")
    res = res if isinstance(res, dict) else {}
    cands = [_public_cand(c) for c in (res.get("candidates") or []) if isinstance(c, dict) and ARTIFACT_RE.match(str(c.get("artifact_id") or ""))]
    sel = res.get("selected")
    sel = _public_cand(sel) if isinstance(sel, dict) and ARTIFACT_RE.match(str(sel.get("artifact_id") or "")) else None
    if sel and not any(c.get("artifact_id") == sel["artifact_id"] for c in cands):
        cands.insert(0, sel)
    info["candidates"] = {c["artifact_id"]: c for c in cands}
    out = {"key": key, "name": info["name"], "selected": sel, "candidates": cands}
    if res.get("error"):
        out["error"] = api.scrub(str(res["error"]))[:300]
    part = res.get("part") or {}
    if isinstance(part, dict) and part.get("sha256"):
        out["part_sha256"] = str(part["sha256"])[:16]
    return out


# ------------------------------------------------------------------ reference payload -> backend payload

def translate_reference(api, svc, raw: Any, stage: Optional[dict], key_to_path: dict) -> Optional[dict]:
    """Browser payload -> the backend's `reference` dict. Server paths are looked up here; the browser only ever names ids."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "The reference settings are not valid JSON.")
    if not isinstance(raw, dict):
        raise HTTPException(400, "The reference settings must be an object.")
    mode = raw.get("mode", "standard")
    if mode not in ("standard", "match"):
        raise HTTPException(400, "Reference mode must be 'standard' or 'match'.")
    if mode == "standard":
        return None
    caps = capabilities(svc)
    if not caps["reference"]:
        raise HTTPException(501, "Reference matching is not available in this backend build. Run in Standard mode.")
    per_in = raw.get("per_part") or {}
    if not isinstance(per_in, dict):
        raise HTTPException(400, "per_part must be an object.")
    per_out: dict = {}
    for key, path in key_to_path.items():
        spec = per_in.get(key) or {"source": "auto"}
        if not isinstance(spec, dict):
            raise HTTPException(400, "Each per_part entry must be an object.")
        source = spec.get("source", "auto")
        if source not in SOURCES:
            raise HTTPException(400, "Unknown reference source.")
        ent: dict = {"source": source}
        if source == "upload":
            sha = str(spec.get("upload_id") or "")
            if not SHA_RE.match(sha):
                raise HTTPException(400, "Upload the reference PDF again (its upload id is not valid).")
            pdf = reference_dir(api) / f"{sha}.pdf"
            if not pdf.is_file():
                raise HTTPException(409, "The uploaded reference PDF is no longer on the server. Upload it again.")
            ent["pdf_path"] = str(pdf)
        elif source == "artifact":
            aid = str(spec.get("artifact_id") or "")
            known = ((stage or {}).get("parts", {}).get(key) or {}).get("candidates") or {}
            if aid not in known:
                raise HTTPException(409, "That saved source was not offered for this part. Find references again.")
            cand = known[aid]
            conf = ((stage or {}).get("parts", {}).get(key) or {}).get("confirmed") or set()
            if cand.get("needs_confirmation") and aid not in conf:
                raise HTTPException(409, "Confirm the saved source for this part before running.")
            ent["artifact_id"] = aid
        per_out[str(path)] = ent
    return {"mode": "match", "fallback_standard": bool(raw.get("fallback_standard")), "per_part": per_out}


def reference_dir(api) -> Path:
    return api._upload_root() / "reference"


# ------------------------------------------------------------------ export

PART_OK = ("completed", "review_required", "failed")
ART = {"slddrw": ("drawing.slddrw", "slddrw"), "pdf": ("drawing.pdf", "pdf"),
       "report": ("replication/report.json", "qa.json", "verification.json")}      # v8: the validation report (replication report first, then the QA record)
MIME = {"slddrw": "application/octet-stream", "pdf": "application/pdf", "zip": "application/zip", "report": "application/json"}
KINDS = ("slddrw", "pdf", "report", "zip")


def _part_view(svc, job_id: str, part_id: str) -> dict:
    try:
        for p in svc.job_view(job_id).get("parts", []):
            if p.get("part_id") == part_id:
                return p
    except Exception:      # noqa: BLE001
        pass
    return {}


def _artifact_rel(part, kind: str) -> Optional[str]:
    for name in ART[kind]:
        rel = (part.artifacts or {}).get(name)
        if rel:
            return rel
    return None


def _resolve(api, svc, job, part, kind: str) -> Optional[Path]:
    rel = _artifact_rel(part, kind)
    if not rel:
        return None
    from reverse import safety
    try:
        return svc.artifact_path(job.job_id, rel)
    except safety.SafetyError:
        return None


def export_status(part_state: str, review_status: str, verification: Optional[dict], replication: Optional[dict] = None) -> dict:
    """Pure: the draft / review status of a drawing and whether downloading it needs an explicit acknowledgement. Never says 'approved'.
    `replication` (v8, V8_CONTRACT section 3) can only make a drawing 'verified' when the backend says so AND nothing else is open; it never
    relaxes a failed or review-required v7 verification."""
    ver = (verification or {}).get("status") if isinstance(verification, dict) else None
    rep = (replication or {}).get("status") if isinstance(replication, dict) else None
    reasons: list[str] = []
    if ver == "failed":
        reasons.append("Verification failed for this drawing.")
    elif ver == "review_required":
        reasons.append("Verification found items that need engineering review.")
    elif ver in (None, "", "not_run", "pending", "unknown"):
        reasons.append("Verification was not completed for this drawing.")
    if part_state == "review_required" and ver != "review_required":
        reasons.append("The run finished with review required.")
    if part_state == "failed" and ver != "failed":
        reasons.append("The run did not finish cleanly.")
    if review_status == "required":
        reasons.append("Engineering review is still open.")
    why = str((replication or {}).get("reason") or "").strip()[:200] if isinstance(replication, dict) else ""
    if rep == "needs_review":
        reasons.append("The drawing does not fully match the source drawing" + (": " + why if why else "."))
    elif rep == "blocked":
        reasons.append("Matching the source drawing was blocked" + (": " + why if why else "."))
    elif rep == "failed":
        reasons.append("Matching the source drawing failed" + (": " + why if why else "."))
    elif rep == "pending":
        reasons.append("Matching the source drawing is not finished.")
    if ver == "failed" or part_state == "failed" or rep == "failed":
        key, label, tone = "failed", "Draft: verification failed", "red"
    elif reasons:
        key, label, tone = "review_required", "Draft: review required", "amber"
    elif rep == "verified":
        key, label, tone = "verified", "Verified against the source drawing (not an engineering approval)", "green"
    else:
        key, label, tone = "draft", "Draft: for review (not approved for manufacture)", "blue"
    return {"key": key, "label": label, "tone": tone, "requires_ack": bool(reasons), "reasons": reasons, "verification": ver or "not_run", "replication": rep or None}


def _safe_stem(name: str, fallback: str) -> str:
    stem = os.path.splitext(re.split(r"[\\/]", name or "")[-1])[0]
    stem = re.sub(r"[^A-Za-z0-9_.\- ]+", "_", stem).strip(" ._")
    return (stem or fallback)[:80]


def export_info(api, svc, job_id: str, part_id: str) -> dict:
    job = api._job_or_404(svc, job_id)
    api._check_id(part_id, "part id")
    try:
        part = job.part(part_id)
    except KeyError:
        raise HTTPException(404, "No such part in this run.")
    view = _part_view(svc, job_id, part_id)
    st = export_status(part.state, part.review_status, view.get("verification"), view.get("replication"))
    stem = _safe_stem(part.name, part.part_id)
    out: dict = {"job_id": job_id, "part_id": part_id, "part_state": part.state, "job_state": job.summary_state(), "status": st, "downloads": {}}
    gate = ""
    if part.state == "canceled":
        gate = "This part was canceled; nothing was exported."
    elif part.state not in PART_OK:
        gate = "The run for this part has not finished."
    missing = {"slddrw": "The native drawing was not produced for this part.", "pdf": "The drawing PDF was not produced for this part.",
               "report": "No validation report was written for this part."}
    for kind, fname in (("slddrw", f"{stem}-drawing.slddrw"), ("pdf", f"{stem}-drawing.pdf"), ("report", f"{stem}-validation-report.json")):
        fp = None if gate else _resolve(api, svc, job, part, kind)
        if gate:
            out["downloads"][kind] = {"available": False, "reason": gate}
        elif fp is None:
            out["downloads"][kind] = {"available": False, "reason": missing[kind]}
        else:
            out["downloads"][kind] = {"available": True, "bytes": fp.stat().st_size, "filename": fname}
    both = all(out["downloads"][k]["available"] for k in ("slddrw", "pdf"))
    out["downloads"]["zip"] = ({"available": True, "bytes": sum(out["downloads"][k]["bytes"] for k in ("slddrw", "pdf")), "filename": f"{stem}-drawing.zip"} if both else
                               {"available": False, "reason": gate or "Both the SLDDRW and the PDF must exist to package them."})
    return out


def _download(api, svc, job_id: str, part_id: str, kind: str, ack: str, expect: Optional[int]):
    if kind not in KINDS:
        raise HTTPException(404, "Unknown export.")
    info = export_info(api, svc, job_id, part_id)
    part_state = info["part_state"]
    if part_state == "canceled":
        raise HTTPException(409, "This part was canceled; there is nothing to download.")
    if part_state not in PART_OK:
        raise HTTPException(409, "The run for this part has not finished yet.")
    d = info["downloads"][kind]
    if not d.get("available"):
        raise HTTPException(404, d.get("reason") or "That file is not available.")
    st = info["status"]
    if st["requires_ack"] and ack != "1":
        raise HTTPException(409, "Acknowledge that this is an unapproved draft before downloading. " + " ".join(st["reasons"]))
    if expect is not None and expect != d["bytes"]:
        raise HTTPException(409, "This file changed since the page was loaded. Refresh and try again.")
    job = api._job_or_404(svc, job_id)
    part = job.part(part_id)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store", "X-Drawing-Status": st["key"]}
    if kind in ("slddrw", "pdf", "report"):
        fp = _resolve(api, svc, job, part, kind)
        if fp is None:
            raise HTTPException(404, "That file is not available.")
        return FileResponse(fp, media_type=MIME[kind], content_disposition_type="attachment", filename=d["filename"], headers=headers)
    files = {k: _resolve(api, svc, job, part, k) for k in ("slddrw", "pdf")}
    if any(v is None for v in files.values()):
        raise HTTPException(404, "Both the SLDDRW and the PDF must exist to package them.")
    tmp_dir = api._data() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="export_", suffix=".zip", dir=str(tmp_dir))
    os.close(fd)
    stem = d["filename"][: -len(".zip")].rsplit("-drawing", 1)[0]
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(files["slddrw"], f"{stem}-drawing.slddrw")
            z.write(files["pdf"], f"{stem}-drawing.pdf")
    except Exception:      # noqa: BLE001
        Path(tmp).unlink(missing_ok=True)
        raise HTTPException(500, "The archive could not be built.")
    return FileResponse(tmp, media_type=MIME["zip"], content_disposition_type="attachment", filename=d["filename"], headers=headers,
                        background=BackgroundTask(lambda: Path(tmp).unlink(missing_ok=True)))


# ------------------------------------------------------------------ v8: pre-run estimate

def _legacy_total(svc, n: int, mode: str, caps: dict) -> dict:
    """An <Estimate> (V8_CONTRACT section 1) built only from what the legacy history estimate knows: a duration range and nothing else.
    Cost is a real zero only for Standard mode (that path makes no model call); for match mode it is unavailable (null), never 0."""
    legacy = None
    try:
        legacy = svc.estimate(n)
    except Exception:      # noqa: BLE001
        legacy = None
    dur = None
    if isinstance(legacy, dict) and legacy.get("available") and isinstance(legacy.get("low_s"), (int, float)) and isinstance(legacy.get("high_s"), (int, float)):
        dur = {"low_s": legacy["low_s"], "expected_s": None, "high_s": legacy["high_s"], "source": "history", "basis": str(legacy.get("basis") or "")}
    if mode == "standard":
        cost = {"low": 0, "expected": 0, "high": 0, "currency": "USD", "rate_version": None, "model": None, "unavailable_reason": None}
        note = "Standard mode makes no model call: local CAD only, no token cost."
    else:
        why = ("Choose the parts and their references to estimate the OpenAI cost." if caps.get("estimate")
               else "This backend build cannot estimate the OpenAI cost before a run.")
        cost = {"low": None, "expected": None, "high": None, "currency": "USD", "rate_version": None, "model": None, "unavailable_reason": why}
        note = ""
    return {"duration": dur, "cost": cost, "tokens": None, "by_stage": {}, "assumptions": [note] if note else [], "labels": [] if dur else ["no_duration_history"]}


def build_estimate(api, svc, body: dict) -> dict:
    """Pre-run estimate for the 3D -> 2D page. Uses ReverseService.estimate_run when the backend has it and the parts are staged on the server (match mode);
    otherwise a history-only duration. Makes no model call and starts nothing."""
    caps = capabilities(svc)
    try:
        n = max(1, min(1000, int(body.get("count") or 1)))
    except (TypeError, ValueError):
        raise HTTPException(400, "count must be a number.")
    ref_in = body.get("reference")
    if isinstance(ref_in, str):
        try:
            ref_in = json.loads(ref_in)
        except ValueError:
            raise HTTPException(400, "The reference settings are not valid JSON.")
    if ref_in is not None and not isinstance(ref_in, dict):
        raise HTTPException(400, "The reference settings must be an object.")
    mode = (ref_in or {}).get("mode", "standard")
    if mode not in ("standard", "match"):
        raise HTTPException(400, "Reference mode must be 'standard' or 'match'.")
    out: dict = {"schema_version": 1, "mode": mode, "count": n, "source": "history", "total": None, "parts": [], "budget": None, "model": None}
    sid = str(body.get("stage_id") or "")
    keys = body.get("keys")
    if caps["estimate"] and sid:
        st = _stage_or_404(sid)
        want = [k for k in st["parts"] if keys is None or k in keys]
        if any(not KEY_RE.match(k) for k in want):
            raise HTTPException(400, "Invalid part key.")
        if want:
            key_to_path = {k: st["parts"][k]["path"] for k in want}
            try:
                ref = translate_reference(api, svc, ref_in, st, key_to_path)
            except HTTPException:
                ref = {"mode": "match", "fallback_standard": False, "per_part": {}} if mode == "match" else None      # choices not final yet: estimate with automatic lookup
            by_path = {str(v): k for k, v in key_to_path.items()}
            try:
                res = svc.estimate_run([Path(v) for v in key_to_path.values()], ref)
            except Exception as e:      # noqa: BLE001
                res = None
                out["error"] = str(api.scrub(str(e)))[:300] or "The estimate could not be computed."
            if isinstance(res, dict) and isinstance(res.get("total"), dict):
                parts = []
                for p in res.get("parts") or []:
                    if isinstance(p, dict):
                        q = dict(p)
                        q["part"] = by_path.get(str(p.get("part")), "")
                        parts.append(q)
                out.update(source="estimate_run", total=res["total"], parts=parts, budget=res.get("budget"), model=res.get("model"))
                return api.scrub(out)
    out["total"] = _legacy_total(svc, n, mode, caps)
    return api.scrub(out)


# ------------------------------------------------------------------ routes

def add_routes(r, api) -> None:
    @r.get("/capabilities")
    def caps():
        return capabilities(api.service())

    @r.post("/estimate")
    async def estimate_post(request: Request):
        svc = api.service()
        try:
            body = await request.json()
        except Exception:      # noqa: BLE001
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(400, "Send JSON {count, reference?, stage_id?, keys?}.")
        return await run_in_threadpool(lambda: build_estimate(api, svc, body))

    # ---- staging: parts are uploaded once, then candidates are looked up and the job is submitted from the stage
    @r.post("/stage")
    async def stage(request: Request):
        svc = api.service()
        _need(svc, "candidates", "Reference lookup")
        _sweep(api)
        ctype = (request.headers.get("content-type") or "").lower()
        parts: dict = {}
        base: Optional[Path] = None
        sid = "s_" + uuid.uuid4().hex[:12]
        cfg = ""
        if ctype.startswith("multipart/"):
            form = await request.form()
            cfg = (form.get("config") or "").strip()
            files = [f for f in form.getlist("files") if hasattr(f, "filename")]
            if not files:
                raise HTTPException(400, "Choose one or more SOLIDWORKS parts (.SLDPRT).")
            if len(files) > MAX_STAGE_PARTS:
                raise HTTPException(400, f"At most {MAX_STAGE_PARTS} parts.")
            from reverse import safety
            base = api._upload_root() / ("u_" + uuid.uuid4().hex[:12])
            for i, f in enumerate(files):
                name = api._safe_filename(f.filename or "")
                if os.path.splitext(name)[1].lower() != ".sldprt" or re.split(r"[\\/]", f.filename or "")[-1].startswith("~$"):
                    continue
                dest = base / str(i) / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                total, big = 0, False
                with open(dest, "wb") as out:
                    while True:
                        chunk = await f.read(1 << 20)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > api.MAX_PART_UPLOAD_BYTES:
                            big = True
                            break
                        out.write(chunk)
                if big:
                    dest.unlink(missing_ok=True)
                    continue
                parts[f"p{i}"] = {"name": name, "path": str(dest), "size": total, "owned": True, "config": cfg}
        else:
            try:
                body = await request.json()
            except Exception:      # noqa: BLE001
                raise HTTPException(400, "Send multipart files or a JSON body {folder, recursive}.")
            from reverse import safety
            if not isinstance(body, dict) or not isinstance(body.get("folder"), str):
                raise HTTPException(400, "A JSON stage needs a 'folder'.")
            cfg = str(body.get("config") or "").strip()
            try:
                folder = safety.authorize(body["folder"], api.authorized_roots())
            except safety.SafetyError as e:
                raise HTTPException(400, str(e))
            if not folder.is_dir():
                raise HTTPException(400, "That folder was not found.")
            for i, p in enumerate(safety.discover_parts(folder, bool(body.get("recursive")))[:MAX_STAGE_PARTS]):
                parts[f"p{i}"] = {"name": p.name, "path": str(p), "size": p.stat().st_size if p.exists() else None, "owned": False, "config": cfg}
        if not parts:
            raise HTTPException(400, "No valid SOLIDWORKS parts were found.")
        with _SLOCK:
            _STAGES[sid] = {"created": time.time(), "parts": parts, "dir": str(base) if base else None}
        return {"stage_id": sid, "parts": [{"key": k, "name": v["name"], "size": v["size"]} for k, v in parts.items()]}

    @r.delete("/stage/{stage_id}")
    def drop_stage(stage_id: str):
        _stage_or_404(stage_id)
        with _SLOCK:
            _drop_stage(stage_id)
        return {"ok": True}

    @r.post("/reference/candidates")
    async def candidates(request: Request):
        svc = api.service()
        _need(svc, "candidates", "Reference lookup")
        try:
            body = await request.json()
        except Exception:      # noqa: BLE001
            body = None
        if not isinstance(body, dict):
            raise HTTPException(400, "Send JSON {stage_id, keys?}.")
        st = _stage_or_404(str(body.get("stage_id") or ""))
        keys = body.get("keys")
        keys = [k for k in st["parts"] if keys is None or k in keys] if keys is not None else list(st["parts"])
        if any(not KEY_RE.match(k) for k in keys):
            raise HTTPException(400, "Invalid part key.")
        rows = await run_in_threadpool(lambda: [_lookup(api, svc, st, k) for k in keys])
        return api.scrub({"stage_id": body["stage_id"], "rows": rows})

    @r.post("/reference/confirm")
    async def confirm(request: Request):
        svc = api.service()
        _need(svc, "candidates", "Reference lookup")
        try:
            body = await request.json()
        except Exception:      # noqa: BLE001
            body = None
        if not isinstance(body, dict):
            raise HTTPException(400, "Send JSON {stage_id, key, artifact_id}.")
        st = _stage_or_404(str(body.get("stage_id") or ""))
        key, aid = str(body.get("key") or ""), str(body.get("artifact_id") or "")
        info = st["parts"].get(key)
        if info is None:
            raise HTTPException(404, "Unknown part in this selection.")
        cand = (info.get("candidates") or {}).get(aid)
        if cand is None:
            raise HTTPException(409, "That saved source was not offered for this part. Find references again.")
        persisted = False
        conf = getattr(svc, "confirm_reference_link", None)
        if callable(conf):
            try:
                await run_in_threadpool(lambda: conf(Path(info["path"]), aid, info.get("config") or "", api._os_user()))
                persisted = True
            except Exception as e:      # noqa: BLE001
                raise HTTPException(409, str(api.scrub(str(e)))[:300] or "The link could not be saved.")
        info.setdefault("confirmed", set()).add(aid)
        return {"ok": True, "artifact_id": aid, "persisted": persisted, "candidate": cand}

    @r.post("/reference/upload")
    async def upload_reference(request: Request):
        svc = api.service()
        _need(svc, "upload", "Reference PDF upload")
        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "filename"):
            raise HTTPException(400, "Choose a PDF file.")
        name = api._safe_filename(f.filename or "")
        if os.path.splitext(name)[1].lower() != ".pdf":
            raise HTTPException(400, "Only PDF files are accepted as a reference drawing.")
        tmp_dir = api._upload_root() / "reference_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / (uuid.uuid4().hex + ".pdf")
        total = 0
        h = hashlib.sha256()
        try:
            with open(tmp, "wb") as out:
                first = True
                while True:
                    chunk = await f.read(1 << 20)
                    if not chunk:
                        break
                    if first:
                        first = False
                        if not chunk.startswith(b"%PDF-"):
                            raise HTTPException(400, "That file is not a PDF (the PDF signature is missing).")
                    total += len(chunk)
                    if total > MAX_REFERENCE_BYTES:
                        raise HTTPException(413, "The reference PDF is larger than 50 MB.")
                    h.update(chunk)
                    out.write(chunk)
            if total == 0:
                raise HTTPException(400, "The file is empty.")
            res = await run_in_threadpool(lambda: svc.save_reference_pdf(tmp))
        finally:
            tmp.unlink(missing_ok=True)
        if not isinstance(res, dict) or not res.get("ok"):
            raise HTTPException(400, api.scrub(str((res or {}).get("error") or "The PDF could not be read."))[:300])
        sha = str(res.get("sha256") or h.hexdigest())
        if not SHA_RE.match(sha):
            raise HTTPException(500, "The backend returned an unexpected reference id.")
        pdf_path = res.get("pdf_path")
        if pdf_path and Path(pdf_path).resolve() != (reference_dir(api) / f"{sha}.pdf").resolve():
            reference_dir(api).mkdir(parents=True, exist_ok=True)
            if not (reference_dir(api) / f"{sha}.pdf").is_file() and Path(pdf_path).is_file():
                shutil.copyfile(pdf_path, reference_dir(api) / f"{sha}.pdf")
        return {"upload_id": sha, "sha256": sha, "filename": name, "pages": res.get("pages"), "size": res.get("size", total), "artifact_id": res.get("artifact_id")}

    # ---- export
    @r.get("/jobs/{job_id}/parts/{part_id}/export")
    def export_state(job_id: str, part_id: str):
        return api.scrub(export_info(api, api.service(), job_id, part_id))

    @r.get("/jobs/{job_id}/parts/{part_id}/export/{kind}")
    def export_download(job_id: str, part_id: str, kind: str, ack: str = Query(""), expect: Optional[int] = Query(None, ge=0)):
        return _download(api, api.service(), job_id, part_id, kind, ack, expect)
