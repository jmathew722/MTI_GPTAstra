# File migration report (v8 reorganisation)

Baseline: tag `pre-reorg-v8` (head of `ImprovementsV7` plus run outputs). `git log --follow <new path>` keeps the full history of every moved file.

## Folder-level moves

| Original | New | Notes |
|---|---|---|
| `DrawingPDFs/` | `data/inputs/drawing_pdfs/` | source drawings (PDF) |
| `NewVerifiedDrawings/` | `data/inputs/verified_drawings/` | |
| `ViewDefinedDrawings/` | `data/inputs/view_defined_drawings/` | `bench/manifest.yaml` and `ir_plan.py` updated |
| `Simple Parts/` | `data/inputs/simple_parts/` | space removed from the name |
| `test_set.csv` | `data/inputs/mti_test_set.csv` | identical copy of `bench/mti_test_set.csv` |
| `docs/PRD*.md` | `docs/product/` | |
| `docs/demo-guide.md`, `docs/demo/` | `docs/guides/` | |
| `docs/mti-modeling-standards.md`, `docs/mti-practices-big-problems.md`, `docs/mti-questions/` | `docs/mti/` | |
| `docs/scoring-rubric-emf.md` | `docs/scoring/` | |
| `docs/solidworks-macro-error-log.md`, `docs/hole-wizard/` | `docs/solidworks/` | |
| `jid.txt` | `archive/misc/jid.txt` | stray job id (gitignored) |

## Removed from version control (files stay on disk, now ignored)

SolidWorks lock/autosave files (`~$*.SLDPRT`, `AUTOSAVE_*`): 21 tracked files. Disposable; `.gitignore` now excludes them.

## Not moved, on purpose

- `2D-3D-CAD-Test-Generation/` (Python packages `pipeline/`, `reverse/`, `bench/`, `utils/`, `tools/`, `tests/`): moving them would change every import, 1601 tests, the golden macro snapshots and the documented commands. The layout is described in `REPOSITORY_MAP.md` instead.
- `FINAL_UI/` (FastAPI server + vanilla-JS UI): already `server/`, `web/`, `tests/`, `docs/`; stored project records and recordings point at its `data/` folder.
- `FINAL_OUTPUTs/`: the live output root the UI and `make_part.py` write to and read from. Stored project records, native `.SLDDRW` to `.SLDPRT` references and recordings use these paths; relocating them is a data migration, not a refactor.
- `2D-3D-CAD-Test-Generation/extraction_11{5,6,7}C.json`: the UI Demo replays them (`/api/demo`); briefly archived and restored, see `ARCHIVE_MANIFEST.md`.
- `graphify-out/`: output location of the graphify tool. `reference-repos/`: untracked, gitignored research clones.

## Backward compatibility

`2D-3D-CAD-Test-Generation/utils/paths.py` holds the central locations and `resolve_input()`, which maps the old folder names (`DrawingPDFs`, `Simple Parts`, ...) to the new ones. `reverse/reference.py` still also searches the old `DrawingPDFs` name. No stored project record in `FINAL_UI/data` or `FINAL_OUTPUTs` held a path to a moved folder (checked by search).

## Complete rename list

180 renames detected by git (`git diff -M --name-status pre-reorg-v8 HEAD`).

<details><summary>All renames</summary>

```
DrawingPDFs/A001131E.PDF -> data/inputs/drawing_pdfs/A001131E.PDF
DrawingPDFs/A001151E.PDF -> data/inputs/drawing_pdfs/A001151E.PDF
DrawingPDFs/A001171E.PDF -> data/inputs/drawing_pdfs/A001171E.PDF
DrawingPDFs/A001351E.PDF -> data/inputs/drawing_pdfs/A001351E.PDF
test_set.csv -> data/inputs/mti_test_set.csv
Simple Parts/0014630E.pdf -> data/inputs/simple_parts/0014630E.pdf
Simple Parts/0178302E.pdf -> data/inputs/simple_parts/0178302E.pdf
Simple Parts/16247.pdf -> data/inputs/simple_parts/16247.pdf
Simple Parts/A001151E.PDF -> data/inputs/simple_parts/A001151E.PDF
Simple Parts/A001161E.PDF -> data/inputs/simple_parts/A001161E.PDF
Simple Parts/A001171E.PDF -> data/inputs/simple_parts/A001171E.PDF
Simple Parts/A001211E.PDF -> data/inputs/simple_parts/A001211E.PDF
Simple Parts/A001211M.PDF -> data/inputs/simple_parts/A001211M.PDF
Simple Parts/A001221E.PDF -> data/inputs/simple_parts/A001221E.PDF
Simple Parts/A001271E.PDF -> data/inputs/simple_parts/A001271E.PDF
Simple Parts/A001291E.PDF -> data/inputs/simple_parts/A001291E.PDF
Simple Parts/A001341E.PDF -> data/inputs/simple_parts/A001341E.PDF
Simple Parts/A001351E.PDF -> data/inputs/simple_parts/A001351E.PDF
Simple Parts/A001421E.PDF -> data/inputs/simple_parts/A001421E.PDF
Simple Parts/A001431E.PDF -> data/inputs/simple_parts/A001431E.PDF
Simple Parts/A001441E.PDF -> data/inputs/simple_parts/A001441E.PDF
Simple Parts/A001451E.PDF -> data/inputs/simple_parts/A001451E.PDF
Simple Parts/A001471E.PDF -> data/inputs/simple_parts/A001471E.PDF
Simple Parts/A001551E.PDF -> data/inputs/simple_parts/A001551E.PDF
Simple Parts/A001561E.PDF -> data/inputs/simple_parts/A001561E.PDF
Simple Parts/A001571E.PDF -> data/inputs/simple_parts/A001571E.PDF
Simple Parts/A001581E.PDF -> data/inputs/simple_parts/A001581E.PDF
Simple Parts/A001591E.PDF -> data/inputs/simple_parts/A001591E.PDF
Simple Parts/A001601E.PDF -> data/inputs/simple_parts/A001601E.PDF
Simple Parts/A001611E.PDF -> data/inputs/simple_parts/A001611E.PDF
Simple Parts/A001621E.PDF -> data/inputs/simple_parts/A001621E.PDF
Simple Parts/A001641E.PDF -> data/inputs/simple_parts/A001641E.PDF
Simple Parts/A001651E.PDF -> data/inputs/simple_parts/A001651E.PDF
Simple Parts/A001661E.PDF -> data/inputs/simple_parts/A001661E.PDF
Simple Parts/A001731E.PDF -> data/inputs/simple_parts/A001731E.PDF
Simple Parts/A001741E.PDF -> data/inputs/simple_parts/A001741E.PDF
Simple Parts/A001761E.PDF -> data/inputs/simple_parts/A001761E.PDF
Simple Parts/A001821E.PDF -> data/inputs/simple_parts/A001821E.PDF
Simple Parts/A001821M.PDF -> data/inputs/simple_parts/A001821M.PDF
Simple Parts/A001831E.PDF -> data/inputs/simple_parts/A001831E.PDF
Simple Parts/A001851E.PDF -> data/inputs/simple_parts/A001851E.PDF
Simple Parts/A001871E.PDF -> data/inputs/simple_parts/A001871E.PDF
Simple Parts/A001901E.PDF -> data/inputs/simple_parts/A001901E.PDF
Simple Parts/A001911E.PDF -> data/inputs/simple_parts/A001911E.PDF
Simple Parts/A001921E.PDF -> data/inputs/simple_parts/A001921E.PDF
Simple Parts/A001931E.PDF -> data/inputs/simple_parts/A001931E.PDF
Simple Parts/A001961E.PDF -> data/inputs/simple_parts/A001961E.PDF
Simple Parts/A001971E.PDF -> data/inputs/simple_parts/A001971E.PDF
Simple Parts/A001971M.PDF -> data/inputs/simple_parts/A001971M.PDF
Simple Parts/A001981E.PDF -> data/inputs/simple_parts/A001981E.PDF
Simple Parts/A002031E.PDF -> data/inputs/simple_parts/A002031E.PDF
Simple Parts/A002041E.PDF -> data/inputs/simple_parts/A002041E.PDF
Simple Parts/A002121E.PDF -> data/inputs/simple_parts/A002121E.PDF
Simple Parts/A002141E.PDF -> data/inputs/simple_parts/A002141E.PDF
Simple Parts/A002151E.PDF -> data/inputs/simple_parts/A002151E.PDF
Simple Parts/A040001E.PDF -> data/inputs/simple_parts/A040001E.PDF
Simple Parts/A040011E.PDF -> data/inputs/simple_parts/A040011E.PDF
Simple Parts/A040061E.PDF -> data/inputs/simple_parts/A040061E.PDF
Simple Parts/A040161E.PDF -> data/inputs/simple_parts/A040161E.PDF
Simple Parts/A040171E.PDF -> data/inputs/simple_parts/A040171E.PDF
Simple Parts/A040181E.PDF -> data/inputs/simple_parts/A040181E.PDF
Simple Parts/A040231E.PDF -> data/inputs/simple_parts/A040231E.PDF
Simple Parts/A040241E.PDF -> data/inputs/simple_parts/A040241E.PDF
Simple Parts/A040271E.PDF -> data/inputs/simple_parts/A040271E.PDF
Simple Parts/A040281E.PDF -> data/inputs/simple_parts/A040281E.PDF
Simple Parts/A040301E.PDF -> data/inputs/simple_parts/A040301E.PDF
Simple Parts/A040311E.PDF -> data/inputs/simple_parts/A040311E.PDF
Simple Parts/A040401E.PDF -> data/inputs/simple_parts/A040401E.PDF
Simple Parts/A040411E.PDF -> data/inputs/simple_parts/A040411E.PDF
Simple Parts/A040421E.PDF -> data/inputs/simple_parts/A040421E.PDF
Simple Parts/A040431E.PDF -> data/inputs/simple_parts/A040431E.PDF
Simple Parts/A040441E.PDF -> data/inputs/simple_parts/A040441E.PDF
Simple Parts/A040471E.PDF -> data/inputs/simple_parts/A040471E.PDF
Simple Parts/A040491E.PDF -> data/inputs/simple_parts/A040491E.PDF
Simple Parts/A040501E.PDF -> data/inputs/simple_parts/A040501E.PDF
Simple Parts/A040511E.PDF -> data/inputs/simple_parts/A040511E.PDF
Simple Parts/A040531E.PDF -> data/inputs/simple_parts/A040531E.PDF
Simple Parts/A040541E.PDF -> data/inputs/simple_parts/A040541E.PDF
Simple Parts/A040551E.PDF -> data/inputs/simple_parts/A040551E.PDF
Simple Parts/A040571E.PDF -> data/inputs/simple_parts/A040571E.PDF
Simple Parts/A040581E.PDF -> data/inputs/simple_parts/A040581E.PDF
Simple Parts/A040591E.PDF -> data/inputs/simple_parts/A040591E.PDF
Simple Parts/A040641E.PDF -> data/inputs/simple_parts/A040641E.PDF
Simple Parts/A040661E.PDF -> data/inputs/simple_parts/A040661E.PDF
Simple Parts/A040671E.PDF -> data/inputs/simple_parts/A040671E.PDF
Simple Parts/A040681E.PDF -> data/inputs/simple_parts/A040681E.PDF
Simple Parts/A040701E.PDF -> data/inputs/simple_parts/A040701E.PDF
Simple Parts/A040711E.PDF -> data/inputs/simple_parts/A040711E.PDF
Simple Parts/A040721E.PDF -> data/inputs/simple_parts/A040721E.PDF
Simple Parts/A040741E.PDF -> data/inputs/simple_parts/A040741E.PDF
Simple Parts/A040751E.PDF -> data/inputs/simple_parts/A040751E.PDF
Simple Parts/A040771E.PDF -> data/inputs/simple_parts/A040771E.PDF
Simple Parts/A040781E.PDF -> data/inputs/simple_parts/A040781E.PDF
Simple Parts/A040831E.PDF -> data/inputs/simple_parts/A040831E.PDF
Simple Parts/A040841E.PDF -> data/inputs/simple_parts/A040841E.PDF
Simple Parts/A040851E.PDF -> data/inputs/simple_parts/A040851E.PDF
Simple Parts/A040861E.PDF -> data/inputs/simple_parts/A040861E.PDF
Simple Parts/A040871E.PDF -> data/inputs/simple_parts/A040871E.PDF
Simple Parts/A040881E.PDF -> data/inputs/simple_parts/A040881E.PDF
Simple Parts/A040891E.PDF -> data/inputs/simple_parts/A040891E.PDF
Simple Parts/A040911E.PDF -> data/inputs/simple_parts/A040911E.PDF
Simple Parts/A040921E.PDF -> data/inputs/simple_parts/A040921E.PDF
Simple Parts/SB10009 SHT 4.pdf -> data/inputs/simple_parts/SB10009 SHT 4.pdf
Simple Parts/SB10010 SHT 2.pdf -> data/inputs/simple_parts/SB10010 SHT 2.pdf
Simple Parts/SB10011.pdf -> data/inputs/simple_parts/SB10011.pdf
Simple Parts/SB10012.pdf -> data/inputs/simple_parts/SB10012.pdf
Simple Parts/SB10016.pdf -> data/inputs/simple_parts/SB10016.pdf
Simple Parts/SB10021 SHT 2.pdf -> data/inputs/simple_parts/SB10021 SHT 2.pdf
Simple Parts/SB10022.pdf -> data/inputs/simple_parts/SB10022.pdf
Simple Parts/SB10049 SHT 8.pdf -> data/inputs/simple_parts/SB10049 SHT 8.pdf
Simple Parts/SB11033.pdf -> data/inputs/simple_parts/SB11033.pdf
Simple Parts/SB11034.pdf -> data/inputs/simple_parts/SB11034.pdf
Simple Parts/SB11037.pdf -> data/inputs/simple_parts/SB11037.pdf
Simple Parts/SB11038.pdf -> data/inputs/simple_parts/SB11038.pdf
Simple Parts/SB11629.pdf -> data/inputs/simple_parts/SB11629.pdf
Simple Parts/SB11780.pdf -> data/inputs/simple_parts/SB11780.pdf
Simple Parts/SB11842.pdf -> data/inputs/simple_parts/SB11842.pdf
NewVerifiedDrawings/0014630E.png -> data/inputs/verified_drawings/0014630E.png
NewVerifiedDrawings/0014630E_front_view (1).png -> data/inputs/verified_drawings/0014630E_front_view (1).png
NewVerifiedDrawings/0014630E_side_view (1).png -> data/inputs/verified_drawings/0014630E_side_view (1).png
NewVerifiedDrawings/16247 (1).png -> data/inputs/verified_drawings/16247 (1).png
NewVerifiedDrawings/16247_front_view (1).png -> data/inputs/verified_drawings/16247_front_view (1).png
NewVerifiedDrawings/16247_side_view.png -> data/inputs/verified_drawings/16247_side_view.png
NewVerifiedDrawings/A001211E_front_view (1).png -> data/inputs/verified_drawings/A001211E_front_view (1).png
NewVerifiedDrawings/A001211E_side_view.png -> data/inputs/verified_drawings/A001211E_side_view.png
NewVerifiedDrawings/A001271E (1).png -> data/inputs/verified_drawings/A001271E (1).png
NewVerifiedDrawings/A001271E_front_view (1).png -> data/inputs/verified_drawings/A001271E_front_view (1).png
NewVerifiedDrawings/A001271E_side_view (1).png -> data/inputs/verified_drawings/A001271E_side_view (1).png
NewVerifiedDrawings/A001291E_front_view.png -> data/inputs/verified_drawings/A001291E_front_view.png
NewVerifiedDrawings/A001291E_side_view (1).png -> data/inputs/verified_drawings/A001291E_side_view (1).png
NewVerifiedDrawings/A001561E_side_view (1).png -> data/inputs/verified_drawings/A001561E_side_view (1).png
NewVerifiedDrawings/A001581E_side_view (1).png -> data/inputs/verified_drawings/A001581E_side_view (1).png
NewVerifiedDrawings/A001591E (1).png -> data/inputs/verified_drawings/A001591E (1).png
NewVerifiedDrawings/A001591E_front_view (1).png -> data/inputs/verified_drawings/A001591E_front_view (1).png
NewVerifiedDrawings/A001601E (1).png -> data/inputs/verified_drawings/A001601E (1).png
NewVerifiedDrawings/A001601E_side_view (1).png -> data/inputs/verified_drawings/A001601E_side_view (1).png
NewVerifiedDrawings/A001621E (1).png -> data/inputs/verified_drawings/A001621E (1).png
NewVerifiedDrawings/A001621E_front_view (1).png -> data/inputs/verified_drawings/A001621E_front_view (1).png
NewVerifiedDrawings/A001621E_side_view (1).png -> data/inputs/verified_drawings/A001621E_side_view (1).png
NewVerifiedDrawings/A001821M (1).png -> data/inputs/verified_drawings/A001821M (1).png
NewVerifiedDrawings/A001821M_front_view.png -> data/inputs/verified_drawings/A001821M_front_view.png
NewVerifiedDrawings/A001821M_side_view (1).png -> data/inputs/verified_drawings/A001821M_side_view (1).png
NewVerifiedDrawings/A001901E.png -> data/inputs/verified_drawings/A001901E.png
NewVerifiedDrawings/A001901E_front_view (1).png -> data/inputs/verified_drawings/A001901E_front_view (1).png
NewVerifiedDrawings/A001901E_side_view (1).png -> data/inputs/verified_drawings/A001901E_side_view (1).png
ViewDefinedDrawings/A040911E-20260618T093212Z-3-001/A040911E/A040911E.png -> data/inputs/view_defined_drawings/A040911E-20260618T093212Z-3-001/A040911E/A040911E.png
ViewDefinedDrawings/A040911E-20260618T093212Z-3-001/A040911E/A040911E_front.png -> data/inputs/view_defined_drawings/A040911E-20260618T093212Z-3-001/A040911E/A040911E_front.png
ViewDefinedDrawings/A040911E-20260618T093212Z-3-001/A040911E/A040911E_side.png -> data/inputs/view_defined_drawings/A040911E-20260618T093212Z-3-001/A040911E/A040911E_side.png
ViewDefinedDrawings/A040921E-20260618T093224Z-3-001/A040921E/A040921E.png -> data/inputs/view_defined_drawings/A040921E-20260618T093224Z-3-001/A040921E/A040921E.png
ViewDefinedDrawings/A040921E-20260618T093224Z-3-001/A040921E/A040921E_front.png -> data/inputs/view_defined_drawings/A040921E-20260618T093224Z-3-001/A040921E/A040921E_front.png
ViewDefinedDrawings/A040921E-20260618T093224Z-3-001/A040921E/A040921E_side.png -> data/inputs/view_defined_drawings/A040921E-20260618T093224Z-3-001/A040921E/A040921E_side.png
ViewDefinedDrawings/SB11033-20260618T093243Z-3-001/SB11033/SB11033.png -> data/inputs/view_defined_drawings/SB11033-20260618T093243Z-3-001/SB11033/SB11033.png
ViewDefinedDrawings/SB11033-20260618T093243Z-3-001/SB11033/SB11033_front.png -> data/inputs/view_defined_drawings/SB11033-20260618T093243Z-3-001/SB11033/SB11033_front.png
ViewDefinedDrawings/SB11033-20260618T093243Z-3-001/SB11033/SB11033_side.png -> data/inputs/view_defined_drawings/SB11033-20260618T093243Z-3-001/SB11033/SB11033_side.png
ViewDefinedDrawings/SB11780-20260618T093317Z-3-001/SB11780/SB11780.png -> data/inputs/view_defined_drawings/SB11780-20260618T093317Z-3-001/SB11780/SB11780.png
ViewDefinedDrawings/SB11780-20260618T093317Z-3-001/SB11780/SB11780_front.png -> data/inputs/view_defined_drawings/SB11780-20260618T093317Z-3-001/SB11780/SB11780_front.png
ViewDefinedDrawings/SB11780-20260618T093317Z-3-001/SB11780/SB11780_side.png -> data/inputs/view_defined_drawings/SB11780-20260618T093317Z-3-001/SB11780/SB11780_side.png
ViewDefinedDrawings/SB11842-20260618T093328Z-3-001/SB11842/SB11842.png -> data/inputs/view_defined_drawings/SB11842-20260618T093328Z-3-001/SB11842/SB11842.png
ViewDefinedDrawings/SB11842-20260618T093328Z-3-001/SB11842/SB11842_front.png -> data/inputs/view_defined_drawings/SB11842-20260618T093328Z-3-001/SB11842/SB11842_front.png
ViewDefinedDrawings/SB11842-20260618T093328Z-3-001/SB11842/SB11842_side.png -> data/inputs/view_defined_drawings/SB11842-20260618T093328Z-3-001/SB11842/SB11842_side.png
docs/demo-guide.md -> docs/guides/demo-guide.md
docs/demo/2026-11-02-mti-demo-runbook.md -> docs/guides/demo/2026-11-02-mti-demo-runbook.md
docs/mti-modeling-standards.md -> docs/mti/mti-modeling-standards.md
docs/mti-practices-big-problems.md -> docs/mti/mti-practices-big-problems.md
docs/mti-questions/2026-10-28-model-vs-drawing-mismatches.md -> docs/mti/mti-questions/2026-10-28-model-vs-drawing-mismatches.md
docs/PRD-aws.md -> docs/product/PRD-aws.md
docs/PRD-azure.md -> docs/product/PRD-azure.md
docs/PRD.md -> docs/product/PRD.md
docs/scoring-rubric-emf.md -> docs/scoring/scoring-rubric-emf.md
docs/hole-wizard/_repo_facts.json -> docs/solidworks/hole-wizard/_repo_facts.json
docs/hole-wizard/callout-inventory.md -> docs/solidworks/hole-wizard/callout-inventory.md
docs/hole-wizard/matrix-results.json -> docs/solidworks/hole-wizard/matrix-results.json
docs/hole-wizard/preflight-result.json -> docs/solidworks/hole-wizard/preflight-result.json
docs/hole-wizard/public-repository-review.md -> docs/solidworks/hole-wizard/public-repository-review.md
docs/hole-wizard/research-sources.md -> docs/solidworks/hole-wizard/research-sources.md
docs/hole-wizard/support-status.md -> docs/solidworks/hole-wizard/support-status.md
docs/solidworks-macro-error-log.md -> docs/solidworks/solidworks-macro-error-log.md
```

</details>
