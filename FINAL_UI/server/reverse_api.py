"""3D -> 2D drawing generation: HTTP surface over reverse.service.ReverseService (the finished backend).

This module owns NO CAD logic. It
  * creates the one ReverseService (lazily; started by the app's startup hook, stopped on shutdown),
  * validates every id / path / upload, copies uploaded SLDPRT files into <data>/uploads/3d-to-2d/<id>/ (size capped, safe names),
  * serves job state, events and artifacts, and the audited engineering-review action,
  * never starts SOLIDWORKS itself (the status probe only looks for a running process) and never returns an absolute server path.

Wired from app.py with one install() call; the app module is passed in so folders that tests monkeypatch (DATA_DIR) are read at request time.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.concurrency import run_in_threadpool

MAX_PART_UPLOAD_BYTES = 500 * 1024 * 1024
MAX_FILES_PER_JOB = 200
MAX_TEMPLATE_BYTES = 25 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}$")
INLINE_EXT = {".pdf": "application/pdf", ".png": "image/png", ".stl": "model/stl"}
ATTACH_TYPES = {".json": "application/json", ".slddrw": "application/octet-stream", ".txt": "text/plain", ".log": "text/plain"}
MAX_EVENTS = 500

_APP = None
_LOCK = threading.RLock()
_SVC: dict = {"svc": None, "key": None}
_PROBE: dict = {"t": 0.0, "v": None}
_CANCEL_PENDING: set = set()           # job ids with a user cancel in flight (the worker re-saves its own copy of the job)
_TASK: dict = {"cur": None}          # the one template task (generate / validate) that may run at a time; it occupies the CAD worker

_WIN_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"<>|]*")
_POSIX_PATH = re.compile(r"(?<![\w.:/\\-])/(?:[\w.\-]+/)+[\w.\-]+")


# ------------------------------------------------------------------ plumbing

def _a():
    if _APP is None:
        raise RuntimeError("reverse_api is not initialised")
    return _APP


def _repo_on_path() -> None:
    repo = str(_a().PROJECT_DIR)
    if repo not in sys.path:
        sys.path.insert(0, repo)


def _data() -> Path:
    return Path(_a().DATA_DIR)


def _upload_root() -> Path:
    return _data() / "uploads" / "3d-to-2d"


def authorized_roots() -> list[Path]:
    """The upload area plus any folders the operator listed in SOLIDFLOW_REVERSE_ROOTS (os.pathsep separated). A browser cannot hand the
    server an arbitrary path, so a server-local folder is only usable when its root was authorised out of band by whoever runs the server."""
    roots = [_upload_root()]
    for raw in (os.environ.get("SOLIDFLOW_REVERSE_ROOTS", "") or "").split(os.pathsep):
        raw = raw.strip()
        if raw and Path(raw).is_absolute():
            roots.append(Path(raw))
    return roots


def service():
    """The ReverseService for the current data dir (re-created if the data dir changes, which only tests do)."""
    _repo_on_path()
    from reverse.service import ReverseService       # noqa: WPS433  (the repo is chosen at launch)
    key = str(_data())
    with _LOCK:
        if _SVC["svc"] is None or _SVC["key"] != key:
            if _SVC["svc"] is not None:
                try:
                    _SVC["svc"].stop()
                except Exception:      # noqa: BLE001
                    pass
            _upload_root().mkdir(parents=True, exist_ok=True)
            _SVC["svc"] = ReverseService(_data(), authorized_roots())
            _lock_store_reads(_SVC["svc"].store)
            _lock_catalog(_SVC["svc"].templates)
            _SVC["key"] = key
        else:
            _SVC["svc"].roots = authorized_roots()
        return _SVC["svc"]


def _lock_store_reads(store) -> None:
    """JobStore.save() replaces job.json under the store lock but load() reads it unlocked; on Windows a read during os.replace raises
    PermissionError (seen as a 500 on polled GETs and as a crash in the worker). Serialize loads with the same lock (backend gap, reported)."""
    orig = store.load

    def load(job_id):
        with store._lock:
            return orig(job_id)
    store.load = load
    orig_save = store.save

    def save(job):
        with store._lock:
            if not job.cancel_requested and job.job_id in _CANCEL_PENDING:
                job.cancel_requested = True          # the worker's in-memory copy must not erase a cancel the user asked for
            orig_save(job)
    store.save = save


def _lock_catalog(cat) -> None:
    """Same Windows read-during-replace race for templates/index.json (TemplateCatalog._load is unlocked): serialize load and save."""
    lock = threading.RLock()
    o_load, o_save = cat._load, cat._save

    def _load():
        with lock:
            return o_load()

    def _save(items):
        with lock:
            return o_save(items)
    cat._load, cat._save = _load, _save


def set_service(svc) -> None:
    """Test hook: use ``svc`` for every request (None restores the lazy default)."""
    with _LOCK:
        _SVC["svc"] = svc
        _SVC["key"] = str(_data()) if svc is not None else None


def scrub(v: Any) -> Any:
    """Remove absolute filesystem paths from any JSON-able value (error strings can carry them)."""
    if isinstance(v, str):
        v = _WIN_PATH.sub(lambda m: "<path>/" + re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1], v)
        return _POSIX_PATH.sub(lambda m: "<path>/" + m.group(0).rsplit("/", 1)[-1], v)
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [scrub(x) for x in v]
    return v


def _check_id(value: str, what: str = "id") -> str:
    if not isinstance(value, str) or not ID_RE.match(value):
        raise HTTPException(400, f"Invalid {what}.")
    return value


def _safe_filename(name: str) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    stem, ext = os.path.splitext(base)
    stem = re.sub(r"[^A-Za-z0-9_.\- ]+", "_", stem).strip(" ._") or "part"
    return stem[:80] + ext.lower()


def _job_or_404(svc, job_id: str):
    _check_id(job_id, "job id")
    try:
        return svc.store.load(job_id)
    except KeyError:
        raise HTTPException(404, "No such job.")


def _is_active(job) -> bool:
    return job.summary_state() in ("running", "queued")


def _sw_process_running() -> bool:
    """Is SLDWORKS.exe running? Never starts anything. Cached for 20 s."""
    now = time.time()
    if _PROBE["v"] is not None and now - _PROBE["t"] < 20:
        return bool(_PROBE["v"])
    ok = False
    if sys.platform == "win32":
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=5).stdout
            ok = "sldworks.exe" in out.lower()
        except (OSError, subprocess.SubprocessError):
            ok = False
    _PROBE.update(t=now, v=ok)
    return ok


def _solidworks_info(svc) -> dict:
    """Revision / SP from the newest job that actually connected; otherwise whether a SOLIDWORKS process is running. Never invented."""
    for j in svc.store.list():
        sw = j.solidworks or {}
        if sw.get("revision"):
            return {"detected": True, "source": "last_job", "revision": sw.get("revision", ""), "service_pack": sw.get("service_pack", ""), "is_2025": bool(sw.get("is_2025"))}
    running = _sw_process_running()
    return {"detected": True if running else False, "source": "process_probe", "revision": "", "service_pack": "", "is_2025": None,
            "note": "SOLIDWORKS is running; the revision is read when a job connects." if running else "No SOLIDWORKS process was found."}


def _task_view() -> Optional[dict]:
    t = _TASK["cur"]
    return None if t is None else {k: t[k] for k in ("id", "kind", "state", "error", "template_id", "label", "started", "ended") if k in t}


def _run_template_task(kind: str, label: str, fn) -> dict:
    """Run a blocking template call (it queues on the CAD worker, minutes) in a background thread; the UI polls GET /templates."""
    with _LOCK:
        cur = _TASK["cur"]
        if cur is not None and cur["state"] == "running":
            raise HTTPException(409, "Another template task is already running. Wait for it to finish.")
        task = {"id": uuid.uuid4().hex[:10], "kind": kind, "label": label, "state": "running", "error": "", "template_id": None, "started": time.time()}
        _TASK["cur"] = task

    def work():
        try:
            entry = fn()
            task["template_id"] = (entry or {}).get("id")
            task["state"] = "done"
        except Exception as e:      # noqa: BLE001
            task["state"] = "failed"
            task["error"] = str(scrub(f"{e}"))[:400] or type(e).__name__
        finally:
            task["ended"] = time.time()

    threading.Thread(target=work, name="reverse-template-task", daemon=True).start()
    return task


def _public_template(t: dict) -> dict:
    val = t.get("validation") or {}
    pv = t.get("preview_pdf")
    return {"has_preview": bool(pv and Path(pv).is_file()), "id": t.get("id"), "name": t.get("name"), "source": t.get("source"), "available": bool(t.get("available", True)), "own_sheet_format": bool(t.get("own_sheet_format")),
            "paper": t.get("paper"), "sha256": (t.get("sha256") or "")[:16],
            "validation": {"ok": val.get("ok") if val else None, "errors": scrub(val.get("errors", [])) if val else [], "views": val.get("views") if val else None}}


def _thumb(svc, job) -> Optional[dict]:
    for p in job.parts:
        files = svc.part_files(job, p)
        f = files.get("preview/page-001.png")
        if f:
            return {"part_id": p.part_id, "url_path": f["url_path"]}
    return None


# ------------------------------------------------------------------ router

def make_router(app_module) -> APIRouter:
    global _APP
    _APP = app_module
    r = APIRouter(prefix="/api/reverse", tags=["reverse"])

    @r.get("/profiles")
    def profiles():
        return {"profiles": service().profiles()}

    @r.get("/templates")
    def templates():
        svc = service()
        items = svc.templates.list()
        try:
            default = svc.templates.default()["id"]
        except Exception:      # noqa: BLE001
            default = None
        return {"templates": [_public_template(t) for t in items], "default_id": default, "task": _task_view(),
                "note": "A template is accepted only after SOLIDWORKS creates a drawing from it that references no model."}

    @r.post("/templates")
    async def upload_template(request: Request):
        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "filename"):
            raise HTTPException(400, "Choose a .drwdot template file.")
        name = _safe_filename(f.filename or "")
        if not name.lower().endswith(".drwdot"):
            raise HTTPException(400, "Only .drwdot drawing templates are accepted (a .slddrt sheet format needs a validated .drwdot).")
        data = await f.read(MAX_TEMPLATE_BYTES + 1)
        if not data or len(data) > MAX_TEMPLATE_BYTES:
            raise HTTPException(400, "The template file is empty or larger than 25 MB.")
        svc = service()
        validate = getattr(svc, "validate_template_async", None)
        if validate is None:
            raise HTTPException(501, "Template validation needs the CAD worker (not wired).")
        svc.start()
        tmp_dir = _upload_root() / "templates" / uuid.uuid4().hex[:12]
        tmp_dir.mkdir(parents=True, exist_ok=True)
        dest = tmp_dir / name

        def go():
            try:
                dest.write_bytes(data)
                return validate(dest, name)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        task = _run_template_task("validate", f"Validating {name}", go)
        return JSONResponse({"task": _task_view()}, status_code=202)

    @r.post("/templates/generate")
    async def generate_template(request: Request):
        try:
            body = await request.json()
        except Exception:      # noqa: BLE001
            body = {}
        key = str((body or {}).get("key") or "solidflow-ansi-b")
        if key not in ("solidflow-ansi-b", "solidflow-ansi-c", "solidflow-a3"):
            raise HTTPException(400, "Unknown template variant.")
        svc = service()
        gen = getattr(svc, "generate_template_async", None)
        if gen is None:
            raise HTTPException(501, "Template generation is not available in this backend.")
        svc.start()
        _run_template_task("generate", f"Generating {key}", lambda: gen(key))
        return JSONResponse({"task": _task_view()}, status_code=202)

    @r.get("/templates/{tid}/preview")
    def template_preview(tid: str):
        _check_id(tid, "template id")
        for t in service().templates.list():
            if t.get("id") == tid:
                pv = t.get("preview_pdf")
                if pv and Path(pv).is_file() and Path(pv).suffix.lower() == ".pdf":
                    return FileResponse(pv, media_type="application/pdf", content_disposition_type="inline", filename=f"{tid}-preview.pdf", headers={"X-Content-Type-Options": "nosniff"})
                break
        raise HTTPException(404, "No preview for that template.")

    @r.get("/estimate")
    def estimate(parts: int = Query(1, ge=1, le=1000)):
        return scrub(service().estimate(parts))

    @r.get("/status")
    def status():
        svc = service()
        q = getattr(svc.queue, "_q", [])
        return {"solidworks": _solidworks_info(svc), "queue_length": len(q), "current_job": svc.queue.current,
                "worker_running": bool(svc.queue._t and svc.queue._t.is_alive())}

    @r.get("/jobs")
    def list_jobs(limit: int = Query(100, ge=1, le=500)):
        svc = service()
        rows = []
        for j in svc.store.list()[:limit]:
            rows.append({"job_id": j.job_id, "kind": "reverse", "created": j.created, "updated": j.updated, "state": j.summary_state(), "template_id": j.template_id, "profile": j.profile,
                         "thumb": _thumb(svc, j), "solidworks": j.solidworks or {},
                         "parts": [{"part_id": p.part_id, "name": p.name, "config": p.config, "state": p.state, "coverage_pct": p.coverage_pct, "review_status": p.review_status,
                                    "seconds": p.seconds, "material": (p.material or {}).get("name")} for p in j.parts]})
        return scrub({"jobs": rows})

    @r.post("/jobs")
    async def submit_job(request: Request):
        svc = service()
        svc.start()
        ctype = (request.headers.get("content-type") or "").lower()
        template_id = profile = config = None
        paths: list[Path] = []
        pre_rejected: list[dict] = []
        if ctype.startswith("multipart/"):
            form = await request.form()
            template_id = (form.get("template_id") or "").strip() or None
            profile = (form.get("profile") or "").strip() or "us_third_angle_inch"
            config = (form.get("config") or "").strip()
            files = [f for f in form.getlist("files") if hasattr(f, "filename")]
            if not files:
                raise HTTPException(400, "Choose one or more SOLIDWORKS parts (.SLDPRT).")
            if len(files) > MAX_FILES_PER_JOB:
                raise HTTPException(400, f"At most {MAX_FILES_PER_JOB} files per job.")
            from reverse import safety
            up = _upload_root() / ("u_" + uuid.uuid4().hex[:12])
            for i, f in enumerate(files):
                name = _safe_filename(f.filename or "")
                ext = os.path.splitext(name)[1].lower()
                if re.split(r"[\/]", f.filename or "")[-1].startswith("~$"):
                    pre_rejected.append({"name": name, "reason": f"{name} is a SOLIDWORKS lock file, not a part."}); continue
                if ext in safety.REFUSED_EXT:
                    pre_rejected.append({"name": name, "reason": f"{name} is {safety.REFUSED_EXT[ext]}."}); continue
                if ext != ".sldprt":
                    pre_rejected.append({"name": name, "reason": f"{name} is not a SOLIDWORKS part (.SLDPRT)."}); continue
                dest = up / str(i) / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                total, too_big = 0, False
                with open(dest, "wb") as out:
                    while True:
                        chunk = await f.read(1 << 20)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_PART_UPLOAD_BYTES:
                            too_big = True
                            break
                        out.write(chunk)
                if too_big:
                    dest.unlink(missing_ok=True)
                    pre_rejected.append({"name": name, "reason": f"{name} is larger than 500 MB."}); continue
                paths.append(dest)
        else:
            try:
                body = await request.json()
            except Exception:      # noqa: BLE001
                raise HTTPException(400, "Send multipart files or a JSON body {folder, recursive}.")
            if not isinstance(body, dict) or not isinstance(body.get("folder"), str):
                raise HTTPException(400, "A JSON submission needs a 'folder'.")
            template_id = (body.get("template_id") or "").strip() or None
            profile = (body.get("profile") or "").strip() or "us_third_angle_inch"
            config = (body.get("config") or "").strip()
            from reverse import safety
            try:
                folder = safety.authorize(body["folder"], authorized_roots())
            except safety.SafetyError as e:
                raise HTTPException(400, str(e))
            if not folder.is_dir():
                raise HTTPException(400, "That folder was not found.")
            paths = safety.discover_parts(folder, bool(body.get("recursive")))[:MAX_FILES_PER_JOB]
            if not paths:
                raise HTTPException(400, "No .SLDPRT files were found in that folder" + (" (including subfolders)." if body.get("recursive") else "."))
        if len(config) > 80 or not re.match(r"^[^\x00-\x1f]*$", config):
            raise HTTPException(400, "Invalid configuration name.")
        if not paths:
            raise HTTPException(400, "No valid SOLIDWORKS parts: " + "; ".join(r["reason"] for r in pre_rejected))
        from reverse import safety, templates as tpl_mod
        try:
            job = await run_in_threadpool(lambda: svc.submit(part_paths=paths, template_id=template_id, profile=profile, configs={str(p): config for p in paths} if config else None))
        except (safety.SafetyError, tpl_mod.TemplateError) as e:
            raise HTTPException(400, str(scrub(str(e))))
        rej = list(job.options.get("rejected", [])) + pre_rejected
        if pre_rejected:
            job.options["rejected"] = rej
            svc.store.save(job)
        return scrub({"job_id": job.job_id, "rejected": rej, "parts": [{"part_id": p.part_id, "name": p.name} for p in job.parts]})

    @r.get("/jobs/{job_id}")
    def get_job(job_id: str):
        svc = service()
        _job_or_404(svc, job_id)
        return scrub(svc.job_view(job_id))

    @r.get("/jobs/{job_id}/events")
    def get_events(job_id: str, after: int = Query(0, ge=0)):
        svc = service()
        _job_or_404(svc, job_id)
        evs = svc.store.events(job_id, after)[:MAX_EVENTS]
        return scrub({"events": evs, "next": (evs[-1]["seq"] + 1) if evs else after})

    @r.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        svc = service()
        job = _job_or_404(svc, job_id)
        if not _is_active(job):
            raise HTTPException(409, "This job is not running or queued.")
        _CANCEL_PENDING.add(job_id)
        svc.cancel(job_id)
        return {"ok": True}

    @r.post("/jobs/{job_id}/retry")
    async def retry(job_id: str, request: Request):
        svc = service()
        job = _job_or_404(svc, job_id)
        if _is_active(job):
            raise HTTPException(409, "This job is still running. Retry after it finishes.")
        ids = None
        try:
            body = await request.json()
            if isinstance(body, dict) and isinstance(body.get("part_ids"), list):
                ids = [_check_id(str(x), "part id") for x in body["part_ids"]]
                known = {p.part_id for p in job.parts}
                if any(x not in known for x in ids):
                    raise HTTPException(404, "Unknown part.")
        except HTTPException:
            raise
        except Exception:      # noqa: BLE001
            ids = None
        from reverse import safety
        try:
            svc.start()
            _CANCEL_PENDING.discard(job_id)
            with svc.store._lock:                    # show "queued" at once instead of waiting for the worker to reach the part
                j2 = svc.store.load(job_id)
                for p in j2.parts:
                    if (ids is None and p.state in ("failed", "canceled")) or (ids is not None and p.part_id in ids):
                        p.state, p.error, p.stages, p.ended = "queued", "", {}, None
                svc.store.save(j2)
            svc.retry(job_id, ids or [p.part_id for p in job.parts if p.state in ("failed", "canceled")])
        except safety.SafetyError as e:
            raise HTTPException(409, str(e))
        return {"ok": True}

    @r.delete("/jobs/{job_id}")
    def delete_job(job_id: str):
        svc = service()
        job = _job_or_404(svc, job_id)
        from reverse import safety
        try:
            svc.delete_job(job_id)
        except safety.SafetyError as e:
            raise HTTPException(409, str(e))
        for p in job.parts:                         # the uploaded copy of the part goes with the job
            try:
                src = Path(p.source)
                if safety.is_within(_upload_root(), src) and src.parent.parent.parent == _upload_root().resolve():
                    shutil.rmtree(src.parent.parent, ignore_errors=True)
            except OSError:
                pass
        return {"ok": True}

    @r.get("/jobs/{job_id}/files/{rel:path}")
    def get_file(job_id: str, rel: str):
        svc = service()
        _job_or_404(svc, job_id)
        if not rel or rel.startswith(("/", "\\")) or "\\" in rel or "\x00" in rel or any(seg in ("..", ".", "") for seg in rel.split("/")):
            raise HTTPException(400, "Invalid file path.")
        from reverse import safety
        try:
            fp = svc.artifact_path(job_id, rel)
        except safety.SafetyError:
            raise HTTPException(404, "No such file.")
        ext = fp.suffix.lower()
        headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"}
        if ext in INLINE_EXT:
            return FileResponse(fp, media_type=INLINE_EXT[ext], content_disposition_type="inline", filename=fp.name, headers=headers)
        return FileResponse(fp, media_type=ATTACH_TYPES.get(ext, "application/octet-stream"), content_disposition_type="attachment", filename=fp.name, headers=headers)

    @r.post("/jobs/{job_id}/parts/{part_id}/review")
    async def review(job_id: str, part_id: str, request: Request):
        svc = service()
        job = _job_or_404(svc, job_id)
        _check_id(part_id, "part id")
        try:
            job.part(part_id)
        except KeyError:
            raise HTTPException(404, "No such part.")
        if _is_active(job):
            raise HTTPException(409, "The job is still running. Review after it finishes (a running job would overwrite the decision).")
        try:
            body = await request.json()
        except Exception:      # noqa: BLE001
            body = None
        if not isinstance(body, dict):
            raise HTTPException(400, "Send JSON {issue_id, action, note}.")
        issue_id, action, note = str(body.get("issue_id", "")), str(body.get("action", "")), str(body.get("note", ""))
        if len(note) > 2000 or len(issue_id) > 200:
            raise HTTPException(400, "The note or issue id is too long.")
        user = str(body.get("user") or "").strip()[:80] or _os_user()
        from reverse import safety
        try:
            res = svc.review_action(job_id, part_id, issue_id, action, user=user, note=note)
        except safety.SafetyError as e:
            msg = str(e)
            raise HTTPException(404 if msg == "Unknown issue." else 400, msg)
        return scrub(res)

    return r


def _os_user() -> str:
    try:
        return getpass.getuser()[:80] or "local user"
    except Exception:      # noqa: BLE001
        return "local user"


def install(app, app_module) -> None:
    """Add the routes directly to ``app`` (flat routes, like materials_api) and hook service start / stop to the app lifecycle."""
    for route in make_router(app_module).routes:
        app.router.routes.append(route)

    def _start() -> None:
        try:
            service().start()
        except Exception:      # noqa: BLE001  never stop the whole UI because the CAD worker could not start
            pass

    def _stop() -> None:
        with _LOCK:
            if _SVC["svc"] is not None:
                try:
                    _SVC["svc"].stop()
                except Exception:      # noqa: BLE001
                    pass

    from contextlib import asynccontextmanager
    orig = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        _start()
        try:
            async with orig(a) as st:
                yield st
        finally:
            _stop()
    app.router.lifespan_context = lifespan
