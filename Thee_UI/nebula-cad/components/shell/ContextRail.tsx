"use client";

import * as React from "react";
import Link from "next/link";
import { Activity, BarChart3, FolderOpen } from "lucide-react";
import { PartGlyph } from "./Atmosphere";
import { useFocusedProjectId } from "./Navigation";
import { CardHeader, EmptyState, ErrorState, Glass, RelTime, Skel, StatRow, StatusStamp } from "@/components/shared";
import { useAudit, useBuildPlan, useExtraction, useProject, useProjects, useRun, useValidation } from "@/lib/api/hooks";
import { fmtDuration } from "@/lib/format";
import { useSettings } from "@/lib/store";
import { summarize } from "@/lib/validation";
import { cn } from "@/lib/utils";

const ACTION_DOT: Record<string, string> = {
  sign_off: "bg-success",
  override_check: "bg-warn",
  override_gate: "bg-warn",
  reject_item: "bg-danger",
  run_started: "bg-violet",
};

export function ContextRailContent({ flat = false }: { flat?: boolean }) {
  const id = useFocusedProjectId();
  const setSettings = useSettings((s) => s.set);
  const { data: projects } = useProjects();
  const project = useProject(id);
  const { data: checks } = useValidation(id);
  const { data: extraction } = useExtraction(id);
  const { data: plan } = useBuildPlan(id);
  const { data: run } = useRun(project.data?.lastRunId);
  const { data: audit } = useAudit(id);
  const p = project.data;
  const s = checks ? summarize(checks) : null;
  const buildMs = run?.stages.reduce((a, st) => a + (st.durationMs ?? 0), 0);
  const validation =
    !s || s.total === 0 ? "not_run" : s.failed ? "failed" : s.notRun ? "not_run" : s.warning ? "warning" : "passed";

  return (
    <div className="flex flex-col gap-4">
      <Glass flat={flat} as="section" className="p-4" aria-label="Project overview">
        <CardHeader icon={<FolderOpen />} title="Project Overview" sample={p?.isSample} />
        <div className="mt-3 border-t border-line/50 pt-3">
          {project.isError ? (
            <ErrorState error={project.error} onRetry={() => project.refetch()} className="m-0" />
          ) : !p ? (
            <div className="flex items-center gap-3">
              <Skel className="size-11" />
              <div className="flex-1 space-y-2">
                <Skel className="h-4 w-2/3" />
                <Skel className="h-3 w-1/2" />
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-3">
                <PartGlyph specKey={p.partSpecKey} className="size-11 shrink-0" />
                <div className="min-w-0 flex-1">
                  <Link href={`/projects/${p.id}`} className="block truncate text-sm font-semibold hover:text-gold-hi">
                    {p.name}
                  </Link>
                  <div className="num truncate text-xs text-muted-foreground">
                    Rev {p.revision} · {p.partNumber}
                  </div>
                </div>
                <StatusStamp status={p.status} />
              </div>
              <label className="mt-3 block">
                <span className="sr-only">Focused project</span>
                <select
                  className="field field-sm"
                  value={p.id}
                  onChange={(e) => setSettings({ focusedProjectId: e.target.value })}
                  aria-label="Focused project"
                >
                  {projects?.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.partNumber} · {x.name}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
        </div>
      </Glass>

      <Glass flat={flat} as="section" className="p-4" aria-label="Performance">
        <CardHeader icon={<BarChart3 />} title="Performance" sample={p?.isSample} />
        <div className="mt-2 border-t border-line/50 pt-1">
          <StatRow label="Build time" value={buildMs ? fmtDuration(buildMs) : "–"} />
          <StatRow label="Items extracted" value={extraction ? extraction.items.length : "–"} />
          <StatRow label="Operations" value={plan ? plan.operations.length : "–"} />
          <StatRow
            label="Checks passed"
            value={s && s.total ? `${s.passed} of ${s.total}${s.notRun ? ` · ${s.notRun} not run` : ""}` : "–"}
          />
          <div className="flex items-center justify-between pt-2">
            <span className="text-[13px] text-muted-foreground">Validation</span>
            <StatusStamp status={validation} />
          </div>
        </div>
      </Glass>

      <Glass flat={flat} as="section" className="p-4" aria-label="Activity">
        <CardHeader icon={<Activity />} title="Activity" sample={p?.isSample} />
        <div className="mt-2 border-t border-line/50 pt-2">
          {!audit ? (
            <div className="space-y-2">
              <Skel className="h-4 w-full" />
              <Skel className="h-4 w-5/6" />
              <Skel className="h-4 w-2/3" />
            </div>
          ) : audit.length === 0 ? (
            <EmptyState title="No activity yet" body="Reviews, overrides and sign-offs for this project appear here." className="py-4" />
          ) : (
            <ol className="relative flex flex-col">
              <span className="absolute bottom-3 left-[5px] top-3 w-px bg-line/60" aria-hidden />
              {audit.slice(0, 6).map((e) => (
                <li key={e.id} className="relative flex items-start gap-3 py-1.5">
                  <span className={cn("relative z-10 mt-1.5 size-[11px] shrink-0 rounded-full ring-2 ring-[#1a1328]", ACTION_DOT[e.action] ?? "bg-gold")} aria-hidden />
                  <span className="min-w-0 flex-1 text-[13px] leading-5 text-text/90">{e.summary}</span>
                  <RelTime iso={e.at} className="mt-0.5" />
                </li>
              ))}
            </ol>
          )}
        </div>
      </Glass>
    </div>
  );
}
