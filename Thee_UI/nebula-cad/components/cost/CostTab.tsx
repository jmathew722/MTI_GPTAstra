"use client";

import * as React from "react";
import Link from "next/link";
// DEFERRED chart imports: Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis
import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";
// DEFERRED icons: ChevronRight, Factory, TrendingUp
import { AlertTriangle, Cpu } from "lucide-react";
import { EmptyState, ErrorState, SampleBadge, Stamp, TableSkeleton } from "@/components/shared";
import { useCost, useMonthlyCost, useProject } from "@/lib/api/hooks";
// DEFERRED cost imports: DENSITY_G_CM3, MATERIAL_LABEL, machiningMinutes, partMassKg, quantityBreaks, roi, type MfgInputs
import { budgetState, formatUsd, runCost, usageCost } from "@/lib/cost";
import { AnimatedNumber } from "@/components/shared/motion";
import { fmtInt } from "@/lib/format";
// DEFERRED: import type { MaterialKey } from "@/lib/schemas";
import { useSettings } from "@/lib/store";
import { cn } from "@/lib/utils";

const tip = {
  contentStyle: { background: "#1c1530", border: "1px solid rgba(166,124,255,.4)", borderRadius: 10, fontFamily: "var(--font-jetbrains)", fontSize: 12, color: "#f7f3fa" },
  labelStyle: { color: "#aba1bd" },
  itemStyle: { color: "#f7f3fa" },
  cursor: { stroke: "rgba(214,175,107,.4)" },
};
// DEFERRED (used by the manufacturing and ROI charts): const axis = { stroke: "#7f7694", fontSize: 11, fontFamily: "var(--font-jetbrains)" };

function Panel({ icon, letter, title, tag, children }: { icon: React.ReactNode; letter: string; title: string; tag?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="glass-raised p-4" aria-label={title}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="grid size-7 place-items-center rounded-lg border border-gold/50 bg-gold/10 text-xs font-bold text-gold-hi">{letter}</span>
        <span className="text-gold [&_svg]:size-4">{icon}</span>
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="ml-auto flex items-center gap-1.5">{tag}</span>
      </div>
      {children}
    </section>
  );
}

function Num({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: string; tone?: "warn" | "danger" | "success" }) {
  return (
    <div className="rounded-lg border border-line/50 bg-bg/40 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn("num text-lg font-semibold", tone === "warn" ? "text-warn" : tone === "danger" ? "text-danger" : tone === "success" ? "text-success" : "text-text")}>{value}</div>
      {sub && <div className="num text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

export default function CostTab({ projectId }: { projectId: string }) {
  const q = useCost(projectId);
  const { data: project } = useProject(projectId);
  const { data: monthly } = useMonthlyCost();
  const rates = useSettings((s) => s.pipelineRates);
  // DEFERRED: const mfg = useSettings((s) => s.mfgRates);
  // DEFERRED: const roiA = useSettings((s) => s.roi);
  const budget = useSettings((s) => s.monthlyBudget);
  const setSettings = useSettings((s) => s.set);
  // DEFERRED: const [material, setMaterial] = React.useState<MaterialKey | null>(null);
  // DEFERRED: const [formulas, setFormulas] = React.useState(false);

  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.isLoading || !project) return <TableSkeleton />;
  if (!q.data) return <EmptyState title="No cost data" body="Run cost comes from a pipeline run, and the manufacturing estimate needs the model's volume. This project has neither yet." />;
  const c = q.data;
  const rc = runCost(c.stages, rates, c.batchSize);
  const monthTotal = monthly ? usageCost(monthly.usage, rates).total : 0;
  const bState = budgetState(monthTotal, budget);
  const trend = c.history.map((h, i) => ({ i: i + 1, date: h.date.slice(5, 10), cost: Number(usageCost(h.usage, rates).total.toFixed(4)) }));

  // DEFERRED (manufacturing estimate and ROI):
  // const inputs: MfgInputs = { material: mat, partVolumeCm3: c.partVolumeCm3, stockVolumeCm3: c.stockVolumeCm3, holes: c.holeCount, features: c.featureCount };
  // const breaks = quantityBreaks(inputs, mfg);
  // const one = breaks[0];
  // const stack = breaks.map((b) => ({
  //   qty: `qty ${b.qty}`,
  //   Material: Number(b.material.toFixed(2)),
  //   Machining: Number(b.machining.toFixed(2)),
  //   Setup: Number(b.setupPerUnit.toFixed(2)),
  //   "Finish + inspect": Number((b.finishing + b.inspection).toFixed(2)),
  //   "Overhead + margin": Number((b.overhead + b.margin).toFixed(2)),
  // }));
  // const r = roi(rc.perPart, roiA);

  return (
    <div className="flex flex-col gap-4 p-3">
      {!rates.confirmed && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-warn/50 bg-warn/10 px-3 py-2.5 text-[13px] leading-5">
          <AlertTriangle className="size-4 shrink-0 text-warn" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="font-semibold text-warn">ASSUMPTION: verify against current provider pricing.</span> The token, vision and compute rates are seed values, not quotes. Every dollar figure below depends on them.
          </span>
          <Link href="/settings#rates" className="btn btn-sm btn-ghost">Edit rates</Link>
          <button type="button" className="btn btn-sm btn-outline" onClick={() => setSettings({ pipelineRates: { ...rates, confirmed: true } })}>
            I have verified these rates
          </button>
        </div>
      )}

      {/* ---------------- A */}
      <Panel icon={<Cpu />} letter="A" title="Pipeline run cost (AI and compute)" tag={<>{c.isSample && <SampleBadge />}{!rates.confirmed && <Stamp tone="warn">Assumed rates</Stamp>}</>}>
        <div className="grid gap-4 xl:grid-cols-[1fr_300px]">
          <div className="overflow-x-auto">
            <table className="dtable min-w-[620px]">
              <thead>
                <tr>
                  <th>Stage</th>
                  <th className="r">Input tok</th>
                  <th className="r">Output tok</th>
                  <th className="r">Vision calls</th>
                  <th className="r">Retries</th>
                  <th className="r">Compute s</th>
                  <th className="r">Cost</th>
                </tr>
              </thead>
              <tbody>
                {rc.stages.map((s) => (
                  <tr key={s.key}>
                    <td className="font-medium">{s.label}</td>
                    <td className="num r">{fmtInt(s.usage.inputTokens)}</td>
                    <td className="num r">{fmtInt(s.usage.outputTokens)}</td>
                    <td className="num r">{s.usage.visionCalls}</td>
                    <td className={cn("num r", s.retries > 0 && "text-warn")}>{s.retries}</td>
                    <td className="num r">{s.usage.computeSeconds.toFixed(1)}</td>
                    <td className="num r font-semibold text-gold-hi">{formatUsd(s.cost.total, 4)}</td>
                  </tr>
                ))}
                <tr className="bg-surface-raised/30">
                  <td className="font-semibold">Run total</td>
                  <td className="num r">{fmtInt(rc.usage.inputTokens)}</td>
                  <td className="num r">{fmtInt(rc.usage.outputTokens)}</td>
                  <td className="num r">{rc.usage.visionCalls}</td>
                  <td className="num r">{rc.stages.reduce((a, s) => a + s.retries, 0)}</td>
                  <td className="num r">{rc.usage.computeSeconds.toFixed(1)}</td>
                  <td className="num r font-semibold text-gold-hi">{formatUsd(rc.perPart, 4)}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="flex flex-col gap-2">
            <div className="grid grid-cols-2 gap-2">
              <Num label="Cost per part" value={<AnimatedNumber value={rc.perPart} format={(n) => formatUsd(n, 4)} />} />
              <Num label={`Per batch (${c.batchSize})`} value={<AnimatedNumber value={rc.perBatch} format={(n) => formatUsd(n, 2)} />} />
              <Num label="Month to date" value={<AnimatedNumber value={monthTotal} format={(n) => formatUsd(n, 2)} />} sub={monthly ? `${monthly.runs} runs` : undefined} tone={bState === "exceeded" ? "danger" : bState === "warning" ? "warn" : undefined} />
              <Num label="Monthly budget" value={budget > 0 ? formatUsd(budget, 2) : "not set"} sub={budget > 0 ? `${Math.round((monthTotal / budget) * 100)}% used` : "set one in Settings"} />
            </div>
            {bState !== "none" && (
              <div className="h-1.5 overflow-hidden rounded-full bg-surface-raised" role="progressbar" aria-label="Budget used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, Math.round((monthTotal / budget) * 100))}>
                <div className={cn("h-full rounded-full", bState === "exceeded" ? "bg-danger" : bState === "warning" ? "bg-warn" : "bg-gold")} style={{ width: `${Math.min(100, (monthTotal / budget) * 100)}%` }} />
              </div>
            )}
            {(bState === "warning" || bState === "exceeded") && (
              <p role="alert" className={cn("rounded-lg px-2.5 py-1.5 text-xs leading-5", bState === "exceeded" ? "bg-danger/10 text-[#ffc2cd]" : "bg-warn/10 text-[#ffd4ab]")}>
                {bState === "exceeded" ? "Budget guardrail: this month's spend is over the budget." : "Budget guardrail: this month's spend has passed 80% of the budget."}
              </p>
            )}
            <div className="h-[92px] rounded-lg border border-line/50 bg-bg/40 p-1.5" aria-label="Cost per run trend" role="img">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trend} margin={{ top: 6, right: 6, bottom: 0, left: 6 }}>
                  <defs>
                    <linearGradient id="cost-trend" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0" stopColor="#A67CFF" stopOpacity={0.5} />
                      <stop offset="1" stopColor="#A67CFF" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Tooltip {...tip} formatter={(v) => [formatUsd(Number(v), 4), "cost per run"]} labelFormatter={(_, p) => p[0]?.payload?.date ?? ""} />
                  <Area type="monotone" dataKey="cost" stroke="#A67CFF" strokeWidth={1.6} fill="url(#cost-trend)" animationDuration={900} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <p className="text-[11px] text-faint">Trend: cost per run, last {trend.length} runs.</p>
          </div>
        </div>
      </Panel>

      {/* DEFERRED (no manufacturing scope yet): Part manufacturing estimate (B) and Automation ROI (C).
         The math stays in lib/cost and is unit-tested. To restore, uncomment this block and the lines marked DEFERRED above.
      
      <Panel icon={<Factory />} letter="B" title="Part manufacturing estimate" tag={<><Stamp tone="warn">Estimate</Stamp>{c.isSample && <SampleBadge />}</>}>
        <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
          <div>
            <div className="mb-3 flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Material</span>
                <select className="field field-sm w-52" value={mat} onChange={(e) => setMaterial(e.target.value as MaterialKey)}>
                  {(Object.keys(DENSITY_G_CM3) as MaterialKey[]).map((k) => (
                    <option key={k} value={k}>
                      {MATERIAL_LABEL[k]} · {DENSITY_G_CM3[k].toFixed(2)} g/cm³
                    </option>
                  ))}
                </select>
              </label>
              <div className="num text-xs leading-5 text-muted-foreground">
                part volume {c.partVolumeCm3.toFixed(2)} cm³ · stock {c.stockVolumeCm3.toFixed(2)} cm³ · mass {partMassKg(c.partVolumeCm3, mat).toFixed(3)} kg
                <br />
                {c.holeCount} holes · {c.featureCount} other features · machining {machiningMinutes(inputs, mfg).toFixed(1)} min
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="dtable min-w-[560px]">
                <thead>
                  <tr>
                    <th>Per unit</th>
                    {breaks.map((b) => (
                      <th key={b.qty} className="r">Qty {b.qty}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["Material", (b) => b.material],
                      ["Machining", (b) => b.machining],
                      ["Setup (amortized)", (b) => b.setupPerUnit],
                      ["Finishing", (b) => b.finishing],
                      ["Inspection", (b) => b.inspection],
                      ["Overhead", (b) => b.overhead],
                      ["Margin", (b) => b.margin],
                    ] as [string, (b: (typeof breaks)[number]) => number][]
                  ).map(([label, f]) => (
                    <tr key={label}>
                      <td>{label}</td>
                      {breaks.map((b) => (
                        <td key={b.qty} className="num r">{formatUsd(f(b), 2)}</td>
                      ))}
                    </tr>
                  ))}
                  <tr className="bg-surface-raised/30">
                    <td className="font-semibold">Unit cost</td>
                    {breaks.map((b) => (
                      <td key={b.qty} className="num r font-semibold text-gold-hi">{formatUsd(b.unitCost, 2)}</td>
                    ))}
                  </tr>
                  <tr>
                    <td className="text-muted-foreground">Order total</td>
                    {breaks.map((b) => (
                      <td key={b.qty} className="num r text-muted-foreground">{formatUsd(b.total, 2)}</td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
            <button type="button" className="btn btn-sm btn-quiet mt-2" aria-expanded={formulas} onClick={() => setFormulas((f) => !f)}>
              <ChevronRight className={cn("size-4 transition-transform", formulas && "rotate-90")} aria-hidden /> How this is calculated
            </button>
            {formulas && (
              <div className="well mt-2 overflow-x-auto p-3">
                <pre className="num text-xs leading-6 text-text/90">{`material_cost = part_volume_cm3 * (1 + stock_allowance) * density_g_cm3 / 1000 * price_per_kg * (1 + scrap_pct)
              = ${c.partVolumeCm3.toFixed(2)} * (1 + ${mfg.stockAllowance}) * ${DENSITY_G_CM3[mat]} / 1000 * ${mfg.pricePerKg[mat]} * (1 + ${mfg.scrapPct})  = ${formatUsd(one.material, 2)}

machining_min = (stock_volume_cm3 - part_volume_cm3) / mrr_cm3_per_min + holes * t_hole_min + features * t_feature_min
              = (${c.stockVolumeCm3.toFixed(2)} - ${c.partVolumeCm3.toFixed(2)}) / ${mfg.mrrCm3PerMin[mat]} + ${c.holeCount} * ${mfg.tHoleMin} + ${c.featureCount} * ${mfg.tFeatureMin}  = ${one.machiningMin.toFixed(2)} min

unit_cost     = (material_cost + machining_min / 60 * machine_rate + setup_cost / qty + finishing + inspection) * (1 + overhead) * (1 + margin)
   qty 1      = (${one.material.toFixed(2)} + ${one.machiningMin.toFixed(2)} / 60 * ${mfg.machineRatePerHour} + ${mfg.setupCost} / 1 + ${mfg.finishing} + ${mfg.inspection}) * (1 + ${mfg.overhead}) * (1 + ${mfg.margin})  = ${formatUsd(one.unitCost, 2)}`}</pre>
                <p className="mt-2 text-xs text-muted-foreground">
                  Densities are physical constants. Every price, rate and percentage is an editable assumption in <Link href="/settings#rates" className="text-gold underline">Settings</Link>.
                </p>
              </div>
            )}
          </div>
          <div className="h-[250px] rounded-lg border border-line/50 bg-bg/40 p-2" role="img" aria-label="Unit cost breakdown by quantity">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stack} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid stroke="rgba(166,124,255,.12)" vertical={false} />
                <XAxis dataKey="qty" {...axis} tickLine={false} />
                <YAxis {...axis} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v}`} />
                <Tooltip {...tip} cursor={{ fill: "rgba(166,124,255,.08)" }} formatter={(v, n) => [formatUsd(Number(v), 2), n]} />
                <Bar dataKey="Material" stackId="a" fill="#D6AF6B" animationDuration={800} />
                <Bar dataKey="Machining" stackId="a" fill="#A67CFF" animationDuration={800} />
                <Bar dataKey="Setup" stackId="a" fill="#7B5BD6" animationDuration={800} />
                <Bar dataKey="Finish + inspect" stackId="a" fill="#55DFA0" animationDuration={800} />
                <Bar dataKey="Overhead + margin" stackId="a" fill="#6E6590" radius={[4, 4, 0, 0]} animationDuration={800} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </Panel>

      
      <Panel icon={<TrendingUp />} letter="C" title="Automation ROI" tag={<Stamp tone="warn">Estimate</Stamp>}>
        <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
          <div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Num label="Manual rebuild" value={formatUsd(r.manualCost, 2)} sub={`${roiA.manualRebuildHours} h × $${roiA.laborRatePerHour}`} />
              <Num label="Automated" value={formatUsd(r.automatedCost, 2)} sub={`${formatUsd(rc.perPart, 3)} + ${roiA.reviewMinutes} min review`} />
              <Num label="Savings per part" value={formatUsd(r.savingsPerPart, 2)} sub={`${(r.savingsPct * 100).toFixed(0)}%`} tone={r.savingsPerPart >= 0 ? "success" : "danger"} />
              <Num label="12-month savings" value={formatUsd(r.cumulative[12].savings, 0)} sub={`${r.cumulative[12].parts} parts`} tone={r.savingsPerPart >= 0 ? "success" : "danger"} />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {(
                [
                  ["Manual rebuild (h)", "manualRebuildHours", 0.25],
                  ["Review time (min)", "reviewMinutes", 1],
                  ["Labor rate ($/h)", "laborRatePerHour", 1],
                  ["Parts per month", "partsPerMonth", 1],
                ] as const
              ).map(([label, key, step]) => (
                <label key={key} className="flex flex-col gap-1">
                  <span className="text-[11px] text-muted-foreground">{label}</span>
                  <input
                    type="number"
                    min={0}
                    step={step}
                    className="field field-sm num"
                    value={roiA[key]}
                    onChange={(e) => setSettings({ roi: { ...roiA, [key]: Math.max(0, Number(e.target.value) || 0) } })}
                  />
                </label>
              ))}
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              savings = manual_hours × labor_rate − (pipeline_cost + review_minutes / 60 × labor_rate). It assumes the automated part passes review. A part that needs rework costs the review time and saves nothing.
            </p>
          </div>
          <div className="h-[210px] rounded-lg border border-line/50 bg-bg/40 p-2" role="img" aria-label="Cumulative cost: manual versus automated over twelve months">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={r.cumulative} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="rgba(166,124,255,.12)" vertical={false} />
                <XAxis dataKey="month" {...axis} tickLine={false} tickFormatter={(v) => `m${v}`} />
                <YAxis {...axis} tickLine={false} axisLine={false} tickFormatter={(v) => `$${Number(v) >= 1000 ? `${(Number(v) / 1000).toFixed(0)}k` : v}`} />
                <Tooltip {...tip} formatter={(v, n) => [formatUsd(Number(v), 0), n]} labelFormatter={(v) => `month ${v}`} />
                <Line type="monotone" dataKey="manual" name="Manual" stroke="#FF9A3D" strokeWidth={2} dot={false} animationDuration={900} />
                <Line type="monotone" dataKey="automated" name="Automated" stroke="#D6AF6B" strokeWidth={2} dot={false} animationDuration={900} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </Panel>
      */}
    </div>
  );
}
