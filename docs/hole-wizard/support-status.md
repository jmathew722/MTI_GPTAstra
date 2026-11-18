# Hole Wizard support status (Stage 4, task 4.14)

**Read this first: no Hole Wizard variant is `verified`.** Live verification could not start: on this machine, in this session, Hole Wizard creation through the API does not work (see [E037](../solidworks-macro-error-log.md)). Nothing below is a claim that a hole type can be created.

Vocabulary (fixed): `verified`, `implemented_not_live_verified`, `unsupported_by_installed_catalog`, `not_implemented`, `ambiguous_source`, `failed_verification`. There is no generic "supported".

## Environment evidence

* SOLIDWORKS **2025 SP5 (33.5)**, window title "Student Edition - Academic Use Only"; a 2026 install (34.0) is also present. Type-library evidence is read from the running 2025 install.
* Environment fingerprint `3c34f433ff091ed0`, the hash of {"swconst.tlb": "95e36f79890b9dcf", "sldworks.tlb": "585e008c1322754e", "Holewzd.idx": "c8936703e77e1279", "ToolboxStandards.xml": "613a6686663e2688"} (hashes of files that exist; **no catalog rows are recorded, and none could be enumerated**).
* `IHoleStandardsData.GetHoleStandards/GetFastenerTypes/...` return `False` for every family; `HoleWizard5` returns `None` for the repo's known-good taps; `InitializeHole` blocks. Structured codes: `HW_CATALOG_ENUMERATION_UNAVAILABLE`, `HW_CREATE_NULL`, `HW_DIALOG_BLOCKED`.

## The nine general families

| Family | Enum | Specific variants | Callout parsed (tested) | Creation | Live-verified |
|---|---|---|---|---|---|
| hole | swWzdHole (2) | 6 | yes | implemented_not_live_verified | no |
| countersink | swWzdCounterSink (1) | 6 | yes | not_implemented | no |
| counterbore | swWzdCounterBore (0) | 12 | yes | implemented_not_live_verified | no |
| straight_tap | swWzdTap (4) | 17 | yes | implemented_not_live_verified | no |
| pipe_tap | swWzdPipeTap (3) | 6 | yes | not_implemented | no |
| counterbore_slot | swWzdCounterBoreSlot (6) | 12 | yes | not_implemented | no |
| countersink_slot | swWzdCounterSinkSlot (7) | 6 | yes | not_implemented | no |
| slot | swWzdHoleSlot (8) | 6 | yes | not_implemented | no |
| legacy | swWzdLegacy (5) | 10 | never inferred from text | not_implemented | no |

Total specific variants classified: **81** of the **81** in the installed `swWzdHoleTypes_e` (identical sets in the 2025 and 2026 installs). Values are non-contiguous (the last is 90).

`implemented_not_live_verified` here means only: the repo already builds a **narrow, MTI-specific** subset of that family through `HoleWizard5` (clearance holes, socket-head counterbores, tapped holes with a cosmetic thread; error log E021/E022, verified on another machine on 2026-10-11). It does **not** cover the family's specific variants, and in this session that path was refused.

## The 81 specific variants

All 81 are classified by `pipeline/ir/solidworks/hole_capabilities.py` (family, end condition, near/middle/far treatments, thread mode, head clearance, candidate properties) and pinned to the installed type library by test. **Status of every one of the 81: `not_implemented`** as a *targeted* creation (no code selects a specific variant), including the niche ones: pipe/taper taps (6), the three slot families (24), countersink-without-head-clearance (6), thread-through / cosmetic / remove-thread taps (11), and the 10 legacy types.

| Group | Count | Notes |
|---|---|---|
| legacy (0-9) | 10 | preserved by an explicit policy only |
| counterbore (10-21) | 12 | blind/through x top/middle/bottom countersinks |
| hole + countersink (22-30, 43-45) | 12 | incl. 3 without head clearance |
| straight taps (31-36, 46-56) | 17 | cosmetic / thread-through / remove-thread variants |
| pipe taps (37-42) | 6 | NPT/NPTF/BSPT etc. are never inferred from a diameter |
| counterbore slots (57-68) | 12 |  |
| slots (69, 70, 72-75) | 6 |  |
| countersink slots (71, 76-79, 90) | 6 |  |

## Advanced Hole and Hole Series (separate domains)

* **Advanced Hole**: `IFeatureManager.AdvancedHole` / `AdvancedHole2` exist in the installed API. Status `not_implemented`. The parser flags stacked near/far callouts as `advanced_hole_candidate` and never treats them as a basic Hole Wizard hole.
* **Hole Series**: the installed `IAssemblyDoc` exposes **no hole-related member** (and `IFeatureManager` has no Hole Series method), so there is no API to create one in this release. Status `not_implemented` (not exposed by the API).

## What is done and tested (no SolidWorks needed)

* Provenance review of 10 public repositories (commits, licenses; no code copied): `public-repository-review.md`; verification limits: `research-sources.md`.
* Capability registry of all 9 families and 81 variants, pinned to the installed enums; every candidate property exists on the installed `IWizardHoleFeatureData2` (75 members).
* Callout parser and a corpus inventory over the repo's own saved runs: of 402 distinct callout strings, 143 parse as hole/thread callouts (5 with a flagged ambiguity); families found: hole=104, straight_tap=21, counterbore=14, pipe_tap=4. Real drawings in this corpus contain **pipe threads** (`pipe_tap`), which the existing compiler deliberately leaves as plain cuts. See `callout-inventory.md`.

## Not done in Stage 4 (be explicit)

| Task | State |
|---|---|
| 4.3 versioned hole-intent IR + migration from `HoleSpec` | **not done** (the registry and parser exist; no IR model or migration) |
| 4.5 installed-catalog discovery | **not done**: `IHoleStandardsData` returns nothing here; no fake-COM adapter or resolver written |
| 4.7 typed creation adapters (7 slices) | **not done** |
| 4.8 placement policy incl. radial holes | **not done** |
| 4.9 CadQuery reference for the expanded geometry | **not done** |
| 4.10 `IWizardHoleFeatureData2` readback verification | **not done** (blocked at creation) |
| 4.11 Hole Callout round trip, save/reopen/rebuild | **not done** (blocked at creation) |
| 4.12 Advanced Hole / Hole Series IR + compiler status | registry/parser status only |
| 4.13 generated acceptance matrix over catalog x registry | **not done**; cannot run until Hole Wizard works here |

## Conflict recorded with an older rule

The compiler still turns a refused Hole Wizard call into a logged plain cut (`compile_solidworks.hole_wizard`). The Stage 4 rule forbids reporting such a result as Hole Wizard support. It is unchanged here (task 4.7) and is exactly why E037 went unnoticed.
