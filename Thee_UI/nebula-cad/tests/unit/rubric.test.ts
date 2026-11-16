import { describe, expect, it } from "vitest";
import { seedDb, SAMPLE_PROJECT_IDS } from "@/lib/data/seed";
import { DEFAULT_TEMPLATE, autoLevel, gradeBand, hardFailGates, releaseStatus, scoreRubric, weightSum } from "@/lib/rubric";
import * as S from "@/lib/schemas";
import { countMismatches, exportGate, riskOrder, summarize } from "@/lib/validation";

const db = seedDb(Date.parse("2026-11-16T12:00:00Z"));
const flange = db.bundles[SAMPLE_PROJECT_IDS.flange];
const plate = db.bundles[SAMPLE_PROJECT_IDS.plate];
const ring = db.bundles[SAMPLE_PROJECT_IDS.ring];
const ctx = (b: typeof flange) => ({ checks: b.checks, extraction: b.extraction, buildPlan: b.buildPlan, signedOff: Boolean(b.rubric.signOff) });
const full = DEFAULT_TEMPLATE.criteria.map((c) => ({ criterionKey: c.key, level: 4, comment: "" }));

describe("seed data", () => {
  it("parses against the schemas", () => {
    for (const b of Object.values(db.bundles)) {
      S.Project.parse(b.project);
      S.Drawing.parse(b.drawing);
      S.ExtractionResult.parse(b.extraction);
      S.BuildPlan.parse(b.buildPlan);
      b.parameters.forEach((p) => S.Parameter.parse(p));
      b.checks.forEach((c) => S.ValidationCheck.parse(c));
      S.CostEstimate.parse(b.cost);
      S.RubricScore.parse(b.rubric);
      b.revisions.forEach((r) => S.Revision.parse(r));
      b.audit.forEach((a) => S.AuditEvent.parse(a));
    }
    db.runs.forEach((r) => S.PipelineRun.parse(r));
    Object.values(db.logs).flat().forEach((l) => S.LogEntry.parse(l));
  });
  it("seeds the central failure: drawing 10 holes, extraction 8", () => {
    const m = countMismatches(flange.extraction);
    expect(m).toHaveLength(1);
    expect(m[0]).toMatchObject({ drawingCount: 10, extractedCount: 8, modeledCount: 8 });
    expect(m[0].expectedPositions).toHaveLength(10);
    expect(flange.checks.find((c) => c.key === "feature_counts")?.status).toBe("failed");
    expect(countMismatches(plate.extraction)).toHaveLength(0);
  });
  it("includes all seven required validation checks", () => {
    expect(flange.checks.map((c) => c.key).sort()).toEqual(["bounding_box", "dimension_deltas", "feature_counts", "rebuild_errors", "sketch_defined", "unit_consistency", "watertight"]);
  });
});

describe("validation gating", () => {
  it("blocks export on a failed critical check", () => {
    const g = exportGate(flange.checks);
    expect(g.blocked).toBe(true);
    expect(g.open.map((r) => r.checkId)).toEqual(["CHK-01"]);
  });
  it("unblocks only with a recorded override, and keeps the reason listed", () => {
    const checks = flange.checks.map((c) => (c.id === "CHK-01" ? { ...c, override: { by: "QA", reason: "Customer accepted 8 holes", at: "2026-11-16T00:00:00Z" } } : c));
    const g = exportGate(checks);
    expect(g.blocked).toBe(false);
    expect(g.reasons).toHaveLength(1);
    expect(g.reasons[0].overridden).toBe(true);
  });
  it("blocks on a critical check that did not run", () => {
    const checks = plate.checks.map((c) => (c.key === "rebuild_errors" ? { ...c, status: "not_run" as const } : c));
    expect(exportGate(checks).blocked).toBe(true);
    expect(exportGate(checks).open[0].kind).toBe("not_run");
  });
  it("does not block on a non-critical check that did not run, and allows a clean part", () => {
    expect(ring.checks.find((c) => c.key === "sketch_defined")?.status).toBe("not_run");
    expect(exportGate(ring.checks).blocked).toBe(false);
    expect(exportGate(plate.checks)).toMatchObject({ blocked: false, reasons: [] });
  });
  it("never counts a not-run check as passed", () => {
    const s = summarize(ring.checks);
    expect(s.notRun).toBe(1);
    expect(s.passed).toBe(6);
    expect(s.passRate).toBe(1); // of the 6 that ran
    expect(summarize([]).passRate).toBeNull();
  });
  it("orders the review queue by risk", () => {
    const order = riskOrder(flange.extraction!.items);
    expect(order[0].status).toBe("conflict");
    expect(order[order.length - 1].status).toBe("verified");
  });
});

describe("rubric", () => {
  it("default weights sum to 100", () => {
    expect(weightSum(DEFAULT_TEMPLATE.criteria)).toBe(100);
    expect(DEFAULT_TEMPLATE.criteria).toHaveLength(7);
  });
  it("grade bands", () => {
    expect([95, 90, 89.9, 80, 79.9, 70, 69.9].map(gradeBand)).toEqual(["A", "A", "B", "B", "C", "C", "Needs rework"]);
  });
  it("scores a clean part at 100 when every reviewer level is 4", () => {
    const r = scoreRubric(DEFAULT_TEMPLATE, full, { ...ctx(plate), signedOff: true });
    expect(r.total).toBe(100);
    expect(r.band).toBe("A");
    expect(r.capped).toBe(false);
    expect(r.status).toBe("approved");
  });
  it("HARD-FAIL CAP: a count mismatch caps release at Needs rework whatever the reviewer scores", () => {
    const r = scoreRubric(DEFAULT_TEMPLATE, full, ctx(flange));
    expect(r.gates.length).toBeGreaterThan(0);
    expect(r.gates[0].reason).toContain("10");
    expect(r.capped).toBe(true);
    expect(r.status).toBe("needs_rework");
    expect(r.total).toBeGreaterThanOrEqual(70); // the score alone would have released it
    expect(r.criteria.find((c) => c.criterion.key === "feature_completeness")?.level).toBe(1);
  });
  it("lifts the cap only through a recorded override, and then never says plain Approved", () => {
    const r = scoreRubric(DEFAULT_TEMPLATE, full, ctx(flange), { by: "QA", reason: "Accepted by customer deviation 114", at: "2026-11-16T00:00:00Z" });
    expect(r.capped).toBe(false);
    expect(r.gates.every((g) => g.overridden)).toBe(true);
    expect(r.status).toBe("approved_with_notes");
  });
  it("a check-level override on the failing check also lifts the cap", () => {
    const checks = flange.checks.map((c) => (c.id === "CHK-01" ? { ...c, override: { by: "QA", reason: "deviation 114", at: "x" } } : c));
    expect(scoreRubric(DEFAULT_TEMPLATE, full, { ...ctx(flange), checks }).capped).toBe(false);
  });
  it("gates on rebuild errors and on a critical dimension out of tolerance", () => {
    const checks = plate.checks.map((c) => (c.key === "rebuild_errors" || c.key === "dimension_deltas" ? { ...c, status: "failed" as const } : c));
    const g = hardFailGates({ ...ctx(plate), checks });
    expect(g.map((x) => x.reason).join(" ")).toMatch(/Rebuild errors/);
    expect(g.map((x) => x.reason).join(" ")).toMatch(/Critical dimension out of tolerance/);
  });
  it("scores not-run evidence as 0 (missing), never as a pass", () => {
    const checks = plate.checks.map((c) => ({ ...c, status: "not_run" as const }));
    for (const key of ["dimensional_accuracy", "feature_completeness", "tolerance_units", "geometry_validity"]) expect(autoLevel(key, { ...ctx(plate), checks })?.level).toBe(0);
  });
  it("is incomplete until reviewer criteria are scored, and unscored counts as 0", () => {
    const none = DEFAULT_TEMPLATE.criteria.map((c) => ({ criterionKey: c.key, level: null, comment: "" }));
    const r = scoreRubric(DEFAULT_TEMPLATE, none, ctx(plate));
    expect(r.complete).toBe(false);
    expect(r.criteria.find((c) => c.criterion.key === "feature_tree")?.points).toBe(0);
    expect(r.criteria.find((c) => c.criterion.key === "documentation")?.source).toBe("auto");
  });
  it("flags weights that do not sum to 100", () => {
    const t = { ...DEFAULT_TEMPLATE, criteria: DEFAULT_TEMPLATE.criteria.map((c, i) => (i === 0 ? { ...c, weight: 30 } : c)) };
    expect(scoreRubric(t, full, ctx(plate)).weightsValid).toBe(false);
  });
  it("release status rules", () => {
    expect(releaseStatus(95, { capped: true, overrideUsed: false, hasNotes: false })).toBe("needs_rework");
    expect(releaseStatus(65, { capped: false, overrideUsed: false, hasNotes: false })).toBe("needs_rework");
    expect(releaseStatus(75, { capped: false, overrideUsed: false, hasNotes: false })).toBe("approved_with_notes");
    expect(releaseStatus(92, { capped: false, overrideUsed: false, hasNotes: true })).toBe("approved_with_notes");
    expect(releaseStatus(92, { capped: false, overrideUsed: false, hasNotes: false })).toBe("approved");
  });
});
