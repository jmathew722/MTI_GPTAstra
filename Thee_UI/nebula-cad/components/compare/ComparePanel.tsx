"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { Columns2, Flame, GripVertical, Link2 } from "lucide-react";
import { CardHeader, ErrorState, Glass, Segmented, Skel } from "@/components/shared";
import { ModelViewer, type ExpectedHole } from "@/components/viewer";
import { useAddComment, useBuildPlan, useComments, useDrawing, useExtraction, useProject } from "@/lib/api/hooks";
import { useUi, type CompareMode } from "@/lib/store";
import { cn } from "@/lib/utils";
import { countMismatches } from "@/lib/validation";

const DrawingViewer = dynamic(() => import("./DrawingViewer"), {
  ssr: false,
  loading: () => (
    <div className="well grid h-full min-h-[240px] place-items-center" role="status">
      <span className="text-sm text-muted-foreground">Loading the drawing viewer…</span>
    </div>
  ),
});

export function ComparePanel({ projectId, className }: { projectId: string; className?: string }) {
  const mode = useUi((s) => s.compareMode);
  const heatmap = useUi((s) => s.heatmap);
  const setUi = useUi((s) => s.set);
  const { data: project } = useProject(projectId);
  const drawing = useDrawing(projectId);
  const { data: extraction } = useExtraction(projectId);
  const { data: plan } = useBuildPlan(projectId);
  const { data: comments } = useComments(projectId);
  const addComment = useAddComment(projectId);
  const [split, setSplit] = React.useState(56);
  const [pane, setPane] = React.useState<"drawing" | "model">("drawing");
  const [opacity, setOpacity] = React.useState(0.9);
  const [link, setLink] = React.useState(false);
  const [zoom, setZoom] = React.useState(1);
  const box = React.useRef<HTMLDivElement>(null);
  const dragging = React.useRef(false);

  const canOverlay = Boolean(drawing.data?.registration && plan?.outline);
  const expected: ExpectedHole[] | undefined = React.useMemo(() => {
    const pos = extraction?.countChecks.flatMap((c) => c.expectedPositions ?? []);
    return pos?.length ? pos.map(([x, y, r]) => ({ x, y, r })) : undefined;
  }, [extraction]);
  const mismatches = countMismatches(extraction);
  // A count mismatch is the thing to look at: open in Diff the first time a project with one is shown.
  const auto = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!extraction || auto.current === projectId) return;
    auto.current = projectId;
    setUi({ compareMode: mismatches.length ? "diff" : "split" });
  }, [extraction, projectId, mismatches.length, setUi]);
  const effective: CompareMode = mode === "overlay" && !canOverlay ? "split" : mode;
  const showOutline = effective !== "split" && canOverlay;

  const onMove = (e: React.PointerEvent) => {
    if (!dragging.current || !box.current) return;
    const r = box.current.getBoundingClientRect();
    setSplit(Math.min(80, Math.max(20, ((e.clientX - r.left) / r.width) * 100)));
  };

  const drawingPane = drawing.isError ? (
    <ErrorState error={drawing.error} onRetry={() => drawing.refetch()} title="The drawing is not available" />
  ) : !drawing.data ? (
    <Skel className="size-full min-h-[240px]" />
  ) : (
    <DrawingViewer
      drawing={drawing.data}
      items={extraction?.items}
      comments={comments}
      plan={plan}
      heatmap={heatmap}
      outline={showOutline}
      outlineOpacity={opacity}
      isSample={project?.isSample}
      onZoom={setZoom}
      onAddPin={(region) => {
        const body = window.prompt("Comment for this spot on the drawing:");
        if (body?.trim()) addComment.mutate({ body: body.trim(), region });
      }}
      className="size-full"
    />
  );
  const modelPane = (
    <ModelViewer
      modelUrl={project?.modelUrl}
      fileName={project?.modelUrl?.split("/").pop()}
      plan={plan}
      expected={expected}
      showDiff={effective === "diff"}
      specKey={project?.partSpecKey}
      isSample={project?.isSample}
      fullHref={`/viewer/${projectId}`}
      linkZoom={link ? zoom : undefined}
      className="size-full"
    />
  );

  return (
    <Glass as="section" className={cn("flex min-h-0 flex-col p-3", className)} aria-label="Drawing and model compare">
      <div className="flex flex-wrap items-center gap-2 px-1 pb-3">
        <CardHeader icon={<Columns2 />} title="Drawing vs model" className="mr-auto" />
        <Segmented
          label="Compare mode"
          value={effective}
          onChange={(v) => setUi({ compareMode: v })}
          options={[
            { value: "split", label: "Split" },
            { value: "overlay", label: "Overlay", disabled: !canOverlay, title: canOverlay ? "Draw the modeled outline over the drawing's front view" : "Needs a drawing registration and a build plan from the backend" },
            { value: "diff", label: mismatches.length ? `Diff · ${mismatches.length}` : "Diff", title: "Show what the drawing has that the model does not" },
          ]}
        />
        <button type="button" className="btn btn-sm btn-ghost" aria-pressed={heatmap} onClick={() => setUi({ heatmap: !heatmap })} title="Color each extracted region by model confidence">
          <Flame className="size-3.5" aria-hidden /> Heatmap
        </button>
        <button
          type="button"
          className="btn btn-sm btn-ghost hidden md:inline-flex"
          aria-pressed={link}
          onClick={() => setLink((l) => !l)}
          title="Zooming the drawing zooms the model by the same factor (pan is not linked: one view is 2D, the other 3D)"
        >
          <Link2 className="size-3.5" aria-hidden /> Link zoom
        </button>
        {showOutline && (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Outline
            <input type="range" min={0.15} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} className="w-20 accent-[#D6AF6B]" aria-label="Modeled outline opacity" />
          </label>
        )}
        <Segmented
          className="md:hidden"
          label="Visible pane"
          value={pane}
          onChange={setPane}
          options={[
            { value: "drawing", label: "Drawing" },
            { value: "model", label: "Model" },
          ]}
        />
      </div>

      {effective === "overlay" ? (
        <div className="min-h-[360px] flex-1 md:min-h-[440px]">{drawingPane}</div>
      ) : (
        <>
          {/* desktop: resizable split */}
          <div
            ref={box}
            className="hidden min-h-[440px] flex-1 md:flex"
            onPointerMove={onMove}
            onPointerUp={() => (dragging.current = false)}
            onPointerLeave={() => (dragging.current = false)}
          >
            <div style={{ width: `${split}%` }} className="min-w-0">
              {drawingPane}
            </div>
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize drawing and model panes"
              aria-valuenow={Math.round(split)}
              aria-valuemin={20}
              aria-valuemax={80}
              tabIndex={0}
              onPointerDown={(e) => {
                dragging.current = true;
                e.preventDefault();
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft") setSplit((s) => Math.max(20, s - 4));
                if (e.key === "ArrowRight") setSplit((s) => Math.min(80, s + 4));
              }}
              className="group mx-0.5 grid w-3 shrink-0 cursor-col-resize place-items-center rounded-full hover:bg-gold/10"
            >
              <GripVertical className="size-4 text-faint group-hover:text-gold" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">{modelPane}</div>
          </div>
          {/* mobile: one pane at a time */}
          <div className="h-[360px] md:hidden">{pane === "drawing" ? drawingPane : modelPane}</div>
        </>
      )}
    </Glass>
  );
}
