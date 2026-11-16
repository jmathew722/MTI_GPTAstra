"use client";

import * as React from "react";
import Link from "next/link";
import { FolderOpen, Play } from "lucide-react";
import { FilterBar, ProjectCard, ProjectRow } from "./index";
import { EmptyState, ErrorState, Glass, PageHeader, Skel } from "@/components/shared";
import { StaggerItem, StaggerList } from "@/components/shared/motion";
import { IS_MOCK } from "@/lib/api";
import { useProjects } from "@/lib/api/hooks";
import type { ProjectStatus } from "@/lib/schemas";

const STATUSES: { value: ProjectStatus; label: string }[] = [
  { value: "needs_rework", label: "Needs rework" },
  { value: "needs_review", label: "Needs review" },
  { value: "approved", label: "Approved" },
  { value: "running", label: "Running" },
  { value: "draft", label: "Draft" },
];

export function ProjectsView({ mode }: { mode: "projects" | "models" }) {
  const q = useProjects();
  const [query, setQuery] = React.useState("");
  const [filter, setFilter] = React.useState<ProjectStatus | "all">("all");
  const [view, setView] = React.useState<"grid" | "table">(mode === "models" ? "table" : "grid");
  const base = (q.data ?? []).filter((p) => (mode === "models" ? Boolean(p.modelUrl) : true));
  const ql = query.trim().toLowerCase();
  const rows = base.filter((p) => (filter === "all" || p.status === filter) && (!ql || `${p.name} ${p.partNumber} ${p.description ?? ""}`.toLowerCase().includes(ql)));
  const options = [{ value: "all" as const, label: "All", count: base.length }, ...STATUSES.map((s) => ({ ...s, count: base.filter((p) => p.status === s.value).length })).filter((s) => s.count > 0)];
  const models = mode === "models";
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={models ? "Models" : "Projects"}
        sample={IS_MOCK}
        description={models ? "Every generated part with its rubric grade, validation status, run cost and revision." : "One project per drawing. Open one to compare the drawing with the model, review the extraction and sign off."}
        actions={
          <Link href="/automation" className="btn btn-primary">
            <Play className="size-4 fill-current" aria-hidden /> New run
          </Link>
        }
      />
      <FilterBar query={query} onQuery={setQuery} placeholder={models ? "Search models" : "Search projects"} filter={filter} onFilter={setFilter} options={options} view={view} onView={setView} />
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => <Skel key={i} className="h-44 rounded-2xl" />)}
        </div>
      ) : rows.length === 0 ? (
        <Glass flat>
          <EmptyState
            icon={<FolderOpen />}
            title={base.length === 0 ? (models ? "No models yet" : "No projects yet") : "Nothing matches"}
            body={base.length === 0 ? "Start a run from a drawing. The generated part will appear here with its validation and grade." : "Clear the search or pick a different status."}
            action={base.length === 0 ? <Link href="/automation" className="btn btn-sm btn-primary">Start a run</Link> : <button type="button" className="btn btn-sm btn-ghost" onClick={() => { setQuery(""); setFilter("all"); }}>Clear filters</button>}
          />
        </Glass>
      ) : view === "grid" ? (
        <StaggerList key={`${filter}-${query}`} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((p) => (
            <StaggerItem key={p.id}>
              <ProjectCard p={p} detail={models} />
            </StaggerItem>
          ))}
        </StaggerList>
      ) : (
        <Glass flat className="overflow-x-auto p-1">
          <table className="dtable min-w-[820px]">
            <thead>
              <tr>
                <th>Name</th><th>Part no.</th><th>Rev</th><th>Status</th><th>Validation</th><th>Rubric</th><th className="r">Run cost</th><th className="r">Updated</th>
              </tr>
            </thead>
            <tbody>{rows.map((p) => <ProjectRow key={p.id} p={p} />)}</tbody>
          </table>
        </Glass>
      )}
    </div>
  );
}
