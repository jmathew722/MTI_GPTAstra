# Public repository review (Stage 4, task 4.1)

Facts below were read from the GitHub API on 2026-11-18 (default-branch head commit and declared license).
**Scope and honesty:** this is a metadata review. The repositories' source was **not** audited line by line, and **no code from any of them was copied or imported**. The role/limitation columns restate the claims in `claude-code-plans/SOLIDWORKS_HOLE_WIZARD_CAPABILITY_MATRIX.md`; they were not independently re-derived here.

| Repository | License | Head commit (default branch) | Commit date | Contribution (per the matrix) | Limitation (per the matrix) | Reuse policy |
|---|---|---|---|---|---|---|
| [soheil-mp/solidworks-mcp](https://github.com/soheil-mp/solidworks-mcp) | MIT | `fd03a7f78eba` | 2026-11-05 | Live-verification notes, `feature_hole`, HoleWizard5 argument pitfalls, geometry rollback | Common families only (drill, clearance, counterbore, countersink, tapped) | Permissive; attribution required if code is copied. No code has been copied. |
| [kilwizac/solidworks-api-mcp](https://github.com/kilwizac/solidworks-api-mcp) | none declared | `7885946e1ee8` | 2026-10-12 | Searchable mirror of the official API docs | Documentation corpus, not an implementation | No license declared, so all rights are reserved by default: **no reuse rights.** Concepts only. |
| [slamatik/pysolidworks](https://github.com/slamatik/pysolidworks) | none declared | `78b9ca7a8294` | 2022-02-22 | Python wrapper exposing IWizardHoleFeatureData2 properties | Last commit 2022; says nothing about valid property combinations | No license declared, so all rights are reserved by default: **no reuse rights.** Concepts only. |
| [HarrierPigeon/Solidworks-MCP-Server](https://github.com/HarrierPigeon/Solidworks-MCP-Server) | MIT | `60c11fe45b6c` | 2026-08-07 | Python HoleWizard5 recipe | Reports Hole Wizard blocking/unreliability; common types | Permissive; attribution required if code is copied. No code has been copied. |
| [ambrosic/SW-MCP](https://github.com/ambrosic/SW-MCP) | none declared | `16a91beceb1b` | 2026-03-12 | COM patterns; documents a Hole Wizard caveat | Suggests a plain-cut workaround: exactly the silent fallback GPTAstra forbids | No license declared, so all rights are reserved by default: **no reuse rights.** Concepts only. |
| [RoboMechatronics/MyCustomTaskpane](https://github.com/RoboMechatronics/MyCustomTaskpane) | none declared | `87b65a12798d` | 2024-05-12 | One concrete HoleWizard5 through-hole call | One simple ANSI metric example | No license declared, so all rights are reserved by default: **no reuse rights.** Concepts only. |
| [xarial/codestack](https://github.com/xarial/codestack) | MIT | `0cde3849a184` | 2026-05-07 | Broad SOLIDWORKS API examples | No all-Hole-Wizard implementation found | Permissive; attribution required if code is copied. No code has been copied. |
| [xarial/xcad](https://github.com/xarial/xcad) | MIT | `f9feb293f745` | 2026-02-25 | CAD abstraction framework | General framework, no exhaustive Hole Wizard coverage | Permissive; attribution required if code is copied. No code has been copied. |
| [streetartist/solidworks-automation](https://github.com/streetartist/solidworks-automation) | GPL-3.0 | `3513f70e0c30` | 2026-05-08 | Offline API docs incl. HoleWizard5 / advanced hole pages | Documentation mirror | Strong copyleft: copying code would make GPTAstra GPL. **Do not copy.** Concepts only. |
| [luigidoria/CADapter](https://github.com/luigidoria/CADapter) | Apache-2.0 | `eef44dd5a149` | 2026-09-30 | Cross-version automation lessons | Explicitly excludes Hole Wizard from its reliable surface | Permissive with patent grant and notice requirements. No code has been copied. |

## Conclusions that shaped the design

* No reviewed repository covers all families and variants with creation, readback and verification; GPTAstra's own live matrix is the evidence.
* Four repositories declare **no license** and one is **GPL-3.0**: nothing may be copied from them. Any reuse of MIT/Apache code requires attribution at the point of use.
* A documented plain-cut workaround (SW-MCP) is the behavior this program forbids: an unsupported Hole Wizard feature returns a structured status, never a silent substitute.
* Documentation mirrors do not prove a call succeeds on a given release; the installed type library and live readback do.
