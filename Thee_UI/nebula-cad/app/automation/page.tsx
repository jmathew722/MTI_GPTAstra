"use client";

import * as React from "react";
import Link from "next/link";
import { useDropzone } from "react-dropzone";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, FileText, FolderUp, Play, Trash2, Upload } from "lucide-react";
import { PipelineCard } from "@/components/pipeline/PipelineTimeline";
import { PartGlyph } from "@/components/shell/Atmosphere";
import { DemoTag, Field, Glass, PageHeader, SampleBadge, Stamp } from "@/components/shared";
import { IS_MOCK } from "@/lib/api";
import { useRun, useStartRun } from "@/lib/api/hooks";
import { DRAWING_EXTENSIONS, MAX_FOLDER_FILES, validateUpload } from "@/lib/cad/loaders";
import { MATERIAL_LABEL, formatUsd, usageCost } from "@/lib/cost";
import { SPECS, type SampleKey } from "@/lib/data/seed";
import { fmtBytes, fmtSeconds } from "@/lib/format";
import type { MaterialKey, PipelineRun, Units } from "@/lib/schemas";
import { useSettings } from "@/lib/store";
import { cn } from "@/lib/utils";

const STEPS = ["Upload", "Options", "Estimate", "Run"] as const;
const PRESETS = {
  fast: { label: "Fast", note: "One extraction pass. Cheapest. Use for simple plates.", k: 0.7, seconds: 60 },
  standard: { label: "Standard", note: "Overview read, extraction, count cross-check, full validation.", k: 1, seconds: 81 },
  "high-accuracy": { label: "High accuracy", note: "Adds a second extraction pass and re-checks low-confidence items.", k: 1.9, seconds: 150 },
} as const;
type Preset = keyof typeof PRESETS;
/** Typical usage of one standard run (from the seeded sample runs). */
const TYPICAL = { inputTokens: 26200, outputTokens: 7600, visionCalls: 3, computeSeconds: 81.4 };

function RunLine({ run }: { run: PipelineRun }) {
  const { data } = useRun(run.id);
  const r = data ?? run;
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-lg border border-line/50 px-3 py-2 text-[13px]">
      <span className="num text-muted-foreground">{r.id}</span>
      <span className="min-w-0 flex-1 truncate font-medium">{r.projectName}</span>
      <Stamp tone={r.status === "succeeded" ? "gold" : r.status === "cancelled" ? "dashed" : r.status === "failed" ? "danger" : "violet"}>{r.status === "cancelled" ? "Not processed" : r.status}</Stamp>
      <Link href={`/projects/${r.projectId}`} className="btn btn-sm btn-ghost">Open</Link>
    </li>
  );
}

export default function AutomationPage() {
  const settings = useSettings();
  const start = useStartRun();
  const [step, setStep] = React.useState(0);
  const [files, setFiles] = React.useState<File[]>([]);
  const [errors, setErrors] = React.useState<string[]>([]);
  const [sample, setSample] = React.useState<SampleKey | null>(null);
  const [name, setName] = React.useState("");
  const [material, setMaterial] = React.useState<MaterialKey>(settings.defaultMaterial);
  const [units, setUnits] = React.useState<Units>(settings.units);
  const [preset, setPreset] = React.useState<Preset>("standard");
  const [runs, setRuns] = React.useState<PipelineRun[]>([]);
  const folder = React.useRef<HTMLInputElement>(null);

  const add = React.useCallback((incoming: File[]) => {
    const errs: string[] = [];
    const ok: File[] = [];
    for (const f of incoming.slice(0, MAX_FOLDER_FILES)) {
      if (f.name.startsWith(".")) continue;
      const bad = validateUpload(f, DRAWING_EXTENSIONS);
      if (bad) errs.push(bad);
      else ok.push(f);
    }
    if (incoming.length > MAX_FOLDER_FILES) errs.push(`Only the first ${MAX_FOLDER_FILES} files were considered.`);
    setErrors(errs);
    if (ok.length) {
      setSample(null);
      setFiles((prev) => [...prev, ...ok.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))]);
    }
  }, []);
  const dz = useDropzone({ onDrop: add, multiple: true, noClick: true, noKeyboard: true });

  const count = sample ? 1 : files.length;
  const p = PRESETS[preset];
  const per = usageCost({ ...TYPICAL, inputTokens: TYPICAL.inputTokens * p.k, outputTokens: TYPICAL.outputTokens * p.k, computeSeconds: p.seconds }, settings.pipelineRates).total;
  const canNext = step === 0 ? count > 0 : true;
  const single = runs.length === 1 ? runs[0] : null;

  const launch = async () => {
    const made: PipelineRun[] = [];
    if (sample) made.push(await start.mutateAsync({ input: { name: name.trim() || SPECS[sample].name, material, units, preset, sampleKey: sample }, files: [] }));
    else
      for (const f of files)
        made.push(await start.mutateAsync({ input: { name: files.length === 1 && name.trim() ? name.trim() : f.name.replace(/\.[^.]+$/, ""), material, units, preset }, files: [f] }));
    setRuns(made);
    setStep(3);
  };

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <PageHeader eyebrow="Automation" title="New run" description="Upload one drawing, many drawings or a whole folder. You see the estimated cost and time before anything runs." />
      <ol className="glass-flat flex items-center gap-1 p-2" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s} className="flex flex-1 items-center gap-2">
            <span
              aria-current={i === step ? "step" : undefined}
              className={cn("flex h-9 flex-1 items-center gap-2 rounded-[10px] px-3 text-sm font-medium", i === step ? "border border-gold/50 bg-gold/10 text-gold-hi" : i < step ? "text-text" : "text-muted-foreground")}
            >
              <span className={cn("num grid size-5 place-items-center rounded-full text-[11px] font-bold", i < step ? "bg-gold text-on-gold" : "border border-current")}>{i < step ? <Check className="size-3" strokeWidth={3} aria-hidden /> : i + 1}</span>
              <span className="hidden sm:inline">{s}</span>
            </span>
          </li>
        ))}
      </ol>

      {step === 0 && (
        <Glass className="flex flex-col gap-4 p-5">
          <div
            {...dz.getRootProps()}
            className={cn("flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors", dz.isDragActive ? "border-gold bg-gold/10" : "border-line bg-bg/40")}
          >
            <input {...dz.getInputProps()} aria-label="Drawing files" />
            <Upload className="size-8 text-gold" aria-hidden />
            <p className="text-base font-semibold">Drop drawings or a folder here</p>
            <p className="max-w-[52ch] text-[13px] text-muted-foreground">
              PDF, PNG, JPG, DXF or DWG. Up to 50 MB per file and {MAX_FOLDER_FILES} files per folder. Files are read in your browser; nothing is uploaded until you start the run.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              <button type="button" className="btn btn-outline" onClick={dz.open}>
                <FileText className="size-4" aria-hidden /> Choose files
              </button>
              <button type="button" className="btn btn-outline" onClick={() => folder.current?.click()}>
                <FolderUp className="size-4" aria-hidden /> Choose a folder
              </button>
              <input
                ref={folder}
                type="file"
                multiple
                className="sr-only"
                tabIndex={-1}
                aria-label="Drawing folder"
                {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
                onChange={(e) => {
                  add(Array.from(e.target.files ?? []));
                  e.target.value = "";
                }}
              />
            </div>
          </div>
          {errors.length > 0 && (
            <ul role="alert" className="rounded-xl border border-danger/50 bg-danger/10 p-3 text-[13px] leading-5 text-[#ffc2cd]">
              {errors.map((e) => <li key={e}>{e}</li>)}
            </ul>
          )}
          {files.length > 0 && (
            <ul className="flex flex-col gap-1.5" aria-label="Selected drawings">
              {files.map((f) => (
                <li key={`${f.name}-${f.size}`} className="flex items-center gap-3 rounded-lg border border-line/50 px-3 py-2">
                  <FileText className="size-4 text-gold" aria-hidden />
                  <span className="num min-w-0 flex-1 truncate text-[13px]">{(f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name}</span>
                  <span className="num text-xs text-muted-foreground">{fmtBytes(f.size)}</span>
                  <button type="button" className="btn btn-icon btn-sm btn-quiet" aria-label={`Remove ${f.name}`} onClick={() => setFiles((prev) => prev.filter((x) => x !== f))}>
                    <Trash2 className="size-3.5" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div>
            <div className="mb-2 flex items-center gap-2">
              <span className="eyebrow">Or use a sample drawing</span> <SampleBadge />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              {(Object.keys(SPECS) as SampleKey[]).map((k) => (
                <button
                  key={k}
                  type="button"
                  aria-pressed={sample === k}
                  onClick={() => {
                    setSample(sample === k ? null : k);
                    setFiles([]);
                  }}
                  className={cn("glass-raised lift flex items-center gap-3 p-3 text-left", sample === k && "glass-active")}
                >
                  <PartGlyph specKey={k} modeled={false} className="size-12 shrink-0" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{SPECS[k].name}</span>
                    <span className="num block text-xs text-muted-foreground">{SPECS[k].partNumber} · synthetic PDF</span>
                    {k === "flange" && <span className="mt-0.5 block text-[11px] text-warn">Reproduces the 10-vs-8 hole failure</span>}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </Glass>
      )}

      {step === 1 && (
        <Glass className="grid gap-4 p-5 sm:grid-cols-2">
          <Field label="Project name" hint={count > 1 ? "With several drawings, each project takes its file name." : undefined}>
            <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder={sample ? SPECS[sample].name : files[0]?.name.replace(/\.[^.]+$/, "") ?? "Part name"} disabled={count > 1} />
          </Field>
          <Field label="Material" hint="Used for the manufacturing estimate. It does not change the geometry.">
            <select className="field" value={material} onChange={(e) => setMaterial(e.target.value as MaterialKey)}>
              {(Object.keys(MATERIAL_LABEL) as MaterialKey[]).map((m) => <option key={m} value={m}>{MATERIAL_LABEL[m]}</option>)}
            </select>
          </Field>
          <Field label="Units" hint="The pipeline keeps the drawing's units. Pick what the drawing uses.">
            <select className="field" value={units} onChange={(e) => setUnits(e.target.value as Units)}>
              <option value="mm">Millimeters</option>
              <option value="in">Inches</option>
            </select>
          </Field>
          <fieldset className="sm:col-span-2">
            <legend className="mb-1 text-xs font-medium text-muted-foreground">Pipeline preset</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              {(Object.keys(PRESETS) as Preset[]).map((k) => (
                <label key={k} className={cn("glass-raised flex cursor-pointer flex-col gap-1 p-3", preset === k && "glass-active")}>
                  <span className="flex items-center gap-2 text-sm font-semibold">
                    <input type="radio" name="preset" className="accent-[#D6AF6B]" checked={preset === k} onChange={() => setPreset(k)} />
                    {PRESETS[k].label}
                  </span>
                  <span className="text-xs leading-5 text-muted-foreground">{PRESETS[k].note}</span>
                </label>
              ))}
            </div>
          </fieldset>
        </Glass>
      )}

      {step === 2 && (
        <Glass className="flex flex-col gap-4 p-5">
          <div className="grid gap-3 sm:grid-cols-4">
            {[
              ["Drawings", String(count)],
              ["Est. cost per part", formatUsd(per, 3)],
              ["Est. batch cost", formatUsd(per * count, 2)],
              ["Est. time", fmtSeconds(p.seconds * count)],
            ].map(([k, v]) => (
              <div key={k} className="rounded-xl border border-line/50 bg-bg/40 p-3">
                <div className="text-xs text-muted-foreground">{k}</div>
                <div className="num text-xl font-semibold">{v}</div>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-[13px] leading-5">
            <div className="flex items-center gap-2 font-semibold text-warn">
              <AlertTriangle className="size-4" aria-hidden /> Estimate, built on assumptions
            </div>
            <ul className="mt-1 list-disc pl-5 text-text/90">
              <li>Usage is the typical standard run ({TYPICAL.inputTokens.toLocaleString()} input and {TYPICAL.outputTokens.toLocaleString()} output tokens, {TYPICAL.visionCalls} vision calls) scaled by the {p.label} preset (×{p.k}).</li>
              <li>Rates come from Settings{settings.pipelineRates.confirmed ? "." : " and have not been verified against current provider pricing."}</li>
              <li>Runs are processed one at a time; retries add cost and time.</li>
            </ul>
          </div>
          {IS_MOCK && (
            <div className="rounded-xl border border-violet/40 bg-violet/10 p-3 text-[13px] leading-5 text-text/90">
              <div className="mb-1 flex items-center gap-2 font-semibold"><DemoTag /> Sample-data mode</div>
              {sample
                ? "This starts a simulated run. Stage timings are simulated and the result is the seeded sample result for this drawing."
                : "No pipeline backend is connected, so your drawings will be stored for this browser session and shown in the project, but they will not be processed. Nothing is extracted or invented for them. Set NEXT_PUBLIC_API_MODE=http to run the real pipeline."}
            </div>
          )}
        </Glass>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          {single ? (
            <PipelineCard runId={single.id} title="Live progress" />
          ) : (
            <Glass className="p-5">
              <h2 className="text-base font-semibold">{runs.length} runs started</h2>
              <ul className="mt-3 flex flex-col gap-2">{runs.map((r) => <RunLine key={r.id} run={r} />)}</ul>
            </Glass>
          )}
          <div className="flex flex-wrap gap-2">
            {single && <Link href={`/projects/${single.projectId}`} className="btn btn-primary">Open project <ArrowRight className="size-4" aria-hidden /></Link>}
            <Link href="/pipelines" className="btn btn-outline">View all runs</Link>
            <button type="button" className="btn btn-ghost" onClick={() => { setStep(0); setFiles([]); setSample(null); setRuns([]); setName(""); }}>Start another</button>
          </div>
        </div>
      )}

      {step < 3 && (
        <div className="flex items-center justify-between">
          <button type="button" className="btn btn-ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>
            <ArrowLeft className="size-4" aria-hidden /> Back
          </button>
          {step < 2 ? (
            <button type="button" className="btn btn-primary" disabled={!canNext} onClick={() => setStep(step + 1)}>
              Next <ArrowRight className="size-4" aria-hidden />
            </button>
          ) : (
            <button type="button" className="btn btn-primary" disabled={start.isPending} onClick={launch}>
              <Play className="size-4 fill-current" aria-hidden /> {start.isPending ? "Starting…" : `Run ${count} drawing${count > 1 ? "s" : ""}`}
            </button>
          )}
        </div>
      )}
      {step === 0 && count === 0 && <p className="text-right text-xs text-muted-foreground">Add a drawing or pick a sample to continue.</p>}
    </div>
  );
}
