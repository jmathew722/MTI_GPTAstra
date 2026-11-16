import type {
  AuditEvent,
  BuildPlan,
  Comment,
  CostEstimate,
  Drawing,
  ExportArtifact,
  ExtractionItem,
  ExtractionResult,
  Kpis,
  LogEntry,
  MonthlyCost,
  Notification,
  Parameter,
  PipelineRun,
  Project,
  Region,
  ReleaseStatus,
  Revision,
  RubricEntry,
  RubricScore,
  RubricTemplate,
  StartRunInput,
  SystemStatus,
  ValidationCheck,
} from "@/lib/schemas";

export interface ItemReviewInput {
  decision: "approved" | "edited" | "rejected" | "pending";
  editedValue?: string;
  note?: string;
  by: string;
}

export interface SignOffInput {
  by: string;
  status: ReleaseStatus;
  total: number;
  band: string;
}

/**
 * The one interface the UI talks to. `mock` and `http` both implement it;
 * NEXT_PUBLIC_API_MODE selects which (see lib/api/index.ts and docs/API_CONTRACT.md).
 */
export interface ApiAdapter {
  readonly mode: "mock" | "http";

  getSystemStatus(): Promise<SystemStatus>;
  getKpis(): Promise<Kpis>;

  listProjects(): Promise<Project[]>;
  getProject(id: string): Promise<Project>;
  cloneProject(id: string, by: string): Promise<Project>;

  getDrawing(projectId: string): Promise<Drawing>;
  /** null = the project has no extraction (for example a drawing that was never processed) */
  getExtraction(projectId: string): Promise<ExtractionResult | null>;
  reviewExtractionItem(projectId: string, itemId: string, input: ItemReviewInput): Promise<ExtractionItem>;
  getBuildPlan(projectId: string): Promise<BuildPlan | null>;

  getParameters(projectId: string): Promise<Parameter[]>;
  updateParameter(projectId: string, paramId: string, value: number, by: string): Promise<Parameter>;

  getValidation(projectId: string): Promise<ValidationCheck[]>;
  overrideCheck(projectId: string, checkId: string, by: string, reason: string): Promise<ValidationCheck>;
  clearOverride(projectId: string, checkId: string, by: string): Promise<ValidationCheck>;

  getCost(projectId: string): Promise<CostEstimate | null>;
  getMonthlyCost(): Promise<MonthlyCost>;

  getRubricScore(projectId: string): Promise<RubricScore>;
  saveRubricScore(projectId: string, patch: { entries?: RubricEntry[]; templateId?: string }): Promise<RubricScore>;
  overrideRubricGate(projectId: string, by: string, reason: string | null): Promise<RubricScore>;
  signOff(projectId: string, input: SignOffInput): Promise<RubricScore>;
  listRubricTemplates(): Promise<RubricTemplate[]>;
  saveRubricTemplate(t: RubricTemplate): Promise<RubricTemplate>;
  deleteRubricTemplate(id: string): Promise<void>;

  listRevisions(projectId: string): Promise<Revision[]>;
  listAudit(projectId: string): Promise<AuditEvent[]>;
  listComments(projectId: string): Promise<Comment[]>;
  addComment(projectId: string, input: { author: string; body: string; region?: Region; itemId?: string }): Promise<Comment>;
  resolveComment(projectId: string, commentId: string, resolved: boolean): Promise<Comment>;
  listExports(projectId: string): Promise<ExportArtifact[]>;
  recordExport(projectId: string, by: string, what: string): Promise<void>;

  listRuns(): Promise<PipelineRun[]>;
  getRun(runId: string): Promise<PipelineRun>;
  startRun(input: StartRunInput, files: File[], by: string): Promise<PipelineRun>;
  cancelRun(runId: string): Promise<PipelineRun>;
  retryRun(runId: string): Promise<PipelineRun>;
  getLogs(runId: string, after?: number): Promise<LogEntry[]>;

  listNotifications(): Promise<Notification[]>;
  markNotificationsRead(): Promise<void>;

  /** mock only: restore the seeded sample data */
  resetSampleData?(): Promise<void>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string = "error",
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
