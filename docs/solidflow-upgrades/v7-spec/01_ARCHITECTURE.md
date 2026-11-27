# Architecture and integration contract

## 1. Discover existing implementation
Locate actual frontend components, route, state store, upload/file APIs, reverse pipeline coordinator, native SolidWorks COM worker, OpenAI extraction client, forward run manifests, artifact storage, project history, scoring, and batch queue. Document real paths and interfaces before edits. Reuse existing stack, worker and API client; do not introduce an independent app. Maintain migrations/backward compatibility and feature flags if required. Confirm installed SolidWorks 2025 type library and service pack; use existing STA COM execution model, serial native operations, explicit document activation and error handling. Do not open multiple interactive jobs concurrently. Read parts and reference PDFs without overwriting them.

## 2. Stages and data flow
1. Validate source part/configuration, template, reference mode, optional PDF and project scope.
2. Open part read-only when compatible with export, rebuild in memory, inventory native features, geometry, model dimensions, properties and units; export STL using existing verified process.
3. Resolve reference: explicit PDF > confirmed linked history > no reference. If explicit Reference match and no source, stop or ask user to select source; do not silently switch modes. Standard mode intentionally skips reference.
4. Load a compatible prior OpenAI extraction, or run fresh extraction; normalize to typed reference schema; preserve evidence and provenance.
5. Build view/annotation plan from reference plus actual geometry (or standard layout when no reference).
6. Create associative native drawing and views, attach dimensions/notes, use shaded-with-edges isometric, apply native leader and dimension standards.
7. Arrange and compare; iterate bounded corrections using actual drawing coordinates, exported PDF rendering and semantic comparison.
8. Validate and publish SLDDRW + PDF with QA status and source/model linkage. Update UI and batch queue.

State machine: queued → preflight → STL export → reference resolution → extraction/cache hit → view planning → native drawing → dimensioning/layout → comparison/correction → verification → publish → completed / review_required / failed / cancelled. Standard mode marks reference-only stages not applicable. Existing progress indicators may group sub-stages. No green completion if hard QA failures remain. Record actual time and actual API usage; distinguish cached zero incremental API charge from historical costs. Local CAD processing time is not token cost.

## 3. Suggested versioned contracts (adapt names to repo)
`ReverseRunRequest`: runId, projectId, partArtifactId, partPath (server-resolved), partSha256, configuration, templateId, mode, referenceSelection (none/manual/history), referenceArtifactId, outputOptions, batchId.
`ReferenceResolution`: sourceKind, sourceArtifactId, forwardRunId, pdfSha256, partMatchEvidence, extractionId, extractionSchemaVersion, cacheStatus, warnings.
`DrawingPlan`: source sheet size/units/projection, sheet/view IDs, orientation/scale/placement, source-to-sheet transform, native entity mappings, dimensions/notes/leader settings, required coverage items, unresolved requirements.
`VerificationReport`: geometry, semantic coverage, view/annotation positions, collisions, clipping, native file checks, reference differences, severity, iteration history, review reasons, status.
`ArtifactManifest`: runId, per-part IDs, source PDF, STL, native drawing, exported PDF, QA JSON, comparison images, MIME, size, SHA256, revision, availability, createdAt; path must remain within authorized artifact storage.

## 4. Persistence and lifecycle
Use immutable run-specific artifacts and atomic publication (temp → validate → rename); keep previous successful runs available. Stable source links must use content hashes and configuration, not filenames alone. Store manifest provenance in existing database or versioned sidecar with migration. Treat old runs missing metadata as candidates, not confirmed matches. Never expose credentials or arbitrary filesystem paths to frontend. For batch, resolve reference per part; never use one PDF for all unless an explicitly verified mapping exists. Cancellation stops between safe COM operations; retain partial diagnostics separately. Restore app preferences changed by the worker and preserve input files. Keep reference matching and manual approval state per part/run.

## 5. API validation
Use installed 2025 interop and official docs https://help.solidworks.com/2025/english/api/ as authorities. Candidate calls/interfaces (verify exact overloads, enums, units, returns and preconditions): ISldWorks.OpenDoc6/NewDocument, IDrawingDoc.CreateDrawViewFromModelView3/Create3rdAngleViews2, IView.Position/GetOutline/ScaleDecimal/ModelToViewTransform/SetDisplayMode3, IDrawingDoc.InsertModelAnnotations3, IModelDoc2.AddDimension2, IDisplayDimension/IAnnotation, IModelDocExtension.AlignDimensions (or installed equivalent), IModelDocExtension.SaveAs variants, IExportPdfData. Do not assume any listed overload is supported without compilation/probe. Record API ledger with verified signatures and evidence. Use meters/radians where required; convert explicitly from drawing and PDF units. Native drawing remains editable and associative; PDF is exported from that drawing, not a background image overlay.

References for implementation lookup (not newly verified in this package): https://github.com/xarial/codestack, https://github.com/xarial/xcad, https://github.com/xarial/xcad-examples, https://github.com/cochilocovt/solidworks-vba-3d-to-2d. Review license and installed API compatibility before borrowing code. No unapproved vendoring. Do not need a new library if existing automation suffices.
