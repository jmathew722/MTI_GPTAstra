# Live run: original PDF -> OpenAI extraction -> native part with material -> regenerated drawing

Date 2026-11-26. Part: `DrawingPDFs/A001151E.PDF` (an authorized drawing already in this repository). SOLIDWORKS 2025 SP5 (33.5.0). Evidence: `docs/phase1-evidence/live_pdf_A001151E/`.
Command (from `2D-3D-CAD-Test-Generation/`):
```
SOLIDFLOW_MATERIAL_SETTINGS=<settings.json> python main.py --drawing ../DrawingPDFs/A001151E.PDF --ir --engine com --output <dir>
python -m reverse.cli fixtures --src <folder holding the built 116-C_ir.SLDPRT> --out <dir> --template <abs .DRWDOT> --own-sheet-format
```

## Result
| Step | Outcome |
|---|---|
| Live OpenAI extraction (`gpt-6-astra`, fresh, **$0.371**) | `material_extraction.status = specified`, raw text **"CRS 1018"**, evidence = page 1, region `title_block`, verbatim quote, normalized bounding box, confidence 0.99 (heuristic), condition "Cold rolled (CRS)", heat treatment "NONE" kept out of the base material |
| Resolver | **matched** the company library entry `co-1018` (source `company`); no review reasons |
| Planner (**$0.176**) and native build | built, `sw_ok`, volume and bbox verified; total run cost **$0.55** |
| Native assignment | `assigned_verified`: "Plain Carbon Steel", density **7800.0 kg/m3**, **read back after closing and reopening the saved SLDPRT** (`reopen_verified: true`) |
| Mass and cost | 1.5686 kg; net material cost **1.33 USD** at the TEST catalog price (0.85 USD/kg, synthetic); shown separately from the 0.55 USD API cost |
| Appearance sidecar | `verified: true`, colour `#A5ABB4` |
| Regenerated drawing from that part | title block **MATERIAL Plain Carbon Steel** (read from the native part), PART NO `116-C_ir`; coverage 83.3 %; all other unknowns `NOT SPECIFIED` |
| Round trip, this part | **18 of 18** original dimensions / hole diameters found among the regenerated drawing's verified values (16 with no print-rounding allowance); 0 original-only; 3 regenerated-only (`roundtrip_this_part.json`) |

## What this run found (all fixed)
1. **Stale extraction cache.** The first attempt printed `Extraction cache HIT` and returned an old extraction without `material_extraction`: the cache key covered only the model and the image, so a prompt or schema change never invalidated old entries. The key now includes a fingerprint of the system prompt and the output schema (`pipeline/extractor.py::_prompt_fingerprint`, test `test_extraction_cache_key_changes_with_the_prompt_and_schema`). The first run is kept as `first_run_stale_cache_material_resolution.json`: it shows the resolver correctly refusing to guess ("CRS 1018" was not an approved spelling then) and the build succeeding with no assignment.
2. A newly extracted material that is not an exact catalog match stays `unmatched`, never auto-assigned.

## Caveats (read these)
* **The catalog is a TEST catalog.** `TEST_company_catalog_materials.json` maps the company-approved spellings "CRS 1018" / "1018" to SOLIDWORKS' installed *Plain Carbon Steel* (7800 kg/m3). That mapping is the kind of decision a real company library makes; it is not a claim that Plain Carbon Steel equals AISI 1018 (7870 kg/m3 nominal). The price is synthetic. Without such a library, the installed standard library has no exact "1018" entry and the correct outcome is `unmatched` with suggestions.
* The model also filled the `finish` field with a rambling sentence about a surface-texture callout. It is stored as text for review and never used as a finish specification; a stricter prompt or a validation rule for that field is a follow-up.
* One drawing, one live extraction. Conflicting callouts, unreadable scans, multi-page drawings and multi-body parts were exercised by schema and unit tests only.
* Budget: 10.48 USD spent before this session's live runs, 11.20 USD after (cap 20 USD; the guard stayed active).
