"use client";

import * as React from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { useDropzone } from "react-dropzone";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, FileText, Folder, FolderUp, Play, Trash2, Upload } from "lucide-react";
import { PipelineCard } from "@/components/pipeline/PipelineTimeline";
import { PartGlyph } from "@/components/shell/Atmosphere";
import { DemoTag, Field, Glass, PageHeader, SampleBadge, Stamp, StatusStamp } from "@/components/shared";
import { IS_MOCK } from "@/lib/api";
import { useCancelRun, useRuns, useStartRun } from "@/lib/api/hooks";
import { groupParts } from "@/lib/cad/parts";
import { DRAWING_EXTENSIONS, MAX_FOLDER_FILES, validateUpload } from "@/lib/cad/loaders";
import { MATERIAL_LABEL, formatUsd, usageCost } from "@/lib/cost";
import { SPECS, type SampleKey } from "@/lib/data/seed";
import { fmtBytes, fmtSeconds } from "@/lib/format";
import { rowVariants } from "@/lib/motion";
import type { MaterialKey, PipelineRun, Units } from "@/lib/schemas";
import { useSettings } from "@/lib/store";
import { cn } from "@/lib/utils";

const STEPS = ["Upload", "Options", "Estimate", "Run"] as const;
const PRESETS = {
  fast: { label: "Fast", note: "One extraction pass. Lowest cost. Suitable for simple plates.", k: 0.7, seconds: 60 },
  standard: { label: "Standard", note: "Overview read, extraction, count cross-check and full validation.", k: 1, seconds: 81 },
  "high-accuracy": { label: "High accuracy", note: "Adds a second extraction pass and re-checks low-confidence items.", k: 1.9, seconds: 150 },
} as const;
type Preset = keyof typeof PRESETS;
/** Typical usage of one standard run (from the seeded sample runs). */
const TYPICAL = { inputTokens: 26200, outputTokens: 7600, visionCalls: 3, computeSeconds: 81.4 };

function BatchRow({ run, index, live }: { run: PipelineRun; index: number; live?: PipelineRun }) {
  const cancel = useCancelRun();
  const r = live ?? run;
  const done = r.stages.filter((s) => s.status === "done").length;
  const active = r.status === "running" || r.status === "queued";
  return (
    <motion.li variants={rowVariants} initial="hidden" animate="show" transition={{ delay: index * 0.05 }} className="rounded-xl border border-line/50 p-3">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <span className="num text-muted-foreground">{r.id}</span>
        <span className="min-w-0 flex-1 truncate font-medium">{r.projectName}</span>
        {r.status === "cancelled" && r.stages.every((s) => s.status === "skipped") ? <Stamp tone="dashed">Not processed</Stamp> : <StatusStamp status={r.status} />}
        {active && (
          <button type="button" className="btn btn-sm btn-quiet" onClick={() => cancel.mutate(r.id)} disabled={cancel.isPending}>
            Cancel
          </button>
        )}
        <Link href={`/projects/${r.projectId}`} className="btn btn-sm btn-ghost">Open</Link>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-raised" role="progressbar" aria-label={`${r.projectName} progress`} aria-valuemin={0} aria-valuemax={4} aria-valuenow={done}>
          <div className={cn("h-full rounded-full transition-[width] duration-500", r.status === "failed" ? "bg-danger" : "bg-gold")} style={{ width: `${(done / 4) * 100}%` }} />
        </div>
        <span className="num w-24 text-right text-xs text-muted-foreground">{r.status === "queued" ? "waiting" : `${done} of 4 stages`}</span>
      </div>
    </motion.li>
  );
}

export default function AutomationPage() {
  const settings = useSettings();
  const start = useStartRun();
  const [step, setStep] = React.useState(0);
  const [files, setFiles] = React.useState<File[]>([]);
  const [errors, setErrors] = React.useState<string[]>([]);
  const [samples, setSamples] = React.useState<SampleKey[]>([]);
  const [name, setName] = React.useState("");
  const [material, setMaterial] = React.useState<MaterialKey>(settings.defaultMaterial);
  const [units, setUnits] = React.useState<Units>(settings.units);
  const [preset, setPreset] = React.useState<Preset>("standard");
  const [runs, setRuns] = React.useState<PipelineRun[]>([]);
  const [launched, setLaunched] = React.useState(0);
  const folder = React.useRef<HTMLInputElement>(null);
  const allRuns = useRuns();

  const parts = React.useMemo(() => groupParts(files), [files]);
  const add = React.useCallback((incoming: File[]) => {
    const errs: string[] = [];
    const ok: File[] = [];
    for (const f of incoming.slice(0, MAX_FOLDER_FILES)) {
      if (f.name.startsWith(".")) continue; // hidden files such as .DS_Store
      const bad = validateUpload(f, DRAWING_EXTENSIONS);
      if (bad) errs.push(bad);
      else ok.push(f);
    }
    if (incoming.length > MAX_FOLDER_FILES) errs.push(`Only the first ${MAX_FOLDER_FILES} files were considered.`);
    setErrors(errs);
    if (ok.length) {
      setSamples([]);
      setFiles((prev) => [...prev, ...ok.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size && (p as File & { webkitRelativePath?: string }).webkitRelativePath === (f as File & { webkitRelativePath?: string }).webkitRelativePath))]);
    }
  }, []);
  const dz = useDropzone({ onDrop: add, multiple: true, noClick: true, noKeyboard: true });

  const count = samples.length || parts.length;
  const p = PRESETS[preset];
  const per = usageCost({ ...TYPICAL, inputTokens: TYPICAL.inputTokens * p.k, outputTokens: TYPICAL.outputTokens * p.k, computeSeconds: p.seconds }, settings.pipelineRates).total;
  const live = new Map((allRuns.data ?? []).map((r) => [r.id, r]));
  const finished = runs.filter((r) => {
    const s = live.get(r.id)?.status ?? r.status;
    return s !== "running" && s !== "queued";
  }).length;
  const toggleSample = (k: SampleKey) => {
    setFiles([]);
    setSamples((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));
  };

  const launch = async () => {
    const made: PipelineRun[] = [];
    setLaunched(0);
    setRuns([]);
    setStep(3);
    const base = { material, units, preset };
    if (samples.length) {
      for (const k of samples) {
        made.push(await start.mutateAsync({ input: { ...base, name: samples.length === 1 && name.trim() ? name.trim() : SPECS[k].name, sampleKey: k }, files: [] }));
        setRuns([...made]);
        setLaunched(made.length);
      }
    } else {
      for (const part of parts) {
        const single = parts.length === 1 && name.trim();
        made.push(await start.mutateAsync({ input: { ...base, name: single ? name.trim() : part.name, viewCount: part.files.length }, files: part.files }));
        setRuns([...made]);
        setLaunched(made.length);
      }
    }
  };
  const reset = () => {
    setStep(0);
    setFiles([]);
    setSamples([]);
    setRuns([]);
    setName("");
    setLaunched(0);
  };

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <PageHeader eyebrow="Automation" title="New run" description="Upload a drawing, several drawings, or a folder of parts. Each part is processed through every pipeline stage, one after another. The estimated cost and time are shown before anything runs." />
      <ol className="glass-flat flex items-center gap-1 p-2" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s} className="flex flex-1 items-center gap-2">
            <span
              aria-current={i === step ? "step" : undefined}
              className={cn("flex h-9 flex-1 items-center gap-2 rounded-[10px] px-3 text-sm font-medium transition-colors duration-300", i === step ? "border border-gold/50 bg-gold/10 text-gold-hi" : i < step ? "text-text" : "text-muted-foreground")}
            >
              <span className={cn("num grid size-5 place-items-center rounded-full text-[11px] font-bold transition-colors duration-300", i < step ? "bg-gold text-on-gold" : "border border-current")}>{i < step ? <Check className="size-3" strokeWidth={3} aria-hidden /> : i + 1}</span>
              <span className="hidden sm:inline">{s}</span>
            </span>
          </li>
        ))}
      </ol>

      <AnimatePresence mode="wait" initial={false}>
        <motion.div key={step} initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -16 }} transition={{ duration: 0.2 }} className="flex flex-col gap-4">
          {step === 0 && (
            <Glass className="flex flex-col gap-4 p-5">
              <div {...dz.getRootProps()} className={cn("flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-all duration-200", dz.isDragActive ? "scale-[1.01] border-gold bg-gold/10" : "border-line bg-bg/40")}>
                <input {...dz.getInputProps()} aria-label="Drawing files" />
                <motion.div animate={dz.isDragActive ? { y: -6, scale: 1.1 } : { y: 0, scale: 1 }} transition={{ type: "spring", stiffness: 380, damping: 22 }}>
                  <Upload className="size-8 text-gold" aria-hidden />
                </motion.div>
                <p className="text-base font-semibold">{dz.isDragActive ? "Release to add the files" : "Drop drawings or a folder of parts here"}</p>
                <p className="max-w-[60ch] text-[13px] text-muted-foreground">
                  PDF, PNG, JPG, DXF or DWG, up to 50 MB per file and {MAX_FOLDER_FILES} files per upload. A folder is split into parts: each sub-folder is one part (its files are the views of that part), and each loose file in the folder is its own part. Files are read in the browser; nothing is sent until the run starts.
                </p>
                <div className="flex flex-wrap justify-center gap-2">
                  <button type="button" className="btn btn-outline" onClick={dz.open}>
                    <FileText className="size-4" aria-hidden /> Choose files
                  </button>
                  <button type="button" className="btn btn-outline" onClick={() => folder.current?.click()}>
                    <FolderUp className="size-4" aria-hidden /> Choose a folder of parts
                  </button>
                  <input
                    ref={folder}
                    type="file"
                    multiple
                    className="sr-only"
                    tabIndex={-1}
                    aria-label="Folder of parts"
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
              {parts.length > 0 && (
                <div>
                  <div className="mb-2 flex items-center gap-2">
                    <h2 className="text-sm font-semibold">{parts.length} part{parts.length > 1 ? "s" : ""} to process</h2>
                    <span className="num text-xs text-muted-foreground">{files.length} file{files.length > 1 ? "s" : ""}</span>
                    <button type="button" className="btn btn-sm btn-quiet ml-auto" onClick={() => setFiles([])}>Clear all</button>
                  </div>
                  <ul className="flex flex-col gap-1.5" aria-label="Parts to process">
                    <AnimatePresence initial={false}>
                      {parts.map((part) => (
                        <motion.li key={part.key} layout="position" variants={rowVariants} initial="hidden" animate="show" exit="exit" className="flex items-center gap-3 rounded-lg border border-line/50 px-3 py-2">
                          {part.folder ? <Folder className="size-4 text-gold" aria-hidden /> : <FileText className="size-4 text-gold" aria-hidden />}
                          <span className="min-w-0 flex-1">
                            <span className="num block truncate text-[13px] font-medium">{part.name}</span>
                            <span className="num block truncate text-xs text-muted-foreground">{part.files.map((f) => f.name).join(", ")}</span>
                          </span>
                          <span className="num text-xs text-muted-foreground">{part.files.length} view{part.files.length > 1 ? "s" : ""} · {fmtBytes(part.files.reduce((a, f) => a + f.size, 0))}</span>
                          <button type="button" className="btn btn-icon btn-sm btn-quiet" aria-label={`Remove part ${part.name}`} onClick={() => setFiles((prev) => prev.filter((f) => !part.files.includes(f)))}>
                            <Trash2 className="size-3.5" aria-hidden />
                          </button>
                        </motion.li>
                      ))}
                    </AnimatePresence>
                  </ul>
                </div>
              )}
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <span className="eyebrow">Or use sample drawings (select several to run a batch)</span> <SampleBadge />
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  {(Object.keys(SPECS) as SampleKey[]).map((k) => (
                    <button key={k} type="button" aria-pressed={samples.includes(k)} onClick={() => toggleSample(k)} className={cn("glass-raised lift flex items-center gap-3 p-3 text-left", samples.includes(k) && "glass-active")}>
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
              <Field label="Project name" hint={count > 1 ? "With several parts, each project takes the name of its part." : undefined}>
                <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder={samples[0] ? SPECS[samples[0]].name : parts[0]?.name ?? "Part name"} disabled={count > 1} />
              </Field>
              <Field label="Material" hint="Recorded on the project. It does not change the geometry.">
                <select className="field" value={material} onChange={(e) => setMaterial(e.target.value as MaterialKey)}>
                  {(Object.keys(MATERIAL_LABEL) as MaterialKey[]).map((m) => <option key={m} value={m}>{MATERIAL_LABEL[m]}</option>)}
                </select>
              </Field>
              <Field label="Units" hint="The pipeline keeps the units of the drawing. Select the units the drawing uses.">
                <select className="field" value={units} onChange={(e) => setUnits(e.target.value as Units)}>
                  <option value="mm">Millimeters</option>
                  <option value="in">Inches</option>
                </select>
              </Field>
              <fieldset className="sm:col-span-2">
                <legend className="mb-1 text-xs font-medium text-muted-foreground">Pipeline preset (applies to every part in the batch)</legend>
                <div className="grid gap-3 sm:grid-cols-3">
                  {(Object.keys(PRESETS) as Preset[]).map((k) => (
                    <label key={k} className={cn("glass-raised lift flex cursor-pointer flex-col gap-1 p-3", preset === k && "glass-active")}>
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
                  ["Parts", String(count)],
                  ["Est. cost per part", formatUsd(per, 3)],
                  ["Est. batch cost", formatUsd(per * count, 2)],
                  ["Est. time, in sequence", fmtSeconds(p.seconds * count)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-xl border border-line/50 bg-bg/40 p-3">
                    <div className="text-xs text-muted-foreground">{k}</div>
                    <div className="num text-xl font-semibold">{v}</div>
                  </div>
                ))}
              </div>
              <div className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-[13px] leading-5">
                <div className="flex items-center gap-2 font-semibold text-warn">
                  <AlertTriangle className="size-4" aria-hidden /> Estimate based on assumptions
                </div>
                <ul className="mt-1 list-disc pl-5 text-text/90">
                  <li>Usage is that of a typical standard run ({TYPICAL.inputTokens.toLocaleString()} input tokens, {TYPICAL.outputTokens.toLocaleString()} output tokens, {TYPICAL.visionCalls} vision calls), scaled by the {p.label} preset (×{p.k}).</li>
                  <li>Rates come from Settings{settings.pipelineRates.confirmed ? "." : " and have not been verified against current provider pricing."}</li>
                  <li>Parts are processed one at a time. Retries add cost and time.</li>
                </ul>
              </div>
              {IS_MOCK && (
                <div className="rounded-xl border border-violet/40 bg-violet/10 p-3 text-[13px] leading-5 text-text/90">
                  <div className="mb-1 flex items-center gap-2 font-semibold"><DemoTag /> Sample-data mode</div>
                  {samples.length
                    ? "Sample drawings start simulated runs. Stage timings are simulated, and the result of each is the stored sample result for that drawing."
                    : "No pipeline service is connected. The uploaded parts are stored for this browser session and appear as projects, but they are not processed, and no extracted data is generated for them. Set NEXT_PUBLIC_API_MODE=http to run the pipeline."}
                </div>
              )}
            </Glass>
          )}

          {step === 3 && (
            <div className="flex flex-col gap-4">
              {runs.length === 1 && count === 1 ? (
                <PipelineCard runId={runs[0].id} title="Live progress" />
              ) : (
                <Glass className="p-5">
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 className="text-base font-semibold">Batch of {count} part{count > 1 ? "s" : ""}</h2>
                    <span className="num text-xs text-muted-foreground">{launched} submitted · {finished} finished</span>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-raised" role="progressbar" aria-label="Batch progress" aria-valuemin={0} aria-valuemax={count} aria-valuenow={finished}>
                    <div className="h-full rounded-full bg-gradient-to-r from-[#A67CFF] to-gold transition-[width] duration-500" style={{ width: `${count ? (finished / count) * 100 : 0}%` }} />
                  </div>
                  <ul className="mt-4 flex flex-col gap-2" aria-label="Runs in this batch">
                    {runs.map((r, i) => <BatchRow key={r.id} run={r} index={i} live={live.get(r.id)} />)}
                  </ul>
                </Glass>
              )}
              <div className="flex flex-wrap gap-2">
                {runs.length === 1 && <Link href={`/projects/${runs[0].projectId}`} className="btn btn-primary">Open project <ArrowRight className="size-4" aria-hidden /></Link>}
                <Link href="/pipelines" className="btn btn-outline">View all runs</Link>
                <button type="button" className="btn btn-ghost" onClick={reset}>Start another</button>
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {step < 3 && (
        <div className="flex items-center justify-between">
          <button type="button" className="btn btn-ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>
            <ArrowLeft className="size-4" aria-hidden /> Back
          </button>
          {step < 2 ? (
            <button type="button" className="btn btn-primary" disabled={count === 0} onClick={() => setStep(step + 1)}>
              Next <ArrowRight className="size-4" aria-hidden />
            </button>
          ) : (
            <button type="button" className="btn btn-primary" disabled={start.isPending} onClick={launch}>
              <Play className="size-4 fill-current" aria-hidden /> {start.isPending ? "Starting…" : `Run ${count} part${count > 1 ? "s" : ""}`}
            </button>
          )}
        </div>
      )}
      {step === 0 && count === 0 && <p className="text-right text-xs text-muted-foreground">Add a drawing or a folder, or pick a sample, to continue.</p>}
    </div>
  );
}
