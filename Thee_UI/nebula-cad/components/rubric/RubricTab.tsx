"use client";

import * as React from "react";
import { Award, Copy, Download, FileText, Link2, Lock, PenLine, Save, ShieldAlert, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { EmptyState, ErrorState, Modal, RelTime, Stamp, StatusStamp, TableSkeleton } from "@/components/shared";
import {
  useBuildPlan,
  useDeleteTemplate,
  useExtraction,
  useProject,
  useRecordExport,
  useRubricGateOverride,
  useRubricScore,
  useSaveRubric,
  useSaveTemplate,
  useSignOff,
  useTemplates,
  useValidation,
} from "@/lib/api/hooks";
import { downloadBlob, downloadJson } from "@/lib/format";
import { DEFAULT_TEMPLATE, LEVEL_NAMES, RELEASE_LABEL, scoreRubric, weightSum, type RubricResult, type ScoredCriterion } from "@/lib/rubric";
import type { RubricEntry, RubricTemplate } from "@/lib/schemas";
import { useSelection, useSettings, useUi } from "@/lib/store";
import { cn } from "@/lib/utils";

const BAND_TONE = { A: "success", B: "success", C: "warn", "Needs rework": "danger" } as const;

function LevelPicker({ value, onChange, disabled, label }: { value: number | null; onChange: (v: number | null) => void; disabled?: boolean; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[10px] border border-line bg-bg/60 p-0.5">
      {[4, 3, 2, 1, 0].map((l) => (
        <button
          key={l}
          type="button"
          role="radio"
          aria-checked={value === l}
          disabled={disabled}
          title={LEVEL_NAMES[l]}
          onClick={() => onChange(value === l ? null : l)}
          className={cn(
            "num h-7 w-8 rounded-lg text-[13px] font-semibold transition-colors disabled:cursor-not-allowed",
            value === l ? "bg-gold/15 text-gold-hi shadow-[inset_0_0_0_1px_rgba(214,175,107,.5)]" : "text-muted-foreground hover:text-text disabled:hover:text-muted-foreground",
          )}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

function CriterionCard({ c, onLevel, onComment }: { c: ScoredCriterion; onLevel: (l: number | null) => void; onComment: (t: string) => void }) {
  const select = useSelection((s) => s.select);
  const setUi = useUi((s) => s.set);
  const [comment, setComment] = React.useState(c.comment);
  React.useEffect(() => setComment(c.comment), [c.comment]);
  const auto = c.criterion.scoredBy === "auto";
  const lvl = c.level;
  return (
    <li className={cn("rounded-xl border p-3", lvl === null ? "border-dashed border-warn/60" : lvl <= 1 ? "border-danger/50 bg-danger/[0.05]" : "border-line/50")}>
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="min-w-0 flex-1 text-sm font-semibold">{c.criterion.label}</h4>
        <Stamp tone="muted">{c.criterion.scoredBy === "auto" ? "Auto" : c.criterion.scoredBy === "reviewer" ? "Reviewer" : "Mixed"}</Stamp>
        <span className="num text-xs text-muted-foreground">weight {c.criterion.weight}</span>
        <span className="num w-20 text-right text-sm font-semibold text-gold-hi">
          {c.points.toFixed(1)} <span className="text-xs font-normal text-muted-foreground">/ {c.criterion.weight}</span>
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <LevelPicker label={`Level for ${c.criterion.label}`} value={lvl} disabled={auto} onChange={onLevel} />
        <span className={cn("text-[13px] font-medium", lvl === null ? "text-warn" : lvl === 0 ? "text-danger" : "text-text")}>
          {lvl === null ? "Not scored yet: a reviewer must set a level" : `${lvl} · ${LEVEL_NAMES[lvl]}`}
        </span>
        {c.criterion.scoredBy === "mixed" && c.autoLevel !== null && <span className="text-xs text-muted-foreground">{c.source === "auto" ? "suggested automatically; set a level to overrule" : `automatic suggestion: ${c.autoLevel}`}</span>}
        {auto && <span className="text-xs text-muted-foreground">computed from validation; not editable</span>}
      </div>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        {lvl !== null && lvl >= 1 ? c.criterion.levels[lvl as 1 | 2 | 3 | 4] : lvl === 0 ? "Missing: the evidence for this criterion does not exist or did not run." : "Levels: 4 Exemplary · 3 Proficient · 2 Developing · 1 Insufficient · 0 Missing."}
      </p>
      <details className="mt-1.5">
        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-text">Level descriptors</summary>
        <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs leading-5">
          {([4, 3, 2, 1] as const).map((l) => (
            <React.Fragment key={l}>
              <dt className="num font-semibold text-text">{l} {LEVEL_NAMES[l]}</dt>
              <dd className="text-muted-foreground">{c.criterion.levels[l]}</dd>
            </React.Fragment>
          ))}
          <dt className="num font-semibold text-text">0 Missing</dt>
          <dd className="text-muted-foreground">No evidence, or the check did not run.</dd>
        </dl>
      </details>
      {(c.evidence.notes.length > 0 || c.evidence.checkIds.length > 0 || c.evidence.itemIds.length > 0) && (
        <div className="mt-2 rounded-lg bg-surface-raised/30 px-2.5 py-2">
          <div className="eyebrow mb-1 text-[10px]">Evidence</div>
          <ul className="list-disc pl-4 text-xs leading-5 text-text/90">
            {c.evidence.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {[...new Set(c.evidence.checkIds)].map((id) => (
              <button
                key={id}
                type="button"
                className="num inline-flex items-center gap-1 rounded-md border border-line px-1.5 py-0.5 text-[11px] text-gold hover:bg-gold/10"
                onClick={() => {
                  select({ checkId: id });
                  setUi({ workspaceTab: "Validation" });
                }}
                title="Open this check in the Validation tab"
              >
                <Link2 className="size-3" aria-hidden /> {id}
              </button>
            ))}
            {[...new Set(c.evidence.itemIds)].map((id) => (
              <button key={id} type="button" className="num inline-flex items-center gap-1 rounded-md border border-line px-1.5 py-0.5 text-[11px] text-[#cdb8ff] hover:bg-violet/10" onClick={() => select({ itemId: id })} title="Show this item's region on the drawing">
                <Link2 className="size-3" aria-hidden /> {id}
              </button>
            ))}
          </div>
        </div>
      )}
      <label className="mt-2 block">
        <span className="sr-only">Reviewer comment for {c.criterion.label}</span>
        <textarea className="field" rows={1} value={comment} placeholder="Reviewer comment" onChange={(e) => setComment(e.target.value)} onBlur={() => comment !== c.comment && onComment(comment)} />
      </label>
    </li>
  );
}

function TemplateEditor({ open, onClose, base }: { open: boolean; onClose: () => void; base: RubricTemplate }) {
  const save = useSaveTemplate();
  const [name, setName] = React.useState("");
  const [weights, setWeights] = React.useState<Record<string, number>>({});
  React.useEffect(() => {
    if (!open) return;
    setName(base.builtIn ? `${base.name} (copy)` : base.name);
    setWeights(Object.fromEntries(base.criteria.map((c) => [c.key, c.weight])));
  }, [open, base]);
  const criteria = base.criteria.map((c) => ({ ...c, weight: weights[c.key] ?? c.weight }));
  const sum = weightSum(criteria);
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={base.builtIn ? "Duplicate and edit weights" : "Edit template weights"} description="Weights must sum to 100. The built-in template cannot be changed, so editing it creates a copy.">
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(
            { id: base.builtIn ? `tpl-${Date.now().toString(36)}` : base.id, name: name.trim() || "Untitled rubric", criteria, builtIn: false, updatedAt: new Date().toISOString() },
            { onSuccess: () => { toast.success("Template saved."); onClose(); } },
          );
        }}
      >
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Template name</span>
          <input className="field" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <ul className="flex flex-col gap-1.5">
          {criteria.map((c) => (
            <li key={c.key} className="flex items-center gap-3">
              <span className="min-w-0 flex-1 text-[13px]">{c.label}</span>
              <input type="number" min={0} max={100} className="field field-sm num w-20 text-right" value={c.weight} aria-label={`Weight for ${c.label}`} onChange={(e) => setWeights((w) => ({ ...w, [c.key]: Math.max(0, Number(e.target.value) || 0) }))} />
            </li>
          ))}
        </ul>
        <div className={cn("num flex items-center justify-between rounded-lg border px-3 py-2 text-sm font-semibold", sum === 100 ? "border-success/40 text-success" : "border-danger/60 bg-danger/10 text-danger")} role="status">
          <span>Total weight</span>
          <span>{sum} / 100{sum !== 100 && ` (${sum > 100 ? "over" : "under"} by ${Math.abs(100 - sum)})`}</span>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-sm btn-quiet" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={sum !== 100 || save.isPending}>
            <Save className="size-3.5" aria-hidden /> Save template
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function useRubricResult(projectId: string): { result: RubricResult | null; template: RubricTemplate; loading: boolean } {
  const { data: score } = useRubricScore(projectId);
  const { data: templates } = useTemplates();
  const { data: checks } = useValidation(projectId);
  const { data: extraction } = useExtraction(projectId);
  const { data: buildPlan } = useBuildPlan(projectId);
  const template = templates?.find((t) => t.id === score?.templateId) ?? DEFAULT_TEMPLATE;
  const ready = score && checks !== undefined && extraction !== undefined && buildPlan !== undefined;
  const result = React.useMemo(
    () => (ready ? scoreRubric(template, score.entries, { checks: checks ?? [], extraction, buildPlan, signedOff: Boolean(score.signOff) }, score.gateOverride) : null),
    [ready, template, score, checks, extraction, buildPlan],
  );
  return { result, template, loading: !ready };
}

export default function RubricTab({ projectId }: { projectId: string }) {
  const scoreQ = useRubricScore(projectId);
  const { data: project } = useProject(projectId);
  const { data: templates } = useTemplates();
  const { data: checks } = useValidation(projectId);
  const { result, template, loading } = useRubricResult(projectId);
  const save = useSaveRubric(projectId);
  const gate = useRubricGateOverride(projectId);
  const signOff = useSignOff(projectId);
  const del = useDeleteTemplate();
  const rec = useRecordExport(projectId);
  const reviewer = useSettings((s) => s.reviewerName);
  const [editing, setEditing] = React.useState(false);
  const [overriding, setOverriding] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [exporting, setExporting] = React.useState(false);

  if (scoreQ.isError) return <ErrorState error={scoreQ.error} onRetry={() => scoreQ.refetch()} />;
  if (loading || !result || !scoreQ.data || !project) return <TableSkeleton />;
  const score = scoreQ.data;
  if (!checks?.length)
    return <EmptyState icon={<Award />} title="Nothing to grade yet" body="The rubric grades a generated part against its drawing. This project has no validation results, so every automatic criterion would be Missing." />;

  const setEntry = (key: string, patch: Partial<RubricEntry>) => {
    const entries = template.criteria.map((c) => {
      const e = score.entries.find((x) => x.criterionKey === c.key) ?? { criterionKey: c.key, level: null, comment: "" };
      return c.key === key ? { ...e, ...patch } : e;
    });
    save.mutate({ entries });
  };
  const exportData = () => ({
    project: { id: project.id, name: project.name, partNumber: project.partNumber, revision: project.revision },
    template: { id: template.id, name: template.name },
    total: result.total,
    band: result.band,
    releaseStatus: result.status,
    capped: result.capped,
    gates: result.gates,
    gateOverride: score.gateOverride ?? null,
    criteria: result.criteria.map((c) => ({ key: c.criterion.key, label: c.criterion.label, weight: c.criterion.weight, level: c.level, source: c.source, points: c.points, comment: c.comment, evidence: c.evidence })),
    signOff: score.signOff ?? null,
    history: score.history,
    exportedAt: new Date().toISOString(),
  });
  const exportPdf = async () => {
    setExporting(true);
    try {
      const { renderRubricPdf } = await import("@/lib/report/pdf");
      downloadBlob(await renderRubricPdf(exportData()), `${project.partNumber}_${project.name}_rubric.pdf`);
      rec.mutate("rubric (PDF)");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "The PDF could not be generated.");
    } finally {
      setExporting(false);
    }
  };
  const canSign = result.complete && result.weightsValid;
  const stale = score.signOff && (score.signOff.total !== result.total || score.signOff.status !== result.status);

  return (
    <div className="grid gap-4 p-3 xl:grid-cols-[1fr_340px]">
      <div className="order-2 xl:order-1">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Template
            <select className="field field-sm w-60" value={template.id} onChange={(e) => save.mutate({ templateId: e.target.value })}>
              {(templates ?? [DEFAULT_TEMPLATE]).map((t) => (
                <option key={t.id} value={t.id}>{t.name}{t.builtIn ? " (built-in)" : ""}</option>
              ))}
            </select>
          </label>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>
            {template.builtIn ? <Copy className="size-3.5" aria-hidden /> : <PenLine className="size-3.5" aria-hidden />} {template.builtIn ? "Duplicate and edit" : "Edit weights"}
          </button>
          {!template.builtIn && (
            <button type="button" className="btn btn-sm btn-quiet" onClick={() => del.mutate(template.id)} aria-label="Delete this template">
              <Trash2 className="size-3.5" aria-hidden /> Delete
            </button>
          )}
          {!result.weightsValid && <Stamp tone="danger">Weights sum to {result.weightSum}, not 100</Stamp>}
        </div>
        <ul className="flex flex-col gap-2.5" aria-label="Rubric criteria">
          {result.criteria.map((c) => (
            <CriterionCard key={c.criterion.key} c={c} onLevel={(level) => setEntry(c.criterion.key, { level })} onComment={(comment) => setEntry(c.criterion.key, { comment })} />
          ))}
        </ul>
      </div>

      <aside className="order-1 flex flex-col gap-3 xl:order-2" aria-label="Rubric summary">
        <div className="glass-raised p-4">
          <div className="flex items-end justify-between">
            <div>
              <div className="eyebrow">Total score</div>
              <div className="num text-[40px] font-semibold leading-[44px] text-text">
                {result.total.toFixed(1)}
                <span className="text-base font-normal text-muted-foreground"> / 100</span>
              </div>
            </div>
            <Stamp tone={BAND_TONE[result.band]} className="h-8 px-3 text-sm">
              {result.band === "Needs rework" ? "Below C" : `Grade ${result.band}`}
            </Stamp>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-raised" aria-hidden>
            <div className={cn("h-full rounded-full", result.total >= 80 ? "bg-success" : result.total >= 70 ? "bg-warn" : "bg-danger")} style={{ width: `${result.total}%` }} />
          </div>
          <div className="mt-3 flex items-center justify-between">
            <span className="text-[13px] text-muted-foreground">Release status</span>
            <StatusStamp status={result.status} />
          </div>
          {!result.complete && <p className="mt-2 rounded-lg bg-warn/10 px-2.5 py-1.5 text-xs leading-5 text-[#ffd4ab]">Incomplete: reviewer criteria without a level count as 0 until scored.</p>}
          <p className="mt-2 text-[11px] leading-4 text-faint">Bands: A 90+, B 80+, C 70+, below 70 needs rework.</p>
        </div>

        {result.gates.length > 0 && (
          <div role="alert" className={cn("rounded-[14px] border p-4", result.capped ? "border-danger/70 bg-danger/10" : "border-warn/50 bg-warn/10")}>
            <div className={cn("flex items-center gap-2 text-sm font-semibold", result.capped ? "text-danger" : "text-warn")}>
              <Lock className="size-4" aria-hidden />
              {result.capped ? "Capped at Needs rework" : "Hard-fail cap overridden"}
            </div>
            <p className="mt-1 text-xs leading-5 text-text/90">
              {result.capped ? "A critical mismatch caps the release status no matter how high the score is." : "A reviewer accepted the critical mismatch below. The status now follows the score."}
            </p>
            <ul className="mt-2 list-disc pl-4 text-xs leading-5 text-text/90">
              {result.gates.map((g) => (
                <li key={g.id}>{g.reason} {g.overridden && <span className="text-warn">(overridden)</span>}</li>
              ))}
            </ul>
            {score.gateOverride && (
              <p className="mt-2 text-xs leading-5 text-[#ffd4ab]">
                Override by <span className="font-semibold">{score.gateOverride.by}</span> <RelTime iso={score.gateOverride.at} className="text-[#ffd4ab]" />: “{score.gateOverride.reason}”
              </p>
            )}
            <div className="mt-3 flex gap-2">
              {result.capped && (
                <button type="button" className="btn btn-sm btn-danger" onClick={() => setOverriding(true)}>
                  <ShieldAlert className="size-3.5" aria-hidden /> Override with reason
                </button>
              )}
              {score.gateOverride && (
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => gate.mutate(null)}>Remove override</button>
              )}
            </div>
          </div>
        )}

        <div className="glass-raised p-4">
          <h4 className="text-sm font-semibold">Reviewer sign-off</h4>
          {score.signOff ? (
            <p className="mt-1 text-xs leading-5 text-text/90">
              Signed by <span className="font-semibold">{score.signOff.by}</span> <RelTime iso={score.signOff.at} /> as <span className="font-semibold">{RELEASE_LABEL[score.signOff.status]}</span>, <span className="num">{score.signOff.total} ({score.signOff.band})</span>.
            </p>
          ) : (
            <p className="mt-1 text-xs leading-5 text-muted-foreground">Not signed off. Signing records your name, the time, the score and the status.</p>
          )}
          {stale && <p className="mt-2 rounded-lg bg-warn/10 px-2.5 py-1.5 text-xs leading-5 text-[#ffd4ab]">The score or status changed since that sign-off. Sign again to record the current result.</p>}
          <button
            type="button"
            className="btn btn-sm btn-primary mt-3 w-full"
            disabled={!canSign || signOff.isPending}
            onClick={() => signOff.mutate({ status: result.status, total: result.total, band: result.band })}
          >
            <PenLine className="size-3.5" aria-hidden /> Sign off as {reviewer}: {RELEASE_LABEL[result.status]}
          </button>
          {!canSign && <p className="mt-1.5 text-[11px] leading-4 text-faint">{!result.weightsValid ? "Fix the template weights first." : "Score every reviewer criterion first."}</p>}
        </div>

        <div className="glass-raised p-4">
          <h4 className="text-sm font-semibold">Export</h4>
          <div className="mt-2 flex gap-2">
            <button type="button" className="btn btn-sm btn-ghost flex-1" onClick={exportPdf} disabled={exporting}>
              <FileText className="size-3.5" aria-hidden /> {exporting ? "Rendering…" : "PDF"}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-ghost flex-1"
              onClick={() => {
                downloadJson(exportData(), `${project.partNumber}_${project.name}_rubric.json`);
                rec.mutate("rubric (JSON)");
              }}
            >
              <Download className="size-3.5" aria-hidden /> JSON
            </button>
          </div>
        </div>

        <div className="glass-raised p-4">
          <h4 className="text-sm font-semibold">Score history</h4>
          {score.history.length === 0 ? (
            <p className="mt-1 text-xs leading-5 text-muted-foreground">No sign-offs yet. Each sign-off adds a row here.</p>
          ) : (
            <ul className="mt-2 flex flex-col gap-1.5">
              {[...score.history].reverse().map((h, i) => (
                <li key={i} className="flex items-center gap-2 text-xs">
                  <span className="num font-semibold">Rev {h.revision}</span>
                  <span className="num text-gold-hi">{h.total} ({h.band})</span>
                  <span className="text-muted-foreground">{RELEASE_LABEL[h.status]}</span>
                  <RelTime iso={h.at} className="ml-auto" />
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      <TemplateEditor open={editing} onClose={() => setEditing(false)} base={template} />
      <Modal open={overriding} onOpenChange={setOverriding} title="Override the hard-fail cap" description="This lets the release status follow the score even though a critical mismatch exists. Your name and reason go into the audit trail and the exported rubric.">
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            gate.mutate(reason, { onSuccess: () => { setOverriding(false); setReason(""); toast.success("Override recorded in the audit trail."); } });
          }}
        >
          <ul className="list-disc rounded-lg border border-danger/40 bg-danger/10 py-2 pl-7 pr-3 text-[13px] leading-5">
            {result.gates.map((g) => (
              <li key={g.id}>{g.reason}</li>
            ))}
          </ul>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Reason (required, at least 10 characters)</span>
            <textarea className="field" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-sm btn-quiet" onClick={() => setOverriding(false)}>Cancel</button>
            <button type="submit" className="btn btn-sm btn-danger" disabled={reason.trim().length < 10 || gate.isPending}>Record override</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
