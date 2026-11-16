"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight, Layers, Play, RefreshCw, X } from "lucide-react";
import { FilterBar } from "@/components/lists";
import { StageList } from "@/components/pipeline/PipelineTimeline";
import { DemoTag, EmptyState, ErrorState, Glass, PageHeader, RelTime, StatusStamp, TableSkeleton } from "@/components/shared";
import { IS_MOCK } from "@/lib/api";
import { useCancelRun, useRetryRun, useRuns } from "@/lib/api/hooks";
import { formatUsd, runCost } from "@/lib/cost";
import { fmtDuration, fmtSeconds } from "@/lib/format";
import type { PipelineRun, RunStatus } from "@/lib/schemas";
import { useSettings } from "@/lib/store";
import { cn } from "@/lib/utils";

const STATUSES: { value: RunStatus; label: string }[] = [
  { value: "running", label: "Running" },
  { value: "queued", label: "Queued" },
  { value: "succeeded", label: "Complete" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

function RunRow({ run }: { run: PipelineRun }) {
  const [open, setOpen] = React.useState(false);
  const retry = useRetryRun();
  const cancel = useCancelRun();
  const rates = useSettings((s) => s.pipelineRates);
  const total = run.stages.reduce((a, s) => a + (s.durationMs ?? 0), 0);
  const cost = runCost(run.stages.map((s) => ({ key: s.key, label: s.label, usage: s.usage, retries: s.attempts - 1 })), rates).perPart;
  const live = run.status === "running" || run.status === "queued";
  const retries = run.stages.reduce((a, s) => a + s.attempts - 1, 0);
  return (
    <>
      <tr className={cn(run.status === "failed" && "bg-danger/[0.06]")}>
        <td>
          <button type="button" className="btn btn-icon btn-sm btn-quiet size-6" aria-expanded={open} aria-label={`${open ? "Hide" : "Show"} stages for ${run.id}`} onClick={() => setOpen((o) => !o)}>
            <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} aria-hidden />
          </button>
        </td>
        <td className="num font-medium">{run.id}</td>
        <td>
          <Link href={`/projects/${run.projectId}`} className="hover:text-gold-hi">{run.projectName}</Link>
        </td>
        <td><span className="flex items-center gap-1.5"><StatusStamp status={run.status} />{run.simulated && <DemoTag title="Simulated run" />}</span></td>
        <td className="num text-muted-foreground">{run.preset}</td>
        <td className="num r">{total ? fmtDuration(total) : "–"}</td>
        <td className="num r">{live && run.etaSeconds !== undefined ? fmtSeconds(run.etaSeconds) : "–"}</td>
        <td className={cn("num r", retries > 0 && "text-warn")}>{retries}</td>
        <td className="num r">{cost > 0 ? formatUsd(cost, 4) : "–"}</td>
        <td className="r"><RelTime iso={run.createdAt} /></td>
        <td className="r whitespace-nowrap">
          {live ? (
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => cancel.mutate(run.id)} disabled={cancel.isPending}>
              <X className="size-3.5" aria-hidden /> Cancel
            </button>
          ) : (
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => retry.mutate(run.id)} disabled={retry.isPending}>
              <RefreshCw className="size-3.5" aria-hidden /> Retry
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={11} className="!h-auto bg-bg/40 !p-4">
            <StageList run={run} horizontal />
            <div className="mt-3 flex gap-2">
              <Link href={`/projects/${run.projectId}`} className="btn btn-sm btn-outline">Open project</Link>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function PipelinesPage() {
  const q = useRuns();
  const [query, setQuery] = React.useState("");
  const [filter, setFilter] = React.useState<RunStatus | "all">("all");
  const all = q.data ?? [];
  const ql = query.trim().toLowerCase();
  const rows = all.filter((r) => (filter === "all" || r.status === filter) && (!ql || `${r.id} ${r.projectName} ${r.preset}`.toLowerCase().includes(ql)));
  const options = [{ value: "all" as const, label: "All", count: all.length }, ...STATUSES.map((s) => ({ ...s, count: all.filter((r) => r.status === s.value).length })).filter((s) => s.count > 0)];
  const queue = all.filter((r) => r.status === "running" || r.status === "queued");
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Pipelines"
        sample={IS_MOCK}
        description="The batch queue and the run history. Expand a run to see each stage, its timing, retries and failure message."
        actions={<Link href="/automation" className="btn btn-primary"><Play className="size-4 fill-current" aria-hidden /> New run</Link>}
      />
      <Glass flat className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 text-[13px]" role="status">
        <span className="font-semibold">Queue</span>
        <span className="num text-muted-foreground">{queue.filter((r) => r.status === "running").length} running · {queue.filter((r) => r.status === "queued").length} queued</span>
        <span className="text-muted-foreground">{queue.length === 0 ? "Nothing is waiting." : `Next finish in about ${fmtSeconds(Math.max(...queue.map((r) => r.etaSeconds ?? 0)))}.`}</span>
      </Glass>
      <FilterBar query={query} onQuery={setQuery} placeholder="Search runs" filter={filter} onFilter={setFilter} options={options} />
      <Glass flat className="overflow-x-auto p-1">
        {q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.isLoading ? (
          <TableSkeleton rows={6} />
        ) : rows.length === 0 ? (
          <EmptyState icon={<Layers />} title={all.length ? "No runs match" : "No runs yet"} body={all.length ? "Clear the search or the status filter." : "Runs appear here as soon as you start one from Automation."} />
        ) : (
          <table className="dtable min-w-[1000px]">
            <thead>
              <tr>
                <th><span className="sr-only">Expand</span></th><th>Run</th><th>Project</th><th>Status</th><th>Preset</th><th className="r">Duration</th><th className="r">ETA</th><th className="r">Retries</th><th className="r">Cost</th><th className="r">Started</th><th className="r"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>{rows.map((r) => <RunRow key={r.id} run={r} />)}</tbody>
          </table>
        )}
      </Glass>
    </div>
  );
}
