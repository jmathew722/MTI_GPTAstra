"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { AlertOctagon, Award, CopyPlus, DollarSign, Download, FileBox, FileJson, FileText, ListTree, Lock, PackagePlus, ShieldCheck, SlidersHorizontal, SquareTerminal, Zap } from "lucide-react";
import { toast } from "sonner";
import { FeaturesTab, LogsTab, ParametersTab, ValidationTab } from "./tabs";
import { useRubricResult } from "@/components/rubric/RubricTab";
import { CardHeader, EmptyState, Glass, Modal, Stamp, TableSkeleton } from "@/components/shared";
import { useBuildPlan, useCloneProject, useCost, useExports, useExtraction, useProject, useRecordExport, useRubricScore, useValidation } from "@/lib/api/hooks";
import { formatUsd, quantityBreaks, runCost } from "@/lib/cost";
import { downloadBlob, downloadJson, downloadUrl } from "@/lib/format";
import { spring, tabContent } from "@/lib/motion";
import type { ExportArtifact } from "@/lib/schemas";
import { WORKSPACE_TABS, useSettings, useUi, type WorkspaceTab } from "@/lib/store";
import { cn } from "@/lib/utils";
import { countMismatches, exportGate, mismatchSentence, summarize } from "@/lib/validation";

const CostTab = dynamic(() => import("@/components/cost/CostTab"), { ssr: false, loading: () => <TableSkeleton /> });
const RubricTab = dynamic(() => import("@/components/rubric/RubricTab"), { ssr: false, loading: () => <TableSkeleton /> });

const ICON: Record<WorkspaceTab, React.ReactNode> = {
  Parameters: <SlidersHorizontal className="size-4" aria-hidden />,
  Features: <ListTree className="size-4" aria-hidden />,
  Validation: <ShieldCheck className="size-4" aria-hidden />,
  Cost: <DollarSign className="size-4" aria-hidden />,
  Logs: <SquareTerminal className="size-4" aria-hidden />,
  Rubric: <Award className="size-4" aria-hidden />,
};

export function WorkspaceTabs({ projectId, className }: { projectId: string | null; className?: string }) {
  const tab = useUi((s) => s.workspaceTab);
  const set = useUi((s) => s.set);
  const { data: checks } = useValidation(projectId);
  const { result } = useRubricResult(projectId ?? "");
  const failed = checks?.filter((c) => c.status === "failed").length ?? 0;
  const refs = React.useRef<Record<string, HTMLButtonElement | null>>({});
  const onKey = (e: React.KeyboardEvent) => {
    const i = WORKSPACE_TABS.indexOf(tab);
    const next = e.key === "ArrowRight" ? (i + 1) % 6 : e.key === "ArrowLeft" ? (i + 5) % 6 : e.key === "Home" ? 0 : e.key === "End" ? 5 : -1;
    if (next < 0) return;
    e.preventDefault();
    set({ workspaceTab: WORKSPACE_TABS[next] });
    refs.current[WORKSPACE_TABS[next]]?.focus();
  };
  return (
    <Glass as="section" id="workspace-tabs" className={cn("min-w-0 scroll-mt-24", className)} aria-label="Workspace">
      <div className="overflow-x-auto p-2 pb-0">
        <div role="tablist" aria-label="Workspace tabs" onKeyDown={onKey} className="glass-raised inline-flex min-w-full gap-1 rounded-[12px] p-1 sm:min-w-0">
          {WORKSPACE_TABS.map((t) => {
            const active = tab === t;
            return (
              <button
                key={t}
                ref={(el) => {
                  refs.current[t] = el;
                }}
                type="button"
                role="tab"
                id={`tab-${t}`}
                aria-selected={active}
                aria-controls="workspace-panel"
                tabIndex={active ? 0 : -1}
                onClick={() => set({ workspaceTab: t })}
                className={cn("relative flex h-9 shrink-0 items-center gap-2 rounded-[10px] px-3 text-sm font-medium transition-colors", active ? "text-gold-hi" : "text-muted-foreground hover:text-text")}
              >
                {active && <motion.span layoutId="workspace-tab" className="tab-pill" transition={spring} />}
                <span className={cn("relative z-10", active && "text-gold")}>{ICON[t]}</span>
                <span className="relative z-10">{t}</span>
                {t === "Validation" && failed > 0 && (
                  <span className="num relative z-10 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-danger px-1 text-[10px] font-bold text-[#2a0710]" aria-label={`${failed} failed`}>
                    {failed}
                  </span>
                )}
                {t === "Rubric" && result?.capped && <Lock className="relative z-10 size-3.5 text-danger" aria-label="capped" />}
              </button>
            );
          })}
        </div>
      </div>
      <div id="workspace-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} tabIndex={0} className="min-h-[220px] outline-none">
        {!projectId ? (
          <EmptyState title="No project selected" body="Pick a project to see its parameters, features, validation, cost, logs and rubric." />
        ) : (
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={`${tab}-${projectId}`} variants={tabContent} initial="hidden" animate="show" exit="exit">
              {tab === "Parameters" && <ParametersTab projectId={projectId} />}
              {tab === "Features" && <FeaturesTab projectId={projectId} />}
              {tab === "Validation" && <ValidationTab projectId={projectId} />}
              {tab === "Cost" && <CostTab projectId={projectId} />}
              {tab === "Logs" && <LogsTab projectId={projectId} />}
              {tab === "Rubric" && <RubricTab projectId={projectId} />}
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </Glass>
  );
}

/* ================================================================ Failure banner */

export function FailureBanner({ projectId }: { projectId: string }) {
  const { data: ex } = useExtraction(projectId);
  const { data: checks } = useValidation(projectId);
  const set = useUi((s) => s.set);
  const bad = countMismatches(ex);
  const gate = exportGate(checks ?? []);
  const failed = (checks ?? []).filter((c) => c.status === "failed");
  if (!bad.length && !failed.length) return null;
  const overridden = !gate.blocked && gate.reasons.length > 0;
  const goValidation = () => {
    set({ workspaceTab: "Validation" });
    document.getElementById("workspace-tabs")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return (
    <div role="alert" className={cn("shake-once flex flex-wrap items-center gap-3 rounded-2xl border-2 px-4 py-3", overridden ? "border-warn/70 bg-[#2a1a0c]" : "border-danger bg-[#2d0d17] shadow-[0_0_28px_rgba(255,102,128,.22)]")}>
      <AlertOctagon className={cn("size-7 shrink-0", overridden ? "text-warn" : "text-danger")} aria-hidden />
      <div className="min-w-0 flex-1 basis-[15rem]">
        <p className={cn("text-base font-semibold leading-6", overridden ? "text-warn" : "text-[#ff8fa3]")}>
          {bad.length ? "The model does not match the drawing." : `${failed.length} validation check${failed.length > 1 ? "s" : ""} failed.`}
          {overridden && " A reviewer has overridden the block."}
        </p>
        <p className="num text-sm leading-6 text-text">
          {bad.length ? bad.map(mismatchSentence).join("  ") : failed.map((c) => c.detail ?? c.label).join(" ")}
        </p>
        <p className="text-xs leading-5 text-text/80">
          {gate.blocked ? "Export is blocked and the rubric is capped at Needs rework until this is resolved or overridden with a reason." : "Export is allowed because every blocking check carries a recorded override."}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => set({ reviewTab: "extraction", compareMode: "diff" })}>
          Show the difference
        </button>
        <button type="button" className="btn btn-sm btn-danger" onClick={goValidation}>
          Open validation
        </button>
      </div>
    </div>
  );
}

/* ================================================================ Export center */

const EXPORT_ICON: Record<string, React.ReactNode> = {
  sldprt: <FileBox className="size-4" aria-hidden />,
  stl: <FileBox className="size-4" aria-hidden />,
  step: <FileBox className="size-4" aria-hidden />,
  report_pdf: <FileText className="size-4" aria-hidden />,
};
/** Deliverables that describe or contain the model are gated; raw review data is not. */
const GATED = new Set(["sldprt", "stl", "step", "report_pdf", "build_plan_json"]);

export function ExportCenter({ projectId }: { projectId: string }) {
  const open = useUi((s) => s.exportOpen);
  const set = useUi((s) => s.set);
  const { data: project } = useProject(projectId);
  const { data: artifacts } = useExports(projectId);
  const { data: checks } = useValidation(projectId);
  const { data: plan } = useBuildPlan(projectId);
  const { data: extraction } = useExtraction(projectId);
  const { data: cost } = useCost(projectId);
  const { data: score } = useRubricScore(projectId);
  const { result, template } = useRubricResult(projectId);
  const rates = useSettings((s) => s.pipelineRates);
  const mfg = useSettings((s) => s.mfgRates);
  const rec = useRecordExport(projectId);
  const [busy, setBusy] = React.useState<string | null>(null);
  const gate = exportGate(checks ?? []);
  const noChecks = (checks ?? []).length === 0;

  const rubricExport = () =>
    result && project
      ? {
          project: { id: project.id, name: project.name, partNumber: project.partNumber, revision: project.revision },
          template: { id: template.id, name: template.name },
          total: result.total,
          band: result.band,
          releaseStatus: result.status,
          capped: result.capped,
          gates: result.gates,
          gateOverride: score?.gateOverride ?? null,
          criteria: result.criteria.map((c) => ({ key: c.criterion.key, label: c.criterion.label, weight: c.criterion.weight, level: c.level, source: c.source, points: c.points, comment: c.comment, evidence: c.evidence })),
          signOff: score?.signOff ?? null,
          history: score?.history ?? [],
          exportedAt: new Date().toISOString(),
        }
      : null;

  const download = async (a: ExportArtifact) => {
    setBusy(a.key);
    try {
      if (a.key === "stl" && a.url) await downloadUrl(a.url, a.fileName);
      else if (a.key === "build_plan_json") downloadJson(plan, a.fileName);
      else if (a.key === "extraction_json") downloadJson(extraction, a.fileName);
      else if (a.key === "rubric_json") downloadJson(rubricExport(), a.fileName);
      else if (a.key === "report_pdf") {
        const rub = rubricExport();
        if (!rub || !project) throw new Error("The report is still loading. Try again in a moment.");
        const { renderReportPdf } = await import("@/lib/report/pdf");
        const rc = cost ? runCost(cost.stages, rates, cost.batchSize) : null;
        const breaks = cost ? quantityBreaks({ material: project.material, partVolumeCm3: cost.partVolumeCm3, stockVolumeCm3: cost.stockVolumeCm3, holes: cost.holeCount, features: cost.featureCount }, mfg) : [];
        downloadBlob(
          await renderReportPdf({
            rubric: rub,
            checks: checks ?? [],
            plan: plan ?? null,
            cost: rc ? { perPart: formatUsd(rc.perPart, 4), perBatch: formatUsd(rc.perBatch, 2), unitCosts: breaks.map((b) => ({ qty: b.qty, unit: formatUsd(b.unitCost, 2) })), ratesConfirmed: rates.confirmed } : null,
            sample: project.isSample,
          }),
          a.fileName,
        );
      } else if (a.url) await downloadUrl(a.url, a.fileName);
      else throw new Error("This file is not available.");
      rec.mutate(`${a.label}${gate.reasons.some((r) => r.overridden) && GATED.has(a.key) ? " (under override)" : ""}`);
      toast.success(`${a.fileName} downloaded.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal open={open} onOpenChange={(o) => set({ exportOpen: o })} title="Export center" description={project ? `${project.partNumber} · ${project.name} · Rev ${project.revision}` : undefined} wide>
      {gate.blocked ? (
        <div role="alert" className="rounded-xl border border-danger/60 bg-danger/10 p-3 text-[13px] leading-5">
          <div className="flex items-center gap-2 font-semibold text-danger">
            <Lock className="size-4" aria-hidden /> Model deliverables are blocked
          </div>
          <ul className="mt-1 list-disc pl-5 text-text/90">
            {gate.open.map((r) => (
              <li key={r.checkId}><span className="num text-xs text-muted-foreground">{r.checkId}</span> {r.text}</li>
            ))}
          </ul>
          <p className="mt-2 text-text/80">Fix the cause and re-run, or override the check with a recorded reason in the Validation tab.</p>
          <button
            type="button"
            className="btn btn-sm btn-danger mt-2"
            onClick={() => {
              set({ exportOpen: false, workspaceTab: "Validation" });
              setTimeout(() => document.getElementById("workspace-tabs")?.scrollIntoView({ behavior: "smooth" }), 200);
            }}
          >
            Open validation
          </button>
        </div>
      ) : noChecks ? (
        <p className="rounded-xl border border-dashed border-faint/60 p-3 text-[13px] leading-5 text-muted-foreground">No validation has run for this project, so there is no verified model to export.</p>
      ) : gate.reasons.length ? (
        <p role="status" className="rounded-xl border border-warn/50 bg-warn/10 p-3 text-[13px] leading-5 text-[#ffd4ab]">Export is allowed under a recorded override. The override is noted in the report and the audit trail.</p>
      ) : (
        <p role="status" className="rounded-xl border border-success/40 bg-success/10 p-3 text-[13px] leading-5 text-text/90">Every critical check ran and none is failing.</p>
      )}
      <ul className="flex flex-col gap-2">
        {!artifacts && <TableSkeleton rows={4} className="p-0" />}
        {artifacts?.map((a) => {
          const blocked = (gate.blocked || noChecks) && GATED.has(a.key);
          const disabled = !a.available || blocked || busy !== null;
          return (
            <li key={a.key} className="flex items-center gap-3 rounded-xl border border-line/50 p-3">
              <span className="text-gold">{EXPORT_ICON[a.key] ?? <FileJson className="size-4" aria-hidden />}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-semibold">{a.label}</div>
                <div className="num truncate text-xs text-muted-foreground">{a.fileName}</div>
                {a.note && <div className="text-xs leading-5 text-faint">{a.note}</div>}
              </div>
              {blocked && a.available ? <Stamp tone="danger" icon={<Lock className="size-3" aria-hidden />}>Blocked</Stamp> : !a.available ? <Stamp tone="dashed">Not available</Stamp> : null}
              <button type="button" className="btn btn-sm btn-outline" disabled={disabled} onClick={() => download(a)} aria-label={`Download ${a.label}`}>
                <Download className="size-3.5" aria-hidden /> {busy === a.key ? "Preparing…" : "Download"}
              </button>
            </li>
          );
        })}
      </ul>
    </Modal>
  );
}

/* ================================================================ Quick actions */

export function QuickActions({ projectId, className }: { projectId: string | null; className?: string }) {
  const router = useRouter();
  const clone = useCloneProject();
  const set = useUi((s) => s.set);
  const { data: checks } = useValidation(projectId);
  const gate = exportGate(checks ?? []);
  const s = checks ? summarize(checks) : null;
  const cls = "glass-raised lift flex h-[88px] flex-col items-center justify-center gap-2 rounded-[14px] text-[13px] font-medium text-text disabled:opacity-50";
  return (
    <Glass as="section" className={cn("p-4", className)} aria-label="Quick actions">
      <CardHeader icon={<Zap />} title="Quick Actions" />
      <div className="mt-4 grid grid-cols-3 gap-3">
        <Link href="/automation" className={cls}>
          <PackagePlus className="size-6 text-gold" aria-hidden /> New Model
        </Link>
        <button
          type="button"
          className={cls}
          disabled={!projectId || clone.isPending}
          onClick={() =>
            projectId &&
            clone.mutate(projectId, {
              onSuccess: (p) => {
                toast.success(`Cloned as ${p.name}.`);
                router.push(`/projects/${p.id}`);
              },
            })
          }
        >
          <CopyPlus className="size-6 text-gold" aria-hidden /> Clone
        </button>
        <button type="button" className={cn(cls, "relative")} disabled={!projectId} onClick={() => set({ exportOpen: true })}>
          <Download className="size-6 text-gold" aria-hidden /> Export
          {gate.blocked && (
            <span className="absolute right-1.5 top-1.5">
              <Lock className="size-3.5 text-danger" aria-label="Export is blocked" />
            </span>
          )}
        </button>
      </div>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        {gate.blocked ? "Export is blocked by a critical check. Open it to see why." : s && s.total ? "SLDPRT, STL, STEP, PDF report and JSON build plan." : "Export needs a validated model."}
      </p>
      {projectId && <ExportCenter projectId={projectId} />}
    </Glass>
  );
}
