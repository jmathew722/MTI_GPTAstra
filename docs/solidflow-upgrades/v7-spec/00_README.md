# Solid Flow | 3D → 2D reference reconstruction and workspace upgrade

## Objective
Extend the existing working SolidWorks 2025 reverse pipeline, not replace it. Implement optional reference-driven reconstruction, reliable native drawing layout and annotation standards, a compact setup rail, source PDF viewer toggle, native drawing/PDF export, and responsive workspace/batch layout. Preserve 2D → 3D, material assignment, recording, scoring and existing project history.

## Execution order
Read all files before editing. Follow `06_MASTER_CLAUDE_PROMPT.md` as the controlling directive. Inventory actual source and APIs; then implement 01 (architecture), 02 (reference extraction/reconstruction), 03 (native drawing standards), 04 (UI/export), and 05 (acceptance). Commit/checkpoint after each validated stage; continue independent work when blocked. No destructive changes to original PDFs or parts.

## Screenshot observations and design decisions
The current screenshot shows setup at the **right** of the reverse workspace, a left STL pane, a right generated PDF pane, and a batch queue far below the viewers. The user also refers to setup as left in text. Preserve the current right-hand setup rail (unless the actual application already places it left); put Export at its bottom, not beneath the left viewer. The left viewer gains the source PDF toggle. Eliminate unexplained empty vertical space between viewers and batch queue. Do not redesign unrelated screens.

Two modes: Standard (no reference) and Reference match (manual or history). Reference matching targets equivalent content, view layout and annotation placement, not a false guarantee of pixel-identical output or engineering equivalence. Never fabricate tolerances or override model geometry to make a drawing appear correct. Mark unresolvable differences explicitly; release requires engineering review when applicable.

Native execution requires the existing Windows environment, licensed SolidWorks 2025, authorized fixtures and configured OpenAI credentials. This package is a specification, not a tested software implementation.
