import type { CountCheck, ExtractionResult, ValidationCheck } from "@/lib/schemas";

export interface ValidationSummary {
  total: number;
  passed: number;
  failed: number;
  warning: number;
  notRun: number;
  /** passed / checks that actually ran; null when nothing ran */
  passRate: number | null;
}

export function summarize(checks: ValidationCheck[]): ValidationSummary {
  const s = { total: checks.length, passed: 0, failed: 0, warning: 0, notRun: 0 };
  for (const c of checks) {
    if (c.status === "passed") s.passed++;
    else if (c.status === "failed") s.failed++;
    else if (c.status === "warning") s.warning++;
    else s.notRun++;
  }
  const ran = s.total - s.notRun;
  return { ...s, passRate: ran > 0 ? s.passed / ran : null };
}

export interface GateReason {
  checkId: string;
  label: string;
  kind: "failed" | "not_run";
  text: string;
  overridden: boolean;
}

export interface ExportGate {
  blocked: boolean;
  reasons: GateReason[];
  /** reasons that still block (not overridden) */
  open: GateReason[];
}

/**
 * Export is blocked while any CRITICAL check has failed, or has not run, without a recorded override.
 * A not-run critical check blocks too: an unverified part is not a verified part.
 */
export function exportGate(checks: ValidationCheck[]): ExportGate {
  const reasons: GateReason[] = [];
  for (const c of checks) {
    if (c.severity !== "critical") continue;
    if (c.status === "failed") {
      reasons.push({
        checkId: c.id,
        label: c.label,
        kind: "failed",
        text: c.detail ?? `${c.label} failed${c.expected ? `: expected ${c.expected}, measured ${c.measured ?? "n/a"}` : ""}.`,
        overridden: Boolean(c.override),
      });
    } else if (c.status === "not_run") {
      reasons.push({
        checkId: c.id,
        label: c.label,
        kind: "not_run",
        text: `${c.label} has not run${c.detail ? `: ${c.detail}` : "."}`,
        overridden: Boolean(c.override),
      });
    }
  }
  const open = reasons.filter((r) => !r.overridden);
  return { blocked: open.length > 0, reasons, open };
}

export function countMismatches(extraction: ExtractionResult | undefined | null): CountCheck[] {
  if (!extraction) return [];
  return extraction.countChecks.filter((c) => {
    const values = [c.drawingCount, c.extractedCount, c.modeledCount].filter((v): v is number => v !== null);
    return new Set(values).size > 1;
  });
}

/** One plain sentence with the numbers, for banners. */
export function mismatchSentence(c: CountCheck): string {
  const parts: string[] = [];
  if (c.drawingCount !== null) parts.push(`Drawing calls out ${c.drawingCount} ${c.feature.toLowerCase()}.`);
  parts.push(`Extraction found ${c.extractedCount}.`);
  if (c.modeledCount !== null) parts.push(`Model has ${c.modeledCount}.`);
  return parts.join(" ");
}

export type ConfidenceBand = "high" | "medium" | "low";
export function confidenceBand(c: number): ConfidenceBand {
  if (c >= 0.9) return "high";
  if (c >= 0.75) return "medium";
  return "low";
}

const STATUS_RANK = { conflict: 0, needs_review: 1, verified: 2 } as const;
/** Reviewer queue order: conflict, then needs review, then verified; lowest confidence first inside a group. */
export function riskOrder<T extends { status: keyof typeof STATUS_RANK; confidence: number; critical?: boolean }>(items: T[]): T[] {
  return [...items].sort(
    (a, b) =>
      STATUS_RANK[a.status] - STATUS_RANK[b.status] ||
      Number(b.critical ?? false) - Number(a.critical ?? false) ||
      a.confidence - b.confidence,
  );
}
