"""Reference-PDF resolution for 3D -> 2D (v7): Standard vs reference-match mode, history lookup, upload validation, provenance.

No SOLIDWORKS and no network here. The rules (spec 01/02):

* explicit upload > explicit/confirmed artifact > confirmed link > automatic history link > nothing;
* a link is *confirmed by evidence* only through content: the submitted part's SHA-256 equals a SLDPRT stored by a forward (2D -> 3D) run, and the PDF is
  either recorded in that run's manifests by SHA-256 or stored inside the same run folder. A file name or part number alone is only ever a
  *candidate* with confidence and reasons (``needs_confirmation``);
* several different PDFs with equal evidence are ambiguous: nothing is auto-selected;
* old runs without recorded links are candidates, never confirmed matches;
* a PDF is data: it is validated (signature, size, pages) and copied content-addressed, never executed or trusted for instructions;
* paths never leave the server: the UI sees ``artifact_id`` (``pdf_<sha256 prefix>``), filenames, hashes and page counts.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from reverse import safety

log = logging.getLogger(__name__)

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 20
LINKS_SCHEMA = 1
DERIVED_PDF_MARKERS = ("_markup", "annotated", "engineering_flags", "drawing.pdf", "preview")
# manifests a forward run writes that record the SHA-256 of the drawing it was built from
RECORDED_SOURCE_FILES = (("engineering_markup.json", ("source_sha256",)), ("solidworks_recording.json", ("source_sha256",)),
                         ("engineering_flag_overlays.json", ("source_pdf_sha256",)), ("flags_ocr.json", ("sha256",)))
SOURCES = ("auto", "upload", "artifact", "none")
MODES = ("standard", "match")


# ------------------------------------------------------------------ PDF validation

def validate_pdf(path, *, max_bytes: int = MAX_PDF_BYTES, max_pages: int = MAX_PDF_PAGES) -> dict:
    """{ok, sha256, pages, size, error}. Signature, size, page count, encryption; the file is only read, never modified."""
    out = {"ok": False, "sha256": "", "pages": 0, "size": 0, "error": ""}
    try:
        p = Path(path)
        if not p.is_file():
            out["error"] = "The file does not exist."
            return out
        out["size"] = p.stat().st_size
        if out["size"] == 0:
            out["error"] = "The file is empty."
            return out
        if out["size"] > max_bytes:
            out["error"] = f"The file is {out['size'] / 1048576:.1f} MB; the limit is {max_bytes // 1048576} MB."
            return out
        with open(p, "rb") as f:
            head = f.read(1024)
        if b"%PDF-" not in head[:1024]:
            out["error"] = "Not a PDF (the %PDF- signature is missing)."
            return out
        out["sha256"] = safety.sha256_file(p)
        import fitz
        try:
            doc = fitz.open(str(p))
        except Exception as e:      # noqa: BLE001
            out["error"] = f"The PDF is corrupted or unreadable ({type(e).__name__})."
            return out
        try:
            if doc.needs_pass or doc.is_encrypted:
                out["error"] = "The PDF is password protected."
                return out
            out["pages"] = doc.page_count
            if doc.page_count < 1:
                out["error"] = "The PDF has no pages."
                return out
            if doc.page_count > max_pages:
                out["error"] = f"The PDF has {doc.page_count} pages; the limit is {max_pages}."
                return out
            doc.load_page(0).get_text("text")           # a truncated file fails here
        except Exception as e:      # noqa: BLE001
            out["error"] = f"The PDF is corrupted or unreadable ({type(e).__name__})."
            return out
        finally:
            doc.close()
        out["ok"] = True
        return out
    except OSError as e:
        out["error"] = f"The file could not be read ({type(e).__name__})."
        return out


def artifact_id_for(pdf_sha: str) -> str:
    return "pdf_" + pdf_sha[:20]


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _part_key(stem: str) -> str:
    """Part-file stem -> comparable key: forward runs name the SLDPRT '<drawing id>_ir', and the drawing id carries E/M sheet suffixes."""
    s = re.sub(r"_IR$", "", stem, flags=re.I)
    return _norm(s)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ the index of forward runs and PDFs

@dataclass
class PdfEntry:
    path: Path
    sha256: str
    pages: int
    size: int
    mtime: float
    origin: str

    @property
    def artifact_id(self) -> str:
        return artifact_id_for(self.sha256)


@dataclass
class ForwardRun:
    dir: Path
    name: str
    root_label: str
    extraction: Optional[Path] = None
    run_id: str = ""
    parts: list = field(default_factory=list)                 # [(Path, sha256)]
    recorded_source_sha: set = field(default_factory=set)
    recorded_source_name: str = ""
    colocated_pdfs: list = field(default_factory=list)
    part_number: str = ""
    part_name: str = ""
    mtime: float = 0.0
    cost_usd: Optional[float] = None


class ReferenceIndex:
    """Scans the authorized history roots (read-only) for forward runs and drawing PDFs. Hashes are cached by (size, mtime)."""

    def __init__(self, roots: Iterable[Path], upload_dir: Optional[Path] = None, links_path: Optional[Path] = None, ttl_s: float = 20.0):
        self.roots = [Path(r) for r in roots if r]
        self.upload_dir = Path(upload_dir) if upload_dir else None
        self.links_path = Path(links_path) if links_path else None
        self._hash_cache: dict[tuple, str] = {}
        self._pages_cache: dict[tuple, int] = {}
        self._runs: list[ForwardRun] = []
        self._pdfs: dict[str, PdfEntry] = {}
        self._built = 0.0
        self._ttl = ttl_s
        self._lock = threading.RLock()

    # ---- hashing
    def _sha(self, p: Path) -> str:
        st = p.stat()
        k = (str(p), st.st_size, st.st_mtime_ns)
        h = self._hash_cache.get(k)
        if h is None:
            h = safety.sha256_file(p)
            self._hash_cache[k] = h
        return h

    def _pages(self, p: Path) -> int:
        st = p.stat()
        k = (str(p), st.st_size, st.st_mtime_ns)
        if k not in self._pages_cache:
            try:
                import fitz
                with fitz.open(str(p)) as d:
                    self._pages_cache[k] = d.page_count
            except Exception:      # noqa: BLE001
                self._pages_cache[k] = 0
        return self._pages_cache[k]

    # ---- scan
    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if not force and self._runs is not None and time.time() - self._built < self._ttl and self._built:
                return
            runs: list[ForwardRun] = []
            pdfs: dict[str, PdfEntry] = {}
            seen_dirs: set[str] = set()
            for root in self.roots:
                if not root.is_dir():
                    continue
                label = root.name
                for dirpath, dirnames, filenames in os.walk(root):
                    dp = Path(dirpath)
                    depth = len(dp.relative_to(root).parts)
                    # never descend into our own outputs, virtualenvs, node_modules or hidden caches
                    dirnames[:] = [d for d in dirnames if d.lower() not in ("3d-to-2d", "node_modules", ".venv", "__pycache__", ".git", ".thumbs") and depth < 5]
                    low = {f.lower(): f for f in filenames}
                    exts = [f for f in filenames if f.lower().endswith("_extraction.json")]
                    parts = [dp / f for f in filenames if f.lower().endswith(".sldprt")]
                    if (exts or parts) and str(dp) not in seen_dirs and not any(m in dp.name.lower() for m in ("_staging",)):
                        seen_dirs.add(str(dp))
                        run = self._read_run(dp, label, exts, parts, low)
                        if run is not None:
                            runs.append(run)
                    for f in filenames:
                        if f.lower().endswith(".pdf") and not any(m in f.lower() for m in DERIVED_PDF_MARKERS):
                            ent = self._pdf_entry(dp / f, self._origin(dp, root))
                            if ent is not None:
                                pdfs.setdefault(ent.sha256 + "|" + ent.path.name.lower(), ent)
            if self.upload_dir and self.upload_dir.is_dir():
                for f in self.upload_dir.rglob("*.pdf"):
                    ent = self._pdf_entry(f, "upload")
                    if ent is not None:
                        pdfs.setdefault(ent.sha256 + "|" + ent.path.name.lower(), ent)
            self._runs, self._pdfs, self._built = runs, pdfs, time.time()

    @staticmethod
    def _origin(dp: Path, root: Path) -> str:
        low = [x.lower() for x in dp.relative_to(root).parts] if dp != root else []
        if ".originals" in low:
            return "ui_original"
        if "input" in low:
            return "run_input"
        if "ui_output" in low or "final_outputs" in root.name.lower():
            return "forward_run"
        return "drawing_folder"

    def _pdf_entry(self, p: Path, origin: str) -> Optional[PdfEntry]:
        try:
            st = p.stat()
            if st.st_size == 0 or st.st_size > MAX_PDF_BYTES:
                return None
            with open(p, "rb") as f:
                if b"%PDF-" not in f.read(1024):
                    return None
            return PdfEntry(p, self._sha(p), self._pages(p), st.st_size, st.st_mtime, origin)
        except OSError:
            return None

    def _read_run(self, dp: Path, label: str, exts: list[str], parts: list[Path], low: dict) -> Optional[ForwardRun]:
        run = ForwardRun(dir=dp, name=dp.name, root_label=label)
        try:
            if exts:
                run.extraction = dp / sorted(exts)[0]
                run.mtime = run.extraction.stat().st_mtime
                try:
                    ex = json.loads(run.extraction.read_text(encoding="utf-8", errors="replace"))
                    run.part_number = str(ex.get("part_number") or "")
                    run.part_name = str(ex.get("part_name") or "")
                except (OSError, ValueError):
                    pass
            for sp in parts:
                try:
                    run.parts.append((sp, self._sha(sp)))
                except OSError:
                    continue
            for fname, keys in RECORDED_SOURCE_FILES:
                fp = low.get(fname)
                if not fp:
                    continue
                try:
                    d = json.loads((dp / fp).read_text(encoding="utf-8", errors="replace"))
                except (OSError, ValueError):
                    continue
                for k in keys:
                    v = d.get(k) if isinstance(d, dict) else None
                    if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v):
                        run.recorded_source_sha.add(v)
                if isinstance(d, dict) and d.get("source_pdf"):
                    run.recorded_source_name = str(d["source_pdf"])
                if isinstance(d, dict) and d.get("run_id"):
                    run.run_id = str(d["run_id"])
            for f in low.values():
                if f.lower().endswith(".pdf") and not any(m in f.lower() for m in DERIVED_PDF_MARKERS):
                    run.colocated_pdfs.append(dp / f)
            if not (run.parts or run.extraction):
                return None
            return run
        except OSError:
            return None

    # ---- links sidecar
    def load_links(self) -> list[dict]:
        if not self.links_path or not self.links_path.is_file():
            return []
        try:
            d = json.loads(self.links_path.read_text(encoding="utf-8"))
            return list(d.get("links", [])) if isinstance(d, dict) else []
        except (OSError, ValueError):
            return []

    def save_link(self, part_sha: str, config: str, pdf_sha: str, user: str = "") -> dict:
        if not self.links_path:
            raise safety.SafetyError("Reference links cannot be stored (no data directory).")
        with self._lock:
            links = [x for x in self.load_links() if not (x.get("part_sha256") == part_sha and (x.get("configuration") or "") == (config or ""))]
            rec = {"part_sha256": part_sha, "configuration": config or "", "pdf_sha256": pdf_sha, "confirmed_by": user or "unknown",
                   "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            links.append(rec)
            self.links_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.links_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"schema_version": LINKS_SCHEMA, "links": links}, indent=2), encoding="utf-8")
            os.replace(tmp, self.links_path)
            return rec

    # ---- lookups
    @property
    def runs(self) -> list[ForwardRun]:
        self.refresh()
        return self._runs

    def pdf_by_sha(self, sha: str) -> list[PdfEntry]:
        self.refresh()
        return [e for e in self._pdfs.values() if e.sha256 == sha]

    def pdf_by_artifact(self, artifact_id: str) -> Optional[PdfEntry]:
        self.refresh()
        hits = [e for e in self._pdfs.values() if e.artifact_id == artifact_id]
        if not hits:
            self.refresh(force=True)
            hits = [e for e in self._pdfs.values() if e.artifact_id == artifact_id]
        if not hits:
            return None
        # prefer the copy stored with a forward run, then the oldest (stable) one
        hits.sort(key=lambda e: (0 if e.origin == "forward_run" else 1, e.mtime))
        return hits[0]

    def all_pdfs(self) -> list[PdfEntry]:
        self.refresh()
        return list(self._pdfs.values())

    # ---- candidate computation
    def candidates(self, part_path: Optional[Path], config: str = "", *, name_hint: str = "") -> dict:
        """Ranked candidate PDFs for a part. See the module docstring for the evidence order. Never raises for a missing part."""
        self.refresh()
        part_sha = ""
        stem = name_hint
        info: dict = {"filename": "", "sha256": "", "configuration": config or ""}
        if part_path is not None:
            p = Path(part_path)
            info["filename"] = p.name
            stem = stem or p.stem
            try:
                if p.is_file():
                    part_sha = self._sha(p)
                    info["sha256"] = part_sha
            except OSError:
                pass
        key = _part_key(stem)
        cands: dict[str, dict] = {}

        def add(ent: PdfEntry, conf: float, reason: str, link: Optional[str], needs: bool, run: Optional[ForwardRun] = None):
            c = cands.get(ent.sha256)
            if c is None:
                c = {"artifact_id": ent.artifact_id, "filename": ent.path.name, "project": (run.root_label if run else ent.path.parent.name), "run": (run.name if run else ""),
                     "date": _iso(ent.mtime), "pages": ent.pages, "confidence": 0.0, "reasons": [], "needs_confirmation": True, "link": None, "sha256": ent.sha256,
                     "_run": run}
                cands[ent.sha256] = c
            if conf > c["confidence"]:
                c["confidence"], c["link"] = conf, link
                c["needs_confirmation"] = needs
                if run is not None:
                    c["run"], c["project"] = run.name, run.root_label
            if reason not in c["reasons"] and not (link == "name_only" and c["link"] not in (None, "name_only")):
                c["reasons"].append(reason)            # a weak name-only remark never decorates a hash / forward-run link
            if not needs:
                c["needs_confirmation"] = False if c["confidence"] >= conf else c["needs_confirmation"]

        # 1. confirmed links (content hashes, user-approved)
        for l in self.load_links():
            if part_sha and l.get("part_sha256") == part_sha and (l.get("configuration") or "") == (config or ""):
                for e in self.pdf_by_sha(l.get("pdf_sha256", "")):
                    add(e, 1.0, f"confirmed by {l.get('confirmed_by', 'a user')} on {l.get('confirmed_at', '')[:10]}", "confirmed", False)
        # 2. forward runs that stored a SLDPRT with the same SHA-256 as this part
        strong = [r for r in self._runs if part_sha and any(h == part_sha for _, h in r.parts)]
        for r in strong:
            for h in r.recorded_source_sha:
                for e in self.pdf_by_sha(h):
                    add(e, 0.99, f"part SHA-256 equals the SLDPRT of forward run '{r.name}', whose manifest records this drawing's SHA-256", "recorded_source_hash", False, r)
            for cp in r.colocated_pdfs:
                e = self._pdf_entry(cp, "forward_run")
                if e is not None:
                    add(e, 0.95, f"part SHA-256 equals the SLDPRT of forward run '{r.name}', and this drawing is stored in that run folder", "forward_run", False, r)
        # 3. name evidence only: candidates, never selected
        names = {key} if key else set()
        for r in strong:
            names.add(_norm(r.name))
            if r.part_number:
                names.add(_norm(r.part_number))
        names.discard("")
        for e in self.all_pdfs():
            ek = _norm(e.path.stem)
            if not ek:
                continue
            if any(ek == n for n in names) or any(len(n) >= 5 and (ek.startswith(n) or n.startswith(ek)) and abs(len(ek) - len(n)) <= 2 for n in names):
                if strong:
                    add(e, 0.6, "file name matches the forward run that produced this part, but no manifest or hash links it to this drawing", "name_only", True)
                else:
                    add(e, 0.4, "file name resembles the part number; no hash or forward-run evidence links it (a name is never enough)", "name_only", True)
        # 4. a run that matches by name only (part hash unknown): its colocated drawing is a candidate
        if not strong:
            for r in self._runs:
                rk = {_norm(r.name), _norm(r.part_number)} - {""}
                if key and key in rk:
                    for cp in r.colocated_pdfs:
                        e = self._pdf_entry(cp, "forward_run")
                        if e is not None:
                            add(e, 0.5, f"stored in forward run '{r.name}', which matches the part name; the part file's SHA-256 does not match that run's model", "name_only", True, r)
        rows = sorted(cands.values(), key=lambda c: (-c["confidence"], c["filename"].lower()))
        # ambiguity: several DIFFERENT drawings reached by evidence (not by name) -> nobody is auto-selected
        strong_rows = [c for c in rows if not c["needs_confirmation"]]
        selected = None
        if len(strong_rows) == 1:
            selected = {k: v for k, v in strong_rows[0].items() if not k.startswith("_")}
        elif len(strong_rows) > 1:
            for c in strong_rows:
                if c["link"] != "confirmed":
                    c["needs_confirmation"] = True
                    c["reasons"].append(f"ambiguous: {len(strong_rows)} different drawings are linked to this part; confirm one")
            conf = [c for c in strong_rows if c["link"] == "confirmed"]
            if len(conf) == 1:
                conf[0]["needs_confirmation"] = False
                selected = {k: v for k, v in conf[0].items() if not k.startswith("_")}
        runs_for_part = {r.name for r in strong}
        public = [{k: v for k, v in c.items() if not k.startswith("_") and k != "sha256"} | {"sha256": c["sha256"]} for c in rows]
        return {"part": info, "selected": selected, "candidates": public, "matched_runs": sorted(runs_for_part)}

    # ---- prior extractions
    def prior_extractions(self, pdf_sha: str, part_sha: str = "") -> list[dict]:
        """Forward extraction JSON files that belong to this drawing: the run records the drawing's SHA-256, or stores a byte-identical copy of the PDF."""
        self.refresh()
        out = []
        for r in self._runs:
            if r.extraction is None:
                continue
            why = ""
            if pdf_sha in r.recorded_source_sha:
                why = "the forward run manifest records this drawing's SHA-256"
            else:
                for cp in r.colocated_pdfs:
                    try:
                        if self._sha(cp) == pdf_sha:
                            why = "a byte-identical copy of the drawing is stored in the forward run folder"
                            break
                    except OSError:
                        continue
            if why:
                out.append({"path": r.extraction, "run": r.name, "why": why, "mtime": r.mtime, "part_sha_match": bool(part_sha and any(h == part_sha for _, h in r.parts)),
                            "cost_usd": r.cost_usd})
        out.sort(key=lambda d: (not d["part_sha_match"], -d["mtime"]))
        return out


# ------------------------------------------------------------------ resolution

def blank_reference(mode: str = "standard") -> dict:
    return {"mode": mode, "status": "not_applicable" if mode == "standard" else "pending", "source_kind": "none", "filename": "", "sha256": "", "pages": 0, "link": None,
            "confidence": None, "reasons": [], "extraction_cache": "none", "extraction_id": "", "extraction_schema": "",
            "api_usage": {"tokens": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0, "calls": 0, "incremental": True, "historical_usd": None}, "warnings": []}


def normalize_request(reference: Optional[dict]) -> dict:
    """Validate the ``reference`` argument of submit(). Raises SafetyError for malformed input; never touches the disk."""
    if reference is None:
        return {"mode": "standard", "fallback_standard": False, "per_part": {}}
    if not isinstance(reference, dict):
        raise safety.SafetyError("reference must be an object {mode, per_part, fallback_standard}.")
    mode = str(reference.get("mode") or "standard").lower()
    if mode not in MODES:
        raise safety.SafetyError(f"Unknown reference mode {mode!r}; use 'standard' or 'match'.")
    per = reference.get("per_part")
    per = {} if per is None else per
    if not isinstance(per, dict):
        raise safety.SafetyError("reference.per_part must be an object.")
    clean = {}
    for k, v in per.items():
        if not isinstance(v, dict):
            raise safety.SafetyError("Each reference.per_part entry must be an object.")
        src = str(v.get("source") or "auto").lower()
        if src not in SOURCES:
            raise safety.SafetyError(f"Unknown reference source {src!r}; use auto, upload, artifact or none.")
        clean[str(k)] = {"source": src, "pdf_path": v.get("pdf_path"), "artifact_id": v.get("artifact_id")}
    return {"mode": mode, "fallback_standard": bool(reference.get("fallback_standard")), "per_part": clean}


class ReferenceResolver:
    def __init__(self, index: ReferenceIndex, upload_dir: Path):
        self.index = index
        self.upload_dir = Path(upload_dir)
        self.ref_dir = self.upload_dir / "reference"

    def save_pdf(self, data_stream_path) -> dict:
        """Validate then copy content-addressed into the reference upload store. The source file is not touched."""
        v = validate_pdf(data_stream_path)
        res = {**v, "pdf_path": "", "artifact_id": "", "filename": Path(str(data_stream_path)).name}
        if not v["ok"]:
            return res
        self.ref_dir.mkdir(parents=True, exist_ok=True)
        dest = self.ref_dir / f"{v['sha256']}.pdf"
        if not dest.is_file():
            tmp = dest.with_suffix(".tmp")
            shutil.copyfile(data_stream_path, tmp)
            os.replace(tmp, dest)
        res["pdf_path"] = str(dest)
        res["artifact_id"] = artifact_id_for(v["sha256"])
        return res

    def _is_store_path(self, p: Path) -> bool:
        return safety.is_within(self.ref_dir, p) and not safety.has_symlink_component(self.ref_dir, p) if self.ref_dir.exists() else False

    def resolve(self, part_path: Path, config: str, spec: Optional[dict], req: dict) -> dict:
        """The ReferenceResolution of one part for ``reference.mode == 'match'``. Returns the part-level ``reference`` dict plus a private
        ``_pdf`` (server path) and ``_blocked`` flag. Never raises."""
        ref = blank_reference("match")
        ref["status"] = "resolved"
        spec = spec or {"source": "auto"}
        src = spec.get("source") or "auto"
        fallback = bool(req.get("fallback_standard"))
        info = self.index.candidates(part_path, config)
        ref["part_sha256"] = info["part"]["sha256"]

        def block(reason: str, code: str = "REFERENCE_BLOCKED") -> dict:
            if fallback:
                ref.update(status="fallback_standard", mode="match", source_kind="none")
                ref["warnings"].append(f"No reference was used; this part runs as Standard because fallback_standard is set. Reason: {reason}")
                ref["_blocked"] = False
                ref["_pdf"] = None
            else:
                ref.update(status="blocked", source_kind="none")
                ref["reasons"].append(reason)
                ref["error"] = f"{code}: {reason}"
                ref["_blocked"] = True
                ref["_pdf"] = None
            return ref

        pdf: Optional[Path] = None
        kind = "none"
        chosen: Optional[dict] = None
        if src == "none":
            return block("Match mode was requested for this part but its reference source is 'none'.")
        if src == "upload":
            raw = spec.get("pdf_path")
            if not raw:
                return block("An upload was selected but no PDF was provided.", "REFERENCE_PDF_REJECTED")
            p = Path(str(raw))
            if not self._is_store_path(p):
                return block("The uploaded PDF is not in the server's reference store; save it with save_reference_pdf first.", "REFERENCE_PDF_REJECTED")
            v = validate_pdf(p)
            if not v["ok"]:
                return block(f"The uploaded PDF was rejected: {v['error']}", "REFERENCE_PDF_REJECTED")
            pdf, kind = p, "upload"
            ref.update(sha256=v["sha256"], pages=v["pages"], filename=str(spec.get("filename") or f"{v['sha256'][:12]}.pdf"))
            ref["reasons"].append("explicitly uploaded by the user (overrides any history)")
            # compare with what the history says this part was generated from: a different drawing is flagged, never silently accepted
            sel = info.get("selected")
            if sel and sel["sha256"] != v["sha256"]:
                ref["warnings"].append(f"The uploaded drawing differs from the drawing this part was generated from ({sel['filename']}, linked by {sel['link']}). "
                                       "The upload was used because uploads override history; verify it is the right drawing.")
                ref["history_conflict"] = {"filename": sel["filename"], "sha256": sel["sha256"]}
            elif not sel and info["candidates"]:
                same = [c for c in info["candidates"] if c["sha256"] == v["sha256"]]
                if not same:
                    ref["warnings"].append("The uploaded drawing does not match any drawing in this part's history; the file name and the geometry check decide whether it is accepted.")
        elif src in ("artifact", "auto"):
            if src == "artifact":
                aid = spec.get("artifact_id") or ""
                ent = self.index.pdf_by_artifact(aid) if aid else None
                if ent is None:
                    return block(f"The selected reference artifact {aid!r} was not found in the project history.", "REFERENCE_PDF_REJECTED")
                chosen_row = next((c for c in info["candidates"] if c["artifact_id"] == aid), None)
                v = validate_pdf(ent.path)
                if not v["ok"]:
                    return block(f"The selected reference was rejected: {v['error']}", "REFERENCE_PDF_REJECTED")
                pdf, kind = ent.path, "artifact"
                ref.update(sha256=v["sha256"], pages=v["pages"], filename=ent.path.name, confidence=(chosen_row or {}).get("confidence"),
                           link=(chosen_row or {}).get("link"))
                ref["reasons"] += (chosen_row or {}).get("reasons", []) or ["selected explicitly from the history candidates"]
                if chosen_row is None or chosen_row.get("needs_confirmation"):
                    ref["reasons"].append("the user confirmed this selection (the evidence alone was not enough)")
                    ref["confirmed_by_selection"] = True
                    ref["warnings"].append("This reference was chosen by explicit selection; linkage evidence is weaker than a hash match.")
            else:
                sel = info.get("selected")
                if not sel:
                    cands = info["candidates"]
                    if not cands:
                        return block("No reference drawing was found in the 2D -> 3D history for this part. Upload the original PDF, or run in Standard mode.")
                    return block(f"{len(cands)} candidate drawing(s) were found but none is confirmed by hash or forward-run evidence "
                                 f"(best: {cands[0]['filename']}, confidence {cands[0]['confidence']:.2f}). Confirm one explicitly or upload the PDF.", "REFERENCE_AMBIGUOUS")
                ent = self.index.pdf_by_artifact(sel["artifact_id"])
                if ent is None:
                    return block("The linked reference drawing is no longer available on disk.")
                v = validate_pdf(ent.path)
                if not v["ok"]:
                    return block(f"The linked reference drawing was rejected: {v['error']}", "REFERENCE_PDF_REJECTED")
                pdf, kind = ent.path, "confirmed_link" if sel["link"] == "confirmed" else "history"
                ref.update(sha256=v["sha256"], pages=v["pages"], filename=ent.path.name, confidence=sel["confidence"], link=sel["link"])
                ref["reasons"] += sel["reasons"]
        ref["source_kind"] = kind
        ref["_pdf"] = pdf
        ref["_blocked"] = False
        ref["candidate_summary"] = [{k: c[k] for k in ("artifact_id", "filename", "confidence", "link", "needs_confirmation")} for c in info["candidates"][:5]]
        ref["matched_runs"] = info.get("matched_runs", [])
        return ref


def public_reference(ref: dict) -> dict:
    """The part-level reference dict without private keys (server paths)."""
    return {k: v for k, v in ref.items() if not k.startswith("_")}


class ReferenceServices:
    """Everything a part run needs for reference mode: the history index, the resolver, the extraction cache and an optional model client (tests inject a mock)."""

    def __init__(self, data_dir: Path, roots: Optional[Iterable[Path]] = None, client=None):
        self.data = Path(data_dir)
        self.upload_dir = self.data / "uploads" / "3d-to-2d"
        self.cache_root = self.data / "reference" / "extractions"
        self.index = ReferenceIndex(roots if roots is not None else default_roots(), upload_dir=self.upload_dir / "reference", links_path=self.data / "reference" / "links.json")
        self.resolver = ReferenceResolver(self.index, self.upload_dir)
        self.client = client


def default_roots() -> list[Path]:
    """History roots searched read-only: SF_REFERENCE_ROOTS (os.pathsep separated) or the repo's FINAL_OUTPUTs, FINAL_UI/data and DrawingPDFs."""
    env = os.environ.get("SF_REFERENCE_ROOTS")
    if env:
        return [Path(x) for x in env.split(os.pathsep) if x.strip()]
    repo = Path(__file__).resolve().parents[2]
    return [repo / "FINAL_OUTPUTs", repo / "FINAL_UI" / "data", repo / "DrawingPDFs"]
