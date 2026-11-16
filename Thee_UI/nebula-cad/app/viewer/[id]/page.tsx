"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Logo } from "@/components/shell/Atmosphere";
import { OperationRow } from "@/components/extraction/ReviewPanel";
import { EmptyState, SampleBadge, StatusStamp } from "@/components/shared";
import { ModelViewer } from "@/components/viewer";
import { useBuildPlan, useExtraction, useProject } from "@/lib/api/hooks";

export default function ViewerPage() {
  const { id } = useParams<{ id: string }>();
  const q = useProject(id);
  const { data: plan } = useBuildPlan(id);
  const { data: ex } = useExtraction(id);
  const expected = ex?.countChecks.flatMap((c) => c.expectedPositions ?? []).map(([x, y, r]) => ({ x, y, r }));
  const p = q.data;
  return (
    <div className="flex h-dvh flex-col gap-3 p-3">
      <header className="glass-flat flex items-center gap-3 px-3 py-2">
        <Link href={p ? `/projects/${p.id}` : "/dashboard"} className="btn btn-icon btn-sm btn-quiet" aria-label="Back to the project">
          <ArrowLeft className="size-4" aria-hidden />
        </Link>
        <Logo className="size-7" />
        <h1 className="min-w-0 truncate text-base font-semibold">{p ? p.name : q.isError ? "Project not found" : "Loading…"}</h1>
        {p && <span className="num hidden text-xs text-muted-foreground sm:inline">{p.partNumber} · Rev {p.revision}</span>}
        {p && <StatusStamp status={p.status} />}
        {p?.isSample && <SampleBadge className="ml-auto" />}
      </header>
      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        <main id="main" className="min-h-[50dvh] flex-1 lg:min-h-0">
          {q.isError ? (
            <div className="glass-flat h-full"><EmptyState title="This project could not be opened" body={q.error instanceof Error ? q.error.message : undefined} action={<Link href="/projects" className="btn btn-sm btn-outline">All projects</Link>} /></div>
          ) : (
            <ModelViewer modelUrl={p?.modelUrl} fileName={p?.modelUrl?.split("/").pop()} plan={plan} expected={expected?.length ? expected : undefined} showDiff={false} specKey={p?.partSpecKey} isSample={p?.isSample} className="size-full" />
          )}
        </main>
        <aside className="glass-flat flex max-h-[38dvh] w-full shrink-0 flex-col p-3 lg:max-h-none lg:w-[320px]" aria-label="Feature tree">
          <h2 className="pb-2 text-sm font-semibold">Feature tree</h2>
          {plan ? (
            <ul className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto">
              {plan.operations.map((op) => <OperationRow key={op.id} op={op} child={Boolean(op.parentId)} />)}
            </ul>
          ) : (
            <EmptyState title="No build plan" body="Load a local STL or STEP file with the toolbar to inspect it. Feature highlights need a build plan from the pipeline." className="py-6" />
          )}
        </aside>
      </div>
    </div>
  );
}
