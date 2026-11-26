# Dependency and reference register

Reference repositories were shallow-cloned into `reference-repos/` (git-ignored, never vendored, nothing executed) on 2026-11-25 and inspected as data.

| Repository | Commit pinned | License | What was used | Decision |
|---|---|---|---|---|
| xarial/codestack | `0cde3849a184cdbbface61238ef431a6ebb9d530` | MIT (Xarial Pty Limited, 2025) | pattern reference for drawing views, annotations, selection | **Reference only.** No code copied. The pipeline calls the installed COM interop directly. |
| xarial/xcad | `f9feb293f74576a6a5dbb3ffcca99502e0a257ed` | MIT | C# CAD abstraction (add-ins, Document Manager) | **Not adopted.** Native COM from the existing Python bridge is the smaller dependency set and needs no extra runtime. |
| xarial/xcad-examples | `6955659619237b86579b7dd610b3a8b10dbd0583` | no LICENSE file found | worker / metadata layout ideas | **Reference only; reuse rights unverified. Nothing copied.** |
| cochilocovt/solidworks-vba-3d-to-2d | `a4d4fbaf298b86f1ec66b6b413652d83701bb490` | **no LICENSE file; reuse rights unverified** | closest prior art (2025 VBA, annotation import, hole-centre ordinate dims, QA). Its `Agents.md` restricts live runs to its own three authorized fixtures and requires permission for any other model, ANSI/Windows-1252 VBA, checked return values, active view before selection. | **Reference only. Not executed on any Solid Flow input, nothing copied or vendored.** Its guidance (read back every value, validate constants against the installed library, evidence gates) was followed independently. |
| Erfouni/solidworks-drawing-api-2026 | `c618b291750bdfc00e5584ae59913e3e92378dc6` | MIT (Erfouni, 2026) | API database derived from 2026 docs | **Discovery aid only.** Every member was re-probed on the installed 2025 runtime (see `api_validation.md`); no 2026-only call is used. |
| Lokesh-J-03/solidworks-drawing-to-pdf | `554573d2aacc62ea9cab04c07fc6e7bd020f8b92` | no LICENSE file; contains a prebuilt `.exe` | batch multi-sheet PDF export UX idea | **Reference only. The bundled executable was not run. Nothing copied.** |

## Runtime dependencies added by this work
No new third-party packages. Already present: `pywin32` (COM), `pydantic` (schemas), `PyMuPDF` (`fitz`, PDF checks and rasterisation; FINAL_UI already ships it), `pytest`.
`CadQuery` is used only by the existing forward pipeline. Document Manager is not used (metadata-only and needs a license key).

## Security review notes
* Catalog / material files are parsed as data: size-capped, `DOCTYPE`/`ENTITY` refused, paths kept inside the chosen folder, symbolic links skipped.
* Job inputs: absolute authorized paths only, traversal and symlink escapes refused, NUL refused, extensions and document types checked, collision-safe ids.
* Artifact downloads are limited to files listed on the job and inside the job folder.
* The source SLDPRT is hashed before and after each job and never saved; a working copy is what the drawing references.
