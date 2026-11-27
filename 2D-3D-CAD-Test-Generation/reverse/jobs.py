"""Job creation and serialized execution for 3D -> 2D: one CAD session, one part at a time, bounded and cancellable.

``run_job`` is what the server's single worker thread calls; ``python -m reverse.cli`` calls the same function, so the command line and the UI run
exactly the same code.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from reverse import engine, reference as refmod, safety, state, worker

log = logging.getLogger(__name__)


def _resolve_part_reference(refs, req: dict, key: str, real: Path, cfg: str, part: state.PartState) -> None:
    """Fill ``part.reference`` for the requested mode. Match mode with no resolvable source blocks THIS part only (explicit reason)."""
    if req["mode"] != "match" or refs is None:
        part.reference = refmod.blank_reference("standard")
        if req["mode"] == "match" and refs is None:
            part.reference = refmod.blank_reference("match")
            part.reference.update(status="blocked", error="REFERENCE_BLOCKED: reference matching is not configured on this server.", _blocked=True)
    else:
        spec = req["per_part"].get(key) or req["per_part"].get(str(real)) or {"source": "auto"}
        r = refs.resolver.resolve(real, cfg, spec, req)
        r["_request"] = {k: spec.get(k) for k in ("source", "artifact_id")} | {"pdf_path": spec.get("pdf_path"), "filename": spec.get("filename")}
        r["_fallback"] = bool(req.get("fallback_standard"))
        if r.get("_pdf") is not None:
            r["_pdf"] = str(r["_pdf"])
        part.reference = r
    if part.reference.get("_blocked"):
        state.finish(part, "failed", str(part.reference.get("error") or "REFERENCE_BLOCKED: no reference source."))
        part.stages["preflight"] = {"status": "failed", "started": state.now(), "ended": state.now(), "seconds": 0.0, "warnings": [], "errors": [part.error]}
        for st in state.STAGES[1:]:
            part.stages.setdefault(st, {"status": "skipped", "started": None, "ended": None, "warnings": [], "errors": []})


def create_job(store: state.JobStore, *, template: dict, part_paths: list[Path], profile: str = "us_third_angle_inch", configs: Optional[dict] = None,
               options: Optional[dict] = None, authorized_roots: Optional[list[Path]] = None, reference: Optional[dict] = None,
               refs: Optional["refmod.ReferenceServices"] = None) -> state.Job:
    """Validate every input BEFORE anything is queued. A bad file is reported with its reason; good files still run (batch isolation)."""
    from reverse.planner import PROFILES
    if profile not in PROFILES:
        raise safety.SafetyError(f"Unknown drawing profile {profile!r}.")
    template = dict(template, path=str(Path(template["path"]).resolve())) if template.get("path") else template
    req = refmod.normalize_request(reference)
    job = state.Job(job_id=safety.new_job_id(), template_id=template["id"], profile=profile, output_root=str(store.root), options=dict(options or {}))
    rejected = []
    entries = []
    for path in part_paths:
        sp = str(path)
        cfg = (configs or {}).get(sp, "") or ""
        real = Path(sp.rsplit("::", 1)[0]) if (cfg and sp.endswith("::" + cfg)) else Path(path)
        entries.append((real, cfg, sp))
    ids = []
    seen: dict[str, int] = {}
    for real, cfg, sp in entries:
        base = safety.safe_id(real.stem) + (("__" + safety.safe_id(cfg)) if cfg else "")
        n = seen.get(base.lower(), 0) + 1
        seen[base.lower()] = n
        ids.append(base if n == 1 else f"{base}-{n}")
    for (real, cfg, sp), pid in zip(entries, ids):
        try:
            p = safety.authorize(real, authorized_roots) if authorized_roots else Path(real).resolve()
            safety.check_part_file(p)
            ps = state.PartState(part_id=pid, source=str(p), name=p.name, config=cfg)
            _resolve_part_reference(refs, req, sp, p, cfg, ps)
            job.parts.append(ps)
        except safety.SafetyError as e:
            rejected.append({"name": Path(real).name, "reason": str(e)})
    job.options["rejected"] = rejected
    job.options["reference_mode"] = req["mode"]
    job.options["reference_fallback_standard"] = req["fallback_standard"]
    if not job.parts:
        raise safety.SafetyError("No valid SOLIDWORKS parts to process: " + "; ".join(f"{r['name']}: {r['reason']}" for r in rejected))
    store.save(job)
    store.event(job.job_id, "created", parts=len(job.parts), rejected=len(rejected))
    return job


def run_job(store: state.JobStore, job_id: str, template: dict, *, cancel: Optional[Callable[[], bool]] = None, session: Optional[worker.CadSession] = None,
            only: Optional[list[str]] = None, refs: Optional["refmod.ReferenceServices"] = None) -> state.Job:
    """Run (or retry, with ``only``) the parts of a job. Never raises for a part failure: each part carries its own result."""
    job = store.load(job_id)
    s = session or worker.CadSession()
    cancelled = cancel or (lambda: store.load(job_id).cancel_requested)
    try:
        job.solidworks = s.connect().as_dict()
    except Exception as e:      # noqa: BLE001
        for p in job.parts:
            if not only or p.part_id in only:
                state.finish(p, "failed", f"SOLIDWORKS is not available: {type(e).__name__}: {e}"[:300])
        job.state = job.summary_state()
        store.save(job)
        store.event(job_id, "solidworks_unavailable", error=str(e))
        return job
    try:        # a stale-document sweep must never be able to stop a job
        stale = s.close_docs_under(store.root) if hasattr(s, "close_docs_under") else []
    except Exception as e:      # noqa: BLE001
        log.warning("stale-document sweep failed: %s", e)
        stale = []
    if stale:
        store.event(job_id, "closed_stale_documents", documents=stale)
    job.state = "running"
    store.save(job)
    for part in job.parts:
        if only and part.part_id not in only:
            continue
        if part.state in ("completed", "review_required") and not only:
            continue
        if part.reference.get("_blocked") and not only:       # blocked in preflight: no reference source (explicit reason already recorded)
            continue
        if only and part.reference.get("_blocked") and refs is not None:      # a retry re-resolves (the user may have uploaded or confirmed a source since)
            _reresolve(refs, job, part)
            if part.reference.get("_blocked"):
                store.save(job)
                continue
        if cancelled():
            if part.state not in state.TERMINAL:
                state.finish(part, "canceled")
            continue
        if only:       # retry: start the part over
            part.state, part.error, part.stages, part.ended = "queued", "", {}, None
        engine.PartRunner(s, store, job, part, template, cancel=cancelled, refs=refs).run()
        store.save(job)
    job.state = job.summary_state()
    store.save(job)
    store.event(job_id, "job_done", state=job.state)
    return job


def _reresolve(refs, job: state.Job, part: state.PartState) -> None:
    spec = dict(part.reference.get("_request") or {"source": "auto"})
    req = {"mode": "match", "fallback_standard": bool(part.reference.get("_fallback")), "per_part": {str(part.source): spec}}
    old_err = part.error
    part.state, part.error, part.ended, part.stages = "queued", "", None, {}
    try:
        r = refs.resolver.resolve(Path(part.source), part.config, spec, req)
    except Exception as e:      # noqa: BLE001
        r = {"_blocked": True, "error": f"REFERENCE_BLOCKED: {type(e).__name__}: {e}"}
    r["_request"] = spec
    r["_fallback"] = req["fallback_standard"]
    if r.get("_pdf") is not None:
        r["_pdf"] = str(r["_pdf"])
    if r.get("_blocked"):
        r.setdefault("error", old_err)
    part.reference = r
    if r.get("_blocked"):
        state.finish(part, "failed", str(r.get("error") or old_err))


class JobQueue:
    """One worker thread, strictly serialized (one COM session). Submitting never blocks the caller."""

    def __init__(self, store: state.JobStore, template_lookup: Callable[[str], dict], refs: Optional["refmod.ReferenceServices"] = None):
        self.store = store
        self.lookup = template_lookup
        self.refs = refs
        self._q: list[tuple[str, Optional[list[str]]]] = []
        self._tasks: list = []
        self._cv = threading.Condition()
        self._stop = False
        self._t: Optional[threading.Thread] = None
        self.current: Optional[str] = None

    WATCHDOG_S = 900.0        # a part that stays in one stage this long is flagged (a hung COM call cannot be killed from here without killing a SOLIDWORKS session that may be the user's)

    def _watchdog(self) -> None:
        import time as _t
        while not self._stop:
            _t.sleep(5.0)
            jid = self.current
            if not jid:
                continue
            try:
                j = self.store.load(jid)
                for p in j.parts:
                    st = p.stages.get(p.state) if p.state in state.STAGES else None
                    if st and st.get("status") == "running" and _t.monotonic() - st.get("t0", _t.monotonic()) > self.WATCHDOG_S and not j.cancel_requested:     # t0 is a monotonic clock value (state.py)
                        j.cancel_requested = True
                        self.store.save(j)
                        self.store.event(jid, "watchdog_timeout", p.part_id, stage=p.state, seconds=self.WATCHDOG_S,
                                         note="The stage exceeded the time limit. Cancellation was requested; if SOLIDWORKS is hung, close it (the job will then fail and can be retried).")
            except Exception:      # noqa: BLE001
                continue

    def start(self) -> None:
        if self._t and self._t.is_alive():
            return
        threading.Thread(target=self._watchdog, name="reverse-watchdog", daemon=True).start()
        self.store.recover()
        self._t = threading.Thread(target=self._loop, name="reverse-cad-worker", daemon=True)
        self._t.start()

    def run_task(self, fn: Callable, timeout: float = 300.0):
        """Run ``fn(session)`` on the CAD worker thread (the only thread allowed to touch COM) and return its result; exceptions propagate."""
        import concurrent.futures
        fut: concurrent.futures.Future = concurrent.futures.Future()
        with self._cv:
            self._tasks.append((fn, fut))
            self._cv.notify()
        return fut.result(timeout=timeout)

    def submit(self, job_id: str, only: Optional[list[str]] = None) -> None:
        with self._cv:
            self._q.append((job_id, only))
            self._cv.notify()

    def cancel(self, job_id: str) -> None:
        j = self.store.load(job_id)
        j.cancel_requested = True
        for p in j.parts:
            if p.state == "queued":
                state.finish(p, "canceled")
        self.store.save(j)
        self.store.event(job_id, "cancel_requested")

    def _loop(self) -> None:
        import pythoncom
        pythoncom.CoInitialize()               # the COM session lives on THIS thread only (STA)
        try:
            session = worker.CadSession()
            while True:
                with self._cv:
                    while not self._q and not self._tasks and not self._stop:
                        self._cv.wait(timeout=1.0)
                    if self._stop:
                        return
                    task = self._tasks.pop(0) if self._tasks else None
                    job_id, only = (self._q.pop(0) if (task is None and self._q) else (None, None))
                if task is not None:
                    fn, fut = task
                    try:
                        if getattr(session, "app", None) is None:        # a template task can arrive before any job: connect lazily on the CAD thread
                            session.connect()
                        fut.set_result(fn(session))
                    except BaseException as e:      # noqa: BLE001
                        fut.set_exception(e)
                    continue
                self.current = job_id
                try:
                    j = self.store.load(job_id)
                    run_job(self.store, job_id, self.lookup(j.template_id), session=session, only=only, refs=self.refs)
                except Exception:      # noqa: BLE001
                    log.exception("job %s crashed", job_id)
                finally:
                    self.current = None
        finally:
            pythoncom.CoUninitialize()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
