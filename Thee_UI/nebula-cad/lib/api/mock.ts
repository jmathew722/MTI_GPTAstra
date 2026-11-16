import { ApiError, type ApiAdapter } from "./adapter";
import { sumUsage } from "@/lib/cost";
import { DEFAULT_TEMPLATE } from "@/lib/rubric";
import { SAMPLE_PROJECT_IDS, SPECS, STAGE_LABEL, makeStages, sampleBundle, seedDb, type Db, type ProjectBundle, type SampleKey } from "@/lib/data/seed";
import type { AuditEvent, ExportArtifact, PipelineRun, PipelineStage, Project, StageUsage } from "@/lib/schemas";
import { summarize } from "@/lib/validation";

/**
 * Mock adapter: an in-memory database seeded with SAMPLE DATA and persisted to localStorage,
 * so reviews, overrides and sign-offs survive a reload. Nothing here talks to a server.
 */
const KEY = "nebula-mock-db-v3";
const ZERO: StageUsage = { inputTokens: 0, outputTokens: 0, visionCalls: 0, computeSeconds: 0 };
/** Simulated stage durations for a run started in the UI, in ms. */
const SIM_MS = [2200, 3200, 5200, 2000];

let db: Db | null = null;
/** Object URLs for files uploaded this session (never persisted). */
const sessionFiles = new Map<string, { url: string; name: string; size: number; kind: "pdf" | "image" }>();
/** Simulated runs in flight: runId -> start time + what to produce at the end. */
const sims = new Map<string, { t0: number; sampleKey?: SampleKey; projectId: string; cancelled?: boolean; finalized?: boolean }>();

function load(): Db {
  if (db) return db;
  if (typeof window !== "undefined") {
    try {
      const raw = window.localStorage.getItem(KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Db;
        if (parsed.version === 3) {
          db = parsed;
          // runs that were in flight when the page closed cannot resume: mark them cancelled
          for (const r of db.runs) if (r.status === "running" || r.status === "queued") if (r.simulated) r.status = "cancelled";
          return db;
        }
      }
    } catch {
      /* corrupt storage: fall through to a fresh seed */
    }
  }
  db = seedDb();
  save();
  return db;
}

function save() {
  if (typeof window === "undefined" || !db) return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(db));
  } catch {
    /* quota or private mode: keep working in memory */
  }
}

const delay = (ms = 140) => new Promise<void>((r) => setTimeout(r, ms + Math.random() * 120));
const clone = <T>(v: T): T => structuredClone(v);
const nowIso = () => new Date().toISOString();

function bundle(id: string): ProjectBundle {
  const b = load().bundles[id];
  if (!b) throw new ApiError(`Project "${id}" was not found.`, "not_found", 404);
  return b;
}

function nextId(prefix: string): string {
  const d = load();
  d.seq += 1;
  return `${prefix}-${d.seq}`;
}

function audit(projectId: string, e: Omit<AuditEvent, "id" | "projectId" | "at">) {
  bundle(projectId).audit.unshift({ id: nextId("AUD"), projectId, at: nowIso(), ...e });
}

function touch(projectId: string) {
  bundle(projectId).project.updatedAt = nowIso();
}

/** Advance a simulated run from elapsed wall time; finalize it once the last stage completes. */
function advance(run: PipelineRun): PipelineRun {
  const sim = sims.get(run.id);
  if (!sim || sim.finalized || sim.cancelled) return run;
  const d = load();
  const elapsed = Date.now() - sim.t0;
  let acc = 0;
  let allDone = true;
  run.status = "running";
  run.stages = run.stages.map((st, i): PipelineStage => {
    const start = acc;
    acc += SIM_MS[i];
    if (elapsed >= acc)
      return { ...st, status: "done", durationMs: SIM_MS[i], startedAt: new Date(sim.t0 + start).toISOString(), usage: sim.sampleKey ? st.usage : ZERO };
    allDone = false;
    if (elapsed >= start) return { ...st, status: "running", startedAt: new Date(sim.t0 + start).toISOString() };
    return { ...st, status: "pending" };
  });
  run.etaSeconds = Math.max(0, Math.round((SIM_MS.reduce((a, b) => a + b, 0) - elapsed) / 1000));
  if (allDone) {
    sim.finalized = true;
    run.status = "succeeded";
    run.finishedAt = nowIso();
    run.etaSeconds = undefined;
    const b = d.bundles[sim.projectId];
    if (b && sim.sampleKey) {
      const made = sampleBundle(sim.sampleKey, sim.projectId);
      const keep = b.project;
      d.bundles[sim.projectId] = {
        ...made.bundle,
        project: { ...made.bundle.project, name: keep.name, material: keep.material, createdAt: keep.createdAt, lastRunId: run.id },
        audit: [...b.audit],
      };
      d.logs[run.id] = made.logs;
      const checks = made.bundle.checks;
      const s = summarize(checks);
      d.notifications.unshift({
        id: nextId("NTF"), at: nowIso(), kind: "run_finished", title: `Run finished: ${keep.name}`,
        body: `${run.id} completed (simulated run on a sample drawing).`, projectId: sim.projectId, read: false,
      });
      if (s.failed)
        d.notifications.unshift({
          id: nextId("NTF"), at: nowIso(), kind: "validation_failed", title: `Validation failed: ${keep.name}`,
          body: checks.find((c) => c.status === "failed")?.detail ?? "A validation check failed.", projectId: sim.projectId, read: false,
        });
    }
    save();
  }
  return run;
}

function exportsFor(b: ProjectBundle): ExportArtifact[] {
  const base = `${b.project.partNumber}_${b.project.name}`;
  const built = Boolean(b.buildPlan);
  return [
    { key: "sldprt", label: "SolidWorks part", fileName: `${base}.SLDPRT`, available: false, generatedInBrowser: false, note: "Produced by the SolidWorks backend. Not available in sample-data mode." },
    { key: "stl", label: "STL mesh", fileName: `${base}.stl`, available: Boolean(b.project.modelUrl), url: b.project.modelUrl, generatedInBrowser: false, note: b.project.modelUrl ? "Viewing copy written beside the .sldprt by the pipeline." : "No model has been built." },
    { key: "step", label: "STEP", fileName: `${base}.step`, available: false, generatedInBrowser: false, note: "Produced by the backend. Not available in sample-data mode." },
    { key: "report_pdf", label: "PDF report", fileName: `${base}_report.pdf`, available: built, generatedInBrowser: true, note: "Build plan, validation, cost and rubric. Generated in your browser." },
    { key: "build_plan_json", label: "Build plan (JSON)", fileName: `${base}_build_plan.json`, available: built, generatedInBrowser: true },
    { key: "extraction_json", label: "Extraction (JSON)", fileName: `${base}_extraction.json`, available: Boolean(b.extraction), generatedInBrowser: true },
    { key: "rubric_json", label: "Rubric (JSON)", fileName: `${base}_rubric.json`, available: true, generatedInBrowser: true },
  ];
}

export const mockAdapter: ApiAdapter = {
  mode: "mock",

  async getSystemStatus() {
    await delay(60);
    const d = load();
    const active = d.runs.filter((r) => r.status === "running").length;
    return { online: true, gpuUtilization: active ? 0.98 : 0.12, queueDepth: d.runs.filter((r) => r.status === "queued").length, activeRuns: active, version: "mock", isSample: true };
  },

  async getKpis() {
    await delay();
    const d = load();
    const done = d.runs.filter((r) => r.status === "succeeded");
    const all = Object.values(d.bundles).flatMap((b) => b.checks);
    const s = summarize(all);
    const secs = done.map((r) => r.stages.reduce((a, st) => a + (st.durationMs ?? 0), 0) / 1000);
    return {
      modelsGenerated: done.length,
      validationRate: s.passRate ?? 0,
      avgBuildSeconds: secs.length ? secs.reduce((a, b) => a + b, 0) / secs.length : 0,
      pipelineErrors: d.runs.filter((r) => r.status === "failed").length,
      trends: {
        modelsGenerated: [1, 2, 2, 3, 4, 4, 5, done.length],
        validationRate: [0.78, 0.8, 0.84, 0.82, 0.86, 0.88, 0.87, s.passRate ?? 0],
        avgBuildSeconds: [96, 92, 94, 88, 86, 84, 83, 81],
        pipelineErrors: [2, 2, 1, 2, 1, 1, 1, 1],
      },
      isSample: true,
    };
  },

  async listProjects() {
    await delay();
    return clone(Object.values(load().bundles).map((b) => b.project)).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  },
  async getProject(id) {
    await delay(80);
    return clone(bundle(id).project);
  },
  async cloneProject(id, by) {
    await delay();
    const d = load();
    const src = bundle(id);
    const newId = `${id}-copy-${d.seq + 1}`;
    const copy = clone(src);
    copy.project = { ...copy.project, id: newId, name: `${src.project.name}_copy`, revision: "A", status: "draft", createdAt: nowIso(), updatedAt: nowIso() };
    for (const k of ["drawing", "extraction", "buildPlan", "cost"] as const) {
      const v = copy[k];
      if (v) v.projectId = newId;
    }
    copy.rubric = { ...copy.rubric, projectId: newId, signOff: undefined, gateOverride: undefined, history: [] };
    copy.checks = copy.checks.map((c) => ({ ...c, override: undefined }));
    copy.revisions = copy.revisions.map((r) => ({ ...r, projectId: newId }));
    copy.comments = [];
    copy.audit = [];
    d.bundles[newId] = copy;
    audit(newId, { actor: by, action: "clone", summary: `Cloned from ${src.project.name} (${src.project.partNumber}).` });
    save();
    return clone(copy.project);
  },

  async getDrawing(projectId) {
    await delay(80);
    const b = bundle(projectId);
    const f = sessionFiles.get(projectId);
    if (b.drawing.url.startsWith("session:") && !f)
      throw new ApiError("This drawing was uploaded in an earlier browser session. Sample-data mode keeps uploads in memory only; upload it again.", "gone", 410);
    return clone(f ? { ...b.drawing, url: f.url } : b.drawing);
  },
  async getExtraction(projectId) {
    await delay();
    return clone(bundle(projectId).extraction);
  },
  async reviewExtractionItem(projectId, itemId, input) {
    await delay(90);
    const b = bundle(projectId);
    const it = b.extraction?.items.find((i) => i.id === itemId);
    if (!it) throw new ApiError(`Item ${itemId} was not found.`, "not_found", 404);
    it.review = { decision: input.decision, by: input.decision === "pending" ? undefined : input.by, at: input.decision === "pending" ? undefined : nowIso(), editedValue: input.editedValue, note: input.note };
    if (input.decision !== "pending") {
      const verb = input.decision === "approved" ? "Approved" : input.decision === "edited" ? "Edited" : "Rejected";
      audit(projectId, {
        actor: input.by,
        action: input.decision === "approved" ? "approve_item" : input.decision === "edited" ? "edit_item" : "reject_item",
        targetId: itemId,
        summary: `${verb} ${itemId} "${it.label}"${input.editedValue ? `: ${it.value} → ${input.editedValue}` : ""}.`,
        reason: input.note,
      });
    }
    touch(projectId);
    save();
    return clone(it);
  },
  async getBuildPlan(projectId) {
    await delay();
    return clone(bundle(projectId).buildPlan);
  },

  async getParameters(projectId) {
    await delay();
    return clone(bundle(projectId).parameters);
  },
  async updateParameter(projectId, paramId, value, by) {
    await delay(80);
    const p = bundle(projectId).parameters.find((q) => q.id === paramId);
    if (!p) throw new ApiError(`Parameter ${paramId} was not found.`, "not_found", 404);
    const before = p.value;
    p.value = value;
    p.updatedAt = nowIso();
    audit(projectId, { actor: by, action: "edit_parameter", targetId: paramId, summary: `${p.name}: ${before} → ${value} ${p.unit}. The model is not rebuilt until the next run.` });
    touch(projectId);
    save();
    return clone(p);
  },

  async getValidation(projectId) {
    await delay();
    return clone(bundle(projectId).checks);
  },
  async overrideCheck(projectId, checkId, by, reason) {
    await delay(90);
    const c = bundle(projectId).checks.find((x) => x.id === checkId);
    if (!c) throw new ApiError(`Check ${checkId} was not found.`, "not_found", 404);
    if (!reason.trim()) throw new ApiError("An override needs a reason.", "invalid", 400);
    c.override = { by, reason: reason.trim(), at: nowIso() };
    audit(projectId, { actor: by, action: "override_check", targetId: checkId, summary: `Override recorded on ${checkId} "${c.label}" (status stays ${c.status}).`, reason: reason.trim() });
    touch(projectId);
    save();
    return clone(c);
  },
  async clearOverride(projectId, checkId, by) {
    await delay(90);
    const c = bundle(projectId).checks.find((x) => x.id === checkId);
    if (!c) throw new ApiError(`Check ${checkId} was not found.`, "not_found", 404);
    c.override = undefined;
    audit(projectId, { actor: by, action: "clear_override", targetId: checkId, summary: `Override removed from ${checkId} "${c.label}".` });
    save();
    return clone(c);
  },

  async getCost(projectId) {
    await delay();
    return clone(bundle(projectId).cost);
  },
  async getMonthlyCost() {
    await delay();
    const d = load();
    const month = new Date().toISOString().slice(0, 7);
    const runs = d.runs; // every seeded run falls in the sample month
    return { month, runs: runs.length, usage: sumUsage(runs.flatMap((r) => r.stages.map((s) => s.usage))), isSample: true };
  },

  async getRubricScore(projectId) {
    await delay();
    return clone(bundle(projectId).rubric);
  },
  async saveRubricScore(projectId, patch) {
    await delay(70);
    const b = bundle(projectId);
    if (patch.entries) b.rubric.entries = clone(patch.entries);
    if (patch.templateId) b.rubric.templateId = patch.templateId;
    save();
    return clone(b.rubric);
  },
  async overrideRubricGate(projectId, by, reason) {
    await delay(90);
    const b = bundle(projectId);
    if (reason === null) {
      b.rubric.gateOverride = undefined;
      audit(projectId, { actor: by, action: "clear_override", summary: "Rubric hard-fail override removed." });
    } else {
      if (!reason.trim()) throw new ApiError("An override needs a reason.", "invalid", 400);
      b.rubric.gateOverride = { by, reason: reason.trim(), at: nowIso() };
      audit(projectId, { actor: by, action: "override_gate", summary: "Rubric hard-fail cap overridden.", reason: reason.trim() });
    }
    save();
    return clone(b.rubric);
  },
  async signOff(projectId, input) {
    await delay(120);
    const b = bundle(projectId);
    const at = nowIso();
    b.rubric.signOff = { ...input, at };
    b.rubric.history.push({ revision: b.project.revision, total: input.total, band: input.band, status: input.status, at, by: input.by });
    b.project.status = input.status === "needs_rework" ? "needs_rework" : "approved";
    audit(projectId, { actor: input.by, action: "sign_off", summary: `Signed off: ${input.status.replaceAll("_", " ")}, ${input.total} (${input.band}).` });
    touch(projectId);
    save();
    return clone(b.rubric);
  },
  async listRubricTemplates() {
    await delay();
    return clone(load().templates);
  },
  async saveRubricTemplate(t) {
    await delay(80);
    const d = load();
    const next = { ...clone(t), updatedAt: nowIso() };
    const i = d.templates.findIndex((x) => x.id === t.id);
    if (i >= 0) {
      if (d.templates[i].builtIn) throw new ApiError("The built-in template cannot be changed. Duplicate it first.", "invalid", 400);
      d.templates[i] = next;
    } else d.templates.push(next);
    save();
    return clone(next);
  },
  async deleteRubricTemplate(id) {
    await delay(80);
    const d = load();
    if (id === DEFAULT_TEMPLATE.id) throw new ApiError("The built-in template cannot be deleted.", "invalid", 400);
    d.templates = d.templates.filter((t) => t.id !== id);
    for (const b of Object.values(d.bundles)) if (b.rubric.templateId === id) b.rubric.templateId = DEFAULT_TEMPLATE.id;
    save();
  },

  async listRevisions(projectId) {
    await delay();
    return clone(bundle(projectId).revisions);
  },
  async listAudit(projectId) {
    await delay(80);
    return clone(bundle(projectId).audit);
  },
  async listComments(projectId) {
    await delay(80);
    return clone(bundle(projectId).comments);
  },
  async addComment(projectId, input) {
    await delay(80);
    const c = { id: nextId("CMT"), projectId, at: nowIso(), author: input.author, body: input.body, region: input.region, itemId: input.itemId, resolved: false };
    bundle(projectId).comments.unshift(c);
    audit(projectId, { actor: input.author, action: "comment", targetId: input.itemId, summary: `Comment added${input.itemId ? ` on ${input.itemId}` : ""}.` });
    save();
    return clone(c);
  },
  async resolveComment(projectId, commentId, resolved) {
    await delay(60);
    const c = bundle(projectId).comments.find((x) => x.id === commentId);
    if (!c) throw new ApiError("Comment not found.", "not_found", 404);
    c.resolved = resolved;
    save();
    return clone(c);
  },
  async listExports(projectId) {
    await delay(80);
    return exportsFor(bundle(projectId));
  },
  async recordExport(projectId, by, what) {
    audit(projectId, { actor: by, action: "export", summary: `Exported ${what}.` });
    save();
  },

  async listRuns() {
    await delay();
    const d = load();
    for (const r of d.runs) advance(r);
    return clone(d.runs).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  },
  async getRun(runId) {
    await delay(60);
    const r = load().runs.find((x) => x.id === runId);
    if (!r) throw new ApiError(`Run ${runId} was not found.`, "not_found", 404);
    return clone(advance(r));
  },
  async startRun(input, files, by) {
    await delay(200);
    const d = load();
    const n = d.runs.length + 1;
    const runId = `RUN-${String(n + 12).padStart(4, "0")}`;
    const sampleKey = input.sampleKey as SampleKey | undefined;
    const projectId = `p-${Date.now().toString(36)}`;
    const at = nowIso();
    const spec = sampleKey ? SPECS[sampleKey] : undefined;
    const file = files[0];
    const project: Project = {
      id: projectId, name: input.name || spec?.name || file?.name.replace(/\.[^.]+$/, "") || "Untitled_Part",
      partNumber: spec?.partNumber ?? "UNASSIGNED", revision: "A", material: input.material, units: input.units,
      status: "running", createdAt: at, updatedAt: at, lastRunId: runId, isSample: true,
      description: sampleKey ? "Created from a bundled sample drawing." : "Created from an uploaded drawing (stored for this session only).",
    };
    if (file) {
      const kind = /\.pdf$/i.test(file.name) ? "pdf" : "image";
      sessionFiles.set(projectId, { url: URL.createObjectURL(file), name: file.name, size: file.size, kind });
    }
    const empty: ProjectBundle = {
      project,
      drawing: {
        id: `DRW-${projectId}`, projectId, fileName: file?.name ?? `${sampleKey}.pdf`, url: file ? `session:${projectId}` : `/samples/${sampleKey}.pdf`,
        kind: file && !/\.pdf$/i.test(file.name) ? "image" : "pdf", pageCount: 1, sizeBytes: file?.size ?? 0, uploadedAt: at,
      },
      extraction: null, buildPlan: null, parameters: [], checks: [], cost: null,
      rubric: { projectId, templateId: DEFAULT_TEMPLATE.id, revision: "A", entries: DEFAULT_TEMPLATE.criteria.map((c) => ({ criterionKey: c.key, level: null, comment: "" })), history: [] },
      revisions: [], audit: [], comments: [],
    };
    d.bundles[projectId] = empty;
    let run: PipelineRun;
    if (sampleKey) {
      run = {
        id: runId, projectId, projectName: project.name, status: "running", preset: input.preset, createdAt: at, startedAt: at,
        stages: makeStages(Date.now(), 0, 1).map((s) => ({ ...s, status: "pending", durationMs: undefined, startedAt: undefined })),
        simulated: true, isSample: true,
      };
      sims.set(runId, { t0: Date.now(), sampleKey, projectId });
    } else {
      // No backend: nothing can process a user's drawing, and nothing is fabricated for it.
      run = {
        id: runId, projectId, projectName: project.name, status: "cancelled", preset: input.preset, createdAt: at, startedAt: at, finishedAt: at,
        stages: (["analyze", "extract", "generate", "validate"] as const).map((key) => ({
          key, label: STAGE_LABEL[key], status: "skipped", attempts: 1,
          message: "Not processed: sample-data mode has no pipeline backend.", usage: ZERO,
        })),
        simulated: true, isSample: true,
      };
      project.status = "draft";
    }
    d.runs.unshift(run);
    audit(projectId, { actor: by, action: "run_started", targetId: runId, summary: sampleKey ? `Simulated run ${runId} started on a sample drawing.` : `Drawing stored. Run ${runId} was not processed (no backend).` });
    save();
    return clone(run);
  },
  async cancelRun(runId) {
    await delay(80);
    const r = load().runs.find((x) => x.id === runId);
    if (!r) throw new ApiError(`Run ${runId} was not found.`, "not_found", 404);
    const sim = sims.get(runId);
    if (sim) sim.cancelled = true;
    if (r.status === "running" || r.status === "queued") {
      r.status = "cancelled";
      r.finishedAt = nowIso();
      r.etaSeconds = undefined;
      r.stages = r.stages.map((s) => (s.status === "running" || s.status === "pending" ? { ...s, status: "skipped", message: "Cancelled by the user." } : s));
      const b = load().bundles[r.projectId];
      if (b && b.project.status === "running") b.project.status = "draft";
    }
    save();
    return clone(r);
  },
  async retryRun(runId) {
    await delay(120);
    const d = load();
    const r = d.runs.find((x) => x.id === runId);
    if (!r) throw new ApiError(`Run ${runId} was not found.`, "not_found", 404);
    const b = d.bundles[r.projectId];
    const sampleKey = (b?.project.partSpecKey ?? Object.entries(SAMPLE_PROJECT_IDS).find(([, v]) => v === r.projectId)?.[0]) as SampleKey | undefined;
    if (!sampleKey) throw new ApiError("This run has no source the mock can re-process. Connect the pipeline backend to retry it.", "unsupported", 400);
    const id = `RUN-${String(d.runs.length + 13).padStart(4, "0")}`;
    const at = nowIso();
    const run: PipelineRun = {
      id, projectId: r.projectId, projectName: r.projectName, status: "running", preset: r.preset, createdAt: at, startedAt: at,
      stages: makeStages(Date.now(), 0, 1).map((s) => ({ ...s, status: "pending", durationMs: undefined, startedAt: undefined })),
      simulated: true, isSample: true,
    };
    sims.set(id, { t0: Date.now(), sampleKey, projectId: r.projectId });
    d.runs.unshift(run);
    save();
    return clone(run);
  },
  async getLogs(runId, after = 0) {
    await delay(70);
    const d = load();
    const run = d.runs.find((r) => r.id === runId);
    const logs = d.logs[runId];
    if (logs) return clone(logs.filter((l) => l.seq > after));
    if (!run) return [];
    // A simulated run in flight streams a short honest log from its stage states.
    const out = run.stages
      .filter((s) => s.status !== "pending")
      .flatMap((s, i) => {
        const base = { stage: s.key, at: s.startedAt ?? run.createdAt };
        const rows = [{ ...base, seq: i * 2 + 1, level: "info" as const, message: s.status === "skipped" ? `${s.label}: ${s.message ?? "skipped"}` : `${s.label} started (simulated)` }];
        if (s.status === "done") rows.push({ ...base, seq: i * 2 + 2, level: "info" as const, message: `${s.label} done (simulated)` });
        return rows;
      });
    return out.filter((l) => l.seq > after);
  },

  async listNotifications() {
    await delay(60);
    return clone(load().notifications);
  },
  async markNotificationsRead() {
    for (const n of load().notifications) n.read = true;
    save();
  },

  async resetSampleData() {
    sims.clear();
    db = seedDb();
    save();
  },
};
