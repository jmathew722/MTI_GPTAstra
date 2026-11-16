"use client";

import * as React from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { RotateCcw, Save } from "lucide-react";
import { DemoTag, Field, Glass, PageHeader, SampleBadge, Segmented, Stamp } from "@/components/shared";
import { API_BASE_URL, API_MODE, IS_MOCK } from "@/lib/api";
import { useResetSampleData } from "@/lib/api/hooks";
import { DENSITY_G_CM3, MATERIAL_LABEL, type MfgRates, type PipelineRates } from "@/lib/cost";
import type { MaterialKey } from "@/lib/schemas";
import { useSettings } from "@/lib/store";

const MATERIALS = Object.keys(MATERIAL_LABEL) as MaterialKey[];

interface RatesForm {
  pipeline: Omit<PipelineRates, "confirmed">;
  mfg: MfgRates;
  monthlyBudget: number;
}

function Section({ id, title, children, tag }: { id: string; title: string; children: React.ReactNode; tag?: React.ReactNode }) {
  return (
    <Glass flat as="section" id={id} className="scroll-mt-24 p-5" aria-label={title}>
      <div className="mb-4 flex items-center gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        {tag}
      </div>
      {children}
    </Glass>
  );
}

function Num({ label, hint, error, ...rest }: { label: string; hint?: string; error?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <Field label={label} hint={error ? <span className="text-danger">{error}</span> : hint}>
      <input type="number" step="any" className="field num" aria-invalid={Boolean(error)} {...rest} />
    </Field>
  );
}

export default function SettingsPage() {
  const s = useSettings();
  const reset = useResetSampleData();
  const { register, handleSubmit, reset: resetForm, formState } = useForm<RatesForm>({
    defaultValues: { pipeline: s.pipelineRates, mfg: s.mfgRates, monthlyBudget: s.monthlyBudget },
  });
  const num = { valueAsNumber: true, min: { value: 0, message: "Must be 0 or more" }, validate: (v: number) => Number.isFinite(v) || "Enter a number" };
  const e = formState.errors;
  const onSave = handleSubmit((v) => {
    s.set({ pipelineRates: { ...v.pipeline, confirmed: s.pipelineRates.confirmed }, mfgRates: v.mfg, monthlyBudget: v.monthlyBudget });
    resetForm(v);
    toast.success("Rates saved.");
  });

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <PageHeader title="Settings" description="Preferences are stored in this browser. No secret is ever stored client-side: model-provider keys live on the pipeline backend." />

      <Section id="reviewer" title="Reviewer">
        <Field label="Your name" hint="Recorded on approvals, overrides and sign-offs. Sample-data mode has no login, so this is taken on trust." className="max-w-sm">
          <input className="field" value={s.reviewerName} onChange={(ev) => s.set({ reviewerName: ev.target.value })} />
        </Field>
      </Section>

      <Section id="display" title="Display and defaults">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Units">
            <select className="field" value={s.units} onChange={(ev) => s.set({ units: ev.target.value as "mm" | "in" })}>
              <option value="mm">Millimeters</option>
              <option value="in">Inches</option>
            </select>
          </Field>
          <Field label="Default material">
            <select className="field" value={s.defaultMaterial} onChange={(ev) => s.set({ defaultMaterial: ev.target.value as MaterialKey })}>
              {MATERIALS.map((m) => <option key={m} value={m}>{MATERIAL_LABEL[m]} · {DENSITY_G_CM3[m].toFixed(2)} g/cm³</option>)}
            </select>
          </Field>
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Density</span>
            <Segmented label="Density" value={s.density} onChange={(v) => s.set({ density: v })} options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} className="self-start" />
            <span className="text-[11px] text-faint">Compact tightens table rows and card padding.</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Motion intensity</span>
            <Segmented label="Motion intensity" value={s.motion} onChange={(v) => s.set({ motion: v })} options={[{ value: "full", label: "Full" }, { value: "reduced", label: "Reduced" }]} className="self-start" />
            <span className="text-[11px] text-faint">Reduced turns off ambient and entrance animation. Your system&apos;s reduced-motion setting is always honored.</span>
          </div>
        </div>
      </Section>

      <form onSubmit={onSave} className="flex flex-col gap-4">
        <Section id="rates" title="Pipeline cost rates" tag={s.pipelineRates.confirmed ? <Stamp tone="success">Verified by you</Stamp> : <Stamp tone="warn">Assumption</Stamp>}>
          {!s.pipelineRates.confirmed && (
            <p className="mb-3 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-[13px] leading-5 text-[#ffd4ab]">
              ASSUMPTION: verify against current provider pricing. These are seed values, not quotes.
            </p>
          )}
          <div className="grid gap-4 sm:grid-cols-4">
            <Num label="Input, $ per 1M tokens" error={e.pipeline?.inputPerMTok?.message} {...register("pipeline.inputPerMTok", num)} />
            <Num label="Output, $ per 1M tokens" error={e.pipeline?.outputPerMTok?.message} {...register("pipeline.outputPerMTok", num)} />
            <Num label="$ per vision call" error={e.pipeline?.perVisionCall?.message} {...register("pipeline.perVisionCall", num)} />
            <Num label="Compute, $ per hour" error={e.pipeline?.computePerHour?.message} {...register("pipeline.computePerHour", num)} />
          </div>
          <label className="mt-3 flex items-center gap-2 text-[13px]">
            <input type="checkbox" className="size-4 accent-[#D6AF6B]" checked={s.pipelineRates.confirmed} onChange={(ev) => s.set({ pipelineRates: { ...s.pipelineRates, confirmed: ev.target.checked } })} />
            I have verified these rates against current provider pricing
          </label>
          <div className="mt-4 max-w-xs">
            <Num label="Monthly budget, $" hint="0 turns the guardrail off. A warning shows from 80%." error={e.monthlyBudget?.message} {...register("monthlyBudget", num)} />
          </div>
        </Section>

        <Section id="mfg" title="Manufacturing estimate rates" tag={<Stamp tone="warn">Estimate</Stamp>}>
          <div className="overflow-x-auto">
            <table className="dtable min-w-[520px]">
              <thead>
                <tr><th>Material</th><th className="r">Density g/cm³</th><th className="r">Price $/kg</th><th className="r">Removal rate cm³/min</th></tr>
              </thead>
              <tbody>
                {MATERIALS.map((m) => (
                  <tr key={m}>
                    <td className="font-medium">{MATERIAL_LABEL[m]}</td>
                    <td className="num r text-muted-foreground" title="Physical constant, not editable">{DENSITY_G_CM3[m].toFixed(2)}</td>
                    <td className="r"><input type="number" step="any" aria-label={`${MATERIAL_LABEL[m]} price per kg`} className="field field-sm num ml-auto w-24 text-right" {...register(`mfg.pricePerKg.${m}`, num)} /></td>
                    <td className="r"><input type="number" step="any" aria-label={`${MATERIAL_LABEL[m]} removal rate`} className="field field-sm num ml-auto w-24 text-right" {...register(`mfg.mrrCm3PerMin.${m}`, { ...num, min: { value: 0.01, message: "Must be above 0" } })} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-4">
            <Num label="Stock allowance (fraction)" hint="0.15 = 15%" {...register("mfg.stockAllowance", num)} />
            <Num label="Scrap (fraction)" {...register("mfg.scrapPct", num)} />
            <Num label="Minutes per hole" {...register("mfg.tHoleMin", num)} />
            <Num label="Minutes per feature" {...register("mfg.tFeatureMin", num)} />
            <Num label="Machine rate, $/h" {...register("mfg.machineRatePerHour", num)} />
            <Num label="Setup cost, $" {...register("mfg.setupCost", num)} />
            <Num label="Finishing, $/unit" {...register("mfg.finishing", num)} />
            <Num label="Inspection, $/unit" {...register("mfg.inspection", num)} />
            <Num label="Overhead (fraction)" {...register("mfg.overhead", num)} />
            <Num label="Margin (fraction)" {...register("mfg.margin", num)} />
          </div>
        </Section>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {formState.isDirty && <span className="text-xs text-warn">Unsaved changes</span>}
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              s.resetRates();
              const st = useSettings.getState();
              resetForm({ pipeline: st.pipelineRates, mfg: st.mfgRates, monthlyBudget: st.monthlyBudget });
              toast.success("Rates reset to the seed assumptions.");
            }}
          >
            <RotateCcw className="size-4" aria-hidden /> Reset to seed values
          </button>
          <button type="submit" className="btn btn-primary" disabled={!formState.isDirty}>
            <Save className="size-4" aria-hidden /> Save rates
          </button>
        </div>
      </form>

      <Section id="rubric" title="Rubric defaults">
        <p className="text-[13px] leading-5 text-muted-foreground">
          New projects use the built-in “MTI default part rubric”. Manage and duplicate templates in the <Link href="/library" className="text-gold underline">Library</Link>; pick a template per project in its Rubric tab.
        </p>
      </Section>

      <Section id="api" title="Pipeline connection" tag={IS_MOCK ? <SampleBadge label="Sample data mode" /> : <Stamp tone="gold">Live</Stamp>}>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-[13px]">
          <dt className="text-muted-foreground">Mode</dt>
          <dd className="num">{API_MODE}</dd>
          <dt className="text-muted-foreground">API base URL</dt>
          <dd className="num break-all">{API_BASE_URL || "not set"}</dd>
        </dl>
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          These are build-time settings. Put <span className="num text-text">NEXT_PUBLIC_API_MODE=http</span> and <span className="num text-text">NEXT_PUBLIC_API_BASE_URL=…</span> in <span className="num text-text">.env.local</span> and restart the app. The URL is not a secret; credentials never belong in the browser.
        </p>
      </Section>

      {IS_MOCK && (
        <Section id="sample" title="Sample data" tag={<DemoTag title="Only available in sample-data mode" />}>
          <p className="mb-3 text-[13px] leading-5 text-muted-foreground">Restores the three seeded projects and removes every review, override, sign-off, comment and run you made in this browser.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn btn-danger" onClick={() => reset.mutate()} disabled={reset.isPending}>Reset sample data</button>
            <button type="button" className="btn btn-ghost" onClick={() => { s.set({ tourDone: false }); toast.success("The tour will show on the next page load."); }}>Replay the onboarding tour</button>
          </div>
        </Section>
      )}
    </div>
  );
}
