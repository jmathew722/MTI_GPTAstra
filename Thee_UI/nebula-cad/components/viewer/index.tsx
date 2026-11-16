"use client";

import dynamic from "next/dynamic";

function ViewerSkeleton() {
  return (
    <div className="well grid h-full min-h-[240px] place-items-center" role="status">
      <div className="flex flex-col items-center gap-3">
        <div className="skel size-24 rounded-2xl" />
        <span className="text-sm text-muted-foreground">Loading the 3D viewer…</span>
      </div>
    </div>
  );
}

/** three.js, R3F and postprocessing load only when a viewer is on screen. */
export const ModelViewer = dynamic(() => import("./ModelViewer"), { ssr: false, loading: ViewerSkeleton });
export type { ExpectedHole, ModelViewerProps } from "./ModelViewer";
