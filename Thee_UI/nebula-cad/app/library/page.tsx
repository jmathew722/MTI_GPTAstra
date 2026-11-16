"use client";

import * as React from "react";
import Link from "next/link";
import { toast } from "sonner";
import { BookMarked, Copy, Plus, Trash2 } from "lucide-react";
import { useFocusedProjectId } from "@/components/shell/Navigation";
import { EmptyState, Glass, PageHeader, RelTime, SampleBadge, Segmented, Stamp } from "@/components/shared";
import { api } from "@/lib/api";
import { useDeleteTemplate, useInvalidateAll, useParameters, useProject, useSaveTemplate, useTemplates } from "@/lib/api/hooks";
import { DENSITY_G_CM3, MATERIAL_LABEL, formatUsd } from "@/lib/cost";
import { weightSum } from "@/lib/rubric";
import type { MaterialKey } from "@/lib/schemas";
import { useSettings, type ParamPreset } from "@/lib/store";

type Tab = "presets" | "templates" | "materials" | "rates";

function Presets() {
  const presets = useSettings((s) => s.paramPresets);
  const set = useSettings((s) => s.set);
  const by = useSettings((s) => s.reviewerName);
  const id = useFocusedProjectId();
  const { data: project } = useProject(id);
  const { data: params } = useParameters(id);
  const invalidate = useInvalidateAll();
  const [busy, setBusy] = React.useState<string | null>(null);

  const saveCurrent = () => {
    if (!params?.length || !project) return;
    const p: ParamPreset = { id: `preset-${Date.now().toString(36)}`, name: `${project.name} parameters`, description: `Saved from ${project.partNumber} Rev ${project.revision}.`, values: params.map((q) => ({ name: q.name, value: q.value, unit: q.unit })) };
    set({ paramPresets: [p, ...presets] });
    toast.success("Preset saved.");
  };
  const apply = async (preset: ParamPreset) => {
    if (!id || !params) return;
    setBusy(preset.id);
    let n = 0;
    try {
      for (const v of preset.values) {
        const target = params.find((q) => q.name === v.name && q.unit === v.unit);
        if (target && target.value !== v.value) {
          await api.updateParameter(id, target.id, v.value, by);
          n++;
        }
      }
      invalidate();
      toast.success(n ? `${n} parameter${n > 1 ? "s" : ""} updated on ${project?.name}. Re-run the pipeline to rebuild.` : "Nothing to change: no matching parameter differs.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not apply the preset.");
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-[13px] text-muted-foreground">
          Presets are named sets of parameter values. Applying one edits the matching parameters of the focused project{project ? ` (${project.name})` : ""}.
        </p>
        <button type="button" className="btn btn-sm btn-outline" onClick={saveCurrent} disabled={!params?.length}>
          <Plus className="size-3.5" aria-hidden /> Save focused project&apos;s parameters
        </button>
      </div>
      {presets.length === 0 ? (
        <EmptyState icon={<BookMarked />} title="No presets" body="Save the parameters of a project you have corrected to reuse them on the next part in the family." />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {presets.map((p) => (
            <li key={p.id} className="glass-raised p-4">
              <div className="flex items-center gap-2">
                <h3 className="min-w-0 flex-1 truncate text-sm font-semibold">{p.name}</h3>
                {p.sample && <SampleBadge label="Sample" />}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">{p.description}</p>
              <dl className="num mt-2 grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 text-xs">
                {p.values.map((v) => (
                  <React.Fragment key={v.name}>
                    <dt className="font-sans text-muted-foreground">{v.name}</dt>
                    <dd>{v.value} {v.unit}</dd>
                  </React.Fragment>
                ))}
              </dl>
              <div className="mt-3 flex gap-2">
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => apply(p)} disabled={!id || busy !== null}>
                  {busy === p.id ? "Applying…" : "Apply to focused project"}
                </button>
                <button type="button" className="btn btn-icon btn-sm btn-quiet ml-auto" aria-label={`Delete preset ${p.name}`} onClick={() => set({ paramPresets: presets.filter((x) => x.id !== p.id) })}>
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Templates() {
  const { data } = useTemplates();
  const save = useSaveTemplate();
  const del = useDeleteTemplate();
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">Rubric templates set the criteria and their weights. Edit weights from a project&apos;s Rubric tab; duplicate or delete them here.</p>
      <ul className="grid gap-3 md:grid-cols-2">
        {data?.map((t) => (
          <li key={t.id} className="glass-raised p-4">
            <div className="flex items-center gap-2">
              <h3 className="min-w-0 flex-1 truncate text-sm font-semibold">{t.name}</h3>
              {t.builtIn ? <Stamp tone="muted">Built-in</Stamp> : <RelTime iso={t.updatedAt} />}
            </div>
            <ul className="mt-2 flex flex-col gap-0.5 text-xs">
              {t.criteria.map((c) => (
                <li key={c.key} className="flex justify-between gap-3">
                  <span className="text-muted-foreground">{c.label}</span>
                  <span className="num">{c.weight}</span>
                </li>
              ))}
              <li className="mt-1 flex justify-between gap-3 border-t border-line/40 pt-1 font-semibold">
                <span>Total</span>
                <span className="num">{weightSum(t.criteria)}</span>
              </li>
            </ul>
            <div className="mt-3 flex gap-2">
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => save.mutate({ ...t, id: `tpl-${Date.now().toString(36)}`, name: `${t.name} (copy)`, builtIn: false }, { onSuccess: () => toast.success("Template duplicated.") })}>
                <Copy className="size-3.5" aria-hidden /> Duplicate
              </button>
              {!t.builtIn && (
                <button type="button" className="btn btn-icon btn-sm btn-quiet ml-auto" aria-label={`Delete template ${t.name}`} onClick={() => del.mutate(t.id)}>
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Materials() {
  const mfg = useSettings((s) => s.mfgRates);
  return (
    <div className="overflow-x-auto">
      <table className="dtable min-w-[520px]">
        <thead>
          <tr><th>Material</th><th className="r">Density g/cm³</th><th className="r">Price $/kg</th><th className="r">Removal rate cm³/min</th></tr>
        </thead>
        <tbody>
          {(Object.keys(MATERIAL_LABEL) as MaterialKey[]).map((m) => (
            <tr key={m}>
              <td className="font-medium">{MATERIAL_LABEL[m]}</td>
              <td className="num r">{DENSITY_G_CM3[m].toFixed(2)}</td>
              <td className="num r">{formatUsd(mfg.pricePerKg[m], 2)}</td>
              <td className="num r">{mfg.mrrCm3PerMin[m]}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">Densities are physical constants. Prices and removal rates are ESTIMATE assumptions; edit them in <Link href="/settings#mfg" className="text-gold underline">Settings</Link>.</p>
    </div>
  );
}

function Rates() {
  const r = useSettings((s) => s.pipelineRates);
  const m = useSettings((s) => s.mfgRates);
  const rows: [string, string][] = [
    ["Input tokens", `${formatUsd(r.inputPerMTok, 2)} per 1M`],
    ["Output tokens", `${formatUsd(r.outputPerMTok, 2)} per 1M`],
    ["Vision call", formatUsd(r.perVisionCall, 4)],
    ["Compute", `${formatUsd(r.computePerHour, 2)} per hour`],
    ["Machine rate", `${formatUsd(m.machineRatePerHour, 2)} per hour`],
    ["Setup", formatUsd(m.setupCost, 2)],
    ["Finishing / inspection", `${formatUsd(m.finishing, 2)} / ${formatUsd(m.inspection, 2)} per unit`],
    ["Overhead / margin", `${(m.overhead * 100).toFixed(0)}% / ${(m.margin * 100).toFixed(0)}%`],
  ];
  return (
    <div>
      <div className="mb-3">{r.confirmed ? <Stamp tone="success">Pipeline rates verified by you</Stamp> : <Stamp tone="warn">Assumption: verify against current provider pricing</Stamp>}</div>
      <dl className="grid max-w-xl grid-cols-[1fr_auto] gap-x-6 text-[13px]">
        {rows.map(([k, v]) => (
          <React.Fragment key={k}>
            <dt className="border-b border-line/40 py-2 text-muted-foreground">{k}</dt>
            <dd className="num border-b border-line/40 py-2 text-right">{v}</dd>
          </React.Fragment>
        ))}
      </dl>
      <Link href="/settings#rates" className="btn btn-sm btn-outline mt-4">Edit the rate card</Link>
    </div>
  );
}

export default function LibraryPage() {
  const [tab, setTab] = React.useState<Tab>("presets");
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Library" description="Reusable parameter presets, rubric templates, materials and rate cards." />
      <Segmented<Tab>
        label="Library section"
        value={tab}
        onChange={setTab}
        className="self-start"
        options={[
          { value: "presets", label: "Parameter presets" },
          { value: "templates", label: "Rubric templates" },
          { value: "materials", label: "Materials" },
          { value: "rates", label: "Rate cards" },
        ]}
      />
      <Glass flat className="p-5">
        {tab === "presets" && <Presets />}
        {tab === "templates" && <Templates />}
        {tab === "materials" && <Materials />}
        {tab === "rates" && <Rates />}
      </Glass>
    </div>
  );
}
