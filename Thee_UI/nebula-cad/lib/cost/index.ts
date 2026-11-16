import type { MaterialKey, StageUsage } from "@/lib/schemas";

/** Real material constants, g/cm3. */
export const DENSITY_G_CM3: Record<MaterialKey, number> = {
  steel: 7.85,
  stainless: 8.0,
  aluminum: 2.7,
  titanium: 4.43,
};

export const MATERIAL_LABEL: Record<MaterialKey, string> = {
  steel: "Carbon steel",
  stainless: "Stainless steel",
  aluminum: "Aluminum",
  titanium: "Titanium",
};

/** A. Pipeline (AI + compute) rates. Every value is an editable assumption. */
export interface PipelineRates {
  inputPerMTok: number;
  outputPerMTok: number;
  perVisionCall: number;
  computePerHour: number;
  /** false until the user confirms the rates against current provider pricing */
  confirmed: boolean;
}

export const DEFAULT_PIPELINE_RATES: PipelineRates = {
  inputPerMTok: 3,
  outputPerMTok: 15,
  perVisionCall: 0.005,
  computePerHour: 1.2,
  confirmed: false,
};

export interface UsageCost {
  tokensIn: number;
  tokensOut: number;
  vision: number;
  compute: number;
  total: number;
}

export function usageCost(u: StageUsage, r: PipelineRates): UsageCost {
  const tokensIn = (u.inputTokens / 1_000_000) * r.inputPerMTok;
  const tokensOut = (u.outputTokens / 1_000_000) * r.outputPerMTok;
  const vision = u.visionCalls * r.perVisionCall;
  const compute = (u.computeSeconds / 3600) * r.computePerHour;
  return { tokensIn, tokensOut, vision, compute, total: tokensIn + tokensOut + vision + compute };
}

export function sumUsage(list: StageUsage[]): StageUsage {
  return list.reduce(
    (a, u) => ({
      inputTokens: a.inputTokens + u.inputTokens,
      outputTokens: a.outputTokens + u.outputTokens,
      visionCalls: a.visionCalls + u.visionCalls,
      computeSeconds: a.computeSeconds + u.computeSeconds,
    }),
    { inputTokens: 0, outputTokens: 0, visionCalls: 0, computeSeconds: 0 },
  );
}

export interface RunCost {
  stages: { key: string; label: string; usage: StageUsage; retries: number; cost: UsageCost }[];
  usage: StageUsage;
  perPart: number;
  perBatch: number;
}

export function runCost(
  stages: { key: string; label: string; usage: StageUsage; retries: number }[],
  rates: PipelineRates,
  batchSize = 1,
): RunCost {
  const rows = stages.map((s) => ({ ...s, cost: usageCost(s.usage, rates) }));
  const perPart = rows.reduce((a, s) => a + s.cost.total, 0);
  return { stages: rows, usage: sumUsage(stages.map((s) => s.usage)), perPart, perBatch: perPart * Math.max(1, batchSize) };
}

export type BudgetState = "none" | "ok" | "warning" | "exceeded";

/** Guardrail: warning from 80% of the budget, exceeded at 100%. A budget of 0 or less means "no budget set". */
export function budgetState(spent: number, budget: number): BudgetState {
  if (!(budget > 0)) return "none";
  if (spent >= budget) return "exceeded";
  if (spent >= 0.8 * budget) return "warning";
  return "ok";
}

/** B. Manufacturing estimate. All dollar figures and rates are editable assumptions. */
export interface MfgRates {
  pricePerKg: Record<MaterialKey, number>;
  /** fraction, e.g. 0.15 = 15% extra stock */
  stockAllowance: number;
  /** fraction */
  scrapPct: number;
  mrrCm3PerMin: Record<MaterialKey, number>;
  tHoleMin: number;
  tFeatureMin: number;
  machineRatePerHour: number;
  setupCost: number;
  finishing: number;
  inspection: number;
  /** fraction */
  overhead: number;
  /** fraction */
  margin: number;
}

export const DEFAULT_MFG_RATES: MfgRates = {
  pricePerKg: { steel: 1.8, stainless: 5.5, aluminum: 4.2, titanium: 38 },
  stockAllowance: 0.15,
  scrapPct: 0.05,
  mrrCm3PerMin: { steel: 12, stainless: 8, aluminum: 40, titanium: 4 },
  tHoleMin: 0.5,
  tFeatureMin: 1.5,
  machineRatePerHour: 85,
  setupCost: 120,
  finishing: 6,
  inspection: 8,
  overhead: 0.2,
  margin: 0.15,
};

export interface MfgInputs {
  material: MaterialKey;
  partVolumeCm3: number;
  stockVolumeCm3: number;
  holes: number;
  features: number;
}

/** material_cost = part_volume_cm3 * (1 + stock_allowance) * density_g_cm3 / 1000 * price_per_kg * (1 + scrap_pct) */
export function materialCost(i: MfgInputs, r: MfgRates): number {
  return (
    ((i.partVolumeCm3 * (1 + r.stockAllowance) * DENSITY_G_CM3[i.material]) / 1000) *
    r.pricePerKg[i.material] *
    (1 + r.scrapPct)
  );
}

/** machining_min = (stock_volume_cm3 - part_volume_cm3) / mrr_cm3_per_min + holes * t_hole_min + features * t_feature_min */
export function machiningMinutes(i: MfgInputs, r: MfgRates): number {
  const removed = Math.max(0, i.stockVolumeCm3 - i.partVolumeCm3);
  return removed / r.mrrCm3PerMin[i.material] + i.holes * r.tHoleMin + i.features * r.tFeatureMin;
}

export interface UnitCostBreakdown {
  qty: number;
  material: number;
  machiningMin: number;
  machining: number;
  setupPerUnit: number;
  finishing: number;
  inspection: number;
  subtotal: number;
  overhead: number;
  margin: number;
  unitCost: number;
  total: number;
}

/**
 * unit_cost = (material_cost + machining_min / 60 * machine_rate + setup_cost / qty + finishing + inspection)
 *             * (1 + overhead) * (1 + margin)
 */
export function unitCost(i: MfgInputs, r: MfgRates, qty: number): UnitCostBreakdown {
  const q = Math.max(1, Math.floor(qty));
  const material = materialCost(i, r);
  const machiningMin = machiningMinutes(i, r);
  const machining = (machiningMin / 60) * r.machineRatePerHour;
  const setupPerUnit = r.setupCost / q;
  const subtotal = material + machining + setupPerUnit + r.finishing + r.inspection;
  const withOverhead = subtotal * (1 + r.overhead);
  const unit = withOverhead * (1 + r.margin);
  return {
    qty: q,
    material,
    machiningMin,
    machining,
    setupPerUnit,
    finishing: r.finishing,
    inspection: r.inspection,
    subtotal,
    overhead: withOverhead - subtotal,
    margin: unit - withOverhead,
    unitCost: unit,
    total: unit * q,
  };
}

export const QUANTITY_BREAKS = [1, 10, 100] as const;

export function quantityBreaks(i: MfgInputs, r: MfgRates, qtys: readonly number[] = QUANTITY_BREAKS) {
  return qtys.map((q) => unitCost(i, r, q));
}

export function partMassKg(volumeCm3: number, material: MaterialKey): number {
  return (volumeCm3 * DENSITY_G_CM3[material]) / 1000;
}

/** C. Automation ROI. */
export interface RoiAssumptions {
  manualRebuildHours: number;
  reviewMinutes: number;
  laborRatePerHour: number;
  partsPerMonth: number;
}

export const DEFAULT_ROI: RoiAssumptions = {
  manualRebuildHours: 3,
  reviewMinutes: 20,
  laborRatePerHour: 65,
  partsPerMonth: 40,
};

export interface RoiResult {
  manualCost: number;
  automatedCost: number;
  reviewCost: number;
  savingsPerPart: number;
  savingsPct: number;
  /** cumulative savings after n parts, n = 0..months*partsPerMonth sampled monthly */
  cumulative: { month: number; parts: number; manual: number; automated: number; savings: number }[];
}

export function roi(pipelineCostPerPart: number, a: RoiAssumptions, months = 12): RoiResult {
  const manualCost = a.manualRebuildHours * a.laborRatePerHour;
  const reviewCost = (a.reviewMinutes / 60) * a.laborRatePerHour;
  const automatedCost = pipelineCostPerPart + reviewCost;
  const savingsPerPart = manualCost - automatedCost;
  const cumulative = Array.from({ length: months + 1 }, (_, m) => {
    const parts = m * a.partsPerMonth;
    return { month: m, parts, manual: parts * manualCost, automated: parts * automatedCost, savings: parts * savingsPerPart };
  });
  return {
    manualCost,
    automatedCost,
    reviewCost,
    savingsPerPart,
    savingsPct: manualCost > 0 ? savingsPerPart / manualCost : 0,
    cumulative,
  };
}

export function formatUsd(v: number, digits?: number): string {
  const d = digits ?? (Math.abs(v) < 1 ? 4 : 2);
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
}
