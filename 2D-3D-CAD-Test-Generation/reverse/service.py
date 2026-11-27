"""The one object the server (and tests) drive for 3D -> 2D: job store + serialized queue + template catalog + review workflow + history.

Everything the UI shows comes from here: nothing is invented, absent files are never listed, and every review action is audited.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from reverse import jobs, planner, qa, reference as refmod, safety, state, templates


class ReverseService:
    def __init__(self, data_dir: Path, authorized_roots: Optional[list[Path]] = None, reference_roots: Optional[list[Path]] = None, reference_client=None):
        self.data = Path(data_dir)
        self.store = state.JobStore(self.data / "outputs" / "3d-to-2d")
        self.templates = templates.TemplateCatalog(self.data / "templates")
        self.roots = [Path(r) for r in (authorized_roots or [])]
        self.refs = refmod.ReferenceServices(self.data, reference_roots, reference_client)
        self.refs.template_lookup = self.templates.get       # lets reference mode switch to the Solid Flow template whose sheet matches the reference
        self.queue = jobs.JobQueue(self.store, self.templates.get, refs=self.refs)
        self.upload_dir = self.data / "uploads" / "3d-to-2d"

    # ---- lifecycle
    def start(self) -> None:
        self.queue.start()

    def stop(self) -> None:
        self.queue.stop()

    # ---- templates (they need SOLIDWORKS, so they run on the CAD worker thread)
    def generate_template_async(self, key: str = templates.DEFAULT_ID) -> dict:
        from reverse import template_gen
        if key not in template_gen.VARIANTS:
            raise safety.SafetyError("Unknown template variant.")
        out = self.data / "templates" / "generated"
        entry = self.queue.run_task(lambda s: template_gen.generate(s, out, key), timeout=600)
        return self.templates.register(entry)

    def validate_template_async(self, path: Path, name: Optional[str] = None) -> dict:
        return self.queue.run_task(lambda s: self.templates.add_uploaded(s, path, name), timeout=300)

    def ensure_default_template(self) -> dict:
        """The generated default if it exists and is on disk, else generate it now (first run)."""
        for t in self.templates.list():
            if t["id"] == templates.DEFAULT_ID and t.get("available"):
                return t
        return self.generate_template_async(templates.DEFAULT_ID)

    # ---- configurations
    def configurations(self, path: Path) -> list[str]:
        """The saved configuration names of a part (opens it read-only on the CAD thread, closes it again)."""
        p = safety.authorize(path, self.roots + [self.upload_dir]) if self.roots else Path(path).resolve()
        safety.check_part_file(p)

        def fn(s):
            doc = s.open_part(p)
            try:
                return s.configurations(doc)
            finally:
                s.close_part(p)
        return self.queue.run_task(fn, timeout=180)

    # ---- submission
    def profiles(self) -> list[dict]:
        return [{"id": k, "projection": v["projection"], "sheet": v["sheet"], "units": v["units"], "paper": planner.SHEETS[v["sheet"]]["paper"]} for k, v in planner.PROFILES.items()]

    # ---- reference PDFs (v7)
    def validate_reference_pdf(self, path) -> dict:
        v = refmod.validate_pdf(path)
        return {k: v[k] for k in ("ok", "sha256", "pages", "size", "error")}

    def save_reference_pdf(self, data_stream_path) -> dict:
        """Validate and store a reference PDF content-addressed. The returned ``pdf_path`` is a SERVER path (keep it server-side)."""
        return self.refs.resolver.save_pdf(data_stream_path)

    def _part_for_lookup(self, part_path_or_part_id) -> tuple[Optional[Path], str, str]:
        raw = str(part_path_or_part_id or "")
        p = Path(raw)
        if raw and p.suffix.lower() == ".sldprt":
            try:
                ap = safety.authorize(p, self.roots + [self.upload_dir]) if self.roots else p.resolve()
            except safety.SafetyError as e:
                return None, "", str(e)
            if ap.is_file():
                return ap, "", ""
            return None, ap.stem, "The part file was not found."
        return None, Path(raw).stem or raw, ""        # an id / name: name evidence only

    def reference_candidates(self, part_path_or_part_id, config: str = "") -> dict:
        """Ranked candidate reference drawings from the 2D -> 3D history; see V7_CONTRACT.md section 2. Never auto-confirms by name."""
        part, hint, err = self._part_for_lookup(part_path_or_part_id)
        res = self.refs.index.candidates(part, config, name_hint=hint)
        if err:
            res["error"] = err
        return res

    def confirm_reference_link(self, part_path, artifact_id: str, config: str = "", user: str = "") -> dict:
        part, _, err = self._part_for_lookup(part_path)
        if part is None:
            raise safety.SafetyError(err or "A saved part file is required to confirm a link.")
        ent = self.refs.index.pdf_by_artifact(artifact_id)
        if ent is None:
            raise safety.SafetyError("Unknown reference artifact.")
        return self.refs.index.save_link(safety.sha256_file(part), config, ent.sha256, user)

    def submit(self, *, part_paths: list[Path], template_id: Optional[str] = None, profile: str = "us_third_angle_inch", configs: Optional[dict] = None,
               reference: Optional[dict] = None, options: Optional[dict] = None, authorized: bool = True) -> state.Job:
        tpl = self.templates.get(template_id) if template_id else self.templates.default()
        options = dict(options or {})
        if options.get("all_configs"):
            part_paths, configs = self._expand_configs(part_paths, configs)
        job = jobs.create_job(self.store, template=tpl, part_paths=part_paths, profile=profile, configs=configs, options=options, reference=reference,
                              refs=self.refs, authorized_roots=(self.roots + [self.upload_dir]) if authorized else None)
        self.queue.submit(job.job_id)
        return job

    def _expand_configs(self, part_paths: list[Path], configs: Optional[dict]):
        """One entry per saved configuration; each gets its own output folder and its own drawing, all referencing the same source part."""
        paths, cfgs = [], dict(configs or {})
        for p in part_paths:
            try:
                names = self.configurations(p)
            except Exception:      # noqa: BLE001 - a part whose configurations cannot be read runs with its active configuration
                names = []
            if len(names) <= 1:
                paths.append(p)
                continue
            for n in names:
                key = f"{p}::{n}"
                paths.append(Path(key))
                cfgs[key] = n
        return paths, cfgs

    def retry(self, job_id: str, part_ids: Optional[list[str]] = None) -> None:
        job = self.store.load(job_id)
        ids = part_ids or [p.part_id for p in job.parts if p.state in ("failed", "canceled")]
        if not ids:
            raise safety.SafetyError("Nothing to retry: no failed or canceled parts.")
        self.store.clear_cancel(job_id)
        job.cancel_requested = False
        for p in job.parts:           # the parts being retried show as queued immediately, not as the old failure until the worker reaches them
            if p.part_id in ids:
                p.state, p.error, p.stages, p.ended = "queued", "", {}, None
        self.store.save(job)
        self.queue.submit(job_id, ids)

    def cancel(self, job_id: str) -> None:
        self.queue.cancel(job_id)

    # ---- reads
    def job_view(self, job_id: str) -> dict:
        j = self.store.load(job_id)
        d = state._to_json(j)
        d["summary_state"] = j.summary_state()
        d["progress"] = state.progress(j)
        d["stage_labels"] = state.STAGE_LABEL
        d["stage_order"] = list(state.STAGES)
        d["reference_stages"] = list(state.REFERENCE_STAGES)
        for p, pj in zip(j.parts, d["parts"]):
            pj.pop("source", None)                      # never expose server paths
            pj["files"] = self.part_files(j, p)
            pj["files_availability"] = self.files_availability(pj["files"])
            pj["reference"] = refmod.public_reference(p.reference) if p.reference else refmod.blank_reference("standard")
            pj["verification"] = p.verification or {"status": "not_run"}
        d.pop("output_root", None)
        return d

    ALIASES = {"slddrw": "drawing.slddrw", "pdf": "drawing.pdf", "source_pdf": "reference/source.pdf", "stl": "model.stl", "qa_json": "qa.json"}

    def part_files(self, job: state.Job, part: state.PartState) -> dict:
        """Only files that exist, with their sizes: the UI must never advertise an absent file. v7 adds stable aliases (slddrw, pdf, source_pdf, stl,
        qa_json, comparison_images) next to the original keys."""
        base = self.store.dir(job.job_id)
        out = {}
        for name, rel in part.artifacts.items():
            fp = base / rel
            if fp.is_file():
                out[name] = {"bytes": fp.stat().st_size, "url_path": rel}
        for alias, key in self.ALIASES.items():
            if key in out:
                out[alias] = dict(out[key], available=True)
        cmp_files = [{"name": n, **v} for n, v in out.items() if n.startswith("comparison/") and n.lower().endswith(".png")]
        if cmp_files:
            out["comparison_images"] = {"files": sorted(cmp_files, key=lambda f: f["name"]), "available": True}
        return out

    @staticmethod
    def files_availability(files: dict) -> dict:
        return {k: (k in files) for k in ("slddrw", "pdf", "source_pdf", "stl", "qa_json", "comparison_images")}

    def artifact_path(self, job_id: str, rel: str) -> Path:
        """A downloadable artifact: must be a listed artifact of a part of this job, inside the job folder, a regular file."""
        base = self.store.dir(job_id).resolve()
        job = self.store.load(job_id)
        allowed = {rel_ for p in job.parts for rel_ in p.artifacts.values()}
        if rel not in allowed:
            raise safety.SafetyError("That file is not an artifact of this job.")
        fp = (base / rel).resolve()
        if not safety.is_within(base, fp) or not fp.is_file() or fp.is_symlink():
            raise safety.SafetyError("That file is not available.")
        return fp

    def history(self, limit: int = 100) -> list[dict]:
        rows = []
        for j in self.store.list()[:limit]:
            def thumb(p):
                rel = next((r for n, r in p.artifacts.items() if n.endswith("preview/page-001.png")), None)
                return rel if rel and (self.store.dir(j.job_id) / rel).is_file() else None
            rows.append({"job_id": j.job_id, "created": j.created, "state": j.summary_state(), "solidworks": j.solidworks,
                         "parts": [{"part_id": p.part_id, "name": p.name, "state": p.state, "coverage_pct": p.coverage_pct, "material": (p.material or {}).get("name"),
                                    "review_status": p.review_status, "seconds": p.seconds, "thumbnail": thumb(p)} for p in j.parts],
                         "template_id": j.template_id, "profile": j.profile, "kind": "reverse"})
        return rows

    def estimate(self, part_count: int) -> dict:
        """Runtime estimate from the real history of completed parts (seconds per part): a range with its basis, or 'not enough data'."""
        secs = sorted(p.seconds for j in self.store.list() for p in j.parts if p.seconds and p.state in ("completed", "review_required"))
        if len(secs) < 3:
            return {"available": False, "basis": f"{len(secs)} completed part(s) in history; at least 3 are needed", "n": len(secs)}
        lo, hi = secs[max(0, int(0.1 * (len(secs) - 1)))], secs[min(len(secs) - 1, int(0.9 * (len(secs) - 1)))]
        return {"available": True, "low_s": lo * part_count, "high_s": hi * part_count, "n": len(secs),
                "basis": f"10th-90th percentile of {len(secs)} completed parts, serialized (one SOLIDWORKS session)"}

    # ---- engineering review (audited; software QA is not approval)
    def review_action(self, job_id: str, part_id: str, issue_id: str, action: str, *, user: str = "unknown", note: str = "") -> dict:
        if action not in ("accept", "reject", "reopen"):
            raise safety.SafetyError("Unknown review action.")
        j = self.store.load(job_id)
        p = j.part(part_id)
        issue = next((i for i in p.issues if i["id"] == issue_id), None)
        if issue is None:
            raise safety.SafetyError("Unknown issue.")
        if action in ("accept", "reject") and not note.strip():
            raise safety.SafetyError("A note is required to disposition an issue.")
        entry = {"at": state.now(), "user": user, "action": action, "note": note.strip()}
        issue.setdefault("history", []).append(entry)
        issue["disposition"] = {"accept": "accepted", "reject": "rejected", "reopen": "open"}[action]
        open_ = [i for i in p.issues if i.get("disposition") not in ("accepted",) and i["severity"] in ("critical", "high", "medium")]
        p.review_status = "resolved" if not open_ else "required"
        if p.state == "review_required" and p.review_status == "resolved" and not any(i.get("disposition") == "rejected" for i in p.issues):
            p.state = "completed"          # "completed" here means reviewed; it is NOT manufacturing release
        elif p.state == "completed" and p.review_status == "required":
            p.state = "review_required"
        self.store.save(j)
        self.store.event(job_id, "review", part_id, issue=issue_id, action=action, user=user)
        # the audit trail is also written next to the artifacts
        qa_path = self.store.dir(job_id) / p.artifacts.get("qa.json", "")
        if p.artifacts.get("qa.json") and qa_path.is_file():
            try:
                q = json.loads(qa_path.read_text(encoding="utf-8"))
                q["issues"] = p.issues
                q["review_status"] = p.review_status
                tmp = qa_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(q, indent=2, default=str), encoding="utf-8")
                os.replace(tmp, qa_path)
            except (OSError, json.JSONDecodeError):
                pass
        return {"part_state": p.state, "review_status": p.review_status, "issue": issue}

    def delete_job(self, job_id: str) -> None:
        j = self.store.load(job_id)
        if j.summary_state() in ("running", "queued"):
            raise safety.SafetyError("A running job cannot be deleted; cancel it first.")
        shutil.rmtree(self.store.dir(job_id), ignore_errors=True)
