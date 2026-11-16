import { z } from "zod";

/** Normative payload definitions. docs/API_CONTRACT.md mirrors this file. */

export const MaterialKey = z.enum(["steel", "stainless", "aluminum", "titanium"]);
export type MaterialKey = z.infer<typeof MaterialKey>;
export const Units = z.enum(["mm", "in"]);
export type Units = z.infer<typeof Units>;

export const Region = z.object({
  page: z.number().int().min(1),
  x: z.number(),
  y: z.number(),
  w: z.number(),
  h: z.number(),
});
export type Region = z.infer<typeof Region>;

export const ProjectStatus = z.enum(["draft", "running", "needs_review", "approved", "needs_rework"]);
export type ProjectStatus = z.infer<typeof ProjectStatus>;

export const Project = z.object({
  id: z.string(),
  name: z.string(),
  partNumber: z.string(),
  revision: z.string(),
  description: z.string().optional(),
  material: MaterialKey,
  units: Units,
  status: ProjectStatus,
  createdAt: z.string(),
  updatedAt: z.string(),
  lastRunId: z.string().optional(),
  modelUrl: z.string().optional(),
  stepUrl: z.string().optional(),
  thumbnailUrl: z.string().optional(),
  partSpecKey: z.string().optional(),
  isSample: z.boolean().default(false),
});
export type Project = z.infer<typeof Project>;

export const Drawing = z.object({
  id: z.string(),
  projectId: z.string(),
  fileName: z.string(),
  url: z.string(),
  kind: z.enum(["pdf", "image"]),
  pageCount: z.number().int(),
  sizeBytes: z.number(),
  uploadedAt: z.string(),
  /** Maps model units onto the front view: normalized page position of the model origin and scale. */
  registration: z
    .object({ page: z.number().int(), originX: z.number(), originY: z.number(), scale: z.number(), aspect: z.number() })
    .optional(),
});
export type Drawing = z.infer<typeof Drawing>;

export const ItemKind = z.enum(["dimension", "hole", "feature", "tolerance", "unit", "note"]);
export type ItemKind = z.infer<typeof ItemKind>;
export const ItemStatus = z.enum(["verified", "needs_review", "conflict"]);
export type ItemStatus = z.infer<typeof ItemStatus>;
export const ReviewDecision = z.enum(["pending", "approved", "edited", "rejected"]);
export type ReviewDecision = z.infer<typeof ReviewDecision>;

export const Tolerance = z.object({ plus: z.number(), minus: z.number() });
export type Tolerance = z.infer<typeof Tolerance>;

export const ExtractionItem = z.object({
  id: z.string(),
  kind: ItemKind,
  label: z.string(),
  value: z.string(),
  numericValue: z.number().optional(),
  unit: z.string().optional(),
  quantity: z.number().optional(),
  tolerance: Tolerance.optional(),
  confidence: z.number().min(0).max(1),
  region: Region.optional(),
  featureId: z.string().optional(),
  status: ItemStatus,
  critical: z.boolean().default(false),
  flag: z.string().optional(),
  review: z.object({
    decision: ReviewDecision,
    by: z.string().optional(),
    at: z.string().optional(),
    editedValue: z.string().optional(),
    note: z.string().optional(),
  }),
});
export type ExtractionItem = z.infer<typeof ExtractionItem>;

export const CountCheck = z.object({
  feature: z.string(),
  drawingCount: z.number().nullable(),
  extractedCount: z.number(),
  modeledCount: z.number().nullable(),
  evidenceItemId: z.string().optional(),
  /** Instance positions implied by the drawing geometry, model units: [x, y, radius]. Lets the viewer show what is missing. */
  expectedPositions: z.array(z.tuple([z.number(), z.number(), z.number()])).optional(),
});
export type CountCheck = z.infer<typeof CountCheck>;

export const ExtractionResult = z.object({
  id: z.string(),
  projectId: z.string(),
  model: z.string(),
  createdAt: z.string(),
  items: z.array(ExtractionItem),
  countChecks: z.array(CountCheck),
  isSample: z.boolean().default(false),
});
export type ExtractionResult = z.infer<typeof ExtractionResult>;

export const Vec3 = z.tuple([z.number(), z.number(), z.number()]);
export const Locator = z.object({
  kind: z.enum(["hole", "face", "edge", "body"]),
  position: Vec3,
  axis: Vec3.optional(),
  radius: z.number().optional(),
  depth: z.number().optional(),
});
export type Locator = z.infer<typeof Locator>;

export const OperationType = z.enum(["sketch", "extrude", "cut", "hole", "pattern", "fillet", "chamfer", "reference"]);
export type OperationType = z.infer<typeof OperationType>;
export const OperationStatus = z.enum(["built", "built_derived", "excluded", "failed"]);
export type OperationStatus = z.infer<typeof OperationStatus>;

export const BuildOperation = z.object({
  id: z.string(),
  order: z.number().int(),
  type: OperationType,
  name: z.string(),
  featureId: z.string(),
  parentId: z.string().optional(),
  params: z.record(z.string(), z.union([z.string(), z.number(), z.boolean()])),
  status: OperationStatus,
  note: z.string().optional(),
  locators: z.array(Locator).optional(),
});
export type BuildOperation = z.infer<typeof BuildOperation>;

export const Outline = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("circle"), diameter: z.number() }),
  z.object({ kind: z.literal("rect"), width: z.number(), height: z.number() }),
]);
export type Outline = z.infer<typeof Outline>;

export const BuildPlan = z.object({
  id: z.string(),
  projectId: z.string(),
  createdAt: z.string(),
  units: Units,
  operations: z.array(BuildOperation),
  outline: Outline.optional(),
  thickness: z.number().optional(),
  isSample: z.boolean().default(false),
});
export type BuildPlan = z.infer<typeof BuildPlan>;

export const Parameter = z.object({
  id: z.string(),
  name: z.string(),
  symbol: z.string().optional(),
  value: z.number(),
  extractedValue: z.number(),
  unit: z.string(),
  tolerance: Tolerance.optional(),
  range: z.object({ min: z.number(), max: z.number() }).optional(),
  sourceItemId: z.string().optional(),
  featureId: z.string().optional(),
  updatedAt: z.string().optional(),
});
export type Parameter = z.infer<typeof Parameter>;

export const StageUsage = z.object({
  inputTokens: z.number(),
  outputTokens: z.number(),
  visionCalls: z.number(),
  computeSeconds: z.number(),
});
export type StageUsage = z.infer<typeof StageUsage>;

export const StageKey = z.enum(["analyze", "extract", "generate", "validate"]);
export type StageKey = z.infer<typeof StageKey>;
export const StageStatus = z.enum(["pending", "running", "done", "failed", "skipped"]);
export type StageStatus = z.infer<typeof StageStatus>;

export const PipelineStage = z.object({
  key: StageKey,
  label: z.string(),
  status: StageStatus,
  startedAt: z.string().optional(),
  durationMs: z.number().optional(),
  attempts: z.number().int().default(1),
  message: z.string().optional(),
  usage: StageUsage,
});
export type PipelineStage = z.infer<typeof PipelineStage>;

export const RunStatus = z.enum(["queued", "running", "succeeded", "failed", "cancelled"]);
export type RunStatus = z.infer<typeof RunStatus>;

export const PipelineRun = z.object({
  id: z.string(),
  projectId: z.string(),
  projectName: z.string(),
  status: RunStatus,
  preset: z.string(),
  createdAt: z.string(),
  startedAt: z.string().optional(),
  finishedAt: z.string().optional(),
  etaSeconds: z.number().optional(),
  stages: z.array(PipelineStage),
  simulated: z.boolean().default(false),
  isSample: z.boolean().default(false),
});
export type PipelineRun = z.infer<typeof PipelineRun>;

export const CheckStatus = z.enum(["passed", "failed", "warning", "not_run"]);
export type CheckStatus = z.infer<typeof CheckStatus>;
export const CheckSeverity = z.enum(["critical", "major", "minor"]);
export type CheckSeverity = z.infer<typeof CheckSeverity>;

export const Override = z.object({ by: z.string(), reason: z.string(), at: z.string() });
export type Override = z.infer<typeof Override>;

export const ValidationCheck = z.object({
  id: z.string(),
  key: z.string(),
  label: z.string(),
  description: z.string(),
  severity: CheckSeverity,
  status: CheckStatus,
  expected: z.string().optional(),
  measured: z.string().optional(),
  detail: z.string().optional(),
  rows: z
    .array(
      z.object({
        label: z.string(),
        expected: z.string(),
        measured: z.string(),
        delta: z.string().optional(),
        tolerance: z.string().optional(),
        ok: z.boolean(),
      }),
    )
    .optional(),
  evidence: z.object({ itemIds: z.array(z.string()), featureIds: z.array(z.string()) }),
  override: Override.optional(),
  ranAt: z.string().optional(),
});
export type ValidationCheck = z.infer<typeof ValidationCheck>;

export const CostEstimate = z.object({
  projectId: z.string(),
  runId: z.string().optional(),
  stages: z.array(z.object({ key: StageKey, label: z.string(), usage: StageUsage, retries: z.number() })),
  batchSize: z.number(),
  partVolumeCm3: z.number(),
  stockVolumeCm3: z.number(),
  holeCount: z.number(),
  featureCount: z.number(),
  history: z.array(z.object({ runId: z.string(), date: z.string(), usage: StageUsage })),
  isSample: z.boolean().default(false),
});
export type CostEstimate = z.infer<typeof CostEstimate>;

export const MonthlyCost = z.object({
  month: z.string(),
  runs: z.number(),
  usage: StageUsage,
  isSample: z.boolean().default(false),
});
export type MonthlyCost = z.infer<typeof MonthlyCost>;

export const RubricCriterion = z.object({
  key: z.string(),
  label: z.string(),
  weight: z.number(),
  scoredBy: z.enum(["auto", "reviewer", "mixed"]),
  levels: z.object({ 4: z.string(), 3: z.string(), 2: z.string(), 1: z.string() }),
});
export type RubricCriterion = z.infer<typeof RubricCriterion>;

export const RubricTemplate = z.object({
  id: z.string(),
  name: z.string(),
  criteria: z.array(RubricCriterion),
  builtIn: z.boolean().default(false),
  updatedAt: z.string(),
});
export type RubricTemplate = z.infer<typeof RubricTemplate>;

export const ReleaseStatus = z.enum(["approved", "approved_with_notes", "needs_rework"]);
export type ReleaseStatus = z.infer<typeof ReleaseStatus>;

export const RubricEntry = z.object({
  criterionKey: z.string(),
  /** Reviewer-set level. null = not scored by a reviewer (auto criteria are computed). */
  level: z.number().int().min(0).max(4).nullable(),
  comment: z.string().default(""),
});
export type RubricEntry = z.infer<typeof RubricEntry>;

export const RubricScore = z.object({
  projectId: z.string(),
  templateId: z.string(),
  revision: z.string(),
  entries: z.array(RubricEntry),
  gateOverride: Override.optional(),
  signOff: z
    .object({ by: z.string(), at: z.string(), status: ReleaseStatus, total: z.number(), band: z.string() })
    .optional(),
  history: z.array(
    z.object({
      revision: z.string(),
      total: z.number(),
      band: z.string(),
      status: ReleaseStatus,
      at: z.string(),
      by: z.string().optional(),
    }),
  ),
});
export type RubricScore = z.infer<typeof RubricScore>;

export const Revision = z.object({
  id: z.string(),
  projectId: z.string(),
  label: z.string(),
  createdAt: z.string(),
  author: z.string(),
  summary: z.string(),
  runId: z.string().optional(),
  metrics: z.object({
    holes: z.number(),
    features: z.number(),
    volumeCm3: z.number(),
    checksPassed: z.number(),
    checksFailed: z.number(),
    rubricTotal: z.number().optional(),
  }),
  parameters: z.array(z.object({ name: z.string(), value: z.number(), unit: z.string() })),
});
export type Revision = z.infer<typeof Revision>;

export const AuditAction = z.enum([
  "approve_item",
  "edit_item",
  "reject_item",
  "edit_parameter",
  "override_check",
  "clear_override",
  "override_gate",
  "sign_off",
  "export",
  "run_started",
  "comment",
  "clone",
]);
export type AuditAction = z.infer<typeof AuditAction>;

export const AuditEvent = z.object({
  id: z.string(),
  projectId: z.string(),
  at: z.string(),
  actor: z.string(),
  action: AuditAction,
  targetId: z.string().optional(),
  summary: z.string(),
  reason: z.string().optional(),
});
export type AuditEvent = z.infer<typeof AuditEvent>;

export const Comment = z.object({
  id: z.string(),
  projectId: z.string(),
  at: z.string(),
  author: z.string(),
  body: z.string(),
  region: Region.optional(),
  itemId: z.string().optional(),
  resolved: z.boolean().default(false),
});
export type Comment = z.infer<typeof Comment>;

export const ExportKey = z.enum(["sldprt", "stl", "step", "report_pdf", "build_plan_json", "rubric_json", "extraction_json"]);
export type ExportKey = z.infer<typeof ExportKey>;

export const ExportArtifact = z.object({
  key: ExportKey,
  label: z.string(),
  fileName: z.string(),
  available: z.boolean(),
  url: z.string().optional(),
  generatedInBrowser: z.boolean().default(false),
  note: z.string().optional(),
});
export type ExportArtifact = z.infer<typeof ExportArtifact>;

export const LogLevel = z.enum(["debug", "info", "warn", "error"]);
export type LogLevel = z.infer<typeof LogLevel>;
export const LogEntry = z.object({
  seq: z.number().int(),
  at: z.string(),
  level: LogLevel,
  stage: z.string().optional(),
  message: z.string(),
});
export type LogEntry = z.infer<typeof LogEntry>;

export const Notification = z.object({
  id: z.string(),
  at: z.string(),
  kind: z.enum(["run_finished", "validation_failed", "budget_warning", "review_needed"]),
  title: z.string(),
  body: z.string(),
  projectId: z.string().optional(),
  read: z.boolean().default(false),
});
export type Notification = z.infer<typeof Notification>;

export const SystemStatus = z.object({
  online: z.boolean(),
  gpuUtilization: z.number().optional(),
  queueDepth: z.number(),
  activeRuns: z.number(),
  version: z.string().optional(),
  isSample: z.boolean().default(false),
});
export type SystemStatus = z.infer<typeof SystemStatus>;

export const Kpis = z.object({
  modelsGenerated: z.number(),
  validationRate: z.number(),
  avgBuildSeconds: z.number(),
  pipelineErrors: z.number(),
  trends: z.object({
    modelsGenerated: z.array(z.number()),
    validationRate: z.array(z.number()),
    avgBuildSeconds: z.array(z.number()),
    pipelineErrors: z.array(z.number()),
  }),
  isSample: z.boolean().default(false),
});
export type Kpis = z.infer<typeof Kpis>;

export const StartRunInput = z.object({
  name: z.string(),
  material: MaterialKey,
  units: Units,
  preset: z.string(),
  sampleKey: z.string().optional(),
});
export type StartRunInput = z.infer<typeof StartRunInput>;
