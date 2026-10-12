# config/mti — MTI proprietary standards (local only)

Files here other than this README are **gitignored**. They hold MTI's confidential
standards and must never be committed or sent to a model API.

| File | What | Read by |
|---|---|---|
| `202.02.0003.local.json` | MTI Std 202.02.0003 *Tap and Hole Specifications* (inch + metric tables) | `pipeline/mti_standards.py` |

Override the location with `MTI_STANDARD_PATH`. Without the file the pipeline still
runs: counterbores fall back to the generic SHCS chart (`pipeline/fasteners.py`) and
the MTI review skips Hole Wizard matching.

Layout: `{"inch": {"columns": [...], "rows": [[...], ...]}, "metric": {...}}`. Columns
used by code: `size`, `nominal`, `preferred`, `tap_drill`, `clearance_normal`,
`clearance_loose` (metric), `cbore_d`, `cbore_depth`. See `tests/test_mti_standards.py`
for a synthetic example.

The current copy is an **unverified transcription** of a screenshot (2026-10-11);
replace it with an export of the controlled document when MTI provides one.
