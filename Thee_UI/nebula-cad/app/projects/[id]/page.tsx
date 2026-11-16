"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Download, FolderX, Lock, PanelRight } from "lucide-react";
import { ComparePanel } from "@/components/compare/ComparePanel";
import { ReviewPanel } from "@/components/extraction/ReviewPanel";
import { PipelineCard } from "@/components/pipeline/PipelineTimeline";
import { PartGlyph } from "@/components/shell/Atmosphere";
import { EmptyState, Glass, RelTime, SampleBadge, Skel, StatusStamp } from "@/components/shared";
import { FailureBanner, QuickActions, WorkspaceTabs } from "@/components/workspace/WorkspaceTabs";
import { useProject, useValidation } from "@/lib/api/hooks";
import { MATERIAL_LABEL } from "@/lib/cost";
import { useUi } from "@/lib/store";
import { exportGate } from "@/lib/validation";

export default function WorkstationPage() {
  const { id } = useParams<{ id: string }>();
  const q = useProject(id);
  const { data: checks } = useValidation(id);
  const set = useUi((s) => s.set);
  const gate = exportGate(checks ?? []);

  if (q.isError)
    return (
      <Glass className="p-6">
        <EmptyState
          icon={<FolderX />}
          title="This project could not be opened"
          body={q.error instanceof Error ? q.error.message : "Unknown error."}
          action={
            <div className="flex gap-2">
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => q.refetch()}>Retry</button>
              <Link href="/projects" className="btn btn-sm btn-outline">All projects</Link>
            </div>
          }
        />
      </Glass>
    );
  const p = q.data;
  return (
    <div className="flex flex-col gap-4">
      <Glass flat as="header" className="flex flex-wrap items-center gap-3 px-4 py-3">
        <Link href="/projects" className="btn btn-icon btn-sm btn-quiet" aria-label="Back to projects">
          <ArrowLeft className="size-4" aria-hidden />
        </Link>
        {!p ? (
          <Skel className="h-10 w-64" />
        ) : (
          <>
            <PartGlyph specKey={p.partSpecKey} className="size-10 shrink-0" />
            <div className="min-w-[11rem] flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="break-words text-xl font-semibold leading-7">{p.name}</h1>
                <StatusStamp status={p.status} />
                {p.isSample && <SampleBadge />}
              </div>
              <div className="num flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                <span>{p.partNumber}</span>·<span>Rev {p.revision}</span>·<span>{MATERIAL_LABEL[p.material]}</span>·<span>{p.units}</span>·
                <span>updated <RelTime iso={p.updatedAt} /></span>
              </div>
            </div>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => set({ railSheetOpen: true })}>
              <PanelRight className="size-3.5" aria-hidden /> Context
            </button>
            <button type="button" className={gate.blocked ? "btn btn-sm btn-danger" : "btn btn-sm btn-primary"} onClick={() => set({ exportOpen: true })}>
              {gate.blocked ? <Lock className="size-3.5" aria-hidden /> : <Download className="size-3.5" aria-hidden />}
              {gate.blocked ? "Export blocked" : "Export"}
            </button>
          </>
        )}
      </Glass>
      <FailureBanner projectId={id} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <ComparePanel projectId={id} />
        <ReviewPanel projectId={id} className="xl:h-[calc(100%)] xl:max-h-[640px]" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <PipelineCard runId={p?.lastRunId} title="Pipeline timeline" horizontal />
        <QuickActions projectId={id} />
      </div>
      <WorkspaceTabs projectId={id} />
    </div>
  );
}
