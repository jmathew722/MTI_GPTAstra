import type {
  BuildPlan,
  ExtractionResult,
  Override,
  ReleaseStatus,
  RubricCriterion,
  RubricEntry,
  RubricTemplate,
  ValidationCheck,
} from "@/lib/schemas";
import { countMismatches, mismatchSentence } from "@/lib/validation";

export const DEFAULT_CRITERIA: RubricCriterion[] = [
  {
    key: "dimensional_accuracy",
    label: "Dimensional accuracy",
    weight: 25,
    scoredBy: "auto",
    levels: {
      4: "Every checked dimension is within its tolerance.",
      3: "At least 90% of checked dimensions are within tolerance; none of the misses is critical.",
      2: "At least 70% of checked dimensions are within tolerance.",
      1: "Fewer than 70% within tolerance, or the bounding box is wrong.",
    },
  },
  {
    key: "feature_completeness",
    label: "Feature completeness and counts",
    weight: 20,
    scoredBy: "auto",
    levels: {
      4: "Every feature on the drawing is modeled and every count matches.",
      3: "All counts match; a minor feature needs review.",
      2: "A non-critical feature is missing or excluded.",
      1: "A feature count does not match the drawing.",
    },
  },
  {
    key: "tolerance_units",
    label: "Tolerance and unit compliance",
    weight: 15,
    scoredBy: "auto",
    levels: {
      4: "Units are consistent and all tolerances were captured.",
      3: "Units are consistent; one tolerance needs review.",
      2: "A tolerance was missed or misread.",
      1: "Unit inconsistency between the drawing and the model.",
    },
  },
  {
    key: "geometry_validity",
    label: "Geometry validity",
    weight: 15,
    scoredBy: "auto",
    levels: {
      4: "Rebuilds clean, watertight, all sketches fully defined.",
      3: "Rebuilds clean and watertight; a sketch is under-defined.",
      2: "One geometry check failed.",
      1: "Rebuild errors or open geometry.",
    },
  },
  {
    key: "feature_tree",
    label: "Feature tree quality",
    weight: 10,
    scoredBy: "reviewer",
    levels: {
      4: "Features are named, ordered logically and driven by editable parametric dimensions.",
      3: "Sound order and parametric dimensions; some default names.",
      2: "Editable, but order or references make changes fragile.",
      1: "Hard to edit: dumb geometry or broken references.",
    },
  },
  {
    key: "manufacturability",
    label: "Manufacturability",
    weight: 5,
    scoredBy: "reviewer",
    levels: {
      4: "Can be made as modeled with standard tooling.",
      3: "Makeable with minor notes for the shop.",
      2: "Needs a design change for a sensible process.",
      1: "Not makeable as modeled.",
    },
  },
  {
    key: "documentation",
    label: "Documentation and traceability",
    weight: 10,
    scoredBy: "mixed",
    levels: {
      4: "Build plan present, every extracted item reviewed, sign-off recorded.",
      3: "Build plan present and at least 80% of items reviewed.",
      2: "Build plan present; review incomplete.",
      1: "No build plan or no review trail.",
    },
  },
];

export const DEFAULT_TEMPLATE: RubricTemplate = {
  id: "tpl-default",
  name: "MTI default part rubric",
  criteria: DEFAULT_CRITERIA,
  builtIn: true,
  updatedAt: "2026-11-01T00:00:00.000Z",
};

export const LEVEL_NAMES: Record<number, string> = {
  4: "Exemplary",
  3: "Proficient",
  2: "Developing",
  1: "Insufficient",
  0: "Missing",
};

export interface RubricContext {
  checks: ValidationCheck[];
  extraction?: ExtractionResult | null;
  buildPlan?: BuildPlan | null;
  signedOff?: boolean;
}

export interface Evidence {
  checkIds: string[];
  itemIds: string[];
  notes: string[];
}

export interface AutoResult {
  level: number;
  evidence: Evidence;
}

const find = (checks: ValidationCheck[], key: string) => checks.find((c) => c.key === key);

/** Automatic level for a criterion, or null when the criterion is reviewer-only. Not-run evidence scores 0. */
export function autoLevel(key: string, ctx: RubricContext): AutoResult | null {
  const ev: Evidence = { checkIds: [], itemIds: [], notes: [] };
  const cite = (c?: ValidationCheck) => {
    if (c) {
      ev.checkIds.push(c.id);
      ev.itemIds.push(...c.evidence.itemIds);
    }
    return c;
  };
  switch (key) {
    case "dimensional_accuracy": {
      const deltas = cite(find(ctx.checks, "dimension_deltas"));
      const bbox = cite(find(ctx.checks, "bounding_box"));
      if (!deltas || deltas.status === "not_run") {
        ev.notes.push("Dimension deltas have not run.");
        return { level: 0, evidence: ev };
      }
      const rows = deltas.rows ?? [];
      const ok = rows.filter((r) => r.ok).length;
      const ratio = rows.length ? ok / rows.length : deltas.status === "passed" ? 1 : 0;
      ev.notes.push(`${ok} of ${rows.length} checked dimensions within tolerance.`);
      let level = ratio === 1 ? 4 : ratio >= 0.9 ? 3 : ratio >= 0.7 ? 2 : 1;
      if (deltas.status === "failed" && level > 2) level = 2;
      if (bbox?.status === "failed") {
        level = 1;
        ev.notes.push("Bounding box does not match the drawing.");
      } else if (bbox?.status === "not_run") {
        level = Math.min(level, 3);
        ev.notes.push("Bounding box check has not run.");
      }
      return { level, evidence: ev };
    }
    case "feature_completeness": {
      const counts = cite(find(ctx.checks, "feature_counts"));
      const mismatches = countMismatches(ctx.extraction);
      for (const m of mismatches) {
        ev.notes.push(mismatchSentence(m));
        if (m.evidenceItemId) ev.itemIds.push(m.evidenceItemId);
      }
      if (!counts || counts.status === "not_run") {
        ev.notes.push("Feature count check has not run.");
        return { level: 0, evidence: ev };
      }
      if (counts.status === "failed" || mismatches.length) return { level: 1, evidence: ev };
      const excluded = ctx.buildPlan?.operations.filter((o) => o.status === "excluded" || o.status === "failed").length ?? 0;
      if (excluded) {
        ev.notes.push(`${excluded} build operation(s) excluded or failed.`);
        return { level: 2, evidence: ev };
      }
      if (counts.status === "warning") return { level: 3, evidence: ev };
      ev.notes.push("All feature counts match.");
      return { level: 4, evidence: ev };
    }
    case "tolerance_units": {
      const units = cite(find(ctx.checks, "unit_consistency"));
      if (!units || units.status === "not_run") {
        ev.notes.push("Unit consistency has not run.");
        return { level: 0, evidence: ev };
      }
      if (units.status === "failed") return { level: 1, evidence: ev };
      const tolItems = ctx.extraction?.items.filter((i) => i.kind === "tolerance" || i.tolerance) ?? [];
      const bad = tolItems.filter((i) => i.status === "conflict" || i.review.decision === "rejected");
      const unsure = tolItems.filter((i) => i.status === "needs_review" && i.review.decision === "pending");
      ev.itemIds.push(...bad.map((i) => i.id), ...unsure.map((i) => i.id));
      if (bad.length) {
        ev.notes.push(`${bad.length} tolerance item(s) in conflict or rejected.`);
        return { level: 2, evidence: ev };
      }
      if (unsure.length || units.status === "warning") {
        ev.notes.push(`${unsure.length} tolerance item(s) still need review.`);
        return { level: 3, evidence: ev };
      }
      ev.notes.push("Units consistent; tolerances captured.");
      return { level: 4, evidence: ev };
    }
    case "geometry_validity": {
      const trio = ["rebuild_errors", "watertight", "sketch_defined"].map((k) => cite(find(ctx.checks, k)));
      const ran = trio.filter((c) => c && c.status !== "not_run");
      if (!ran.length) {
        ev.notes.push("No geometry check has run.");
        return { level: 0, evidence: ev };
      }
      const failed = trio.filter((c) => c?.status === "failed").length;
      const warned = trio.filter((c) => c?.status === "warning").length;
      const notRun = trio.length - ran.length;
      if (notRun) ev.notes.push(`${notRun} geometry check(s) have not run.`);
      if (trio[0]?.status === "failed" || failed > 1) return { level: 1, evidence: ev };
      if (failed === 1) return { level: 2, evidence: ev };
      if (warned || notRun) return { level: 3, evidence: ev };
      ev.notes.push("Rebuild clean, watertight, sketches defined.");
      return { level: 4, evidence: ev };
    }
    case "documentation": {
      if (!ctx.buildPlan || !ctx.buildPlan.operations.length) {
        ev.notes.push("No build plan.");
        return { level: 1, evidence: ev };
      }
      const items = ctx.extraction?.items ?? [];
      const reviewed = items.filter((i) => i.review.decision !== "pending").length;
      const ratio = items.length ? reviewed / items.length : 0;
      ev.notes.push(`${reviewed} of ${items.length} extracted items reviewed.`);
      if (ratio === 1 && ctx.signedOff) return { level: 4, evidence: ev };
      if (ratio >= 0.8) return { level: 3, evidence: ev };
      return { level: 2, evidence: ev };
    }
    default:
      return null;
  }
}

export interface ScoredCriterion {
  criterion: RubricCriterion;
  /** level used in the total (0..4); null = a reviewer criterion nobody has scored */
  level: number | null;
  source: "auto" | "reviewer" | "unscored";
  autoLevel: number | null;
  points: number;
  evidence: Evidence;
  comment: string;
}

export interface GateItem {
  id: string;
  reason: string;
  checkId?: string;
  overridden: boolean;
}

export interface RubricResult {
  criteria: ScoredCriterion[];
  total: number;
  band: "A" | "B" | "C" | "Needs rework";
  status: ReleaseStatus;
  complete: boolean;
  capped: boolean;
  gates: GateItem[];
  weightSum: number;
  weightsValid: boolean;
}

export function weightSum(criteria: RubricCriterion[]): number {
  return criteria.reduce((a, c) => a + c.weight, 0);
}

export function gradeBand(total: number): RubricResult["band"] {
  if (total >= 90) return "A";
  if (total >= 80) return "B";
  if (total >= 70) return "C";
  return "Needs rework";
}

/** Critical mismatches that cap the release status until a reviewer overrides them with a reason. */
export function hardFailGates(ctx: RubricContext): GateItem[] {
  const gates: GateItem[] = [];
  const counts = find(ctx.checks, "feature_counts");
  for (const m of countMismatches(ctx.extraction)) {
    gates.push({
      id: `count:${m.feature}`,
      reason: `Feature count mismatch. ${mismatchSentence(m)}`,
      checkId: counts?.id,
      overridden: Boolean(counts?.override),
    });
  }
  for (const c of ctx.checks) {
    if (c.severity !== "critical" || c.status !== "failed") continue;
    if (c.key === "feature_counts" && gates.some((g) => g.id.startsWith("count:"))) continue;
    const what =
      c.key === "rebuild_errors"
        ? "Rebuild errors"
        : c.key === "dimension_deltas"
          ? "Critical dimension out of tolerance"
          : c.label;
    gates.push({
      id: `check:${c.id}`,
      reason: `${what}. ${c.detail ?? ""}`.trim(),
      checkId: c.id,
      overridden: Boolean(c.override),
    });
  }
  return gates;
}

export function scoreRubric(
  template: RubricTemplate,
  entries: RubricEntry[],
  ctx: RubricContext,
  gateOverride?: Override,
): RubricResult {
  const criteria: ScoredCriterion[] = template.criteria.map((criterion) => {
    const entry = entries.find((e) => e.criterionKey === criterion.key);
    const auto = autoLevel(criterion.key, ctx);
    const empty: Evidence = { checkIds: [], itemIds: [], notes: [] };
    let level: number | null;
    let source: ScoredCriterion["source"];
    if (criterion.scoredBy === "auto") {
      level = auto ? auto.level : 0;
      source = "auto";
    } else if (entry?.level !== null && entry?.level !== undefined) {
      level = entry.level;
      source = "reviewer";
    } else if (criterion.scoredBy === "mixed" && auto) {
      level = auto.level;
      source = "auto";
    } else {
      level = null;
      source = "unscored";
    }
    return {
      criterion,
      level,
      source,
      autoLevel: auto ? auto.level : null,
      points: ((level ?? 0) / 4) * criterion.weight,
      evidence: auto?.evidence ?? empty,
      comment: entry?.comment ?? "",
    };
  });
  const sum = weightSum(template.criteria);
  const total = Math.round(criteria.reduce((a, c) => a + c.points, 0) * 10) / 10;
  const band = gradeBand(total);
  const complete = criteria.every((c) => c.level !== null);
  const gates = hardFailGates(ctx).map((g) => ({ ...g, overridden: g.overridden || Boolean(gateOverride) }));
  const capped = gates.some((g) => !g.overridden);
  return {
    criteria,
    total,
    band,
    status: releaseStatus(total, { capped, overrideUsed: gates.some((g) => g.overridden), hasNotes: criteria.some((c) => c.comment.trim() !== "") }),
    complete,
    capped,
    gates,
    weightSum: sum,
    weightsValid: sum === 100,
  };
}

export function releaseStatus(
  total: number,
  o: { capped: boolean; overrideUsed: boolean; hasNotes: boolean },
): ReleaseStatus {
  if (o.capped) return "needs_rework";
  if (total < 70) return "needs_rework";
  if (o.overrideUsed || o.hasNotes || total < 80) return "approved_with_notes";
  return "approved";
}

export const RELEASE_LABEL: Record<ReleaseStatus, string> = {
  approved: "Approved",
  approved_with_notes: "Approved with notes",
  needs_rework: "Needs rework",
};
