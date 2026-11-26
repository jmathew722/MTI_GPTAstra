"""Job creation and serialized execution for 3D -> 2D: one CAD session, one part at a time, bounded and cancellable.

``run_job`` is what the server's single worker thread calls; ``python -m reverse.cli`` calls the same function, so the command line and the UI run
exactly the same code.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from reverse import engine, safety, state, worker

log = logging.getLogger(__name__)


def create_job(store: state.JobStore, *, template: dict, part_paths: list[Path], profile: str = "us_third_angle_inch", configs: Optional[dict] = None,
               options: Optional[dict] = None, authorized_roots: Optional[list[Path]] = None) -> state.Job:
    """Validate every input BEFORE anything is queued. A bad file is reported with its reason; good files still run (batch isolation)."""
    from reverse.planner import PROFILES
    if profile not in PROFILES:
        raise safety.SafetyError(f"Unknown drawing profile {profile!r}.")
    template = dict(template, path=str(Path(template["path"]).resolve())) if template.get("path") else template
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
            job.parts.append(state.PartState(part_id=pid, source=str(p), name=p.name, config=cfg))
        except safety.SafetyError as e:
            rejected.append({"name": Path(real).name, "reason": str(e)})
    job.options["rejected"] = rejected
    if not job.parts:
        raise safety.SafetyError("No valid SOLIDWORKS parts to process: " + "; ".join(f"{r['name']}: {r['reason']}" for r in rejected))
    store.save(job)
    store.event(job.job_id, "created", parts=len(job.parts), rejected=len(rejected))
    return job


def run_job(store: state.JobStore, job_id: str, template: dict, *, cancel: Optional[Callable[[], bool]] = None, session: Optional[worker.CadSession] = None,
            only: Optional[list[str]] = None) -> state.Job:
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
        if cancelled():
            if part.state not in state.TERMINAL:
                state.finish(part, "canceled")
            continue
        if only:       # retry: start the part over
            part.state, part.error, part.stages, part.ended = "queued", "", {}, None
        engine.PartRunner(s, store, job, part, template, cancel=cancelled).run()
        store.save(job)
    job.state = job.summary_state()
    store.save(job)
    store.event(job_id, "job_done", state=job.state)
    return job


class JobQueue:
    """One worker thread, strictly serialized (one COM session). Submitting never blocks the caller."""

    def __init__(self, store: state.JobStore, template_lookup: Callable[[str], dict]):
        self.store = store
        self.lookup = template_lookup
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
                    if st and st.get("status") == "running" and _t.time() - st.get("t0", _t.time()) > self.WATCHDOG_S and not j.cancel_requested:
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
                    run_job(self.store, job_id, self.lookup(j.template_id), session=session, only=only)
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
