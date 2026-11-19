# Stage 4 gate report — SOLIDWORKS 2025 Hole Wizard, live run (2026-11-19)

Branch `Improvements_2`. Machine: SOLIDWORKS 2025 SP5 (revision 33.5.0), Windows 11. Details and every API finding: error log **E039**.

## Environment

- Before: Hole Wizard folder -> `C:\SOLIDWORKS Data` (2026 data, database 29.01, expected 28.00): `HW_DATABASE_VERSION_MISMATCH`.
- With the user's go-ahead the preference `swHoleWizardToolBoxFolder` was set to `C:\SOLIDWORKS Data (2)` (2025 data). No database was touched.
- Now: `python tools/sw_preflight.py` -> `ready` (database 28.00 = expected, Toolbox index 33.5.0.53, catalog enumerable). Record: `docs/hole-wizard/preflight-result.json`.

## Live matrix (`python tools/run_hole_wizard_matrix.py --live`, one child process + watchdog per variant)

| External status | Count |
|---|---|
| `SUPPORTED_AND_LIVE_VERIFIED` | 13 |
| `SUPPORTED_BY_ADAPTER_NOT_INSTALLED` (created + read back + reopened + callout ok, geometry reference not modelled: pipe taps) | 2 |
| `UNSUPPORTED_WITH_REASON` (56 failed verification with the exact mismatch, 10 legacy with no adapter) | 66 |

`verified` requires: native creation, field-level definition readback, removed volume equal to an independent reference (analytic / CadQuery, agreement
better than 1e-6), save + close + reopen, and the drawing Hole Callout round trip (SOLIDWORKS' own callout text parsed back and compared with the intent).

Verified: hole blind/thru; counterbore blind/thru; countersink blind/thru without head clearance; cosmetic taps blind/thru (M6x1.0, class 6H on the callout);
counterbore slot blind/thru; plain slot blind; countersink slot blind/thru without head clearance.

Not reached (calls tried, evidence in the matrix `note` per row, never a plain-cut substitute): near/middle/far countersink treatments, head-clearance
countersinks, plain taps / thread-through / remove-thread, plain through slot. Advanced Hole: element data + face selection work, `AdvancedHole2` reports
incorrect parameters. Hole Series: no creation API in the installed type library.

## Fixtures and tests

- HW-EX-001..005 remain permanent parser fixtures (`tests/test_hole_callouts_fixtures.py`); the live part of each needs a plan with its resolved catalog row.
- New: `tests/test_hole_callout_roundtrip.py` (callout text captured live), slot reference volumes equal the live-removed volumes, matrix gate tests.
- Python: 1288 passed, 66 skipped, 0 failed.

## Limits

- 56 of 81 variants are not live-verified (listed above); the pipe-tap reference geometry is missing; Advanced Hole is not created.
- The data-root change is a SolidWorks user preference: to undo, set it back to `C:\SOLIDWORKS Data`.
