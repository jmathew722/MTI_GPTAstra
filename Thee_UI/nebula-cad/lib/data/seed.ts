import specsJson from "./part-specs.json";
import flangeMeta from "./generated/flange.json";
import plateMeta from "./generated/plate.json";
import ringMeta from "./generated/ring.json";
import { DEFAULT_TEMPLATE } from "@/lib/rubric";
import type {
  AuditEvent,
  BuildOperation,
  BuildPlan,
  Comment,
  CostEstimate,
  Drawing,
  ExtractionItem,
  ExtractionResult,
  LogEntry,
  MaterialKey,
  Notification,
  Parameter,
  PipelineRun,
  PipelineStage,
  Project,
  Region,
  Revision,
  RubricScore,
  RubricTemplate,
  StageUsage,
  ValidationCheck,
} from "@/lib/schemas";

/**
 * SAMPLE DATA. Everything in this file is synthetic and is labeled as such in the UI
 * (isSample: true -> SAMPLE DATA badge). No customer drawing or model is included.
 */

interface HoleSpec {
  pattern: string;
  count: number;
  diameter: number;
  bc?: number;
  px?: number;
  py?: number;
}
export interface PartSpec {
  partNumber: string;
  name: string;
  title: string;
  revision: string;
  materialNote: string;
  outline: { kind: string; diameter?: number; width?: number; height?: number };
  thickness: number;
  bore: number;
  boreNote: string;
  drawingHoles: HoleSpec;
  modelHoles: HoleSpec;
  scale: number;
}
export type SampleKey = "flange" | "plate" | "ring";
export const SPECS = specsJson as Record<SampleKey, PartSpec>;
const META = { flange: flangeMeta, plate: plateMeta, ring: ringMeta } as Record<
  SampleKey,
  {
    regions: Record<string, Region>;
    registration: { page: number; originX: number; originY: number; scale: number; aspect: number };
    stl: { triangles: number; sizeBytes: number };
    pdf: { sizeBytes: number };
    modelVolumeCm3: number;
    drawingVolumeCm3: number;
  }
>;
const MATERIAL: Record<SampleKey, MaterialKey> = { flange: "steel", plate: "aluminum", ring: "stainless" };

export function holePositions(h: HoleSpec): [number, number][] {
  if (h.pattern === "circle") {
    return Array.from({ length: h.count }, (_, i) => {
      const a = Math.PI / 2 + (i * 2 * Math.PI) / h.count;
      return [((h.bc ?? 0) / 2) * Math.cos(a), ((h.bc ?? 0) / 2) * Math.sin(a)] as [number, number];
    });
  }
  const x = (h.px ?? 0) / 2;
  const y = (h.py ?? 0) / 2;
  return [
    [-x, -y],
    [x, -y],
    [x, y],
    [-x, y],
  ];
}

const f1 = (v: number) => v.toFixed(1);
const iso = (now: number, minutesAgo: number) => new Date(now - minutesAgo * 60_000).toISOString();

export interface ProjectBundle {
  project: Project;
  drawing: Drawing;
  extraction: ExtractionResult | null;
  buildPlan: BuildPlan | null;
  parameters: Parameter[];
  checks: ValidationCheck[];
  cost: CostEstimate | null;
  rubric: RubricScore;
  revisions: Revision[];
  audit: AuditEvent[];
  comments: Comment[];
}

export interface Db {
  version: number;
  seededAt: string;
  bundles: Record<string, ProjectBundle>;
  runs: PipelineRun[];
  logs: Record<string, LogEntry[]>;
  templates: RubricTemplate[];
  notifications: Notification[];
  seq: number;
}

const USAGE: Record<string, StageUsage> = {
  analyze: { inputTokens: 6200, outputTokens: 900, visionCalls: 1, computeSeconds: 8.4 },
  extract: { inputTokens: 14800, outputTokens: 4100, visionCalls: 2, computeSeconds: 12.7 },
  generate: { inputTokens: 5200, outputTokens: 2600, visionCalls: 0, computeSeconds: 54.1 },
  validate: { inputTokens: 0, outputTokens: 0, visionCalls: 0, computeSeconds: 6.2 },
};
export const STAGE_LABEL = {
  analyze: "Analyze Drawing",
  extract: "Extract Features",
  generate: "Generate CAD Model",
  validate: "Validate Geometry",
} as const;
const STAGE_KEYS = ["analyze", "extract", "generate", "validate"] as const;

function scaleUsage(u: StageUsage, k: number): StageUsage {
  return {
    inputTokens: Math.round(u.inputTokens * k),
    outputTokens: Math.round(u.outputTokens * k),
    visionCalls: u.visionCalls,
    computeSeconds: Math.round(u.computeSeconds * k * 10) / 10,
  };
}

export function makeStages(
  now: number,
  startMinutesAgo: number,
  k = 1,
  opts: { failAt?: number; retriesAt?: number; pendingFrom?: number; message?: string } = {},
): PipelineStage[] {
  let t = startMinutesAgo * 60_000;
  return STAGE_KEYS.map((key, i) => {
    const usage = scaleUsage(USAGE[key], k);
    const durationMs = Math.round(usage.computeSeconds * 1000);
    const startedAt = new Date(now - t).toISOString();
    t -= durationMs;
    const attempts = opts.retriesAt === i ? 2 : 1;
    if (opts.pendingFrom !== undefined && i >= opts.pendingFrom)
      return { key, label: STAGE_LABEL[key], status: "pending", attempts: 1, usage: { inputTokens: 0, outputTokens: 0, visionCalls: 0, computeSeconds: 0 } };
    if (opts.failAt !== undefined && i > opts.failAt)
      return { key, label: STAGE_LABEL[key], status: "skipped", attempts: 1, message: "Not reached: an earlier stage failed.", usage: { inputTokens: 0, outputTokens: 0, visionCalls: 0, computeSeconds: 0 } };
    if (opts.failAt === i)
      return { key, label: STAGE_LABEL[key], status: "failed", startedAt, durationMs, attempts: 3, message: opts.message ?? "Stage failed after 3 attempts.", usage };
    return {
      key,
      label: STAGE_LABEL[key],
      status: "done",
      startedAt,
      durationMs,
      attempts,
      message: attempts > 1 ? "Succeeded on attempt 2 (first attempt returned an invalid tool call)." : undefined,
      usage: attempts > 1 ? scaleUsage(usage, 1.8) : usage,
    };
  });
}

function makeLogs(now: number, startMinutesAgo: number, key: SampleKey, runId: string): LogEntry[] {
  const s = SPECS[key];
  const dh = s.drawingHoles;
  const mh = s.modelHoles;
  const lines: [LogEntry["level"], string, string][] = [
    ["info", "analyze", `run ${runId} started · preset standard · drawing ${key}.pdf`],
    ["debug", "analyze", "image_prep: rasterized page 1 at 2576 px long edge"],
    ["info", "analyze", "overview: 2 views found (FRONT, SIDE), 1 title block, 3 notes"],
    ["debug", "analyze", `overview: global callout "${dh.count}X Ø${f1(dh.diameter)} THRU"`],
    ["info", "analyze", "stage analyze done in 8.4 s"],
    ["info", "extract", "extractor: forced tool call, schema DrawingData v7"],
    ["debug", "extract", `extractor: outline ${s.outline.kind}, thickness ${f1(s.thickness)} mm`],
    ["debug", "extract", `extractor: bore Ø${f1(s.bore)} ${s.boreNote}`],
    ["info", "extract", `extractor: hole group Ø${f1(mh.diameter)} with ${mh.count} located instance(s)`],
  ];
  if (dh.count !== mh.count) {
    lines.push(
      ["warn", "extract", `count cross-check: callout says ${dh.count}X, located instances = ${mh.count}`],
      ["warn", "extract", "count cross-check: mismatch recorded as CRITICAL (source: callout_count)"],
    );
  } else lines.push(["info", "extract", `count cross-check: callout ${dh.count}X matches ${mh.count} located instance(s)`]);
  lines.push(
    ["info", "extract", "planner: 6 operations planned"],
    ["info", "extract", "stage extract done in 12.7 s"],
    ["info", "generate", "reference build (CadQuery): solid ok, watertight"],
    ["info", "generate", "SolidWorks: new part from template, units mm"],
    ["debug", "generate", "SolidWorks: Base-Extrude mid plane ok (volume verified)"],
    ["debug", "generate", "SolidWorks: Bore cut Up To Next ok (volume verified)"],
    ["debug", "generate", `SolidWorks: hole pattern x${mh.count} ok (volume verified)`],
    ["info", "generate", `saved ${s.name}.sldprt`],
    ["info", "generate", `saved ${s.name}.stl (viewing copy)`],
    ["info", "generate", "stage generate done in 54.1 s"],
    ["info", "validate", "bounding box matches reference"],
    ["info", "validate", "rebuild: 0 errors, 0 warnings"],
  );
  if (dh.count !== mh.count)
    lines.push(["error", "validate", `feature_counts FAILED: holes expected ${dh.count} (drawing callout), modeled ${mh.count}`]);
  else lines.push(["info", "validate", "feature_counts passed"]);
  if (key === "ring") lines.push(["warn", "validate", "sketch_defined not run: SolidWorks session closed before sketch status was read"]);
  lines.push(["info", "validate", "stage validate done in 6.2 s"], ["info", "validate", `run ${runId} finished`]);
  // pad with believable debug detail so the virtualized list has something to scroll
  const pad: [LogEntry["level"], string, string][] = [];
  for (let i = 0; i < 140; i++)
    pad.push(["debug", "generate", `SolidWorks: define_sketch constraint ${String(i + 1).padStart(3, "0")} applied (dx=${(i * 0.37).toFixed(2)}, dy=${(i * 0.21).toFixed(2)})`]);
  const all = [...lines.slice(0, 17), ...pad, ...lines.slice(17)];
  const t0 = now - startMinutesAgo * 60_000;
  return all.map(([level, stage, message], i) => ({
    seq: i + 1,
    at: new Date(t0 + i * 480).toISOString(),
    level,
    stage,
    message,
  }));
}

function makeBundle(key: SampleKey, id: string, now: number, minutesAgo: number): { bundle: ProjectBundle; run: PipelineRun; logs: LogEntry[] } {
  const s = SPECS[key];
  const m = META[key];
  const R = m.regions;
  const dh = s.drawingHoles;
  const mh = s.modelHoles;
  const mismatch = dh.count !== mh.count;
  const circle = s.outline.kind === "circle";
  const runId = `RUN-${id.toUpperCase()}-01`;
  const at = iso(now, minutesAgo);

  const item = (
    n: number,
    partial: Omit<ExtractionItem, "id" | "review" | "critical" | "status"> & Partial<Pick<ExtractionItem, "critical" | "status" | "review">>,
  ): ExtractionItem => ({
    id: `EX-${String(n).padStart(3, "0")}`,
    critical: false,
    status: partial.confidence >= 0.9 ? "verified" : "needs_review",
    review: { decision: "pending" },
    ...partial,
  });

  const items: ExtractionItem[] = [
    item(1, {
      kind: "hole",
      label: "Bolt holes",
      value: `${mh.count}X Ø${f1(mh.diameter)} THRU`,
      numericValue: mh.diameter,
      unit: "mm",
      quantity: mh.count,
      confidence: mismatch ? 0.93 : 0.97,
      region: R.holes,
      featureId: "F003",
      critical: true,
      status: mismatch ? "conflict" : "verified",
      flag: mismatch
        ? `The drawing callout reads ${dh.count}X, but only ${mh.count} hole positions were located. Confidence was high (0.93): this is the quiet failure the review exists to catch.`
        : undefined,
    }),
    item(2, circle
      ? { kind: "dimension", label: "Bolt circle", value: `Ø${f1(dh.bc ?? 0)}`, numericValue: dh.bc, unit: "mm", confidence: 0.96, region: R.holes, featureId: "F003" }
      : { kind: "dimension", label: "Hole pattern", value: `${f1(dh.px ?? 0)} × ${f1(dh.py ?? 0)}`, numericValue: dh.px, unit: "mm", confidence: 0.95, region: R.holes, featureId: "F003" }),
    ...(circle
      ? [item(3, { kind: "dimension", label: "Outer diameter", value: `Ø${f1(s.outline.diameter ?? 0)}`, numericValue: s.outline.diameter, unit: "mm", confidence: 0.98, region: R.outer, featureId: "F001" })]
      : [
          item(3, { kind: "dimension", label: "Width", value: f1(s.outline.width ?? 0), numericValue: s.outline.width, unit: "mm", confidence: 0.98, region: R.width, featureId: "F001" }),
          item(31, { kind: "dimension", label: "Height", value: f1(s.outline.height ?? 0), numericValue: s.outline.height, unit: "mm", confidence: 0.97, region: R.height, featureId: "F001" }),
        ]),
    item(4, {
      kind: "dimension",
      label: "Bore",
      value: `Ø${f1(s.bore)} ${s.boreNote}`,
      numericValue: s.bore,
      unit: "mm",
      tolerance: s.boreNote.startsWith("+") ? { plus: Number(s.boreNote.split("/")[0]), minus: 0 } : { plus: 0.025, minus: 0 },
      confidence: key === "ring" ? 0.82 : 0.94,
      region: R.bore,
      featureId: "F002",
      critical: true,
      flag: key === "ring" ? "Tolerance text is small on the sheet; the upper limit was read as +0.1." : undefined,
    }),
    item(5, { kind: "dimension", label: "Thickness", value: `${f1(s.thickness)} ±0.1`, numericValue: s.thickness, unit: "mm", tolerance: { plus: 0.1, minus: 0.1 }, confidence: 0.97, region: R.thickness, featureId: "F001" }),
    item(6, { kind: "tolerance", label: "General tolerance", value: "X.X ±0.1 · Ø ±0.05", confidence: key === "plate" ? 0.95 : 0.88, region: R.tolerance_note }),
    item(7, { kind: "unit", label: "Units", value: "millimeters", confidence: 0.99, region: R.units_note }),
    item(8, { kind: "note", label: "Material", value: s.materialNote, confidence: 0.95, region: R.material }),
    item(9, {
      kind: "note",
      label: "Edge break",
      value: "Break all sharp edges 0.2 max",
      confidence: key === "plate" ? 0.91 : 0.71,
      region: R.edge_note,
      flag: key === "plate" ? undefined : "Read with low confidence. Not modeled: an edge break is a shop note, not a feature.",
    }),
  ];
  if (key === "plate") for (const it of items) it.review = { decision: "approved", by: "Sample Reviewer", at: iso(now, minutesAgo - 20) };

  const extraction: ExtractionResult = {
    id: `EXT-${id}`,
    projectId: id,
    model: "claude-vision (sample)",
    createdAt: at,
    items,
    countChecks: [
      {
        feature: "Bolt holes", drawingCount: dh.count, extractedCount: mh.count, modeledCount: mh.count, evidenceItemId: "EX-001",
        expectedPositions: holePositions(dh).map(([x, y]) => [Number(x.toFixed(4)), Number(y.toFixed(4)), dh.diameter / 2] as [number, number, number]),
      },
      { feature: "Bores", drawingCount: 1, extractedCount: 1, modeledCount: 1, evidenceItemId: "EX-004" },
    ],
    isSample: true,
  };

  const holes = holePositions(mh);
  const od = circle ? (s.outline.diameter ?? 0) : 0;
  const ops: BuildOperation[] = [
    { id: "OP-01", order: 1, type: "reference", name: "Top Plane", featureId: "F000", params: { plane: "Top", origin: "part center" }, status: "built" },
    {
      id: "OP-02", order: 2, type: "sketch", name: "Sketch1 · base profile", featureId: "F001", parentId: "OP-03",
      params: circle ? { profile: "circle", diameter: od, fullyDefined: true } : { profile: "center rectangle", width: s.outline.width ?? 0, height: s.outline.height ?? 0, fullyDefined: true },
      status: "built",
    },
    {
      id: "OP-03", order: 3, type: "extrude", name: "Base-Extrude", featureId: "F001",
      params: { endCondition: "Mid Plane", depth: s.thickness, units: "mm" }, status: "built",
      locators: [{ kind: "body", position: [0, 0, 0], radius: circle ? od / 2 : Math.max(s.outline.width ?? 0, s.outline.height ?? 0) / 2, depth: s.thickness }],
    },
    {
      id: "OP-04", order: 4, type: "cut", name: "Bore-Cut", featureId: "F002",
      params: { diameter: s.bore, endCondition: "Up To Next", fit: s.boreNote }, status: "built",
      locators: [{ kind: "hole", position: [0, 0, 0], axis: [0, 0, 1], radius: s.bore / 2, depth: s.thickness }],
    },
    {
      id: "OP-05", order: 5, type: "hole", name: "Hole1 · seed", featureId: "F003", parentId: "OP-06",
      params: { type: "Hole Wizard, clearance", diameter: mh.diameter, endCondition: "Up To Next", x: Number(holes[0][0].toFixed(3)), y: Number(holes[0][1].toFixed(3)) },
      status: "built",
      locators: [{ kind: "hole", position: [holes[0][0], holes[0][1], 0], axis: [0, 0, 1], radius: mh.diameter / 2, depth: s.thickness }],
    },
    {
      id: "OP-06", order: 6, type: "pattern", name: circle ? "CirPattern1 · bolt holes" : "LPattern1 · bolt holes", featureId: "F003",
      params: circle
        ? { kind: "circular", instances: mh.count, boltCircle: mh.bc ?? 0, equalSpacing: true, axis: "bore axis" }
        : { kind: "linear 2-direction", instances: mh.count, spacingX: mh.px ?? 0, spacingY: mh.py ?? 0 },
      status: mismatch ? "built_derived" : "built",
      note: mismatch ? `Built with ${mh.count} instances from the located hole positions. The callout count (${dh.count}X) was not used.` : undefined,
      locators: holes.map(([x, y]) => ({ kind: "hole" as const, position: [x, y, 0] as [number, number, number], axis: [0, 0, 1] as [number, number, number], radius: mh.diameter / 2, depth: s.thickness })),
    },
  ];
  const buildPlan: BuildPlan = {
    id: `BP-${id}`,
    projectId: id,
    createdAt: at,
    units: "mm",
    operations: ops,
    outline: circle ? { kind: "circle", diameter: od } : { kind: "rect", width: s.outline.width ?? 0, height: s.outline.height ?? 0 },
    thickness: s.thickness,
    isSample: true,
  };

  const p = (n: number, name: string, symbol: string, value: number, unit: string, range: [number, number], src: string, feat: string, tol?: { plus: number; minus: number }): Parameter => ({
    id: `P-${String(n).padStart(2, "0")}`, name, symbol, value, extractedValue: value, unit, range: { min: range[0], max: range[1] }, sourceItemId: src, featureId: feat, tolerance: tol,
  });
  const parameters: Parameter[] = [
    ...(circle
      ? [p(1, "Outer diameter", "Do", od, "mm", [od * 0.75, od * 1.25], "EX-003", "F001", { plus: 0.1, minus: 0.1 })]
      : [
          p(1, "Width", "W", s.outline.width ?? 0, "mm", [(s.outline.width ?? 0) * 0.75, (s.outline.width ?? 0) * 1.25], "EX-003", "F001", { plus: 0.1, minus: 0.1 }),
          p(11, "Height", "H", s.outline.height ?? 0, "mm", [(s.outline.height ?? 0) * 0.75, (s.outline.height ?? 0) * 1.25], "EX-031", "F001", { plus: 0.1, minus: 0.1 }),
        ]),
    p(2, "Bore diameter", "Di", s.bore, "mm", [s.bore * 0.5, s.bore * 1.5], "EX-004", "F002", { plus: 0.05, minus: 0 }),
    p(3, "Thickness", "t", s.thickness, "mm", [5, 25], "EX-005", "F001", { plus: 0.1, minus: 0.1 }),
    circle
      ? p(4, "Bolt circle", "Dbc", dh.bc ?? 0, "mm", [s.bore + 3 * dh.diameter, od - 2 * dh.diameter], "EX-002", "F003", { plus: 0.1, minus: 0.1 })
      : p(4, "Hole spacing X", "px", dh.px ?? 0, "mm", [40, (s.outline.width ?? 0) - 12], "EX-002", "F003", { plus: 0.1, minus: 0.1 }),
    p(5, "Hole diameter", "d", mh.diameter, "mm", [3, 14], "EX-001", "F003", { plus: 0.05, minus: 0.05 }),
    p(6, "Hole count", "n", mh.count, "ea", [2, 24], "EX-001", "F003"),
  ];

  const bboxW = circle ? od : (s.outline.width ?? 0);
  const bboxH = circle ? od : (s.outline.height ?? 0);
  const ranAt = iso(now, minutesAgo - 1);
  const checks: ValidationCheck[] = [
    {
      id: "CHK-01", key: "feature_counts", label: "Feature counts match the drawing", severity: "critical",
      description: "Compares the count in each drawing callout with the instances extraction located and the instances in the built model.",
      status: mismatch ? "failed" : "passed",
      expected: `${dh.count} bolt holes, 1 bore`, measured: `${mh.count} bolt holes, 1 bore`,
      detail: mismatch ? `Drawing calls out ${dh.count} bolt holes. Extraction found ${mh.count}. Model has ${mh.count}.` : "Every count agrees across the drawing callouts, the extraction and the model.",
      rows: [
        { label: "Bolt holes", expected: String(dh.count), measured: String(mh.count), delta: String(mh.count - dh.count), ok: !mismatch },
        { label: "Bores", expected: "1", measured: "1", delta: "0", ok: true },
      ],
      evidence: { itemIds: ["EX-001"], featureIds: ["F003"] }, ranAt,
    },
    {
      id: "CHK-02", key: "bounding_box", label: "Bounding box vs drawing", severity: "major",
      description: "The model's overall envelope against the overall dimensions on the drawing.",
      status: "passed", expected: `${f1(bboxW)} × ${f1(bboxH)} × ${f1(s.thickness)} mm`, measured: `${f1(bboxW)} × ${f1(bboxH)} × ${f1(s.thickness)} mm`,
      rows: [
        { label: "X", expected: f1(bboxW), measured: bboxW.toFixed(3), delta: "0.000", tolerance: "±0.1", ok: true },
        { label: "Y", expected: f1(bboxH), measured: bboxH.toFixed(3), delta: "0.000", tolerance: "±0.1", ok: true },
        { label: "Z", expected: f1(s.thickness), measured: s.thickness.toFixed(3), delta: "0.000", tolerance: "±0.1", ok: true },
      ],
      evidence: { itemIds: ["EX-003", "EX-005"], featureIds: ["F001"] }, ranAt,
    },
    {
      id: "CHK-03", key: "dimension_deltas", label: "Dimension deltas vs tolerance", severity: "critical",
      description: "Each extracted dimension is measured on the built model and compared with its tolerance.",
      status: "passed", detail: "All measured dimensions are inside their tolerance.",
      rows: [
        { label: circle ? "Outer diameter" : "Width", expected: f1(bboxW), measured: bboxW.toFixed(3), delta: "0.000", tolerance: "±0.1", ok: true },
        { label: "Bore diameter", expected: f1(s.bore), measured: (s.bore + 0.012).toFixed(3), delta: "+0.012", tolerance: "+0.05/0", ok: true },
        { label: "Thickness", expected: f1(s.thickness), measured: s.thickness.toFixed(3), delta: "0.000", tolerance: "±0.1", ok: true },
        { label: "Hole diameter", expected: f1(mh.diameter), measured: mh.diameter.toFixed(3), delta: "0.000", tolerance: "±0.05", ok: true },
        { label: circle ? "Bolt circle" : "Hole spacing X", expected: f1(circle ? (dh.bc ?? 0) : (dh.px ?? 0)), measured: (circle ? (dh.bc ?? 0) : (dh.px ?? 0)).toFixed(3), delta: "0.000", tolerance: "±0.1", ok: true },
      ],
      evidence: { itemIds: ["EX-002", "EX-003", "EX-004", "EX-005"], featureIds: ["F001", "F002", "F003"] }, ranAt,
    },
    {
      id: "CHK-04", key: "unit_consistency", label: "Unit consistency", severity: "minor",
      description: "The drawing's unit note, the extraction units and the SolidWorks document units agree.",
      status: "passed", expected: "mm", measured: "mm", evidence: { itemIds: ["EX-007"], featureIds: [] }, ranAt,
    },
    {
      id: "CHK-05", key: "rebuild_errors", label: "Rebuild errors", severity: "critical",
      description: "A forced rebuild of the SolidWorks part reports no errors.",
      status: "passed", expected: "0 errors", measured: "0 errors, 0 warnings", evidence: { itemIds: [], featureIds: [] }, ranAt,
    },
    key === "ring"
      ? {
          id: "CHK-06", key: "sketch_defined", label: "Sketches fully defined", severity: "major",
          description: "Every sketch in the feature tree is fully defined.",
          status: "not_run", detail: "The SolidWorks session closed before sketch status was read.", evidence: { itemIds: [], featureIds: [] },
        }
      : {
          id: "CHK-06", key: "sketch_defined", label: "Sketches fully defined", severity: "major",
          description: "Every sketch in the feature tree is fully defined.",
          status: key === "flange" ? "warning" : "passed", expected: "3 of 3", measured: key === "flange" ? "2 of 3" : "3 of 3",
          detail: key === "flange" ? "The hole-pattern seed sketch is under-defined (1 degree of freedom)." : undefined,
          evidence: { itemIds: [], featureIds: ["F003"] }, ranAt,
        },
    {
      id: "CHK-07", key: "watertight", label: "Watertight geometry", severity: "major",
      description: "The exported mesh is a closed manifold solid with a positive volume.",
      status: "passed", expected: "closed solid", measured: `closed, ${m.modelVolumeCm3.toFixed(2)} cm³`, evidence: { itemIds: [], featureIds: ["F001"] }, ranAt,
    },
  ];

  const stages = makeStages(now, minutesAgo, key === "flange" ? 1 : key === "plate" ? 0.82 : 0.9, key === "ring" ? { retriesAt: 1 } : {});
  const run: PipelineRun = {
    id: runId, projectId: id, projectName: s.name, status: "succeeded", preset: "standard",
    createdAt: at, startedAt: at, finishedAt: iso(now, minutesAgo - 1.4), stages, simulated: false, isSample: true,
  };

  const status: Project["status"] = key === "flange" ? "needs_rework" : key === "plate" ? "approved" : "needs_review";
  const project: Project = {
    id, name: s.name, partNumber: s.partNumber, revision: s.revision,
    description: `${s.title.charAt(0)}${s.title.slice(1).toLowerCase()}, ${s.materialNote.toLowerCase()}`,
    material: MATERIAL[key], units: "mm", status,
    createdAt: iso(now, minutesAgo + 60 * 24 * (key === "flange" ? 1 : key === "plate" ? 6 : 3)), updatedAt: iso(now, minutesAgo - 2),
    lastRunId: runId, modelUrl: `/samples/${key}.stl`, partSpecKey: key, isSample: true,
  };
  const drawing: Drawing = {
    id: `DRW-${id}`, projectId: id, fileName: `${s.partNumber}_${s.name}.pdf`, url: `/samples/${key}.pdf`, kind: "pdf",
    pageCount: 1, sizeBytes: m.pdf.sizeBytes, uploadedAt: iso(now, minutesAgo + 3), registration: m.registration,
  };

  const stockVolume =
    ((circle ? (od + 6) ** 2 : ((s.outline.width ?? 0) + 6) * ((s.outline.height ?? 0) + 6)) * (s.thickness + 3)) / 1000;
  const cost: CostEstimate = {
    projectId: id, runId,
    stages: stages.map((st) => ({ key: st.key, label: st.label, usage: st.usage, retries: st.attempts - 1 })),
    batchSize: key === "flange" ? 12 : 6,
    partVolumeCm3: m.modelVolumeCm3, stockVolumeCm3: Number(stockVolume.toFixed(2)),
    holeCount: mh.count + 1, featureCount: 2,
    history: Array.from({ length: 8 }, (_, i) => ({
      runId: `${runId}-h${i}`,
      date: iso(now, minutesAgo + (8 - i) * 60 * 24),
      usage: scaleUsage({ inputTokens: 26200, outputTokens: 7600, visionCalls: 3, computeSeconds: 81.4 }, 0.8 + ((i * 37) % 11) / 20),
    })),
    isSample: true,
  };

  const rubric: RubricScore = {
    projectId: id, templateId: DEFAULT_TEMPLATE.id, revision: s.revision,
    entries: DEFAULT_TEMPLATE.criteria.map((c) => ({
      criterionKey: c.key,
      level: key === "plate" && c.scoredBy !== "auto" ? (c.key === "feature_tree" ? 3 : 4) : null,
      comment: key === "plate" && c.key === "feature_tree" ? "Default feature names on the hole pattern; otherwise clean." : "",
    })),
    signOff: key === "plate" ? { by: "Sample Reviewer", at: iso(now, minutesAgo - 30), status: "approved_with_notes", total: 97.5, band: "A" } : undefined,
    history: key === "plate" ? [{ revision: "A", total: 78.8, band: "C", status: "approved_with_notes", at: iso(now, minutesAgo + 60 * 24 * 4), by: "Sample Reviewer" }, { revision: "B", total: 97.5, band: "A", status: "approved_with_notes", at: iso(now, minutesAgo - 30), by: "Sample Reviewer" }] : [],
  };

  const revParams = parameters.map((q) => ({ name: q.name, value: q.value, unit: q.unit }));
  const revisions: Revision[] = [
    {
      id: `REV-${id}-2`, projectId: id, label: `Rev ${s.revision}`, createdAt: at, author: "pipeline", summary: mismatch ? "Current build. Hole count does not match the drawing callout." : "Current build.", runId,
      metrics: { holes: mh.count, features: ops.length, volumeCm3: m.modelVolumeCm3, checksPassed: checks.filter((c) => c.status === "passed").length, checksFailed: checks.filter((c) => c.status === "failed").length },
      parameters: revParams,
    },
    {
      id: `REV-${id}-1`, projectId: id, label: "Rev 0 (first run)", createdAt: iso(now, minutesAgo + 60 * 24 * 2), author: "pipeline", summary: "First run. Thickness read as 12.0 before the side view was included.",
      metrics: { holes: mh.count, features: ops.length - 1, volumeCm3: Number(((m.modelVolumeCm3 * 12) / s.thickness).toFixed(3)), checksPassed: 4, checksFailed: mismatch ? 2 : 1 },
      parameters: revParams.map((q) => (q.name === "Thickness" ? { ...q, value: 12 } : q)),
    },
  ];

  const audit: AuditEvent[] = [
    { id: `AUD-${id}-1`, projectId: id, at, actor: "pipeline", action: "run_started", targetId: runId, summary: `Run ${runId} started (preset standard).` },
  ];
  if (key === "plate")
    audit.unshift(
      { id: `AUD-${id}-3`, projectId: id, at: iso(now, minutesAgo - 30), actor: "Sample Reviewer", action: "sign_off", summary: "Signed off: Approved with notes, 97.5 (A)." },
      { id: `AUD-${id}-2`, projectId: id, at: iso(now, minutesAgo - 20), actor: "Sample Reviewer", action: "approve_item", summary: "Approved all 10 extracted items." },
    );

  const comments: Comment[] = mismatch
    ? [{ id: `CMT-${id}-1`, projectId: id, at: iso(now, minutesAgo - 3), author: "Sample Reviewer", body: "Callout clearly says 10X. Count the circles on the front view: there are 10.", region: R.holes, itemId: "EX-001", resolved: false }]
    : [];

  return { bundle: { project, drawing, extraction, buildPlan, parameters, checks, cost, rubric, revisions, audit, comments }, run, logs: makeLogs(now, minutesAgo, key, runId) };
}

export const SAMPLE_PROJECT_IDS = { flange: "fl-2210", plate: "bp-1042", ring: "sr-0077" } as const;

export function seedDb(now = Date.now()): Db {
  const a = makeBundle("flange", SAMPLE_PROJECT_IDS.flange, now, 4);
  const b = makeBundle("plate", SAMPLE_PROJECT_IDS.plate, now, 190);
  const c = makeBundle("ring", SAMPLE_PROJECT_IDS.ring, now, 75);
  const mk = (n: number, projectId: string, name: string, minutesAgo: number, status: PipelineRun["status"], k: number, opts: Parameters<typeof makeStages>[3] = {}): PipelineRun => ({
    id: `RUN-${String(n).padStart(4, "0")}`, projectId, projectName: name, status, preset: n % 3 === 0 ? "high-accuracy" : "standard",
    createdAt: iso(now, minutesAgo), startedAt: status === "queued" ? undefined : iso(now, minutesAgo),
    finishedAt: status === "queued" ? undefined : iso(now, minutesAgo - 1.5), etaSeconds: status === "queued" ? 95 : undefined,
    stages: makeStages(now, minutesAgo, k, opts), simulated: false, isSample: true,
  });
  const history: PipelineRun[] = [
    mk(12, SAMPLE_PROJECT_IDS.ring, "Spacer_Ring", 60 * 26, "failed", 0.9, { failAt: 2, message: "SolidWorks: Hole Wizard returned Nothing on all 3 attempts; fallback cut failed volume check." }),
    mk(11, SAMPLE_PROJECT_IDS.plate, "Bearing_Plate", 60 * 24 * 4, "succeeded", 0.85),
    mk(10, SAMPLE_PROJECT_IDS.flange, "Flange_Adapter", 60 * 24 * 2, "succeeded", 1.1, { retriesAt: 1 }),
    mk(9, SAMPLE_PROJECT_IDS.plate, "Bearing_Plate", 60 * 24 * 6, "cancelled", 0.4, { pendingFrom: 2 }),
    mk(8, SAMPLE_PROJECT_IDS.ring, "Spacer_Ring", 60 * 24 * 3, "succeeded", 0.95),
  ];
  const notifications: Notification[] = [
    { id: "NTF-3", at: iso(now, 2.5), kind: "validation_failed", title: "Validation failed: Flange_Adapter", body: "Drawing calls out 10 bolt holes. Model has 8. Export is blocked.", projectId: SAMPLE_PROJECT_IDS.flange, read: false },
    { id: "NTF-2", at: iso(now, 3), kind: "run_finished", title: "Run finished: Flange_Adapter", body: "RUN-FL-2210-01 completed in 1m 21s.", projectId: SAMPLE_PROJECT_IDS.flange, read: false },
    { id: "NTF-1", at: iso(now, 74), kind: "review_needed", title: "Review needed: Spacer_Ring", body: "3 extracted items need review; one check did not run.", projectId: SAMPLE_PROJECT_IDS.ring, read: true },
  ];
  return {
    version: 3,
    seededAt: new Date(now).toISOString(),
    bundles: { [a.bundle.project.id]: a.bundle, [b.bundle.project.id]: b.bundle, [c.bundle.project.id]: c.bundle },
    runs: [a.run, c.run, b.run, ...history],
    logs: { [a.run.id]: a.logs, [b.run.id]: b.logs, [c.run.id]: c.logs },
    templates: [DEFAULT_TEMPLATE],
    notifications,
    seq: 100,
  };
}

/** Bundle for a new project created from a bundled sample drawing (used by the mock run wizard). */
export function sampleBundle(key: SampleKey, id: string, now = Date.now()) {
  return makeBundle(key, id, now, 0);
}
