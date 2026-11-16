"use client";

import * as React from "react";
import { motion } from "motion/react";
import { Check, CircleDashed, Loader2, RefreshCw, Workflow, X } from "lucide-react";
import { useIntro } from "@/components/shell/Providers";
import { CardHeader, DemoTag, EmptyState, Glass, Skel, StatusStamp } from "@/components/shared";
import { useCancelRun, useInvalidateAll, useRetryRun, useRun } from "@/lib/api/hooks";
import { fmtDuration } from "@/lib/format";
import { fadeUp, stagger } from "@/lib/motion";
import type { PipelineRun, PipelineStage } from "@/lib/schemas";
import { cn } from "@/lib/utils";

function Node({ status }: { status: PipelineStage["status"] }) {
  const base = "relative z-10 grid size-7 shrink-0 place-items-center rounded-full border-2";
  if (status === "done")
    return (
      <span className={cn(base, "border-gold bg-gold text-on-gold shadow-[0_0_12px_rgba(214,175,107,.45)]")}>
        <Check className="size-4" strokeWidth={3} aria-hidden />
      </span>
    );
  if (status === "running")
    return (
      <span className={cn(base, "pulse-gold border-gold bg-[#1a1328] text-gold")}>
        <Loader2 className="size-4 animate-spin" aria-hidden />
      </span>
    );
  if (status === "failed")
    return (
      <span className={cn(base, "border-danger bg-danger/15 text-danger")}>
        <X className="size-4" strokeWidth={3} aria-hidden />
      </span>
    );
  return (
    <span className={cn(base, "border-dashed border-faint bg-[#1a1328] text-faint")}>
      <CircleDashed className="size-3.5" aria-hidden />
    </span>
  );
}

const STATUS_TEXT: Record<PipelineStage["status"], string> = { done: "Complete", running: "Running", failed: "Failed", pending: "Pending", skipped: "Skipped" };

export function StageList({ run, horizontal = false }: { run: PipelineRun; horizontal?: boolean }) {
  const intro = useIntro();
  const done = run.stages.filter((s) => s.status === "done").length;
  const progress = run.stages.length > 1 ? Math.min(1, Math.max(0, (done - (run.status === "succeeded" ? 1 : 0.5)) / (run.stages.length - 1))) : 0;
  return (
    <motion.ol
      variants={stagger(0.2)}
      initial={intro ? "hidden" : false}
      animate="show"
      className={cn("relative", horizontal ? "grid grid-cols-2 gap-x-4 gap-y-3 lg:grid-cols-4" : "flex flex-col gap-4")}
      aria-label="Pipeline stages"
    >
      {!horizontal && (
        <>
          <span className="absolute bottom-4 left-[13px] top-4 w-0.5 rounded bg-line/50" aria-hidden />
          <motion.span
            className="absolute bottom-4 left-[13px] top-4 w-0.5 origin-top rounded bg-gold"
            initial={{ scaleY: 0 }}
            animate={{ scaleY: done === 0 ? 0 : progress }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            aria-hidden
          />
        </>
      )}
      {run.stages.map((s) => (
        <motion.li key={s.key} variants={fadeUp} className="relative flex items-start gap-3">
          <Node status={s.status} />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold leading-5 text-text">{s.label}</div>
            <div className={cn("num text-xs", s.status === "failed" ? "text-danger" : "text-muted-foreground")}>
              {STATUS_TEXT[s.status]}
              {s.durationMs !== undefined && s.status !== "pending" ? ` · ${fmtDuration(s.durationMs)}` : ""}
              {s.attempts > 1 ? ` · ${s.attempts} attempts` : ""}
            </div>
            {s.message && <div className={cn("mt-0.5 text-xs leading-4", s.status === "failed" ? "text-danger/90" : "text-faint")}>{s.message}</div>}
          </div>
        </motion.li>
      ))}
    </motion.ol>
  );
}

export function PipelineCard({ runId, title = "Automation Pipeline", horizontal = false, className }: { runId?: string | null; title?: string; horizontal?: boolean; className?: string }) {
  const { data: run, isLoading } = useRun(runId);
  const retry = useRetryRun();
  const cancel = useCancelRun();
  const invalidate = useInvalidateAll();
  const prev = React.useRef<string | undefined>(undefined);
  const [sweep, setSweep] = React.useState(false);
  React.useEffect(() => {
    if (prev.current && prev.current !== "succeeded" && run?.status === "succeeded") {
      setSweep(true);
      invalidate();
      const t = setTimeout(() => setSweep(false), 1300);
      return () => clearTimeout(t);
    }
    prev.current = run?.status;
  }, [run?.status, invalidate]);
  const total = run?.stages.reduce((a, s) => a + (s.durationMs ?? 0), 0) ?? 0;
  const live = run?.status === "running" || run?.status === "queued";

  return (
    <Glass as="section" className={cn("relative overflow-hidden p-4", sweep && "sweep", className)} aria-label={title}>
      <CardHeader
        icon={<Workflow />}
        title={title}
        subtitle={run ? <span className="num">{run.id} · {run.preset}{total ? ` · ${fmtDuration(total)}` : ""}</span> : undefined}
        sample={run?.isSample}
      />
      <div className="mt-3 border-t border-line/50 pt-4">
        {!runId ? (
          <EmptyState title="No run yet" body="Start a run from Automation to see each stage, its timing and any retries here." className="py-6" />
        ) : isLoading || !run ? (
          <div className="space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <Skel key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : (
          <>
            <StageList run={run} horizontal={horizontal} />
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <StatusStamp status={run.status} />
              {run.simulated && <DemoTag title="Simulated run: stage timings are not from a real pipeline." />}
              {run.simulated && <span className="text-xs text-muted-foreground">Simulated run</span>}
              <span className="flex-1" />
              {live ? (
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => cancel.mutate(run.id)} disabled={cancel.isPending}>
                  <X className="size-3.5" aria-hidden /> Cancel
                </button>
              ) : (
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => retry.mutate(run.id)} disabled={retry.isPending} title="Run the pipeline again for this project">
                  <RefreshCw className="size-3.5" aria-hidden /> Re-run
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </Glass>
  );
}
