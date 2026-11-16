import { describe, expect, it } from "vitest";
import { DEFAULT_MFG_RATES, DEFAULT_PIPELINE_RATES, DENSITY_G_CM3, budgetState, machiningMinutes, materialCost, quantityBreaks, roi, runCost, unitCost, usageCost, type MfgInputs } from "@/lib/cost";

const inputs: MfgInputs = { material: "steel", partVolumeCm3: 200, stockVolumeCm3: 400, holes: 9, features: 2 };
const r = DEFAULT_MFG_RATES;

describe("densities", () => {
  it("are the real constants", () => {
    expect(DENSITY_G_CM3).toEqual({ steel: 7.85, stainless: 8.0, aluminum: 2.7, titanium: 4.43 });
  });
});

describe("pipeline run cost", () => {
  it("prices tokens, vision calls and compute", () => {
    const c = usageCost({ inputTokens: 1_000_000, outputTokens: 500_000, visionCalls: 4, computeSeconds: 1800 }, DEFAULT_PIPELINE_RATES);
    expect(c.tokensIn).toBeCloseTo(3);
    expect(c.tokensOut).toBeCloseTo(7.5);
    expect(c.vision).toBeCloseTo(0.02);
    expect(c.compute).toBeCloseTo(0.6);
    expect(c.total).toBeCloseTo(11.12);
  });
  it("sums stages and scales to a batch", () => {
    const u = { inputTokens: 1000, outputTokens: 1000, visionCalls: 0, computeSeconds: 0 };
    const rc = runCost([{ key: "a", label: "A", usage: u, retries: 0 }, { key: "b", label: "B", usage: u, retries: 1 }], DEFAULT_PIPELINE_RATES, 10);
    expect(rc.perPart).toBeCloseTo(2 * (0.003 + 0.015));
    expect(rc.perBatch).toBeCloseTo(rc.perPart * 10);
    expect(rc.usage.inputTokens).toBe(2000);
  });
  it("budget guardrail warns at 80% and trips at 100%", () => {
    expect(budgetState(5, 0)).toBe("none");
    expect(budgetState(7.9, 10)).toBe("ok");
    expect(budgetState(8, 10)).toBe("warning");
    expect(budgetState(10, 10)).toBe("exceeded");
  });
});

describe("manufacturing estimate", () => {
  it("material_cost follows the formula", () => {
    // 200 * 1.15 * 7.85 / 1000 * 1.8 * 1.05
    expect(materialCost(inputs, r)).toBeCloseTo(3.412395, 5);
  });
  it("machining_min follows the formula", () => {
    // (400 - 200) / 12 + 9 * 0.5 + 2 * 1.5
    expect(machiningMinutes(inputs, r)).toBeCloseTo(24.1666667, 5);
  });
  it("never removes negative material", () => {
    expect(machiningMinutes({ ...inputs, stockVolumeCm3: 100 }, r)).toBeCloseTo(9 * 0.5 + 2 * 1.5);
  });
  it("unit_cost follows the formula", () => {
    const u = unitCost(inputs, r, 1);
    const expected = (3.412395 + (24.1666667 / 60) * 85 + 120 / 1 + 6 + 8) * 1.2 * 1.15;
    expect(u.unitCost).toBeCloseTo(expected, 4);
    expect(u.material + u.machining + u.setupPerUnit + u.finishing + u.inspection + u.overhead + u.margin).toBeCloseTo(u.unitCost, 6);
  });
  it("amortizes setup across quantity breaks 1, 10, 100", () => {
    const b = quantityBreaks(inputs, r);
    expect(b.map((x) => x.qty)).toEqual([1, 10, 100]);
    expect(b[0].setupPerUnit).toBe(120);
    expect(b[1].setupPerUnit).toBe(12);
    expect(b[2].setupPerUnit).toBeCloseTo(1.2);
    expect(b[0].unitCost).toBeGreaterThan(b[1].unitCost);
    expect(b[1].unitCost).toBeGreaterThan(b[2].unitCost);
    expect(b[2].total).toBeCloseTo(b[2].unitCost * 100);
  });
  it("treats a quantity below 1 as 1", () => {
    expect(unitCost(inputs, r, 0).qty).toBe(1);
  });
});

describe("automation ROI", () => {
  it("compares manual rebuild with pipeline plus review", () => {
    const x = roi(0.5, { manualRebuildHours: 3, reviewMinutes: 30, laborRatePerHour: 60, partsPerMonth: 10 }, 12);
    expect(x.manualCost).toBe(180);
    expect(x.automatedCost).toBeCloseTo(30.5);
    expect(x.savingsPerPart).toBeCloseTo(149.5);
    expect(x.cumulative).toHaveLength(13);
    expect(x.cumulative[12].parts).toBe(120);
    expect(x.cumulative[12].savings).toBeCloseTo(149.5 * 120);
  });
  it("reports a loss when automation costs more", () => {
    expect(roi(500, { manualRebuildHours: 1, reviewMinutes: 60, laborRatePerHour: 50, partsPerMonth: 1 }).savingsPerPart).toBeLessThan(0);
  });
});
