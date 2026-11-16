"use client";

import Link from "next/link";
import { Box } from "lucide-react";
import { Hero, KpiRow } from "@/components/hero/Hero";
import { PipelineCard } from "@/components/pipeline/PipelineTimeline";
import { useFocusedProjectId } from "@/components/shell/Navigation";
import { CardHeader, Glass, StatusStamp } from "@/components/shared";
import { ModelViewer } from "@/components/viewer";
import { FailureBanner, QuickActions, WorkspaceTabs } from "@/components/workspace/WorkspaceTabs";
import { useBuildPlan, useExtraction, useProject } from "@/lib/api/hooks";

export default function DashboardPage() {
  const id = useFocusedProjectId();
  const { data: project } = useProject(id);
  const { data: plan } = useBuildPlan(id);
  const { data: ex } = useExtraction(id);
  const expected = ex?.countChecks.flatMap((c) => c.expectedPositions ?? []).map(([x, y, r]) => ({ x, y, r }));
  return (
    <div className="flex flex-col gap-4">
      <Hero />
      <KpiRow />
      {id && <FailureBanner projectId={id} />}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
        <Glass as="section" className="flex min-h-[380px] flex-col p-3" aria-label="Model viewer">
          <CardHeader
            className="px-1 pb-3"
            icon={<Box />}
            title="Model Viewer"
            subtitle={project ? `${project.name.replaceAll("_", " ")} · Rev ${project.revision}` : "No project selected"}
            right={
              project && (
                <>
                  <StatusStamp status={project.status} />
                  <Link href={`/projects/${project.id}`} className="btn btn-sm btn-outline">
                    Open workstation
                  </Link>
                </>
              )
            }
          />
          <ModelViewer
            modelUrl={project?.modelUrl}
            fileName={project?.modelUrl?.split("/").pop()}
            plan={plan}
            expected={expected?.length ? expected : undefined}
            specKey={project?.partSpecKey}
            isSample={project?.isSample}
            fullHref={id ? `/viewer/${id}` : undefined}
            compact
            className="min-h-[300px] flex-1"
          />
        </Glass>
        <PipelineCard runId={project?.lastRunId} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
        <WorkspaceTabs projectId={id} />
        <QuickActions projectId={id} className="self-start" />
      </div>
    </div>
  );
}
