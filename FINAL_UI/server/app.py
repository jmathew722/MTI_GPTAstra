"""FastAPI web front-end for the 2D->3D SolidWorks pipeline (McAgent UI).

SINGLE CHANGE vs. the original pipeline_app/webapp/app.py: the pipeline repo is
no longer "the parent directory of webapp/". PROJECT_DIR now comes from the
MCAGENT_REPO environment variable (set by run.sh / run.ps1 / run.bat). User data
(parts/, runs/, UI_Output/, convert cache, conversion log) lives under
MCAGENT_DATA (default FINAL_UI/data/) instead of inside webapp/ or the repo, and
the static frontend is served from FINAL_UI/web/. Routes and payloads are
identical to the original.

Drives the existing CLI (`main.py`) as a subprocess so the proven entrypoint is
untouched. Serves a single-file UI, streams the pipeline's console output live,
and serves the result files (VBA macros, verification report, JSON).

Run:
    ./run.sh --repo /path/to/pipeline/repo     # from FINAL_UI/
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import uuid
import shlex
import shutil
import zipfile
import threading
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Query, Request, UploadFile, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telemetry as _telemetry  # noqa: E402  structured run events (Stage 1)
import costs as _costs  # noqa: E402  ledger cost scopes (Stage 2)
import flags as _flags  # noqa: E402  engineering-flag artifacts (Stage 3)
import estimates as _est  # noqa: E402  run time / cost estimates from finished runs
import scoring_hub as _sh  # noqa: E402  Scoring tab: methodology, persisted evaluations

# FINAL_UI/server/app.py. The pipeline repo (main.py + pipeline/ + samples) is
# external and chosen by the launcher through MCAGENT_REPO.
SERVER_DIR = Path(__file__).resolve().parent
UI_ROOT = SERVER_DIR.parent
WEB_DIR = UI_ROOT / "web"
_repo_env = os.environ.get("MCAGENT_REPO", "").strip()
if not _repo_env:
    raise RuntimeError(
        "MCAGENT_REPO is not set. Start the UI with FINAL_UI/run.sh (or run.ps1 / run.bat) "
        "and --repo <path to a folder containing main.py and pipeline/>."
    )
PROJECT_DIR = Path(_repo_env).expanduser().resolve()
if not (PROJECT_DIR / "main.py").is_file() or not (PROJECT_DIR / "pipeline").is_dir():
    raise RuntimeError(
        f"MCAGENT_REPO={PROJECT_DIR} is not a pipeline repo: it needs main.py and a pipeline/ package."
    )
# User data (never inside the repo or the UI source tree).
DATA_DIR = Path(os.environ.get("MCAGENT_DATA", "").strip() or (UI_ROOT / "data")).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR = DATA_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
# Multi-part working area: parts/<session>/<part>/ holds one part's crop JPEGs
# (the --views-folder for that part); parts/<session>/.thumbs/<part>.jpg holds
# the source thumbnail (kept OUT of the views folder so it is never treated as a
# view); the pipeline writes into parts/<session>/<part>/output/.
PARTS_DIR = DATA_DIR / "parts"
PARTS_DIR.mkdir(parents=True, exist_ok=True)
# Human-facing deliverables: every UI run copies its finished outputs here into a
# folder named after the part, so they are easy to find and open (as opposed to
# the buried per-session working dir under parts/). Re-running a part refreshes
# its folder with the latest outputs.
DELIVER_DIR = DATA_DIR / "UI_Output"
DELIVER_DIR.mkdir(parents=True, exist_ok=True)
# Same per-part deliverables are also mirrored into the user's Downloads folder so
# they can be found outside the project tree.
DOWNLOADS_DIR = Path.home() / "Downloads" / "SolidWorksModel_Parts"

load_dotenv(PROJECT_DIR / ".env")

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".tif", ".tiff", ".bmp"}

# Untouched uploads (PDF/JPG/DWG) are kept per part so the original drawing is
# always delivered next to the generated outputs.
ORIGINALS_DIRNAME = ".originals"

# Photo-app crop name -> (canonical order index, pipeline view name). The pipeline's
# view_ingest classifies views from the filename; naming the uploaded crops this way
# guarantees correct classification + processing order.
VIEW_MAP: dict[str, tuple[int, str]] = {
    "front": (1, "front"),
    "top": (2, "top"),
    "side": (3, "side"),
    "right": (3, "side"),
    "left": (4, "second_side"),
    "back": (4, "second_side"),
    "bottom": (5, "bottom"),
    # The "Full Overview View" dropdown option — the canonical way the overview
    # image is tagged. Saved as 00_full.jpg (OVERVIEW_FILENAME) so view_ingest
    # classifies it as the "full" overview view (whole-part context, and the
    # image the post-build Overview Cross-Verification re-examines).
    "overview": (0, "full"),
    "full": (0, "full"),
}

app = FastAPI(title="MTI 2D->3D Pipeline UI")

# Static assets: the verbatim photo app (Tab 1) and the vendored 3D-viewer libs.
app.mount("/photoapp", StaticFiles(directory=str(WEB_DIR / "photoapp"), html=True), name="photoapp")
app.mount("/vendor", StaticFiles(directory=str(WEB_DIR / "vendor")), name="vendor")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")  # design tokens (shared by both documents)

# id -> {"lines": list[str], "done": bool, "exit": int|None, "output": Path}
RUNS: dict[str, dict] = {}


# Which key the pipeline actually needs depends on EXTRACTION_PROVIDER (pipeline/extractor.py
# DEFAULT_MODELS). Checking the wrong one makes a perfectly configured machine look keyless.
_PROVIDER_KEYS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def _provider() -> str:
    return (os.getenv("EXTRACTION_PROVIDER", "").strip() or "openai").lower()


def _key_name() -> str:
    return _PROVIDER_KEYS.get(_provider(), "OPENAI_API_KEY")


def _has_api_key() -> bool:
    val = os.getenv(_key_name(), "").strip()
    return bool(val) and val != "your_key_here"      # the .env.template placeholder is not a key


def _no_key_message() -> str:
    return (f"No {_key_name()} set — live extraction is unavailable. Set it in the project "
            f".env and restart the UI.")


# The pipeline writes one folder per part here, matching make_part.py so UI runs and CLI runs
# sit side by side. ir_pipeline.run_part() appends the part name itself.
FINAL_OUTPUTS_DIR = Path(
    os.environ.get("MCAGENT_FINAL_OUTPUTS", "").strip() or (PROJECT_DIR.parent / "FINAL_OUTPUTs")
).expanduser().resolve()


def _pipeline_cmd(src: Path, out_dir: Path, no_cache: bool = False, record: bool = False) -> list[str]:
    """argv for one build: the Feature-IR path, native SolidWorks engine.

    `--ir` accepts a single drawing file or a folder of views, so one helper covers both
    intake routes. Every run site goes through here; the three sites previously drifted and
    all passed flags (`--no-export`, `--source-file`) that this repo's main.py rejects.
    """
    flag = "--drawing" if src.is_file() else "--views-folder"
    cmd = [sys.executable, "main.py", flag, str(src), "--output", str(out_dir),
           "--ir", "--engine", "com"]
    if no_cache:
        cmd.append("--no-extract-cache")
    if record:
        cmd.append("--record-solidworks")     # records only the SolidWorks window during the native build
    return cmd


def _samples() -> list[str]:
    """Saved extractions usable for a no-API demo run (e.g. '117C')."""
    names = []
    for p in sorted(PROJECT_DIR.glob("extraction_*.json")):
        stem = p.stem  # extraction_117C
        names.append(stem.replace("extraction_", "", 1))
    return names


def _flatten_copy(out_dir: Path, dest: Path) -> Path | None:
    """Copy a finished run's outputs into ``dest/`` (flat, openable).

    The pipeline writes all of a part's artifacts into a single subfolder of
    ``out_dir`` (named after the part); its contents are copied up so the delivered
    folder holds the files directly (sldprt, stl, macros/, reports, json), plus the
    loose ``token_usage_log.txt`` / summary csv. SolidWorks lock/autosave junk is
    skipped. An existing ``dest`` is replaced. Returns the folder, or None on error."""
    def _skip(name: str) -> bool:
        return name.startswith("~$") or name.startswith("AUTOSAVE_")

    try:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)

        for sub in sorted(p for p in out_dir.iterdir() if p.is_dir() and p.name != ".extraction_cache"):
            for item in sub.iterdir():
                if _skip(item.name):
                    continue
                target = dest / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("~$*", "AUTOSAVE_*"))
                else:
                    shutil.copy2(item, target)
        # Loose top-level files (token log, multiview_summary.csv).
        for f in out_dir.iterdir():
            if f.is_file() and not _skip(f.name):
                shutil.copy2(f, dest / f.name)
        return dest
    except Exception:
        return None


def _deliver_run(out_dir: Path, part_name: str,
                 extra_files: list[Path] | None = None) -> dict:
    """Deliver a finished run's outputs to BOTH the project ``UI_Output/<part>/``
    and the user's ``~/Downloads/SolidWorksModel_Parts/<part>/`` so they are easy
    to find and open. ``extra_files`` (e.g. the untouched original upload) are
    copied alongside. Returns the paths that were written."""
    part = _sanitize(part_name)
    project = _flatten_copy(out_dir, DELIVER_DIR / part)
    downloads = _flatten_copy(out_dir, DOWNLOADS_DIR / part)
    for extra in extra_files or []:
        try:
            if extra and Path(extra).is_file():
                for dest in (project, downloads):
                    if dest:
                        shutil.copy2(extra, Path(dest) / Path(extra).name)
        except Exception:
            pass
    return {
        "project": str(project) if project else None,
        "downloads": str(downloads) if downloads else None,
    }


def _start_run(cmd: list[str], output_dir: Path, run_id: str | None = None,
               deliver_name: str | None = None,
               extra_files: list[Path] | None = None) -> str:
    """Spawn the pipeline CLI and stream its output into RUNS[id]['lines'].

    When ``deliver_name`` is given, a successful run's outputs are also copied into
    ``UI_Output/<deliver_name>/`` so they are easy to find and open."""
    run_id = run_id or uuid.uuid4().hex[:12]
    output_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "lines": [], "done": False, "exit": None, "output": output_dir,
        "proc": None, "started": time.time(), "finished": None, "cancelled": False,
        "deliver_name": deliver_name, "delivered": None, "delivered_downloads": None,
        "extra_files": extra_files or [],
        "telemetry": _telemetry.new_state(),
    }
    RUNS[run_id] = state

    state["lines"].append(f"$ {' '.join(shlex.quote(c) for c in cmd)}")

    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    # Keep rich output plain & wide so the log panel reads cleanly.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("COLUMNS", "120")
    env.setdefault("GPTASTRA_STRUCTURED_EVENTS", "1")   # structured progress + cost events
    env.setdefault("GPTASTRA_AUTO_ENGINEERING_FLAGS", "1")   # automatic red flags over the drawing

    def _worker():
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Force UTF-8 with replacement: the pipeline's rich console emits
                # UTF-8 box-drawing output. Without this, text mode defaults to the
                # Windows locale codec (cp1252), which raises UnicodeDecodeError on
                # the first non-cp1252 byte, kills this reader thread, stops draining
                # the pipe, fills the OS buffer, and hangs the child forever.
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:  # spawn failure
            state["lines"].append(f"[launch error] {type(e).__name__}: {e}")
            state["exit"] = 127
            state["done"] = True
            state["finished"] = time.time()
            return
        state["proc"] = proc
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                text = line.rstrip("\n")
                state["lines"].append(text)
                _telemetry.apply_line(state["telemetry"], text)   # idempotent; ignores ordinary lines
        except Exception as e:
            # A reader failure must never leave the child undrained (that would
            # fill the pipe buffer and hang it). Record it, then kill + reap below.
            state["lines"].append(f"[reader error] {type(e).__name__}: {e}")
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            state["exit"] = proc.wait()
            # Deliver clean, openable copies for a completed, non-cancelled run:
            # one in the project (UI_Output/) and one in the user's Downloads
            # folder. Exit 8 = completed with review flags — the outputs (model,
            # reports, macros) exist and are delivered too; only a hard failure
            # or a cancel skips delivery.
            if state["exit"] in (0, 8) and not state["cancelled"] and deliver_name:
                paths = _deliver_run(output_dir, deliver_name,
                                     extra_files=state.get("extra_files"))
                state["delivered"] = paths.get("project")
                state["delivered_downloads"] = paths.get("downloads")
                if paths.get("project"):
                    state["lines"].append(f"[delivered outputs to] {paths['project']}")
                if paths.get("downloads"):
                    state["lines"].append(f"[delivered outputs to] {paths['downloads']}")
            state["done"] = True
            state["finished"] = time.time()
            # Persist the console transcript with the run so Sheet 4's Console
            # sub-tab works for historical runs, not just the live one.
            try:
                (output_dir / "ui_console.log").write_text(
                    "\n".join(state["lines"]) + "\n", encoding="utf-8")
            except OSError:
                pass

    threading.Thread(target=_worker, daemon=True).start()
    return run_id


def _cancel_run(run_id: str) -> None:
    """Terminate a run's process (and any children it spawned)."""
    state = RUNS[run_id]
    if state["done"]:
        return
    proc = state.get("proc")
    if proc is None:
        raise HTTPException(409, "Run has not started yet")
    state["cancelled"] = True
    state["lines"].append("[cancel requested by user]")
    try:
        if os.name == "nt":
            # taskkill /T also kills any child processes the pipeline spawned.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            proc.terminate()
    except Exception as e:
        state["lines"].append(f"[cancel error] {type(e).__name__}: {e}")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/bridge.js")
def bridge_js():
    return FileResponse(WEB_DIR / "bridge.js", media_type="application/javascript")


# The verbatim photo app references pdf.js at ABSOLUTE root paths (/pdf.min.js,
# /pdf.worker.min.js). Serve them there so the file stays byte-for-byte unmodified.
@app.get("/pdf.min.js")
def pdf_js():
    return FileResponse(WEB_DIR / "pdf.min.js", media_type="application/javascript")


@app.get("/pdf.worker.min.js")
def pdf_worker_js():
    return FileResponse(WEB_DIR / "pdf.worker.min.js", media_type="application/javascript")


@app.get("/api/status")
def status():
    """`engine`/`model` are read from the pipeline's own pinned config, never hard-coded, so
    the header reports what will actually run."""
    model = ""
    try:
        import json as _json
        cfg = _json.loads((PROJECT_DIR / "config" / "models.json").read_text(encoding="utf-8"))
        model = (cfg.get("planner") or {}).get(_provider(), "")
    except Exception:
        model = os.getenv("EXTRACTION_MODEL", "").strip()
    return {
        "live": _has_api_key(),
        "samples": _samples(),
        "provider": _provider(),
        "keyName": _key_name(),
        "model": model,
        "outputs": str(FINAL_OUTPUTS_DIR),
    }


@app.get("/api/samples")
def samples():
    return {"samples": _samples()}


@app.post("/api/run")
async def run(file: UploadFile = File(...)):
    if not _has_api_key():
        raise HTTPException(
            400,
            _no_key_message() + " Or use the demo (runs a saved extraction, no API call).",
        )
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXT)}")

    run_id = uuid.uuid4().hex[:12]
    run_root = RUNS_DIR / run_id
    in_dir = run_root / "input"
    in_dir.mkdir(parents=True, exist_ok=True)
    dest = in_dir / Path(file.filename).name
    dest.write_bytes(await file.read())

    # The pipeline creates FINAL_OUTPUTs/<drawing stem>/ itself (ir_pipeline.run_part).
    out_dir = FINAL_OUTPUTS_DIR / dest.stem
    _start_run(_pipeline_cmd(dest, FINAL_OUTPUTS_DIR), out_dir, run_id=run_id)
    return {"id": run_id}


class DemoReq(BaseModel):
    sample: str | None = None


@app.post("/api/demo")
def demo(req: DemoReq):
    samples = _samples()
    if not samples:
        raise HTTPException(404, "No saved extraction_*.json samples found to demo.")
    sample = req.sample or samples[0]
    if sample not in samples:
        raise HTTPException(404, f"Sample '{sample}' not found. Available: {samples}")

    json_path = PROJECT_DIR / f"extraction_{sample}.json"
    run_id = uuid.uuid4().hex[:12]
    out_dir = RUNS_DIR / run_id / "output"
    # Demo replays a saved extraction through the v1 macro path: --from-json costs nothing and
    # needs no key. It stays in the run sandbox, never FINAL_OUTPUTs, so demo output cannot be
    # mistaken for a real part.
    cmd = [sys.executable, "main.py", "--from-json", str(json_path), "--output", str(out_dir)]
    _start_run(cmd, out_dir, run_id=run_id)
    return {"id": run_id}


@app.get("/api/runs/{run_id}/log")
def log(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id")

    state = RUNS[run_id]

    def gen():
        import time
        idx = 0
        while True:
            lines = state["lines"]
            while idx < len(lines):
                # SSE: escape newlines are not needed (each item is one line).
                yield f"data: {lines[idx]}\n\n"
                idx += 1
            if state["done"] and idx >= len(state["lines"]):
                yield f"event: done\ndata: {state['exit']}\n\n"
                return
            time.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/telemetry")
def run_telemetry(run_id: str):
    """Bounded progress/cost snapshot for a live run (the full stream is the run_events.jsonl artifact)."""
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id")
    return _telemetry_for(RUNS[run_id]["output"])


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id")
    if RUNS[run_id]["done"]:
        return {"ok": True, "already_done": True}
    _cancel_run(run_id)
    return {"ok": True}


def _categorize(name: str) -> str:
    low = name.lower()
    if low.endswith((".vba", ".bas", ".swp", ".swb")):
        return "macro"
    if low.endswith(".json"):
        return "json"
    if "verif" in low or "report" in low or low.endswith((".txt", ".md")):
        return "report"
    return "other"


def _result_files(run_id: str) -> list[Path]:
    state = RUNS.get(run_id)
    if not state:
        return []
    out: Path = state["output"]
    if not out.exists():
        return []
    files = [p for p in out.rglob("*") if p.is_file() and ".extraction_cache" not in p.parts]
    return sorted(files)


@app.get("/api/runs/{run_id}/files")
def files(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id")
    out: Path = RUNS[run_id]["output"]
    items = []
    inline = None
    for p in _result_files(run_id):
        rel = p.relative_to(out).as_posix()
        cat = _categorize(p.name)
        items.append({"name": rel, "size": p.stat().st_size, "category": cat})
        # Inline the first small text report so the UI can render it.
        if inline is None and cat == "report" and p.suffix.lower() in {".txt", ".md"} and p.stat().st_size < 200_000:
            try:
                inline = {"name": rel, "text": p.read_text(encoding="utf-8", errors="replace")}
            except Exception:
                pass
    return {"done": RUNS[run_id]["done"], "exit": RUNS[run_id]["exit"], "files": items, "report": inline}


@app.get("/api/runs/{run_id}/download/{name:path}")
def download(run_id: str, name: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id")
    out: Path = RUNS[run_id]["output"]
    target = (out / name).resolve()
    if out.resolve() not in target.parents and target != out.resolve():
        raise HTTPException(403, "Path outside run output")
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(str(target), filename=target.name)


@app.get("/api/runs/{run_id}/zip")
def zip_run(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id")
    out: Path = RUNS[run_id]["output"]
    files = _result_files(run_id)
    if not files:
        raise HTTPException(404, "No result files to zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(out).as_posix())
    buf.seek(0)
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="results_{run_id}.zip"'},
    )


# ── Multi-view run from photo-app crops (Tab 1 "Run SolidWorks Pipeline") ──────

def _sanitize(name: str) -> str:
    keep = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name.strip())
    return keep.strip("_") or "part"


def _crop_filename(crop_name: str, seq: int) -> str:
    """Map a photo-app crop name to a pipeline-classifiable filename.

    Known views get an ordered ``NN_<view>.jpg`` name so view_ingest classifies
    and orders them; the "Marked View" (annotated drawing) saves as the
    canonical full_marked_view.jpg that view_ingest exposes as
    ``PartViews.marked_view`` and extraction consumes as ground truth; anything
    else keeps its own (sanitized) name and is left for the pipeline to warn
    about / skip."""
    key = crop_name.strip().lower().replace(" ", "_")
    if key in ("marked", "marked_view", "markedview"):
        return MARKED_VIEW_FILENAME
    if key in VIEW_MAP:
        order, view = VIEW_MAP[key]
        return f"{order:02d}_{view}.jpg"
    return f"{_sanitize(crop_name)}.jpg"


@app.post("/api/run-views")
async def run_views(
    part: str = Form("drawing"),
    source: UploadFile | None = File(None),
    crops: list[UploadFile] = File(...),
):
    if not _has_api_key():
        raise HTTPException(400, _no_key_message())
    if not crops:
        raise HTTPException(400, "No cropped views were provided.")

    part_name = _sanitize(part)
    run_id = uuid.uuid4().hex[:12]
    run_root = RUNS_DIR / run_id
    in_dir = run_root / "input" / part_name
    out_dir = FINAL_OUTPUTS_DIR / part_name
    in_dir.mkdir(parents=True, exist_ok=True)

    used: set[str] = set()
    for i, up in enumerate(crops, start=1):
        stem = Path(up.filename or f"view{i}").stem
        fname = _crop_filename(stem, i)
        # Avoid clobbering when two crops map to the same view.
        if fname in used:
            fname = f"{Path(fname).stem}_{i}{Path(fname).suffix}"
        used.add(fname)
        (in_dir / fname).write_bytes(await up.read())

    # Full original drawing: kept for Tab 2's Overview panel AND fed into extraction
    # as whole-part context (saved in the views folder as the "full" overview view).
    # A crop tagged "Full Overview View" is canonical and wins over the source mirror.
    if source is not None:
        src_bytes = await source.read()
        (run_root / "source.jpg").write_bytes(src_bytes)
        if OVERVIEW_FILENAME not in used:
            (in_dir / OVERVIEW_FILENAME).write_bytes(src_bytes)

    # Point at the PART folder, not its parent: --ir takes the part name from the folder name
    # (main.py _run_ir: `part = src.stem if src.is_file() else src.name`), and run_part then
    # creates FINAL_OUTPUTs/<part>/ under the output root.
    _start_run(_pipeline_cmd(in_dir, FINAL_OUTPUTS_DIR), out_dir, run_id=run_id,
               deliver_name=part_name)
    return {"id": run_id, "part": part_name, "views": sorted(used)}


@app.get("/api/runs/{run_id}/source.jpg")
def run_source(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id")
    p = RUNS[run_id]["output"].parent / "source.jpg"
    if not p.is_file():
        raise HTTPException(404, "No source image for this run")
    return FileResponse(str(p), media_type="image/jpeg")


def _all_stls(out: Path) -> list[Path]:
    """Every .stl under out, matched case-insensitively.

    SolidWorks' SaveAs3 writes the extension uppercase (`<part>_ir.STL`). pathlib.rglob
    happens to be case-insensitive on Windows, but relying on that would silently break the
    3D panel anywhere else, so the comparison is explicit.
    """
    if not out.exists():
        return []
    return sorted((p for p in out.rglob("*") if p.is_file() and p.suffix.lower() == ".stl"),
                  key=lambda p: p.as_posix())


def _find_stl(out: Path) -> Path | None:
    """The REAL (SolidWorks) STL — the CadQuery prevalidation STL is excluded."""
    stls = [p for p in _all_stls(out) if p.name.lower() != "prevalidation.stl"]
    return stls[0] if stls else None


def _find_preval_stl(out: Path) -> Path | None:
    hits = [p for p in _all_stls(out) if p.name.lower() == "prevalidation.stl"]
    return hits[0] if hits else None


def _active_stl(out: Path) -> tuple[Path | None, str | None]:
    """(path, source): the SolidWorks STL when built, else the pre-validated
    CadQuery STL (shown with a badge until the real one replaces it)."""
    p = _find_stl(out)
    if p is not None:
        return p, "solidworks"
    p = _find_preval_stl(out)
    if p is not None:
        return p, "prevalidation"
    return None, None


@app.get("/api/runs/{run_id}/model.stl")
def run_stl(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id")
    p, _src = _active_stl(RUNS[run_id]["output"])
    if p is None:
        raise HTTPException(404, "No STL for this run yet")
    return FileResponse(str(p), media_type="model/stl", filename=p.name)


def _first(out: Path, patterns: list[str], exclude: list[str] | None = None) -> Path | None:
    exclude = exclude or []
    for pat in patterns:
        for p in sorted(out.rglob(pat)):
            if any(ex in p.name for ex in exclude):
                continue
            if p.is_file():
                return p
    return None


_INLINE_CAP = 400_000


def _cat(p: Path | None) -> dict:
    if p is None:
        return {"present": False}
    try:
        text = p.read_text(encoding="utf-8", errors="replace") if p.stat().st_size < _INLINE_CAP else None
    except Exception:
        text = None
    return {"present": True, "name": p.name, "text": text}


def _review_items(build_plan: Path | None, review_txt: Path | None) -> dict:
    """Engineering Flags tab payload: the structured severity-ranked items from
    build_plan.json (single source of truth) plus the plain-text report."""
    items = []
    if build_plan is not None:
        try:
            import json as _json

            plan = _json.loads(build_plan.read_text(encoding="utf-8"))
            items = plan.get("engineering_review", []) or []
        except Exception:
            items = []
    text = None
    if review_txt is not None:
        try:
            text = review_txt.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = None
    return {"present": bool(items) or text is not None, "items": items, "text": text}


def _usage_summary(out: Path) -> dict:
    """Token/Cost tab payload from the run's own ledger files (source of truth:
    the same token_usage_log.* the CLI writes)."""
    import json as _json

    jsonl = out / "token_usage_log.jsonl"
    txt = out / "token_usage_log.txt"
    rows = []
    if jsonl.is_file():
        for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(_json.loads(line))
                except Exception:
                    continue
    total_cost = round(sum(r.get("cost_usd", 0.0) for r in rows), 4)
    pname = out.parent.name if out.name == "output" else out.name
    led = _costs.summarize(_costs.read_rows(_costs.ledger_paths(out)), part=pname)
    if led["present"] and led["scopes"]["part"]["cost_usd"] is not None:
        total_cost = float(led["scopes"]["part"]["cost_usd"])   # the pipeline ledger is the source of truth
    ledger_text = None
    if txt.is_file():
        try:
            ledger_text = txt.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return {
        "present": bool(rows) or ledger_text is not None or led["present"],
        "ledger": led,
        "rows": rows,
        "last_run": rows[-1] if rows else None,
        "total_cost_usd": total_cost,
        "text": ledger_text,
    }


def _file_listing(out: Path) -> list[dict]:
    """Files tab payload: every output file with its relative path and size."""
    files = []
    if out.exists():
        for p in sorted(out.rglob("*")):
            if p.is_file() and ".extraction_cache" not in p.parts:
                files.append({"name": p.relative_to(out).as_posix(),
                              "size": p.stat().st_size})
    return files


def _mm_summary(out: Path) -> dict:
    """Must-meet checklist payload for Tab 2: the post-build
    constraint_verification.json wins; prevalidation_report.json is shown until
    the real SolidWorks build replaces it. macro_result.json failures (exact
    failing feature) are folded into ``failed`` so the banner is precise —
    never a generic exit code."""
    import json as _json

    def _load(p: Path | None):
        if p is None:
            return None
        try:
            return _json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return None

    cv = _load(_first(out, ["constraint_verification.json"]))
    pv = _load(_first(out, ["prevalidation_report.json"]))
    mc = _load(_first(out, ["must_meet_constraints.json"])) or {}
    data, stage = (cv, "post_build") if cv else (pv, "prevalidation" if pv else None)

    results = (data or {}).get("constraints", []) or []
    failed = list((data or {}).get("failed_constraints", []) or [])
    if not failed and (data or {}).get("error"):
        failed = [f"verification error: {data['error']}"]

    # macro_result.json: the COM builder writes {"results": [...]}; the VBA
    # macros append JSON Lines. Read both shapes.
    macro_results: list = []
    mr_path = _first(out, ["macro_result.json"])
    if mr_path is not None:
        raw = _load(mr_path)
        if isinstance(raw, dict):
            macro_results = raw.get("results", []) or []
        else:
            try:
                for line in mr_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line:
                        macro_results.append(_json.loads(line))
            except Exception:
                macro_results = []
    for r in macro_results:
        if str(r.get("status", "")).upper() == "FAIL":
            failed.append(f"feature {r.get('feature', '?')} FAILED: {r.get('detail', '')}")

    return {
        "present": bool(results or mc.get("constraints")),
        "stage": stage,
        "ok": (data or {}).get("ok"),
        "results": results,
        "constraints": mc.get("constraints", []),
        "failed": failed,
        "macro_results": macro_results,
    }


def _overview_analysis_summary(out: Path) -> dict:
    """Stage 1.5 payload for the collapsible panel under the Full Overview View:
    the parsed overview_analysis.json (holistic cross-view read of the sheet)."""
    import json as _json

    p = _first(out, ["overview_analysis.json"])
    if p is None:
        return {"present": False}
    try:
        data = _json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {"present": False}
    return {"present": True, "name": p.name, "data": data}


# ── Feature-IR artifacts ──────────────────────────────────────────────────────
# The IR path writes plan.json / ir_report.json / feature_map.json where the v1 path wrote
# *_build_plan.json / *verification_report.txt / *model_check.txt. The tabs are unchanged:
# only what feeds them is widened, so a v1 run and an IR run both render.

def _load_json(p: Path | None) -> dict | None:
    if p is None or not p.is_file():
        return None
    try:
        import json as _json
        return _json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _ir_verification_text(rep: dict) -> str:
    """ir_report.json rendered as the verification report the tab expects."""
    L = [f"Part:            {rep.get('part', '')}",
         f"Gate 1:          {rep.get('gate1') or 'n/a'}",
         f"Features planned:{rep.get('planned', 0):>4}",
         f"SolidWorks build:{'  ' + ('PASSED' if rep.get('sw_ok') else 'FAILED' if rep.get('sw_ok') is False else 'not run')}",
         f"Reference STEP:  {Path(rep.get('reference_step') or '').name or 'none'}",
         f"Volume:          {rep.get('volume')}",
         f"Cost:            ${rep.get('cost_usd', 0.0):.4f}"]
    feats = rep.get("sw_features") or {}
    if feats:
        L += ["", "Per-feature SolidWorks result (each volume-checked against the reference):"]
        L += [f"  {k:<6} {v}" for k, v in sorted(feats.items())]
    conv = rep.get("conventions") or []
    if conv:
        L += ["", "MTI conventions applied:"] + [f"  - {c}" for c in conv]
    if rep.get("error"):
        L += ["", f"ERROR: {rep['error']}"]
    return "\n".join(L) + "\n"


def _ir_model_check_text(fmap: dict, rep: dict | None) -> str:
    """feature_map.json rendered as the Model Check tab: what the reference measured."""
    bb = fmap.get("bbox") or []
    L = [f"Part:    {fmap.get('part', '')}",
         f"Units:   {fmap.get('units', '')}",
         f"Volume:  {fmap.get('volume')}"]
    if len(bb) == 6:
        L.append(f"Bounding box: {bb[3]-bb[0]:.4f} x {bb[4]-bb[1]:.4f} x {bb[5]-bb[2]:.4f}")
    built = fmap.get("features") or []
    L += ["", f"Features built in the reference ({len(built)}): " + ", ".join(built)]
    skipped = fmap.get("skipped") or {}
    if skipped:
        L += ["", "Skipped (the drawing does not settle these):"]
        L += [f"  {k}: {v}" for k, v in skipped.items()]
    if rep:
        for key, label in (("sw_bbox_ok", "SolidWorks bounding box matches reference"),
                           ("sw_volume_ok", "SolidWorks volume matches reference")):
            if rep.get(key) is not None:
                L.append(f"{label}: {'yes' if rep[key] else 'NO'}")
    return "\n".join(L) + "\n"


def _ir_review(rep: dict) -> list[dict]:
    """IR questions and advisory MTI findings as Engineering-Flags items.

    Severity ladder is the UI's existing one. An unresolved feature blocks geometry, so it is
    HIGH; an mti_review finding is advisory by design (never blocks a part) so it is LOW.
    """
    items = [{"severity": "HIGH", "code": "UNRESOLVED", "message": q,
              "detail": "The drawing does not define this. The pipeline asked instead of guessing."}
             for q in (rep.get("questions") or [])]
    items += [{"severity": "LOW", "code": "MTI_PRACTICE", "message": m,
               "detail": "Advisory MTI modeling practice. Never blocks a part."}
              for m in (rep.get("mti_review") or [])]
    items += [{"severity": "MEDIUM", "code": "FLAGGED", "message": f,
               "detail": "Planned with a justification; worth a reviewer's eye."}
              for f in (rep.get("flagged") or [])]
    return items


def _telemetry_for(out: Path) -> dict:
    """Structured telemetry for an output dir: the live run writing to it, else a replay of its
    saved run_events.jsonl, else an explicitly labeled legacy placeholder."""
    out_r = Path(out).resolve()
    live = [s for s in RUNS.values() if Path(s["output"]).resolve() == out_r
            and s.get("telemetry", {}).get("run_id")]
    active = [s for s in RUNS.values() if Path(s["output"]).resolve() == out_r and not s.get("done")]
    if live:
        newest = max(live, key=lambda s: s.get("started") or 0)
        snap = dict(newest["telemetry"])
    elif active:
        # A run is writing here but has not emitted its first event yet: never replay the PREVIOUS run's saved events
        # (it would show that run's failure as the new run's state).
        snap = _telemetry.legacy_state()
    else:
        events = _telemetry.find_events_file(out_r)
        snap = (_telemetry.replay_file(events) if events else None) or _telemetry.legacy_state()
    if snap.get("source") == "structured":
        snap["events_artifact"] = _telemetry.EVENTS_NAME
    return snap


def _current_source_sha(session: str | None, part: str) -> str | None:
    """SHA-256 of the drawing the pipeline reads for this part NOW (the untouched original, else the full-sheet
    image). Engineering-flag overlays are only drawn when this equals the hash they were computed for."""
    if not session:
        return None
    try:
        sdir = _session_dir(session)
    except HTTPException:
        return None
    cands = sorted((sdir / ORIGINALS_DIRNAME).glob(f"{_sanitize(part)}.*")) if (sdir / ORIGINALS_DIRNAME).is_dir() else []
    cands = [p for p in cands if p.is_file()] or sorted((sdir / _sanitize(part)).glob("00_full.*"))
    if not cands:
        return None
    import hashlib
    h = hashlib.sha256()
    with open(cands[0], "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _flags_for(out: Path, session: str | None) -> dict:
    pname = out.parent.name if out.name == "output" else out.name
    tel = _telemetry_for(out)
    return _flags.load_flags(out, current_sha=_current_source_sha(session, pname),
                             latest_run_id=tel.get("run_id") if tel.get("source") == "structured" else None)


def _markup_for(out: Path, session: str | None) -> dict:
    """Post-run Engineering Markup summary. Separate from the human pre-run full_marked_view.jpg."""
    pname = out.parent.name if out.name == "output" else out.name
    return _flags.load_markup(out, current_sha=_current_source_sha(session, pname))


def _recording_capability() -> dict:
    """Can this machine record the SolidWorks window? Same interpreter as the pipeline child, so the check is truthful."""
    import importlib.util as u
    if sys.platform != "win32":
        return {"available": False, "backend": None, "encoder": None, "reason": "Recording needs Windows."}
    have = lambda m: u.find_spec(m) is not None    # noqa: E731
    if not (have("numpy") and have("cv2")):
        return {"available": False, "backend": None, "encoder": None, "reason": "Recording needs numpy and opencv-python."}
    backend = "wgc" if have("windows_capture") else ("gdi" if have("win32gui") and have("win32ui") else None)
    if backend is None:
        return {"available": False, "backend": None, "encoder": None,
                "reason": "No window-capture backend (pip install windows-capture)."}
    return {"available": True, "backend": backend,
            "encoder": "h264" if have("imageio_ffmpeg") else "webm", "reason": ""}


def _recording_for(out: Path, session: str | None) -> dict:
    """SolidWorks build recording summary (manifest only; the video is served by its own endpoint)."""
    pname = out.parent.name if out.name == "output" else out.name
    out_r = Path(out).resolve()
    active = any(Path(s["output"]).resolve() == out_r and not s.get("done") for s in RUNS.values())
    return _flags.load_recording(out, current_sha=_current_source_sha(session, pname), run_active=active)


def _categorize_output(out: Path, session: str | None = None) -> dict:
    """Categorise a pipeline output dir into the shape the output tabs consume.
    Shared by run-id-scoped and per-part outputs so both render identically —
    the UI reads the SAME files written to disk (one source of truth)."""
    extraction = _first(out, ["*_extraction.json", "*extraction*.json"], exclude=["resolved"])
    resolved = _first(out, ["*_resolved_extraction.json", "*resolved*.json"])
    build_plan = _first(out, ["*build_plan*.json", "**/build_plan*.json"]) or _first(out, ["plan.json"])
    verification = _first(out, ["*verification_report*.txt", "*verification*.txt"])
    model_check = _first(out, ["*model_check*.txt", "*model_validation*.txt", "*validation_report*.txt"])
    review_txt = _first(out, ["*_engineering_review.txt"])

    ir_report = _load_json(_first(out, ["ir_report.json"]))
    ir_fmap = _load_json(_first(out, ["feature_map.json"]))

    macros_files = []
    if out.exists():
        for m in sorted(out.rglob("*.vba")):
            try:
                txt = m.read_text(encoding="utf-8", errors="replace") if m.stat().st_size < _INLINE_CAP else "(too large to inline)"
            except Exception:
                txt = "(unreadable)"
            macros_files.append({"name": m.relative_to(out).as_posix(), "text": txt})

    stl, stl_source = _active_stl(out)

    # v1 artifacts win when present; IR equivalents fill in otherwise.
    verification_cat = _cat(verification)
    if not verification_cat["present"] and ir_report is not None:
        verification_cat = {"present": True, "name": "ir_report.json",
                            "text": _ir_verification_text(ir_report)}
    model_check_cat = _cat(model_check)
    if not model_check_cat["present"] and ir_fmap is not None:
        model_check_cat = {"present": True, "name": "feature_map.json",
                           "text": _ir_model_check_text(ir_fmap, ir_report)}
    review_cat = _review_items(build_plan, review_txt)
    if not review_cat["present"] and ir_report is not None:
        ir_items = _ir_review(ir_report)
        review_cat = {"present": bool(ir_items), "items": ir_items, "text": None}

    has_any = any(x is not None for x in (extraction, resolved, build_plan, verification, model_check)) \
        or bool(macros_files) or ir_report is not None or ir_fmap is not None
    # Compact IR facts for the frontend's verdict/tracker logic (McA.runstate, McA.stages): the
    # IR path has no multiview_summary.csv (that is v1-only), so deriveVerdict/finalize read
    # this instead of falling through to "unknown" for every successful IR run.
    ir_report_cat = ({"present": True, **{k: ir_report.get(k) for k in
                      ("part", "gate1", "planned", "questions", "sw_ok", "error", "cost_usd")}}
                     if ir_report is not None else {"present": False})
    return {
        "has_any": has_any,
        "stl_mtime": int(stl.stat().st_mtime) if stl else 0,
        "stl_source": stl_source,
        "categories": {
            "extraction": _cat(extraction),
            "resolved": _cat(resolved),
            "build_plan": _cat(build_plan),
            "verification": verification_cat,
            "model_check": model_check_cat,
            "review": review_cat,
            "ir_report": ir_report_cat,
            "usage": _usage_summary(out),
            "telemetry": _telemetry_for(out),
            "flags": _flags_for(out, session),
            "engineering_markup": _markup_for(out, session),
            "recording": _recording_for(out, session),
            "macros": {"present": bool(macros_files), "files": macros_files},
            "sldprt": {"present": bool(_first(out, ["*.sldprt"]))},
            "stl": {"present": stl is not None, "name": stl.name if stl else None,
                    "source": stl_source},
            "must_meet": _mm_summary(out),
            "overview_analysis": _overview_analysis_summary(out),
            "console": _cat(_first(out, ["ui_console.log"])),
            "files": {"present": out.exists(), "list": _file_listing(out)},
        },
    }


@app.get("/api/runs/{run_id}/outputs")
def run_outputs(run_id: str):
    """Categorised pipeline artifacts for the output tabs. Each category reports
    presence + inline text so a tab can render the file as soon as it is written."""
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id")
    state = RUNS[run_id]
    out: Path = state["output"]
    payload = _categorize_output(out)
    payload.update({
        "done": state["done"],
        "exit": state["exit"],
        "source": (out.parent / "source.jpg").is_file(),
        "started": state.get("started"),
        "finished": state.get("finished"),
        "cancelled": state.get("cancelled", False),
        "delivered": state.get("delivered"),
        "delivered_downloads": state.get("delivered_downloads"),
    })
    return payload


# ── DWG intake: convert to a raster PNG server-side ────────────────────────────

# Common install locations of the free ODA File Converter (DWG -> DXF).
_ODA_GLOBS = (
    r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
    r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe",
)


def _find_oda_converter() -> str | None:
    import glob as _glob

    exe = shutil.which("ODAFileConverter")
    if exe:
        return exe
    for pattern in _ODA_GLOBS:
        hits = sorted(_glob.glob(pattern))
        if hits:
            return hits[-1]  # newest version
    return None


def _dxf_layouts(dxf_path: Path) -> list[str]:
    """Non-empty layouts of a DXF: 'Model' plus any paper-space sheets that
    actually contain entities (empty default sheets are noise, not choices)."""
    import ezdxf

    doc = ezdxf.readfile(str(dxf_path))
    names = []
    if len(doc.modelspace()) > 0:
        names.append("Model")
    for name in doc.layout_names_in_taborder():
        if name == "Model":
            continue
        try:
            if len(doc.layout(name)) > 0:
                names.append(name)
        except Exception:
            continue
    return names or ["Model"]


def _render_dxf_to_png(dxf_path: Path, png_path: Path, layout: str = "Model") -> None:
    """Render one DXF layout/sheet to a high-resolution PNG via ezdxf+matplotlib."""
    import matplotlib

    matplotlib.use("Agg")
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    import matplotlib.pyplot as plt

    doc = ezdxf.readfile(str(dxf_path))
    space = doc.modelspace() if layout in ("", "Model") else doc.layout(layout)
    fig = plt.figure(figsize=(20, 14))
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    # Force BLACK line work on a WHITE page. Without this, entities drawn in
    # the DXF default color (7 = white on AutoCAD's dark canvas) render
    # white-on-white and the "converted" image is blank paper.
    try:
        from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration

        config = Configuration(background_policy=BackgroundPolicy.WHITE,
                               color_policy=ColorPolicy.BLACK)
        Frontend(ctx, MatplotlibBackend(ax), config=config).draw_layout(space, finalize=True)
    except ImportError:  # older ezdxf without Configuration policies
        ctx.set_current_layout(space)
        Frontend(ctx, MatplotlibBackend(ax)).draw_layout(space, finalize=True)
    ax.set_facecolor("#ffffff")
    fig.patch.set_facecolor("#ffffff")
    fig.savefig(str(png_path), dpi=150, facecolor="#ffffff")
    plt.close(fig)


# Converted CAD artifacts are cached next to the uploads and every conversion is
# logged (source format, tool, output) so a bad artifact is traceable later.
CONVERT_CACHE = DATA_DIR / ".convert_cache"
CONVERSION_LOG = DATA_DIR / "conversion_log.jsonl"


def _log_conversion(source_name: str, source_format: str, tool: str,
                    output: str, n_bytes: int) -> None:
    import datetime

    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": source_name, "source_format": source_format,
        "tool": tool, "output": output, "bytes": n_bytes,
    }
    try:
        with CONVERSION_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


_EDRAWINGS_SUFFIXES = (".edrw", ".eprt", ".easm")


@app.post("/api/convert-dwg")
async def convert_dwg(file: UploadFile = File(...), layout: str = Form("")):
    """Convert an uploaded CAD file (DWG, DXF, or eDrawings) to a viewable PNG.

    - DXF renders directly (ezdxf+matplotlib). DWG converts DWG→DXF first via the
      free ODA File Converter; when it is missing a clear 422 explains exactly
      what to install — never a silent failure.
    - Multi-sheet DWG/DXF: when the file has more than one non-empty layout and
      no ``layout`` was chosen, a JSON body {"layouts": [...]} is returned so the
      client can offer a sheet picker (mirrors multi-page PDF handling).
    - eDrawings (.edrw/.eprt/.easm): a true interactive viewer is not feasible
      server-side, so the largest embedded raster preview is extracted and
      returned with ``X-Static-Preview: 1`` — the client must label it a static
      preview, not the interactive model.

    Responses carry ``X-Source-Format`` / ``X-Conversion-Tool``; every
    conversion is cached (.convert_cache) and logged (conversion_log.jsonl).
    """
    import hashlib
    import tempfile

    name = Path(file.filename or "drawing.dwg").name
    suffix = Path(name).suffix.lower()
    if suffix not in (".dwg", ".dxf") + _EDRAWINGS_SUFFIXES:
        raise HTTPException(
            400, f"Expected a .dwg, .dxf, or eDrawings (.edrw/.eprt/.easm) file, got '{suffix}'.")

    blob = await file.read()
    digest = hashlib.sha256(blob + layout.encode("utf-8")).hexdigest()[:32]
    CONVERT_CACHE.mkdir(exist_ok=True)
    cached = CONVERT_CACHE / f"{digest}.png"
    src_format = "edrawings" if suffix in _EDRAWINGS_SUFFIXES else suffix.lstrip(".")
    headers = {"X-Source-Format": src_format}
    if src_format == "edrawings":
        headers["X-Static-Preview"] = "1"

    if cached.is_file():
        _log_conversion(name, src_format, "cache", cached.name, cached.stat().st_size)
        headers["X-Conversion-Tool"] = "cache"
        return Response(cached.read_bytes(), media_type="image/png", headers=headers)

    # ── eDrawings: extract the embedded static preview ──────────────────────
    if src_format == "edrawings":
        from preview_extract import extract_preview_png

        png_bytes = extract_preview_png(blob)
        if png_bytes is None:
            raise HTTPException(
                422,
                f"'{name}' contains no extractable raster preview. A server-side "
                "interactive eDrawings view is not available in this environment — "
                "open the file in eDrawings and export a PDF or PNG (File → Save As), "
                "then upload that.",
            )
        cached.write_bytes(png_bytes)
        _log_conversion(name, "edrawings", "preview_extract(embedded raster)",
                        cached.name, len(png_bytes))
        headers["X-Conversion-Tool"] = "preview_extract"
        return Response(png_bytes, media_type="image/png", headers=headers)

    # ── DWG/DXF ──────────────────────────────────────────────────────────────
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        raise HTTPException(
            422,
            "DWG/DXF support needs the 'ezdxf' and 'matplotlib' Python packages. "
            "Run: pip install -r FINAL_UI/server/requirements-ui.txt and restart the UI.",
        )

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        src = tdir / name
        src.write_bytes(blob)
        tool = "ezdxf+matplotlib"

        if suffix == ".dwg":
            # No-ODA engine chain: ezdwg (pip) → SolidWorks translator (COM,
            # handles even R13 files) → ODA if it happens to be installed.
            sys.path.insert(0, str(PROJECT_DIR))
            from pipeline.vector_extract.dwg_convert import detect_dwg_version, dwg_to_dxf

            conv_notes: list[str] = []
            dxf_out = tdir / (src.stem + "_converted.dxf")
            engine = dwg_to_dxf(src, dxf_out, conv_notes)
            if engine is None:
                version = detect_dwg_version(src)
                raise HTTPException(
                    422,
                    f"Could not convert '{name}' (DWG {version}). Tried: "
                    + " | ".join(conv_notes)
                    + " — export the drawing as DXF or PDF and upload that instead.",
                )
            src = dxf_out
            tool = f"{engine} + ezdxf+matplotlib"

        # Multi-sheet: offer the choice before rendering anything (like PDF pages).
        try:
            layouts = _dxf_layouts(src)
        except Exception as e:
            raise HTTPException(422, f"Could not read '{name}': {type(e).__name__}: {e}")
        if len(layouts) > 1 and not layout:
            return JSONResponse({"layouts": layouts, "source_format": src_format},
                                headers=headers)
        chosen = layout or layouts[0]
        if chosen not in layouts:
            raise HTTPException(400, f"Unknown layout '{chosen}'; available: {layouts}")

        png = tdir / "render.png"
        try:
            _render_dxf_to_png(src, png, layout=chosen)
        except Exception as e:
            raise HTTPException(422, f"Could not render '{name}' ({chosen}): "
                                     f"{type(e).__name__}: {e}")
        data = png.read_bytes()
        cached.write_bytes(data)
        _log_conversion(name, src_format, tool, f"{cached.name} (layout={chosen})", len(data))
        headers["X-Conversion-Tool"] = tool
        headers["X-Layout"] = chosen
        return Response(data, media_type="image/png", headers=headers)


# ── Multi-part working set (Tab 1 part selector + per-part run) ────────────────

def _safe_session(session: str) -> str:
    s = "".join(c for c in (session or "") if c.isalnum() or c in "-_")
    if not s:
        raise HTTPException(400, "Invalid session id")
    return s


def _session_dir(session: str) -> Path:
    return PARTS_DIR / _safe_session(session)


def _part_output_dir(session: str, part: str) -> Path:
    """Where a part's build artifacts actually live.

    /api/run-part and /api/run-views write to FINAL_OUTPUTS_DIR/<part>/ (ir_pipeline.run_part
    appends the part name itself) so a UI run and a make_part.py run of the same part share
    one folder -- the single source of truth. Every route that READS a part's outputs must
    resolve the same way or a successful run shows as empty in the UI.
    Falls back to the legacy per-session "<session>/<part>/output" layout for runs made before
    this folder existed, so old sessions keep working."""
    p = _sanitize(part)
    final = FINAL_OUTPUTS_DIR / p
    if final.is_dir():
        return final
    return _session_dir(session) / p / "output"


# The full drawing is stored in the views folder under this name so view_ingest
# classifies it as the "full" overview view (whole-part extraction context). It is
# not one of the orthographic views, so it is excluded from the view count/list.
OVERVIEW_FILENAME = "00_full.jpg"

# Image types accepted in a part's views folder (crop flow writes .jpg; the
# parts-folder upload keeps whatever the preprocessed folders contain).
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
# Filename stems view_ingest treats as the overview/full drawing.
_OVERVIEW_STEMS = ("full", "overview", "isometric", "iso")


def _part_images(pdir: Path) -> list[Path]:
    return sorted(p for p in pdir.iterdir()
                  if p.is_file() and p.suffix.lower() in IMG_EXTS)


def _is_overview_image(p: Path, part_name: str) -> bool:
    stem = p.stem.lower()
    norm = "".join(c for c in stem if c.isalnum())
    part_norm = "".join(c for c in part_name.lower() if c.isalnum())
    return (p.name == OVERVIEW_FILENAME
            or any(k in stem for k in _OVERVIEW_STEMS)
            or (bool(part_norm) and norm == part_norm))


def _find_overview_image(pdir: Path) -> Path | None:
    """The part's overview drawing: 00_full.jpg from the crop flow, else the
    file the pipeline itself would classify as the full/overview view."""
    exact = pdir / OVERVIEW_FILENAME
    if exact.is_file():
        return exact
    for p in _part_images(pdir):
        if p.name == MARKED_VIEW_FILENAME:
            continue  # the annotated composite is not the source overview
        if _is_overview_image(p, pdir.name):
            return p
    return None


META_NAME = ".meta.json"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_epoch(s: str | None) -> float | None:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _read_meta(pdir: Path) -> dict:
    try:
        d = json.loads((pdir / META_NAME).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _touch_meta(pdir: Path, **fields) -> None:
    """Persist created_at once (UTC) and any last_run_at update. Never fatal."""
    try:
        m = _read_meta(pdir)
        m.setdefault("created_at", _now_iso())
        m.update({k: v for k, v in fields.items() if v is not None})
        (pdir / META_NAME).write_text(json.dumps(m), encoding="utf-8")
    except OSError:
        pass


def _part_times(sdir: Path, pdir: Path) -> dict:
    """Creation time and latest activity (a project creation or a run/update event, never thumbnail
    generation or page views). Values are epoch seconds or None when not trustworthy ("unknown")."""
    meta = _read_meta(pdir)
    created = _iso_epoch(meta.get("created_at"))
    src = "recorded"
    if created is None:      # older parts: the upload's own file time is the only trustworthy record
        odir = sdir / ORIGINALS_DIRNAME
        cands = [p.stat().st_mtime for p in odir.glob(pdir.name + ".*")] if odir.is_dir() else []
        cands += [p.stat().st_mtime for p in (pdir / OVERVIEW_FILENAME,) if p.is_file()]
        created, src = (min(cands), "file") if cands else (None, "unknown")
    events = [created] if created else []
    run = _iso_epoch(meta.get("last_run_at"))
    if run:
        events.append(run)
    ev = FINAL_OUTPUTS_DIR / pdir.name / "run_events.jsonl"
    if ev.is_file():
        for r in _est._jsonl(ev):
            t = _iso_epoch(r.get("occurred_at"))
            if t and r.get("kind") in ("run.started", "run.completed", "run.failed", "run.cancelled"):
                events.append(t)
    return {"created_at": created, "created_source": src, "last_activity": max(events) if events else None}


def _list_parts(sdir: Path) -> list[dict]:
    if not sdir.is_dir():
        return []
    parts = []
    for pdir in sorted(p for p in sdir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        views = sorted(v.name for v in _part_images(pdir)
                       if not _is_overview_image(v, pdir.name))
        out = _part_output_dir(sdir.name, pdir.name)
        fmt_file = pdir / ".source_format"
        # The must-meet spec (authoritative) wins; legacy notes.txt still shows.
        notes_text = ""
        for nf in (pdir / "must_meet_spec.txt", pdir / "notes.txt"):
            if nf.is_file():
                notes_text = nf.read_text(encoding="utf-8", errors="replace")[:20000]
                break
        parts.append({
            "name": pdir.name,
            "n_views": len(views),
            "views": views,
            "has_output": out.is_dir() and _categorize_output(out)["has_any"],
            "has_overview": _find_overview_image(pdir) is not None,
            # The Full Overview View + Marked View are ALSO pulled into the run
            # (overview as whole-part context, marked as hole-placement ground
            # truth) — surfaced so the Pipeline tab shows every image it uses.
            "has_marked": (pdir / MARKED_VIEW_FILENAME).is_file(),
            "has_original": _source_for_preview(sdir, pdir.name) is not None,
            "has_thumb": (sdir / ".thumbs" / f"{pdir.name}.jpg").is_file(),
            "source_format": fmt_file.read_text(encoding="utf-8").strip()
                             if fmt_file.is_file() else "",
            "notes": notes_text,
            **_part_times(sdir, pdir),
        })
    # Newest activity first (numeric, stable tie-break on the name); unknown dates sort last.
    parts.sort(key=lambda p: (-(p["last_activity"] or 0), p["name"].lower()))
    return parts


def _write_thumbnail(sdir: Path, part_name: str, image_path: Path) -> None:
    """Small JPEG thumbnail for the parts list (never fatal)."""
    try:
        from PIL import Image

        thumbs = sdir / ".thumbs"
        thumbs.mkdir(exist_ok=True)
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            im.thumbnail((360, 360))
            im.save(thumbs / f"{part_name}.jpg", "JPEG", quality=85)
    except Exception:
        pass


@app.post("/api/session")
def new_session():
    sid = uuid.uuid4().hex[:12]
    (PARTS_DIR / sid).mkdir(parents=True, exist_ok=True)
    return {"session": sid}


@app.post("/api/parts")
async def add_part(
    session: str = Form(...),
    part: str = Form("drawing"),
    source_format: str = Form(""),
    notes: str = Form(""),
    source: UploadFile | None = File(None),
    original: UploadFile | None = File(None),
    # Views are optional: the IR path reads the full sheet (pipeline/ir_pipeline.py
    # images_for), so a part with zero crops and just a drawing is a complete input. The
    # cropper is still available for the occasional part that benefits from separate
    # front/side crops; it is never required.
    crops: list[UploadFile] = File(default_factory=list),
):
    if not crops and source is None and original is None:
        raise HTTPException(400, "No drawing was provided.")
    sdir = _session_dir(session)
    sdir.mkdir(parents=True, exist_ok=True)
    part_name = _sanitize(part)
    pdir = sdir / part_name
    # Re-adding a part replaces its crops (fresh set), but keeps any prior output.
    if pdir.exists():
        for old in pdir.glob("*.jpg"):
            old.unlink()
    pdir.mkdir(parents=True, exist_ok=True)
    _touch_meta(pdir)
    # Remember what kind of file this part came from (PDF / DWG / eDrawings /
    # image) so the verification view can label the source correctly.
    if source_format.strip():
        (pdir / ".source_format").write_text(source_format.strip()[:64], encoding="utf-8")

    # Human-authored MUST-MEET SPECIFICATIONS (authoritative, tier 0). Saved as
    # must_meet_spec.txt (Stage 2.6 parses it into MM constraints that override
    # vision extraction) AND as notes.txt (legacy per-line grading) — same text,
    # discovered by the pipeline in the views folder.
    _write_spec_files(pdir, notes)

    used: set[str] = set()
    for i, up in enumerate(crops, start=1):
        stem = Path(up.filename or f"view{i}").stem
        fname = _crop_filename(stem, i)
        if fname in used:
            fname = f"{Path(fname).stem}_{i}{Path(fname).suffix}"
        used.add(fname)
        (pdir / fname).write_bytes(await up.read())

    if source is not None:
        src_bytes = await source.read()
        thumbs = sdir / ".thumbs"
        thumbs.mkdir(exist_ok=True)
        (thumbs / f"{part_name}.jpg").write_bytes(src_bytes)
        # Also feed the FULL drawing into extraction as whole-part context: saved in
        # the views folder as an overview view (00_full.jpg -> classified "full").
        # A crop explicitly tagged "Full Overview View" is the canonical overview
        # and takes precedence — never clobber it with the mirrored source.
        if OVERVIEW_FILENAME not in used:
            (pdir / OVERVIEW_FILENAME).write_bytes(src_bytes)

    # Keep the untouched original upload (PDF/JPG/DWG) OUTSIDE the views folder
    # so it is never mis-classified as a view; it is delivered with the outputs.
    if original is not None:
        odir = sdir / ORIGINALS_DIRNAME
        odir.mkdir(exist_ok=True)
        ext = Path(original.filename or "").suffix.lower() or ".bin"
        for old in odir.glob(f"{part_name}.*"):
            old.unlink()
        (odir / f"{part_name}{ext}").write_bytes(await original.read())

    return {"session": _safe_session(session), "part": part_name, "parts": _list_parts(sdir)}


@app.get("/api/parts")
def list_parts(session: str):
    return {"session": _safe_session(session), "parts": _list_parts(_session_dir(session))}


@app.post("/api/parts/upload-batch")
async def upload_parts_batch(
    session: str = Form(...),
    paths: list[str] = Form(...),
    files: list[UploadFile] = File(...),
):
    """Upload a whole FOLDER OF PARTS (each subfolder = one preprocessed part:
    view images named per the --views-folder conventions plus optional
    notes/must_meet_spec txt files). Files are written VERBATIM into
    ``parts/<session>/<part>/`` — the exact layout the CLI runs unchanged —
    so Run Pipeline processes each part fully, one at a time.

    ``paths`` carries each file's folder-relative path (webkitRelativePath),
    parallel to ``files``: "<root>/<part>/<file>" (or "<part>/<file>" when a
    single part folder was selected)."""
    if len(paths) != len(files):
        raise HTTPException(400, "paths and files must be parallel lists")
    sdir = _session_dir(session)
    sdir.mkdir(parents=True, exist_ok=True)

    TXT_EXTS = {".txt"}
    added: dict[str, int] = {}
    skipped = 0
    for rel, up in zip(paths, files):
        comps = [c for c in rel.replace("\\", "/").split("/") if c and c not in (".", "..")]
        if len(comps) < 2:
            skipped += 1
            continue
        # "<root>/<part>/.../<file>" -> part = the folder directly containing
        # the file when nested, else the first-level folder.
        part_raw = comps[-2] if len(comps) >= 3 else comps[0]
        fname = comps[-1]
        if fname.startswith(".") or part_raw.startswith("."):
            skipped += 1
            continue
        ext = Path(fname).suffix.lower()
        if ext not in IMG_EXTS and ext not in TXT_EXTS:
            skipped += 1
            continue
        part_name = _sanitize(part_raw)
        pdir = sdir / part_name
        pdir.mkdir(parents=True, exist_ok=True)
        data = await up.read()
        if not data:
            skipped += 1
            continue
        (pdir / fname).write_bytes(data)
        added[part_name] = added.get(part_name, 0) + 1
        _touch_meta(pdir)

    # notes.txt mirror (legacy grading) + thumbnails for every touched part.
    for part_name in added:
        pdir = sdir / part_name
        spec = pdir / "must_meet_spec.txt"
        legacy = pdir / "notes.txt"
        if spec.is_file() and not legacy.is_file():
            legacy.write_text(spec.read_text(encoding="utf-8", errors="replace"),
                              encoding="utf-8")
        thumb_src = _find_overview_image(pdir)
        if thumb_src is None:
            imgs = _part_images(pdir)
            thumb_src = imgs[0] if imgs else None
        if thumb_src is not None:
            _write_thumbnail(sdir, part_name, thumb_src)

    if not added:
        raise HTTPException(400, "No part folders with images/txt files were found "
                                 "in the selected folder.")
    return {"session": _safe_session(session), "added": sorted(added),
            "n_files": sum(added.values()), "n_skipped": skipped,
            "parts": _list_parts(sdir)}


def _source_for_preview(sdir: Path, part: str) -> Path | None:
    odir = sdir / ORIGINALS_DIRNAME
    if odir.is_dir():
        for p in sorted(odir.glob(f"{_sanitize(part)}.*")):
            if p.suffix.lower() == ".pdf" or p.suffix.lower() in IMG_EXTS:
                return p
    return None


def _fingerprint(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(str(p.stat().st_size).encode())
    with p.open("rb") as f:
        h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


@app.get("/api/parts/{session}/{part}/preview.png")
def part_preview(session: str, part: str):
    """First-page preview of the part's ORIGINAL drawing (PDF page 1 rendered whole, or the image itself),
    aspect preserved, cached by content fingerprint so an edited source regenerates. 204 with an X-Preview-Reason
    header when no real preview can be produced (a 4xx would log a console error; the client shows its fallback)."""
    sdir = _session_dir(session)
    src = _source_for_preview(sdir, part)
    if src is None:
        return Response(status_code=204, headers={"X-Preview-Reason": "no original drawing is stored for this part"})
    cache = sdir / ".thumbs" / "previews"
    cache.mkdir(parents=True, exist_ok=True)
    png = cache / f"{_sanitize(part)}-{_fingerprint(src)}.png"
    if not png.is_file():
        try:
            if src.suffix.lower() == ".pdf":
                import fitz
                with fitz.open(str(src)) as doc:
                    if doc.page_count < 1:
                        raise ValueError("the PDF has no pages")
                    pg = doc.load_page(0)
                    zoom = min(2.0, 640.0 / max(pg.rect.width, 1.0))
                    pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(str(png))
            else:
                from PIL import Image
                with Image.open(src) as im:
                    im = im.convert("RGB")
                    im.thumbnail((640, 640))
                    im.save(png, "PNG")
        except Exception:  # noqa: BLE001 - any renderer failure is "unavailable", never a crash (and the raw error can name server paths)
            return Response(status_code=204, headers={"X-Preview-Reason": "the preview could not be rendered (the source looks corrupt)"})
        for old in cache.glob(f"{_sanitize(part)}-*.png"):      # drop stale versions
            if old != png:
                try:
                    old.unlink()
                except OSError:
                    pass
    return FileResponse(str(png), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/estimate")
def estimate_run(session: str = "", parts: list[str] = Query(default_factory=list)):
    """Estimated time and cost for running ``parts`` one after another, from finished runs on this machine."""
    names = [_sanitize(p) for p in parts]
    ledger = _costs.read_rows(_costs.ledger_paths(FINAL_OUTPUTS_DIR / "_"))
    est = _est.build(FINAL_OUTPUTS_DIR, ledger, len(names))
    info = []
    if session:
        odir = _session_dir(session) / ORIGINALS_DIRNAME
        for n in names:
            pages, err = None, None
            src = next(iter(sorted(odir.glob(f"{n}.*"))), None) if odir.is_dir() else None
            if src is not None and src.suffix.lower() == ".pdf":
                pages, err = _est.pdf_pages(src)
            elif src is not None:
                pages = 1
            info.append({"part": n, "pages": pages, "error": err})
    est["parts"] = info
    return est


PREFLIGHT_MAX_BYTES = 200 * 1024 * 1024


@app.get("/api/parts/{session}/{part}/last-run")
def part_last_run(session: str, part: str):
    """Persisted timing and measured cost of the part's latest run (survives refresh and reconnection)."""
    out = FINAL_OUTPUTS_DIR / _sanitize(part)
    ledger = [r for r in _costs.read_rows(_costs.ledger_paths(out)) if r.get("part") == _sanitize(part)]
    return {"part": _sanitize(part), "run": _est.last_run(out, ledger)}


@app.post("/api/preflight/pdf")
async def preflight_pdf(file: UploadFile = File(...)):
    """Page count and readability of one uploaded PDF (used by the batch preflight list)."""
    data = await file.read(PREFLIGHT_MAX_BYTES + 1)
    if len(data) > PREFLIGHT_MAX_BYTES:
        return {"ok": False, "pages": None, "error": "The PDF is larger than 200 MB, which is more than the preflight check reads."}
    if not data.startswith(b"%PDF-"):
        return {"ok": False, "pages": None, "error": "Not a PDF file (the content does not start with %PDF-)."}
    tmp = DATA_DIR / f".preflight-{uuid.uuid4().hex[:8]}.pdf"
    tmp.write_bytes(data)
    try:
        pages, err = _est.pdf_pages(tmp)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return {"ok": pages is not None, "pages": pages, "error": err}


# ── Scoring tab ─────────────────────────────────────────────────────────────────────────────
SCORING_DIR = DATA_DIR / "scoring"


def _all_scoring_parts() -> list[tuple[str, str]]:
    """[(session, part)] for every saved part in every session, plus parts that only have an output folder."""
    seen: dict[str, str] = {}
    if PARTS_DIR.is_dir():
        for sdir in sorted(PARTS_DIR.iterdir()):
            if sdir.is_dir() and not sdir.name.startswith("."):
                for pdir in sorted(sdir.iterdir()):
                    if pdir.is_dir() and not pdir.name.startswith("."):
                        seen[pdir.name] = sdir.name
    if FINAL_OUTPUTS_DIR.is_dir():
        for d in sorted(FINAL_OUTPUTS_DIR.iterdir()):
            if d.is_dir() and d.name != "usage" and not d.name.startswith(".") and d.name not in seen:
                seen[d.name] = ""
    return [(sess, part) for part, sess in seen.items()]


def _latest_run_id(part: str) -> str | None:
    ev = FINAL_OUTPUTS_DIR / part / "run_events.jsonl"
    rid = None
    if ev.is_file():
        for r in _est._jsonl(ev):
            if r.get("kind") == "run.started":
                rid = r.get("run_id")
    return rid


def _scoring_row(session: str, part: str) -> dict:
    out = FINAL_OUTPUTS_DIR / part
    has_out = out.is_dir() and _categorize_output(out)["has_any"]
    rec = _sh.latest(SCORING_DIR, part)
    pdir = _session_dir(session) / part if session else None
    t = _part_times(_session_dir(session), pdir) if pdir is not None and pdir.is_dir() else {}
    gen = next(iter(sorted(out.glob("*_ir.SLDPRT"))), None) if out.is_dir() else None
    row = {"part": part, "session": session, "has_output": has_out, "has_part": gen is not None,
           "run_id": _latest_run_id(part), "last_activity": t.get("last_activity")}
    if rec:
        row.update({k: rec.get(k) for k in ("state", "score", "exact", "reason", "explanation", "error", "evaluated_at",
                                            "rubric_version", "key_kind")})
        row["stale_rubric"] = rec.get("rubric_version") != _sh.rubric_version(PROJECT_DIR)
        pr = rec.get("practices")
        row["practices_score"] = pr.get("score") if isinstance(pr, dict) else None
        row["flags"] = rec.get("consistency_flags") or []
    else:
        row["state"] = "pending" if has_out else "no_output"
    return row


@app.get("/api/scoring")
def scoring_overview():
    rows = [_scoring_row(s, p) for s, p in _all_scoring_parts()]
    rows.sort(key=lambda r: (-(r.get("last_activity") or 0), r["part"].lower()))
    latest = {r["part"]: _sh.latest(SCORING_DIR, r["part"]) for r in rows}
    return {"version": _sh.rubric_version(PROJECT_DIR), "parts": rows,
            "summary": _sh.summarize(latest, [r["part"] for r in rows if r["has_output"]])}


@app.get("/api/scoring/methodology")
def scoring_methodology():
    try:
        return {"methodology": _sh.methodology(PROJECT_DIR), "example": _sh.worked_example(PROJECT_DIR)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"The scorer configuration could not be read ({PROJECT_DIR / _sh.CONFIG_REL}): {e}")


@app.get("/api/scoring/parts/{part}")
def scoring_part(part: str):
    p = _sanitize(part)
    h = _sh.history(SCORING_DIR, p)
    return {"part": p, "latest": h[-1] if h else None,
            "history": [{k: r.get(k) for k in ("evaluated_at", "rubric_version", "state", "score", "run_id")} for r in h]}


class ScoreRequest(BaseModel):
    parts: list[str]
    export: bool = False        # True lets the scorer export the SLDPRT to STEP through an already-running SolidWorks


@app.post("/api/scoring/evaluate")
def scoring_evaluate(req: ScoreRequest):
    """Run the free scorer (python -m bench.score) for each part and append the result to its history.
    A failed generation and a failed scoring are different states."""
    version = _sh.rubric_version(PROJECT_DIR)
    results = []
    for raw in req.parts[:50]:
        part = _sanitize(raw)
        out = FINAL_OUTPUTS_DIR / part
        if not out.is_dir():
            results.append({"part": part, "state": "no_output"})
            continue
        try:
            row, _tail = _sh.run_scorer(PROJECT_DIR, out, SCORING_DIR, part, export=req.export)
        except Exception as e:  # noqa: BLE001
            row = {"part": part, "error": f"The scorer could not be run: {str(e)[:200]}"}
        rec = _sh.record_from_scorer(row, run_id=_latest_run_id(part), version=version)
        _sh.append(SCORING_DIR, part, rec)
        results.append({"part": part, "state": rec["state"], "score": rec.get("score")})
    return {"version": version, "results": results}


@app.get("/api/parts/{session}/{part}/thumb.jpg")
def part_thumb(session: str, part: str):
    p = _session_dir(session) / ".thumbs" / f"{_sanitize(part)}.jpg"
    if not p.is_file():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(str(p), media_type="image/jpeg")


def _write_spec_files(pdir: Path, notes: str) -> None:
    """Persist the operator's must-meet text as BOTH must_meet_spec.txt (the
    Stage 2.6 authoritative input, kept with the run) and notes.txt (legacy
    per-line grading). Clearing the text removes both."""
    text = (notes or "").strip()[:20000]
    for fname in ("must_meet_spec.txt", "notes.txt"):
        p = pdir / fname
        if text:
            p.write_text(text + "\n", encoding="utf-8")
        elif p.is_file():
            p.unlink()


@app.post("/api/parts/{session}/{part}/notes")
def update_part_notes(session: str, part: str, notes: str = Form("")):
    """Update a saved part's must-meet specifications in place (applied tier-0
    on the next run)."""
    pdir = _session_dir(session) / _sanitize(part)
    if not pdir.is_dir():
        raise HTTPException(404, "Unknown part")
    _write_spec_files(pdir, notes)
    return {"part": _sanitize(part), "parts": _list_parts(_session_dir(session))}


_IMG_MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
              ".webp": "image/webp", ".bmp": "image/bmp",
              ".tif": "image/tiff", ".tiff": "image/tiff"}


# ── Human-marked reference regions (dimension-region markup) ───────────────────
# The reviewer draws colored highlight boxes over the part's drawing BEFORE
# extraction runs: boxes sharing a color are one feature group (e.g. a hole's
# center + its X-dimension + its Y-dimension). Stored with the part INPUTS
# (reference_regions.json, normalized 0-1 coordinates) so it survives
# clear-all-models and is available to the pipeline for future OCR
# cross-checking / low-confidence fallback.
REGIONS_FILENAME = "reference_regions.json"
# The composited drawing (linework + the colored region boxes) the pipeline
# feeds into Claude extraction as human ground truth for hole placement.
MARKED_VIEW_FILENAME = "full_marked_view.jpg"
_REGION_ROLES = {"center", "x-dimension", "y-dimension", "tolerance", "other"}


def _sanitize_region(r: dict) -> dict | None:
    """Validate + normalize one region object; None if unusable."""
    try:
        bb = r.get("boundingBox") or {}
        x, y = float(bb["x"]), float(bb["y"])
        w, h = float(bb["width"]), float(bb["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0):
        return None
    role = str(r.get("role") or "other")
    return {
        "id": str(r.get("id") or uuid.uuid4().hex[:10])[:40],
        "color": str(r.get("color") or "#888888")[:16],
        "colorLabel": str(r.get("colorLabel") or "")[:64],
        "role": role if role in _REGION_ROLES else "other",
        "boundingBox": {"x": round(x, 6), "y": round(y, 6),
                        "width": round(w, 6), "height": round(h, 6)},
        "value": str(r.get("value") or "")[:200],
        "createdAt": str(r.get("createdAt") or "")[:40],
    }


def _sanitize_origin(o: object) -> dict | None:
    """Validate the locked (0,0) datum: normalized bottom-left corner of the
    top view, the fixed reference so every model shares the drawing's
    orientation. None if unusable."""
    if not isinstance(o, dict):
        return None
    try:
        x, y = float(o["x"]), float(o["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
    return {"x": round(x, 6), "y": round(y, 6),
            "locked": bool(o.get("locked", True)),
            "view": str(o.get("view") or "top")[:16]}


# GD&T datum reference points — the primary origin plus lettered datums and
# datum holes. Included in extraction so the model anchors positions/orientation
# to the same references the operator marked.
_DATUM_KINDS = {"origin", "datum_a", "datum_b", "datum_c", "datum_hole"}


def _sanitize_datum(d: object) -> dict | None:
    if not isinstance(d, dict):
        return None
    try:
        x, y = float(d["x"]), float(d["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
    kind = str(d.get("kind") or "datum_a")
    return {"id": str(d.get("id") or uuid.uuid4().hex[:10])[:40],
            "x": round(x, 6), "y": round(y, 6),
            "kind": kind if kind in _DATUM_KINDS else "datum_a",
            "value": str(d.get("value") or "")[:120]}


def _group_regions(regions: list[dict]) -> list[dict]:
    """Group regions by color into the featureGroups structure (stable order)."""
    groups: dict[str, dict] = {}
    for r in regions:
        g = groups.setdefault(r["color"], {"color": r["color"],
                                           "colorLabel": r.get("colorLabel", ""),
                                           "regions": []})
        g["regions"].append(r)
    return list(groups.values())


@app.get("/api/parts/{session}/{part}/regions")
def get_regions(session: str, part: str):
    pdir = _session_dir(session) / _sanitize(part)
    if not pdir.is_dir():
        raise HTTPException(404, "Unknown part")
    f = pdir / REGIONS_FILENAME
    if not f.is_file():
        return {"regions": [], "featureGroups": []}
    try:
        data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {"regions": [], "featureGroups": []}
    regions = [s for s in (_sanitize_region(r) for r in data.get("regions", [])) if s]
    datums = [s for s in (_sanitize_datum(d) for d in data.get("datums", [])) if s]
    return {"regions": regions, "featureGroups": _group_regions(regions),
            "origin": _sanitize_origin(data.get("origin")), "datums": datums}


@app.post("/api/parts/{session}/{part}/regions")
async def save_regions(session: str, part: str, request: Request):
    pdir = _session_dir(session) / _sanitize(part)
    if not pdir.is_dir():
        raise HTTPException(404, "Unknown part")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Body must be JSON: {\"regions\": [...]}")
    raw = body.get("regions", []) if isinstance(body, dict) else []
    regions = [s for s in (_sanitize_region(r) for r in raw) if s]
    origin = _sanitize_origin(body.get("origin")) if isinstance(body, dict) else None
    datums = [s for s in (_sanitize_datum(d) for d in (body.get("datums", []) if isinstance(body, dict) else [])) if s]
    payload = {"regions": regions, "featureGroups": _group_regions(regions),
               "origin": origin, "datums": datums}
    (pdir / REGIONS_FILENAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Nothing marked -> drop the stale composited marked view so extraction never
    # feeds an out-of-date annotation.
    if not regions and not origin and not datums:
        try:
            (pdir / MARKED_VIEW_FILENAME).unlink()
        except OSError:
            pass
    return {"saved": len(regions), "origin": origin, "datums": datums,
            "featureGroups": payload["featureGroups"]}


@app.post("/api/parts/{session}/{part}/marked-view")
async def save_marked_view(session: str, part: str, file: UploadFile = File(...)):
    """Store the composited drawing (linework + region boxes) as
    full_marked_view.jpg in the part INPUT folder — the pipeline includes it in
    Claude extraction for correct hole placement."""
    pdir = _session_dir(session) / _sanitize(part)
    if not pdir.is_dir():
        raise HTTPException(404, "Unknown part")
    data = await file.read()
    (pdir / MARKED_VIEW_FILENAME).write_bytes(data)
    return {"saved": True, "bytes": len(data)}


@app.get("/api/parts/{session}/{part}/marked-view.jpg")
def get_marked_view(session: str, part: str):
    p = _session_dir(session) / _sanitize(part) / MARKED_VIEW_FILENAME
    if not p.is_file():
        raise HTTPException(404, "No marked view for this part")
    return FileResponse(str(p), media_type="image/jpeg")


@app.get("/api/parts/{session}/{part}/overview.jpg")
def part_overview(session: str, part: str):
    """The part's overview/full drawing for Tab 2's Overview panel: the crop
    flow's 00_full.jpg, or the file the pipeline classifies as the overview in
    an uploaded parts folder. Falls back to the first view image so selecting
    a part always shows its drawing. 404 only when the part has no images."""
    pdir = _session_dir(session) / _sanitize(part)
    p = _find_overview_image(pdir) if pdir.is_dir() else None
    if p is None and pdir.is_dir():
        imgs = _part_images(pdir)
        p = imgs[0] if imgs else None
    if p is None:
        raise HTTPException(404, "No overview image for this part")
    return FileResponse(str(p), media_type=_IMG_MEDIA.get(p.suffix.lower(), "image/jpeg"))


@app.get("/api/parts/{session}/{part}/outputs")
def part_outputs(session: str, part: str):
    pdir = _session_dir(session) / _sanitize(part)
    if not pdir.is_dir():
        raise HTTPException(404, "Unknown part")
    out_dir = _part_output_dir(session, part)
    payload = _categorize_output(out_dir, session=session)
    # Cumulative session cost: sum every part's ledger in this session.
    session_total = 0.0
    session_rows: list[dict] = []
    for other in _session_dir(session).iterdir():
        if other.is_dir() and not other.name.startswith("."):
            odir = _part_output_dir(session, other.name)
            session_total += _usage_summary(odir).get("total_cost_usd", 0.0)
            session_rows += [r for r in _costs.read_rows(_costs.ledger_paths(odir)) if r.get("part") == _sanitize(other.name)]
    payload["categories"]["usage"]["session_total_cost_usd"] = round(session_total, 4)
    payload["categories"]["usage"]["session"] = _costs._totals(_costs.dedupe(session_rows))
    delivered = DELIVER_DIR / _sanitize(part)
    downloads = DOWNLOADS_DIR / _sanitize(part)
    payload.update({
        "part": _sanitize(part),
        "ran": out_dir.is_dir(),
        "delivered": str(delivered) if delivered.is_dir() else None,
        "delivered_downloads": str(downloads) if downloads.is_dir() else None,
    })
    return payload


@app.get("/api/parts/{session}/{part}/ledger.jsonl")
def part_ledger(session: str, part: str):
    """The raw cost ledger rows of THIS part only (the shared ledger also holds other parts' rows)."""
    pname = _sanitize(part)
    if not (_session_dir(session) / pname).is_dir():
        raise HTTPException(404, "Unknown part")
    rows = [r for r in _costs.read_rows(_costs.ledger_paths(_part_output_dir(session, part))) if r.get("part") == pname]
    if not rows:
        raise HTTPException(404, "No cost ledger rows for this part")
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    return Response(body, media_type="application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="{pname}_usage_ledger.jsonl"'})


class ReviewReq(BaseModel):
    state: str
    reason: str = ""


@app.get("/api/parts/{session}/{part}/flags")
def part_flags(session: str, part: str):
    """Validated engineering flags for one part (the same object the part outputs carry)."""
    if not (_session_dir(session) / _sanitize(part)).is_dir():
        raise HTTPException(404, "Unknown part")
    return _flags_for(_part_output_dir(session, part), session)


@app.get("/api/parts/{session}/{part}/engineering-markup")
def part_engineering_markup(session: str, part: str, request: Request):
    """The automatic post-run Engineering Markup manifest (NOT the human full_marked_view.jpg)."""
    out, summary = _markup_part(session, part)
    headers = _markup_headers(summary)
    if request.headers.get("if-none-match") == headers["ETag"] and summary.get("present"):
        return Response(status_code=304, headers=headers)
    return JSONResponse(summary, headers=headers)


@app.get("/api/parts/{session}/{part}/engineering-markup.pdf")
def part_engineering_markup_pdf(session: str, part: str):
    out, summary = _markup_part(session, part)
    p = _flags.markup_pdf_path(out) if summary.get("status") in ("ready", "partial") else None
    if p is None:
        raise HTTPException(404, "No engineering markup PDF for this part")
    return FileResponse(str(p), media_type="application/pdf",
                        headers={**_markup_headers(summary), "Content-Disposition": f'inline; filename="{p.name}"'})


@app.get("/api/parts/{session}/{part}/engineering-markup/page/{page}.png")
def part_engineering_markup_page(session: str, part: str, page: int):
    out, summary = _markup_part(session, part)
    p = _flags.markup_page_path(out, page) if summary.get("status") in ("ready", "partial") else None
    if p is None:
        raise HTTPException(404, "No such engineering markup page")
    return FileResponse(str(p), media_type="image/png", headers=_markup_headers(summary))


def _markup_headers(summary: dict) -> dict:
    key = summary.get("generation_key") or "none"
    return {"ETag": f'"{key}"', "Cache-Control": "no-cache"}


def _markup_part(session: str, part: str) -> tuple:
    if not (_session_dir(session) / _sanitize(part)).is_dir():
        raise HTTPException(404, "Unknown part")
    out = _part_output_dir(session, part)
    return out, _markup_for(out, session)


@app.get("/api/recording/capability")
def recording_capability():
    """Whether 'Record pipeline run' can work here (the UI disables the box with this reason otherwise)."""
    return _recording_capability()


def _recording_part(session: str, part: str) -> tuple:
    if not (_session_dir(session) / _sanitize(part)).is_dir():
        raise HTTPException(404, "Unknown part")
    out = _part_output_dir(session, part)
    return out, _recording_for(out, session)


def _recording_headers(summary: dict) -> dict:
    return {"ETag": f'"rec-{summary.get("generation_key") or "none"}"', "Cache-Control": "no-cache"}


@app.get("/api/parts/{session}/{part}/recording")
def part_recording(session: str, part: str, request: Request):
    """The SolidWorks build recording manifest (status, chapters, failure code)."""
    out, summary = _recording_part(session, part)
    headers = _recording_headers(summary)
    if request.headers.get("if-none-match") == headers["ETag"] and summary.get("present"):
        return Response(status_code=304, headers=headers)
    return JSONResponse(summary, headers=headers)


@app.get("/api/parts/{session}/{part}/recording.video")
def part_recording_video(session: str, part: str, download: bool = False):
    """The recorded video. Range requests are honoured (seeking); the name comes from the validated manifest only."""
    out, summary = _recording_part(session, part)
    p = _flags.recording_video_path(out) if summary.get("status") in ("ready", "partial") else None
    if p is None:
        raise HTTPException(404, "No recording for this part")
    disp = "attachment" if download else "inline"
    return FileResponse(str(p), media_type=_flags.REC_VIDEOS[p.name],
                        headers={**_recording_headers(summary), "Content-Disposition": f'{disp}; filename="{_sanitize(part)}_{p.name}"'})


@app.get("/api/parts/{session}/{part}/recording-poster.jpg")
def part_recording_poster(session: str, part: str):
    out, summary = _recording_part(session, part)
    p = _flags.recording_poster_path(out) if summary.get("status") in ("ready", "partial") else None
    if p is None:
        raise HTTPException(404, "No recording poster for this part")
    return FileResponse(str(p), media_type="image/jpeg", headers=_recording_headers(summary))


@app.post("/api/parts/{session}/{part}/flags/{finding_id}/review")
def review_flag(session: str, part: str, finding_id: str, req: ReviewReq):
    """A person's decision about a flag (acknowledge / corrected / dismissed). Never edits the pipeline's finding."""
    if not (_session_dir(session) / _sanitize(part)).is_dir():
        raise HTTPException(404, "Unknown part")
    try:
        return _flags.set_review(_part_output_dir(session, part), finding_id, req.state, req.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Scoring Rubric ──────────────────────────────────────────────────────────
# Two genuinely different, never-blended measures (bench/scoring.py PartScore: "practices:
# weight 0 for now" is the same separation already encoded in the pipeline's own scoring
# dataclass). Neither is invented here:
#   geometry  -- from <part>/scores.json, written by `python -m bench.score` (needs a signed
#                answer key; only exists for official benchmark parts, not ordinary uploads).
#   practices -- the real MTI modeling-practice findings already in ir_report.json's
#                mti_review (pipeline/ir/mti_review.py), the same data Engineering Flags
#                shows as LOW-severity items, regrouped under its real check codes.
_MTI_CHECK_LABELS = {
    "mti_hole_wizard":   "Hole Wizard sizing matched to MTI's hole standard",
    "mti_hole_grouping": "Identical holes grouped into one Hole Wizard feature",
    "mti_edge_ops_last":  "Fillets/chamfers modeled last in the feature tree",
    "mti_avoid":         "No features on MTI's 'generally avoid' list",
}


def _practices_rubric(ir_report: dict | None) -> dict:
    if ir_report is None:
        return {"present": False}
    findings = []
    for line in ir_report.get("mti_review") or []:
        m = re.match(r"^\[([a-z_0-9]+)\]\s*(.*)$", str(line))
        findings.append({"code": m.group(1), "message": m.group(2)} if m else {"code": "other", "message": str(line)})
    checks = []
    for code, label in _MTI_CHECK_LABELS.items():
        items = [f["message"] for f in findings if f["code"] == code]
        checks.append({"code": code, "label": label, "flagged": bool(items), "items": items})
    other = [f["message"] for f in findings if f["code"] not in _MTI_CHECK_LABELS]
    return {"present": True, "checks": checks, "other": other,
            "clean": not any(c["flagged"] for c in checks) and not other}


@app.get("/api/parts/{session}/{part}/scoring")
def part_scoring(session: str, part: str):
    out_dir = _part_output_dir(session, part)
    scores_path = out_dir / "scores.json"
    geometry: dict = {"present": False}
    if scores_path.is_file():
        try:
            data = json.loads(scores_path.read_text(encoding="utf-8"))
            # bench.score writes {"parts": [{"part": ..., "score": ..., "exact": ..., "rows": [...]}]}
            # or a single-part shape depending on how it was invoked; handle both honestly.
            rows = data.get("parts") if isinstance(data, dict) and "parts" in data else (data if isinstance(data, list) else [data])
            mine = next((r for r in rows if r.get("part") == _sanitize(part)), rows[0] if len(rows) == 1 else None)
            if mine:
                geometry = {"present": True, "part": mine.get("part"), "score": mine.get("score"),
                            "exact": mine.get("exact"), "rows": mine.get("rows") or [],
                            "extras": mine.get("extras") or [], "drawing_only": mine.get("drawing_only") or [],
                            "source": str(scores_path)}
        except Exception as e:
            geometry = {"present": False, "error": f"scores.json could not be read: {e}"}
    ir_report = _load_json(_first(out_dir, ["ir_report.json"]))
    return {"part": _sanitize(part), "geometry": geometry, "practices": _practices_rubric(ir_report)}


@app.get("/api/parts/{session}/{part}/file/{name:path}")
def part_file(session: str, part: str, name: str):
    """Download any single output file of a part (Files tab links)."""
    out = _part_output_dir(session, part).resolve()
    target = (out / name).resolve()
    if not str(target).startswith(str(out)) or target == out:
        raise HTTPException(403, "Path outside part output")
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(str(target), filename=target.name)


@app.get("/api/parts/{session}/{part}/model.stl")
def part_stl(session: str, part: str):
    p, _src = _active_stl(_part_output_dir(session, part))
    if p is None:
        raise HTTPException(404, "No STL for this part yet")
    return FileResponse(str(p), media_type="model/stl", filename=p.name)


# ── Shared run history: ONE persistent inventory of completed runs ─────────────
# Backs BOTH Sheet 2's "Select Model" dropdown and Sheet 4's "Select Run"
# dropdown, so the two can never disagree. Sourced from disk (DATA/parts/
# <session>/<part>/output), not in-memory state — runs survive server restarts
# and browser sessions.

def _run_presence(out: Path) -> dict:
    """File-existence flags for each output category (drives the ✓ indicators
    without reading file contents — cheap enough to scan every part)."""
    stl, _src = _active_stl(out)
    build_plan = _first(out, ["*build_plan*.json", "**/build_plan*.json"])
    return {
        "extraction": _first(out, ["*_extraction.json", "*extraction*.json"],
                             exclude=["resolved"]) is not None,
        "resolved": _first(out, ["*_resolved_extraction.json", "*resolved*.json"]) is not None,
        "build_plan": build_plan is not None,
        "verification": _first(out, ["*verification_report*.txt", "*verification*.txt"]) is not None,
        "flags": build_plan is not None
                 or _first(out, ["*_engineering_review.txt"]) is not None,
        "model_check": _first(out, ["*model_check*.txt", "*model_validation*.txt",
                                    "*validation_report*.txt"]) is not None,
        "macros": next(out.rglob("*.vba"), None) is not None if out.exists() else False,
        "cost": (out / "token_usage_log.jsonl").is_file() or (out / "token_usage_log.txt").is_file(),
        "console": _first(out, ["ui_console.log"]) is not None,
        "files": out.exists(),
        "stl": stl is not None,
        "overview_analysis": _first(out, ["overview_analysis.json"]) is not None,
    }


def _run_timestamp(out: Path) -> float:
    """When the run completed: the newest mtime among its output files."""
    newest = 0.0
    try:
        for p in out.rglob("*"):
            if ".extraction_cache" in p.parts or not p.is_file():
                continue
            newest = max(newest, p.stat().st_mtime)
    except OSError:
        pass
    return newest or (out.stat().st_mtime if out.exists() else 0.0)


@app.get("/api/run-history")
def run_history():
    """Every completed run across every session/part, newest first."""
    from datetime import datetime as _dt

    runs = []
    if PARTS_DIR.is_dir():
        for sdir in sorted(PARTS_DIR.iterdir()):
            if not sdir.is_dir() or sdir.name.startswith("."):
                continue
            for pdir in sorted(sdir.iterdir()):
                if not pdir.is_dir() or pdir.name.startswith("."):
                    continue
                out = _part_output_dir(sdir.name, pdir.name)
                if not out.is_dir():
                    continue
                present = _run_presence(out)
                # A "completed run" left at least one core artifact behind.
                if not (present["extraction"] or present["build_plan"] or present["stl"]):
                    continue
                epoch = _run_timestamp(out)
                stamp = _dt.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M") if epoch else "?"
                runs.append({
                    "session": sdir.name,
                    "part": pdir.name,
                    "key": f"{sdir.name}|{pdir.name}",
                    "label": f"{pdir.name} — run @ {stamp}",
                    "epoch": int(epoch),
                    "timestamp": stamp,
                    "output": str(out),
                    "present": present,
                })
    runs.sort(key=lambda r: -r["epoch"])
    return {"runs": runs}


@app.post("/api/run-history/clear")
def clear_run_history():
    """Clear ALL stored run outputs (the source of the shared run history).

    Deletes every legacy ``DATA/parts/<session>/<part>/output`` folder, emptying both
    Sheet 2's model dropdown and Sheet 4's run dropdown for runs made before FINAL_OUTPUTs
    existed. The saved part inputs (views, specs) are untouched — every part can simply be
    re-run — and FINAL_OUTPUTS_DIR, ``UI_Output/`` and ``~/Downloads`` are NOT touched (they
    are the user's deliverables, shared with make_part.py, not the browsing store)."""
    import shutil

    removed = 0
    errors: list[str] = []
    if PARTS_DIR.is_dir():
        for sdir in PARTS_DIR.iterdir():
            if not sdir.is_dir() or sdir.name.startswith("."):
                continue
            for pdir in sdir.iterdir():
                if not pdir.is_dir() or pdir.name.startswith("."):
                    continue
                out = pdir / "output"
                if out.is_dir():
                    try:
                        shutil.rmtree(out)
                        removed += 1
                    except OSError as e:  # e.g. an STL locked by a viewer
                        errors.append(f"{sdir.name}/{pdir.name}: {e}")
    return {"removed": removed, "errors": errors}


@app.post("/api/run-part")
def run_part(session: str = Form(...), part: str = Form(...),
             feedback: str = Form(""), no_cache: bool = Form(False), record: bool = Form(False)):
    if not _has_api_key():
        raise HTTPException(400, _no_key_message())
    pdir = _session_dir(session) / _sanitize(part)
    # A part needs a drawing, not a set of assigned views: the IR path reads the full sheet
    # (ir_pipeline.images_for -> a file yields one "FULL SHEET" image). Either an untouched
    # original or any saved image is enough to run.
    originals = sorted((_session_dir(session) / ORIGINALS_DIRNAME).glob(f"{_sanitize(part)}.*")) \
        if (_session_dir(session) / ORIGINALS_DIRNAME).is_dir() else []
    if not pdir.is_dir() or not (originals or _part_images(pdir)):
        raise HTTPException(400, "Selected part has no drawing. Upload a PDF or image first.")
    out_dir = FINAL_OUTPUTS_DIR / _sanitize(part)
    # Correction feedback from the reviewer (Tab 3) becomes an authoritative
    # must-meet correction line, appended to the spec so the specs-first
    # extraction + Stage 2.5 resolution + final grading all apply it. Forcing a
    # fresh extraction guarantees the correction takes effect on the re-run.
    fb = (feedback or "").strip()
    if fb:
        from datetime import datetime

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"CORRECTION ({stamp}): {fb}"
        for fname in ("must_meet_spec.txt", "notes.txt"):
            f = pdir / fname
            prev = f.read_text(encoding="utf-8", errors="replace").rstrip("\n") + "\n" if f.is_file() else ""
            f.write_text(prev + line + "\n", encoding="utf-8")
        no_cache = True
    # Prefer the untouched original drawing: one file, read as the full sheet, no view
    # assignment involved. Fall back to the part folder when only derived images exist.
    original = next((p for p in originals if p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg",
                                                                  ".tif", ".tiff", ".bmp")), None)
    src = original if original is not None else pdir
    # run_part() creates <output root>/<part>/, so hand it the root, not the part folder.
    if record and not _recording_capability()["available"]:
        record = False        # the UI disables the box in this case; a stale client must not fail the run over a video
    cmd = _pipeline_cmd(src, FINAL_OUTPUTS_DIR, no_cache=no_cache, record=record)
    _touch_meta(pdir, last_run_at=_now_iso())
    run_id = _start_run(cmd, out_dir, deliver_name=_sanitize(part), extra_files=originals)
    return {"id": run_id, "part": _sanitize(part)}
