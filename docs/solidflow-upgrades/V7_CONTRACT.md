# Solid Flow v7: backend service contract (3D -> 2D reference-driven reconstruction)

Audience: the UI/server agent (`FINAL_UI/server/reverse_api.py`). Backend owner: `2D-3D-CAD-Test-Generation/reverse/*`.
Everything below is implemented in `reverse/service.py` (`ReverseService`) and is additive: old jobs, old submit calls and old job views keep
working. Paths never leave the server; the UI only ever sees ids, hashes, filenames and relative artifact paths.

## 1. Submit

```python
ReverseService.submit(*, part_paths, template_id=None, profile="us_third_angle_inch", configs=None,
                      reference=None, options=None, authorized=True) -> state.Job
```

`reference` (default `None` == `{"mode": "standard"}`):

```json
{
  "mode": "standard" | "match",
  "fallback_standard": false,
  "per_part": {
    "<str(part_path) exactly as passed in part_paths>": {
      "source": "auto" | "upload" | "artifact" | "none",
      "pdf_path": "<server-side path of an already saved reference PDF (from save_reference_pdf)>",
      "artifact_id": "<id returned by reference_candidates>"
    }
  }
}
```

* `standard` ignores `per_part`; the three reference stages are `not_applicable`.
* `match`: each part resolves independently (never one PDF for a whole batch). Order: explicit `upload` > `artifact` (explicit selection or a
  previously confirmed link) > `auto` (history lookup, only a non-ambiguous high-confidence link is used) > nothing.
  A missing `per_part` entry means `source: "auto"`. For a part key with a `::config` suffix (config expansion) the lookup tries the exact key, then the key without it.
* If no source resolves (none, `auto` found nothing, or `auto` is ambiguous / needs confirmation) the part is **blocked in preflight**:
  `part.state == "failed"`, `part.reference.status == "blocked"`, `part.error` = an explicit reason beginning `REFERENCE_BLOCKED:`;
  the other parts of the job still run. If `reference["fallback_standard"]` is true the part instead runs as Standard
  and `reference.status == "fallback_standard"` with a warning saying why. The backend never silently switches mode.
* `pdf_path` must come from `save_reference_pdf` (inside the service's upload directory) or the part is blocked (`REFERENCE_PDF_REJECTED`).
* The job is created synchronously (reference resolution is cheap and COM-free); extraction (model calls) runs on the worker inside the job.

## 2. Candidate lookup

```python
ReverseService.reference_candidates(part_path_or_part_id, config="") -> {
  "part": {"filename", "sha256", "configuration"},
  "selected": null | {"artifact_id", "filename", "project", "run", "date", "pages", "confidence", "reasons": [...], "needs_confirmation": false, "link": "part_hash"|"forward_run"|"recorded_source_hash"|"confirmed"},
  "candidates": [{"artifact_id", "filename", "project", "run", "date", "pages", "confidence": 0..1, "reasons": [...], "needs_confirmation": bool, "link": "..."}]
}
```

* `selected` is non-null only when exactly one candidate has `needs_confirmation == false` and it clearly outranks the next one.
  Several equal-scoring candidates, or only name-based candidates, give `selected: null` and `needs_confirmation: true` on each.
* Evidence ranking: confirmed user link > source-PDF SHA256 recorded in a forward manifest (`engineering_markup.json`, `solidworks_recording.json`,
  `engineering_flag_overlays.json`) whose forward run contains a SLDPRT with the **same SHA256** as the submitted part > the PDF stored inside the
  same forward-run folder as that hash-matching part > filename / part number only (candidate, never selected).
* `artifact_id` is opaque (`pdf_<sha256 prefix>`); it identifies PDF *content*. Pass it back in `submit(... source:"artifact")` to confirm.
* `confirm_reference_link(part_path, artifact_id, config="", user="")` persists a confirmed link (sidecar `<data>/reference/links.json`, versioned).
* A bad/unreadable part path returns `{"part": ..., "selected": null, "candidates": [], "error": "..."}` (no exception for a missing file).

## 3. Reference PDF upload / validation

```python
ReverseService.save_reference_pdf(data_stream_path) -> {"ok", "sha256", "pages", "size", "error", "pdf_path", "artifact_id", "filename"}
ReverseService.validate_reference_pdf(path)         -> {"ok", "sha256", "pages", "size", "error"}
```

* `data_stream_path` is a temp file the server already wrote (the UI route owns the HTTP size cap; the backend re-checks: `%PDF-` signature, <= 50 MB,
  1..20 pages, openable by PyMuPDF, not encrypted). `save_reference_pdf` copies to `<data>/uploads/3d-to-2d/reference/<sha256>.pdf` (content addressed, immutable)
  and returns `pdf_path` for `submit`. `pdf_path` is a server path: the UI must hold it server-side only (never return it to the browser; return `artifact_id`/`sha256`).

## 4. Job view (additions)

`job_view(job_id)["parts"][i]` keeps everything it had and adds:

```json
{
  "reference": {
    "mode": "standard" | "match",
    "status": "not_applicable" | "resolved" | "blocked" | "fallback_standard" | "pending",
    "source_kind": "none" | "upload" | "artifact" | "history" | "confirmed_link",
    "filename": "A001151E.pdf", "sha256": "...", "pages": 1,
    "link": "part_hash" | "forward_run" | "recorded_source_hash" | "confirmed" | null, "confidence": 0.98, "reasons": ["..."],
    "extraction_cache": "hit" | "supplemented" | "fresh" | "none",
    "extraction_id": "...", "extraction_schema": "ref/1",
    "api_usage": {"tokens": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0, "calls": 0, "incremental": true, "historical_usd": 0.0},
    "warnings": ["..."]
  },
  "verification": {
    "status": "passed" | "review_required" | "failed" | "pending" | "not_run",
    "coverage": {"matched": 0, "total": 0, "unresolved": [{"id", "kind", "text", "reason", "severity"}]},
    "collisions": {"count": 0, "items": [...], "clearance_mm": 1.5},
    "comparison": {"semantic": {...}, "spatial": {...}},
    "iterations": {"used": 0, "max": 3, "best": 0, "history": [...]},
    "standards": {"iso_shaded_with_edges": bool|null, "black_text": bool|null, "broken_leaders": {...}, "arrange": {...}}
  },
  "files": { ... existing keys ... }
}
```

* `reference` and `verification` are `{}`-free: old jobs (created before v7) return `reference: {"mode":"standard","status":"not_applicable",...}` and `verification: {"status":"not_run"}`.
* `reference.api_usage.usd` is the **incremental** spend of this part's run; a cache hit is `usd: 0.0, calls: 0`. `historical_usd` is what the cached extraction originally cost (from the forward ledger when known, otherwise null). Local CAD time is never a token cost.
* The completed status of a part is `completed` only when `verification.status == "passed"` (no hard QA failure and nothing unresolved). Reference match is **not** engineering approval; every drawing stays `PRELIMINARY / FOR REVIEW`.

### part_files()

`ReverseService.part_files(job, part)` (and `job_view[...]["files"]`) lists only files that exist. New stable aliases (each `{"bytes", "url_path", "available": true}`; an absent file is omitted from `files`, and listed in `files_availability` as `false`):

| key | file |
|---|---|
| `slddrw` | `drawing.slddrw` |
| `pdf` | `drawing.pdf` (generated, native export) |
| `source_pdf` | the reference PDF actually used (copied immutably into the part folder as `reference/source.pdf`) |
| `stl` | `model.stl` |
| `qa_json` | `qa.json` |
| `comparison_images` | `comparison/page-NNN.png` (side-by-side / overlay pages); value is `{"files": [{"name","bytes","url_path"}], "available": bool}` |

The pre-existing keys (`drawing.slddrw`, `drawing.pdf`, `model.stl`, `qa.json`, `preview/page-001.png`, ...) still exist. `job_view(...)["parts"][i]["files_availability"]` is `{"slddrw": bool, "pdf": bool, "source_pdf": bool, "stl": bool, "qa_json": bool, "comparison_images": bool}`.

### artifact_path(job_id, rel)

Unchanged containment (must be a listed artifact of a part of this job, inside the job folder, a regular non-symlink file). v7 adds the new files (`reference/source.pdf`, `reference/reference_extraction.json`, `comparison/*`, `verification.json`) to `part.artifacts`, so they are served by the same route. Stale or absent artifacts raise `SafetyError` as before.

## 5. Stages (state machine)

`queued -> preflight -> stl_export -> reference_resolution -> extraction -> view_planning -> native_drawing -> dimensioning_layout -> comparison_correction -> verification -> publish -> completed | review_required | failed | canceled`

* Terminal spelling stays `canceled` (existing spelling; the specification's `cancelled` is an alias the UI may display).
* Stage status values in `part.stages[stage].status`: `running`, `succeeded`, `warning`, `failed`, `skipped`, `not_applicable`.
  In Standard mode `reference_resolution`, `extraction` and `comparison_correction` get `not_applicable` (they appear in `stages` so the UI can render them as such).
  `state.STAGES` / `job_view["stage_order"]` / `job_view["stage_labels"]` give the order and the labels. `stl_export` includes the geometry inventory (it runs in the same open document).
* Old jobs keep their old stage keys (`mesh_export`, `inventory`, `planning`, `drawing`, `dimensioning`, `publishing`); `stage_labels` contains both vocabularies. Do not hard-code the order, read `stage_order`.
* `progress` counts `not_applicable`/`skipped` stages as done.
* Cancellation stops between safe COM operations (stage boundaries and iteration boundaries); partial diagnostics stay in `_staging` removed only on success.

## 6. Provenance sidecars (server-side)

* `<data>/reference/links.json`: confirmed links `{schema_version: 1, links: [{part_sha256, configuration, pdf_sha256, confirmed_by, confirmed_at}]}`.
* `<job>/<part>/<config>/reference/resolution.json` (`ReferenceResolution`), `reference_extraction.json` (normalized schema `ref/1`), `verification.json`, `comparison/`.
* Old runs without these are *candidates*, never confirmed matches.

## 7. Errors the UI should expect

`safety.SafetyError(message)` for malformed requests (unknown template/profile, mode, unsafe `pdf_path`). Per-part problems are never exceptions: they are part state + `reference.warnings` / `part.error`.
