"use client";

import * as React from "react";
import Link from "next/link";
import { LayoutGrid, List, Search } from "lucide-react";
import { useRubricResult } from "@/components/rubric/RubricTab";
import { PartGlyph } from "@/components/shell/Atmosphere";
import { RelTime, SampleBadge, Segmented, Stamp, StatusStamp } from "@/components/shared";
import { useCost, useValidation } from "@/lib/api/hooks";
import { formatUsd, runCost } from "@/lib/cost";
import type { Project } from "@/lib/schemas";
import { useSettings } from "@/lib/store";
import { cn } from "@/lib/utils";
import { summarize } from "@/lib/validation";

export function FilterBar<T extends string>({
  query,
  onQuery,
  placeholder,
  filter,
  onFilter,
  options,
  view,
  onView,
}: {
  query: string;
  onQuery: (q: string) => void;
  placeholder: string;
  filter: T | "all";
  onFilter: (f: T | "all") => void;
  options: { value: T | "all"; label: string; count: number }[];
  view?: "grid" | "table";
  onView?: (v: "grid" | "table") => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="relative min-w-[200px] flex-1 sm:max-w-xs">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <input className="field pl-9" value={query} onChange={(e) => onQuery(e.target.value)} placeholder={placeholder} aria-label={placeholder} />
      </label>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
        {options.map((o) => (
          <button key={o.value} type="button" className="btn btn-sm btn-ghost" aria-pressed={filter === o.value} onClick={() => onFilter(o.value)}>
            {o.label} <span className="num text-xs text-muted-foreground">{o.count}</span>
          </button>
        ))}
      </div>
      {view && onView && (
        <Segmented
          className="ml-auto"
          label="Layout"
          value={view}
          onChange={onView}
          options={[
            { value: "grid", label: <LayoutGrid className="size-4" aria-label="Grid" /> },
            { value: "table", label: <List className="size-4" aria-label="Table" /> },
          ]}
        />
      )}
    </div>
  );
}

export function useProjectMetrics(id: string) {
  const { data: checks } = useValidation(id);
  const { data: cost } = useCost(id);
  const { result } = useRubricResult(id);
  const rates = useSettings((s) => s.pipelineRates);
  const s = checks ? summarize(checks) : null;
  const validation = !s ? null : s.total === 0 ? "not_run" : s.failed ? "failed" : s.notRun ? "not_run" : s.warning ? "warning" : "passed";
  return {
    validation,
    summary: s,
    runCost: cost ? runCost(cost.stages, rates).perPart : null,
    grade: result && s && s.total > 0 ? result : null,
  };
}

export function GradeStamp({ id }: { id: string }) {
  const { grade } = useProjectMetrics(id);
  if (!grade) return <Stamp tone="dashed">Not graded</Stamp>;
  return (
    <Stamp tone={grade.capped || grade.total < 70 ? "danger" : grade.total < 80 ? "warn" : "success"} title={grade.capped ? "Capped at Needs rework by a critical mismatch" : undefined}>
      <span className="num">{grade.total.toFixed(0)}</span> {grade.capped ? "· capped" : grade.band === "Needs rework" ? "" : `· ${grade.band}`}
    </Stamp>
  );
}

export function ProjectCard({ p, detail = false }: { p: Project; detail?: boolean }) {
  const m = useProjectMetrics(p.id);
  return (
    <Link href={`/projects/${p.id}`} className={cn("glass-flat lift flex flex-col gap-3 p-4", p.status === "needs_rework" && "border-danger/50")}>
      <div className="flex items-start gap-3">
        <PartGlyph specKey={p.partSpecKey} className="size-14 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[15px] font-semibold">{p.name}</div>
          <div className="num text-xs text-muted-foreground">
            {p.partNumber} · Rev {p.revision}
          </div>
          <div className="mt-1 line-clamp-1 text-xs text-muted-foreground">{p.description}</div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusStamp status={p.status} />
        {m.validation && <StatusStamp status={m.validation} label={m.validation === "passed" ? "Checks passed" : m.validation === "failed" ? `${m.summary?.failed} check failed` : undefined} />}
        {detail && <GradeStamp id={p.id} />}
      </div>
      <div className="mt-auto flex items-center justify-between border-t border-line/40 pt-2 text-xs text-muted-foreground">
        <span>
          updated <RelTime iso={p.updatedAt} />
        </span>
        {detail && <span className="num">{m.runCost !== null ? `${formatUsd(m.runCost, 3)} / run` : "no run"}</span>}
        {p.isSample && <SampleBadge label="Sample" />}
      </div>
    </Link>
  );
}

export function ProjectRow({ p }: { p: Project }) {
  const m = useProjectMetrics(p.id);
  return (
    <tr>
      <td>
        <Link href={`/projects/${p.id}`} className="flex items-center gap-3 py-1.5 font-medium hover:text-gold-hi">
          <PartGlyph specKey={p.partSpecKey} className="size-8 shrink-0" />
          {p.name}
        </Link>
      </td>
      <td className="num text-muted-foreground">{p.partNumber}</td>
      <td className="num text-muted-foreground">{p.revision}</td>
      <td><StatusStamp status={p.status} /></td>
      <td>{m.validation ? <StatusStamp status={m.validation} /> : <span className="text-faint">…</span>}</td>
      <td><GradeStamp id={p.id} /></td>
      <td className="num r">{m.runCost !== null ? formatUsd(m.runCost, 3) : "–"}</td>
      <td className="r"><RelTime iso={p.updatedAt} /></td>
    </tr>
  );
}
