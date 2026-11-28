# Research sources and verification status (Stage 4, task 4.1)

## What was verified, and how

| Claim | Evidence | Where |
|---|---|---|
| 9 general families (`swWzdGeneralHoleTypes_e`) with values 0-8 | Installed type library (SOLIDWORKS 2025, `swconst.tlb`) | `tests/fixtures/sw_hole_enums_2025.json`, `tests/test_hole_capabilities.py` |
| 81 specific variants (`swWzdHoleTypes_e`), values 0-79 and 90, non-contiguous | Installed type library | same |
| The 2026 install on this machine has the same 9 and 81 | Both installs' type libraries compared | `tools/read_sw_typelib.py` |
| 19 `swWzdHoleStandards_e` and 404 `swWzdHoleStandardFastenerTypes_e` members | Installed type library | fixture |
| `ISldWorks.GetHoleStandardsData`, `IHoleStandardsData.GetHoleStandards/GetFastenerTypes/GetFastenerTableTypes/GetFastenerTable` exist | Installed type library | fixture / typelib tool |
| `IFeatureManager.CreateDefinition/CreateFeature/HoleWizard5/AdvancedHole(2)` exist; `IWizardHoleFeatureData2` has 75 named members incl. `InitializeHole` | Installed type library | fixture |
| `IAssemblyDoc` exposes no hole method: **Hole Series has no API in this release** | Installed type library | fixture |
| Public repository commits and licenses | GitHub API, 2026-11-18 | `public-repository-review.md` |

## What could NOT be verified from this environment

* **Official documentation pages** (`help.solidworks.com`): requests are refused (HTTP 403 to a plain client, 502 through the fetch tool). The official *valid-property table per hole type*, the Hole Callout pages and the Hole Wizard PropertyManager pages were therefore **not read**. Per-variant property validity is consequently established only by live readback (see the matrix), not by the table.
* **`IHoleStandardsData` enumeration does not work in this install**: `GetHoleStandards`, `GetFastenerTypes` etc. return `False` for every family, with a part open and after Hole Wizard use, through both early- and late-bound calls. `HoleWizard5` itself works. Catalog discovery therefore uses live creation probing here (`HW_CATALOG_ENUMERATION_UNAVAILABLE` is recorded), and the fingerprint comes from files that exist (version, `ToolboxStandards.xml`, `Holewzd.idx`).
* Two SOLIDWORKS installs coexist (2026 and 2025). The running session is **2025 SP5 (33.5)**; evidence is read from that install. The repo's constants loader selected the 2026 (34.0) type library for a 2025 session: values for the hole enums are identical, but this is a latent risk for other enums.

## Official references named in the plan (not re-verified; see above)

The links listed in `SOLIDWORKS_HOLE_WIZARD_CAPABILITY_MATRIX.md` section 12 remain the reference list. Treat any statement that depends solely on them as unverified until the pages can be read.
