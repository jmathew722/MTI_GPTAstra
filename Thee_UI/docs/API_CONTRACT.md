# API CONTRACT — what the backend must implement

The UI talks to one interface, `ApiAdapter` (`nebula-cad/lib/api/adapter.ts`). The `http` adapter maps each method to the REST endpoint below. The Zod schemas in `nebula-cad/lib/schemas/index.ts` are the normative payload definitions; this document mirrors them. Every response is parsed with its schema, and a parse failure is shown to the user as an error.

## Conventions

- Base URL: `NEXT_PUBLIC_API_BASE_URL` (for example `http://127.0.0.1:8092/api`). Select the real adapter with `NEXT_PUBLIC_API_MODE=http`.
- JSON, UTF-8. Timestamps are ISO-8601 UTC strings. IDs are opaque strings.
- Lengths are in the project's `units` (`mm` or `in`). Volumes in cost payloads are cm³.
- Errors: non-2xx with `{ "error": { "code": string, "message": string } }`.
- Auth is out of scope for the UI. The backend holds all model-provider keys. The UI never sends or stores a secret.
- `isSample` must be `false` (or absent) on real data. The UI shows SAMPLE DATA wherever it is `true`.
- **Never send a status the pipeline did not earn.** A check that did not run is `not_run`. A stage that did not run is `skipped` or `pending`.

## Endpoints

| Method | Path | Adapter method | Returns |
|---|---|---|---|
| GET | `/system/status` | `getSystemStatus` | `SystemStatus` |
| GET | `/kpis` | `getKpis` | `Kpis` |
| GET | `/projects` | `listProjects` | `Project[]` |
| GET | `/projects/{id}` | `getProject` | `Project` |
| POST | `/projects/{id}/clone` | `cloneProject` | `Project` |
| GET | `/projects/{id}/drawing` | `getDrawing` | `Drawing` |
| GET | `/projects/{id}/extraction` | `getExtraction` | `ExtractionResult` |
| PATCH | `/projects/{id}/extraction/items/{itemId}` | `reviewExtractionItem` | `ExtractionItem` |
| GET | `/projects/{id}/build-plan` | `getBuildPlan` | `BuildPlan` |
| GET | `/projects/{id}/parameters` | `getParameters` | `Parameter[]` |
| PATCH | `/projects/{id}/parameters/{paramId}` | `updateParameter` | `Parameter` |
| GET | `/projects/{id}/validation` | `getValidation` | `ValidationCheck[]` |
| POST | `/projects/{id}/validation/{checkId}/override` | `overrideCheck` | `ValidationCheck` |
| DELETE | `/projects/{id}/validation/{checkId}/override` | `clearOverride` | `ValidationCheck` |
| GET | `/projects/{id}/cost` | `getCost` | `CostEstimate` |
| GET | `/projects/{id}/rubric` | `getRubricScore` | `RubricScore` |
| PUT | `/projects/{id}/rubric` | `saveRubricScore` | `RubricScore` |
| POST | `/projects/{id}/rubric/sign-off` | `signOff` | `RubricScore` |
| GET | `/projects/{id}/revisions` | `listRevisions` | `Revision[]` |
| GET | `/projects/{id}/audit` | `listAudit` | `AuditEvent[]` |
| GET | `/projects/{id}/comments` | `listComments` | `Comment[]` |
| POST | `/projects/{id}/comments` | `addComment` | `Comment` |
| GET | `/projects/{id}/exports` | `listExports` | `ExportArtifact[]` |
| GET | `/runs` | `listRuns` | `PipelineRun[]` |
| GET | `/runs/{runId}` | `getRun` | `PipelineRun` |
| POST | `/runs` (multipart: files + options JSON) | `startRun` | `PipelineRun` |
| POST | `/runs/{runId}/cancel` | `cancelRun` | `PipelineRun` |
| POST | `/runs/{runId}/retry` | `retryRun` | `PipelineRun` |
| GET | `/runs/{runId}/logs?after={seq}` | `getLogs` | `LogEntry[]` |
| GET | `/cost/monthly` | `getMonthlyCost` | `MonthlyCost` |
| GET | `/rubric/templates` | `listRubricTemplates` | `RubricTemplate[]` |
| PUT | `/rubric/templates/{id}` | `saveRubricTemplate` | `RubricTemplate` |
| DELETE | `/rubric/templates/{id}` | `deleteRubricTemplate` | `204` |
| GET | `/notifications` | `listNotifications` | `Notification[]` |
| POST | `/notifications/read` | `markNotificationsRead` | `204` |

Live progress: the UI polls `GET /runs/{runId}` every 1.5 s and `GET /runs/{runId}/logs?after=` every 2 s while a run is `queued` or `running`. Server-sent events may replace polling later without changing the schemas.

## Schemas (summary; Zod is normative)

```ts
Project        { id, name, partNumber, revision, description?, material: MaterialKey, units: "mm"|"in",
                 status: "draft"|"running"|"needs_review"|"approved"|"needs_rework",
                 createdAt, updatedAt, lastRunId?, modelUrl?: string /* STL */, stepUrl?: string,
                 modelFormat?: "stl"|"step", thumbnailUrl?, partSpecKey?, isSample }

Drawing        { id, projectId, fileName, url, kind: "pdf"|"image", pageCount, sizeBytes, uploadedAt,
                 registration?: { page, originX, originY, scale /* normalized page units per model unit */ } }

Region         { page: number, x, y, w, h }           // normalized 0..1, origin top-left

ExtractionItem { id, kind: "dimension"|"hole"|"feature"|"tolerance"|"unit"|"note",
                 label, value: string, numericValue?, unit?, quantity?, tolerance?: { plus, minus },
                 confidence: 0..1, region?: Region, featureId?,
                 status: "verified"|"needs_review"|"conflict", critical: boolean, flag?: string,
                 review: { decision: "pending"|"approved"|"edited"|"rejected", by?, at?, editedValue?, note? } }

CountCheck     { feature: string, drawingCount: number|null, extractedCount: number, modeledCount: number|null,
                 evidenceItemId? }

ExtractionResult { id, projectId, model: string /* vision model id */, createdAt, items: ExtractionItem[],
                   countChecks: CountCheck[], isSample }

BuildOperation { id, order, type: "sketch"|"extrude"|"cut"|"hole"|"pattern"|"fillet"|"chamfer"|"reference",
                 name, featureId, parentId?, params: Record<string, string|number|boolean>,
                 status: "built"|"built_derived"|"excluded"|"failed", note?,
                 locator?: { kind: "hole"|"face"|"edge"|"body", position: [x,y,z], axis?: [x,y,z], radius?, depth? } }

BuildPlan      { id, projectId, createdAt, units, operations: BuildOperation[],
                 outline?: { kind: "circle", diameter } | { kind: "rect", width, height }, isSample }

Parameter      { id, name, symbol?, value, extractedValue, unit, tolerance?: { plus, minus },
                 range?: { min, max }, sourceItemId?, featureId?, updatedAt? }

StageUsage     { inputTokens, outputTokens, visionCalls, computeSeconds }
PipelineStage  { key: "analyze"|"extract"|"generate"|"validate", label,
                 status: "pending"|"running"|"done"|"failed"|"skipped", startedAt?, durationMs?,
                 attempts, message?, usage: StageUsage }
PipelineRun    { id, projectId, projectName, status: "queued"|"running"|"succeeded"|"failed"|"cancelled",
                 preset, createdAt, startedAt?, finishedAt?, etaSeconds?, stages: PipelineStage[],
                 simulated: boolean, isSample }

ValidationCheck { id, key: "feature_counts"|"bounding_box"|"dimension_deltas"|"unit_consistency"|
                       "rebuild_errors"|"sketch_defined"|"watertight"|string,
                  label, description, severity: "critical"|"major"|"minor",
                  status: "passed"|"failed"|"warning"|"not_run",
                  expected?, measured?, delta?, tolerance?, detail?,
                  rows?: { label, expected, measured, delta?, tolerance?, ok: boolean }[],
                  evidence: { itemIds: string[], featureIds: string[] },
                  override?: { by, reason, at }, ranAt? }

CostEstimate   { projectId, runId?, stages: { key, label, usage: StageUsage, retries }[],
                 batchSize, partVolumeCm3, stockVolumeCm3, holeCount, featureCount,
                 history: { runId, date, costUsd? }[], isSample }
MonthlyCost    { month: "YYYY-MM", runs, tokensIn, tokensOut, visionCalls, computeSeconds, isSample }

RubricCriterion { key, label, weight, scoredBy: "auto"|"reviewer"|"mixed",
                  levels: { 4: string, 3: string, 2: string, 1: string } }
RubricTemplate  { id, name, criteria: RubricCriterion[], builtIn: boolean, updatedAt }
RubricScore     { projectId, templateId, revision,
                  entries: { criterionKey, level: 0|1|2|3|4|null, comment, evidence: { checkIds, itemIds } }[],
                  gateOverride?: { by, reason, at }, signOff?: { by, at, status, total },
                  history: { revision, total, band, status, at, by? }[] }

Revision       { id, projectId, label, createdAt, author, summary, runId?,
                 metrics: { holes, features, volumeCm3, checksPassed, checksFailed, rubricTotal? },
                 parameters: { name, value, unit }[] }
AuditEvent     { id, projectId, at, actor, action: "approve_item"|"edit_item"|"reject_item"|"edit_parameter"|
                 "override_check"|"clear_override"|"override_gate"|"sign_off"|"export"|"run_started"|"comment",
                 targetId?, summary, reason? }
Comment        { id, projectId, at, author, body, region?: Region, itemId?, resolved }
ExportArtifact { key: "sldprt"|"stl"|"step"|"report_pdf"|"build_plan_json"|"rubric_json"|"extraction_json",
                 label, fileName, available: boolean, url?, generatedInBrowser: boolean, sizeBytes? }
LogEntry       { seq, at, level: "debug"|"info"|"warn"|"error", stage?, message }
Notification   { id, at, kind: "run_finished"|"validation_failed"|"budget_warning"|"review_needed",
                 title, body, projectId?, read }
SystemStatus   { online, gpuUtilization?: 0..1, queueDepth, activeRuns, version?, isSample }
Kpis           { modelsGenerated, validationRate /* 0..1, checks that ran and passed */, avgBuildSeconds,
                 pipelineErrors, trends: { modelsGenerated: number[], validationRate: number[],
                 avgBuildSeconds: number[], pipelineErrors: number[] }, isSample }
```

## Behavior the backend must guarantee

1. **Validation is real.** The seven required checks exist for every built part: `feature_counts` (holes in particular), `bounding_box`, `dimension_deltas`, `unit_consistency`, `rebuild_errors`, `sketch_defined`, `watertight`. A check that could not run returns `not_run` with a `detail` saying why.
2. **Count checks compare three numbers:** what the drawing's callout says (`drawingCount`, `null` if no explicit callout was read), what extraction produced, and what the model contains. The UI treats any disagreement as critical.
3. **Overrides are recorded server-side** with actor, reason and time, and are returned on the check. An override does not change `status`.
4. **Every reviewer action writes an `AuditEvent`.**
5. **Regions and registration.** Each `ExtractionItem.region` is the item's source box on the drawing page. `Drawing.registration` (optional) lets the UI draw the modeled outline on the front view; omit it when unknown.
6. **Model files.** `modelUrl` serves the STL. The pipeline now writes `<Part>.stl` beside every `.sldprt` (`pipeline/solidworks_builder.py::export_stl`), so this is always available after a successful COM build. `stepUrl` is optional.
7. **Uploads.** `POST /runs` accepts PDF, PNG, JPG, DXF, DWG; reject anything else and anything over 50 MB with a `4xx`.
8. **Costs are raw usage, not dollars.** The backend returns tokens, vision calls and compute seconds. The UI prices them with rates from Settings so the assumption stays visible and editable. If the backend has authoritative billed cost, add `billedUsd` per stage; the UI will show it instead and label it "billed".

## Mapping to the current pipeline artifacts (`2D-3D-CAD-Test-Generation/`)

| Contract object | Pipeline source |
|---|---|
| `ExtractionResult.items` | `<Part>_extraction.json` (dimensions, hole callouts, features, confidences); regions from `mti_markup.py` / `pipeline/ocr_locate.py` positions |
| `BuildPlan.operations` | the Feature IR plan (`pipeline/ir`), per-feature SolidWorks results (`sw_features`) |
| `PipelineRun.stages[].usage` | `<output>/usage/usage_ledger.jsonl` (role, tokens, latency) |
| `ValidationCheck` | IR volume/bbox verification per feature, validator report, `bench.score` stage blame |
| `Project.modelUrl` | `<Part>_ir.stl` / `<Part>.stl` (new), `reference.step` for `stepUrl` |
| `MonthlyCost` | `~/.mti-2d-3d/budget_ledger.jsonl` |

The four UI stages group the pipeline's steps: **Analyze Drawing** = image prep + overview read; **Extract Features** = extraction + planning; **Generate CAD Model** = reference build + SolidWorks COM build + STL export; **Validate Geometry** = per-feature verification and scoring.
