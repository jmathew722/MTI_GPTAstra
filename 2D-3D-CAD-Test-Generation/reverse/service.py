"""The one object the server (and tests) drive for 3D -> 2D: job store + serialized queue + template catalog + review workflow + history.

Everything the UI shows comes from here: nothing is invented, absent files are never listed, and every review action is audited.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from reverse import jobs, planner, qa, safety, state, templates


class ReverseService:
    def __init__(self, data_dir: Path, authorized_roots: Optional[list[Path]] = None):
        self.data = Path(data_dir)
        self.store = state.JobStore(self.data / "outputs" / "3d-to-2d")
        self.templates = templates.TemplateCatalog(self.data / "templates")
        self.roots = [Path(r) for r in (authorized_roots or [])]
        self.queue = jobs.JobQueue(self.store, self.templates.get)
        self.upload_dir = self.data / "uploads" / "3d-to-2d"

    # ---- lifecycle
    def start(self) -> None:
        self.queue.start()

    def stop(self) -> None:
        self.queue.stop()

    # ---- submission
    def profiles(self) -> list[dict]:
        return [{"id": k, "projection": v["projection"], "sheet": v["sheet"], "units": v["units"], "paper": planner.SHEETS[v["sheet"]]["paper"]} for k, v in planner.PROFILES.items()]

    def submit(self, *, part_paths: list[Path], template_id: Optional[str] = None, profile: str = "us_third_angle_inch", configs: Optional[dict] = None,
               options: Optional[dict] = None, authorized: bool = True) -> state.Job:
        tpl = self.templates.get(template_id) if template_id else self.templates.default()
        job = jobs.create_job(self.store, template=tpl, part_paths=part_paths, profile=profile, configs=configs, options=options,
                              authorized_roots=(self.roots + [self.upload_dir]) if authorized else None)
        self.queue.submit(job.job_id)
        return job

    def retry(self, job_id: str, part_ids: Optional[list[str]] = None) -> None:
        job = self.store.load(job_id)
        ids = part_ids or [p.part_id for p in job.parts if p.state in ("failed", "canceled")]
        if not ids:
            raise safety.SafetyError("Nothing to retry: no failed or canceled parts.")
        job.cancel_requested = False
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
        for p, pj in zip(j.parts, d["parts"]):
            pj.pop("source", None)                      # never expose server paths
            pj["files"] = self.part_files(j, p)
        d.pop("output_root", None)
        return d

    def part_files(self, job: state.Job, part: state.PartState) -> dict:
        """Only files that exist, with their sizes: the UI must never advertise an absent file."""
        base = self.store.dir(job.job_id)
        out = {}
        for name, rel in part.artifacts.items():
            fp = base / rel
            if fp.is_file():
                out[name] = {"bytes": fp.stat().st_size, "url_path": rel}
        return out

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
            rows.append({"job_id": j.job_id, "created": j.created, "state": j.summary_state(), "parts": [{"part_id": p.part_id, "name": p.name, "state": p.state,
                         "coverage_pct": p.coverage_pct, "material": (p.material or {}).get("name"), "review_status": p.review_status, "seconds": p.seconds} for p in j.parts],
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
