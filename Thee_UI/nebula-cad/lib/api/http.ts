import { z } from "zod";
import { ApiError, type ApiAdapter } from "./adapter";
import * as S from "@/lib/schemas";

/**
 * HTTP adapter for the real SolidWorks automation service (docs/API_CONTRACT.md).
 * Every response is parsed with its Zod schema: a malformed payload becomes a visible
 * error, never a silently wrong screen.
 */
const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

async function req<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  if (!BASE) throw new ApiError("NEXT_PUBLIC_API_BASE_URL is not set.", "config");
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(
      typeof navigator !== "undefined" && !navigator.onLine ? "You are offline." : `Could not reach the pipeline service at ${BASE}.`,
      "network",
    );
  }
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    let code = "http";
    try {
      const body = (await res.json()) as { error?: { code?: string; message?: string } };
      if (body.error?.message) message = body.error.message;
      if (body.error?.code) code = body.error.code;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, code, res.status);
  }
  if (res.status === 204) return undefined as T;
  const parsed = schema.safeParse(await res.json());
  if (!parsed.success) {
    const first = parsed.error.issues[0];
    throw new ApiError(`The service returned an unexpected payload for ${path}: ${first?.path.join(".")} ${first?.message}`, "schema");
  }
  return parsed.data;
}

const json = (body: unknown, method = "POST"): RequestInit => ({ method, body: JSON.stringify(body) });
const none = z.undefined() as unknown as z.ZodType<void>;
const p = (id: string) => `/projects/${encodeURIComponent(id)}`;

export const httpAdapter: ApiAdapter = {
  mode: "http",
  getSystemStatus: () => req("/system/status", S.SystemStatus),
  getKpis: () => req("/kpis", S.Kpis),
  listProjects: () => req("/projects", z.array(S.Project)),
  getProject: (id) => req(p(id), S.Project),
  cloneProject: (id, by) => req(`${p(id)}/clone`, S.Project, json({ by })),
  getDrawing: (id) => req(`${p(id)}/drawing`, S.Drawing),
  getExtraction: (id) => req(`${p(id)}/extraction`, S.ExtractionResult.nullable()),
  reviewExtractionItem: (id, itemId, input) => req(`${p(id)}/extraction/items/${encodeURIComponent(itemId)}`, S.ExtractionItem, json(input, "PATCH")),
  getBuildPlan: (id) => req(`${p(id)}/build-plan`, S.BuildPlan.nullable()),
  getParameters: (id) => req(`${p(id)}/parameters`, z.array(S.Parameter)),
  updateParameter: (id, paramId, value, by) => req(`${p(id)}/parameters/${encodeURIComponent(paramId)}`, S.Parameter, json({ value, by }, "PATCH")),
  getValidation: (id) => req(`${p(id)}/validation`, z.array(S.ValidationCheck)),
  overrideCheck: (id, checkId, by, reason) => req(`${p(id)}/validation/${encodeURIComponent(checkId)}/override`, S.ValidationCheck, json({ by, reason })),
  clearOverride: (id, checkId, by) => req(`${p(id)}/validation/${encodeURIComponent(checkId)}/override`, S.ValidationCheck, json({ by }, "DELETE")),
  getCost: (id) => req(`${p(id)}/cost`, S.CostEstimate.nullable()),
  getMonthlyCost: () => req("/cost/monthly", S.MonthlyCost),
  getRubricScore: (id) => req(`${p(id)}/rubric`, S.RubricScore),
  saveRubricScore: (id, patch) => req(`${p(id)}/rubric`, S.RubricScore, json(patch, "PUT")),
  overrideRubricGate: (id, by, reason) => req(`${p(id)}/rubric/gate-override`, S.RubricScore, json({ by, reason }, reason === null ? "DELETE" : "POST")),
  signOff: (id, input) => req(`${p(id)}/rubric/sign-off`, S.RubricScore, json(input)),
  listRubricTemplates: () => req("/rubric/templates", z.array(S.RubricTemplate)),
  saveRubricTemplate: (t) => req(`/rubric/templates/${encodeURIComponent(t.id)}`, S.RubricTemplate, json(t, "PUT")),
  deleteRubricTemplate: (id) => req(`/rubric/templates/${encodeURIComponent(id)}`, none, { method: "DELETE" }),
  listRevisions: (id) => req(`${p(id)}/revisions`, z.array(S.Revision)),
  listAudit: (id) => req(`${p(id)}/audit`, z.array(S.AuditEvent)),
  listComments: (id) => req(`${p(id)}/comments`, z.array(S.Comment)),
  addComment: (id, input) => req(`${p(id)}/comments`, S.Comment, json(input)),
  resolveComment: (id, commentId, resolved) => req(`${p(id)}/comments/${encodeURIComponent(commentId)}`, S.Comment, json({ resolved }, "PATCH")),
  listExports: (id) => req(`${p(id)}/exports`, z.array(S.ExportArtifact)),
  recordExport: (id, by, what) => req(`${p(id)}/exports`, none, json({ by, what })),
  listRuns: () => req("/runs", z.array(S.PipelineRun)),
  getRun: (runId) => req(`/runs/${encodeURIComponent(runId)}`, S.PipelineRun),
  startRun: (input, files, by) => {
    const form = new FormData();
    form.set("options", JSON.stringify({ ...input, by }));
    for (const f of files) form.append("files", f, f.name);
    return req("/runs", S.PipelineRun, { method: "POST", body: form });
  },
  cancelRun: (runId) => req(`/runs/${encodeURIComponent(runId)}/cancel`, S.PipelineRun, { method: "POST" }),
  retryRun: (runId) => req(`/runs/${encodeURIComponent(runId)}/retry`, S.PipelineRun, { method: "POST" }),
  getLogs: (runId, after = 0) => req(`/runs/${encodeURIComponent(runId)}/logs?after=${after}`, z.array(S.LogEntry)),
  listNotifications: () => req("/notifications", z.array(S.Notification)),
  markNotificationsRead: () => req("/notifications/read", none, { method: "POST" }),
};
