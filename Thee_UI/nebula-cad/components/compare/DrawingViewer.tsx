"use client";

import * as React from "react";
import { MessageSquarePlus, Minus, Plus, Scan } from "lucide-react";
import { SampleBadge, Stamp } from "@/components/shared";
import { fmtBytes } from "@/lib/format";
import type { BuildPlan, Comment, Drawing, ExtractionItem, Region } from "@/lib/schemas";
import { useSelection } from "@/lib/store";
import { cn } from "@/lib/utils";
import { confidenceBand } from "@/lib/validation";

type View = { s: number; x: number; y: number };
const MIN = 1;
const MAX = 8;

const STATUS_BOX: Record<ExtractionItem["status"], string> = {
  verified: "border-[#6b5a9a] hover:border-[#8f79cc]",
  needs_review: "border-[#ff9a3d] bg-[#ff9a3d]/10",
  conflict: "border-[#ff4d6d] bg-[#ff4d6d]/15",
};
const HEAT: Record<string, string> = {
  high: "bg-[#6b5a9a]/25 border-[#6b5a9a]",
  medium: "bg-[#ff9a3d]/35 border-[#ff9a3d]",
  low: "bg-[#ff4d6d]/40 border-[#ff4d6d]",
};

export interface DrawingViewerProps {
  drawing: Drawing;
  items?: ExtractionItem[];
  comments?: Comment[];
  plan?: BuildPlan | null;
  heatmap?: boolean;
  /** draw the modeled outline over the front view (needs drawing.registration and a plan) */
  outline?: boolean;
  outlineOpacity?: number;
  isSample?: boolean;
  onAddPin?: (region: Region) => void;
  onZoom?: (scale: number) => void;
  className?: string;
}

export default function DrawingViewer({ drawing, items = [], comments = [], plan, heatmap, outline, outlineOpacity = 0.9, isSample, onAddPin, onZoom, className }: DrawingViewerProps) {
  const wrap = React.useRef<HTMLDivElement>(null);
  const canvas = React.useRef<HTMLCanvasElement>(null);
  const [aspect, setAspect] = React.useState<number | null>(drawing.registration?.aspect ?? null);
  const [loaded, setLoaded] = React.useState<string | null>(null);
  const [failure, setFailure] = React.useState<{ url: string; message: string } | null>(null);
  const state: "loading" | "ready" | "error" = failure?.url === drawing.url ? "error" : loaded === drawing.url ? "ready" : "loading";
  const error = failure?.message ?? "";
  const [view, setView] = React.useState<View>({ s: 1, x: 0, y: 0 });
  const [size, setSize] = React.useState({ w: 0, h: 0 });
  const [pinning, setPinning] = React.useState(false);
  const [animate, setAnimate] = React.useState(false);
  const drag = React.useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
  const itemId = useSelection((s) => s.itemId);
  const select = useSelection((s) => s.select);

  // ---- render the page with pdf.js (loaded on demand), or show the image
  React.useEffect(() => {
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    const url = drawing.url;
    if (drawing.kind === "image") {
      const img = new Image();
      img.onload = () => {
        if (cancelled || !canvas.current) return;
        const c = canvas.current;
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
        c.getContext("2d")?.drawImage(img, 0, 0);
        setAspect(img.naturalWidth / img.naturalHeight);
        setLoaded(url);
      };
      img.onerror = () => {
        if (cancelled) return;
        setFailure({ url, message: "The image could not be decoded." });
      };
      img.src = drawing.url;
      return () => {
        cancelled = true;
      };
    }
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdfjs/pdf.worker.min.mjs";
        const doc = await pdfjs.getDocument({ url: drawing.url, standardFontDataUrl: "/pdfjs/standard_fonts/" }).promise;
        const page = await doc.getPage(1);
        const base = page.getViewport({ scale: 1 });
        const vp = page.getViewport({ scale: Math.min(3, 2600 / base.width) });
        if (cancelled || !canvas.current) return;
        const c = canvas.current;
        c.width = Math.round(vp.width);
        c.height = Math.round(vp.height);
        const rt = page.render({ canvas: c, viewport: vp });
        task = rt;
        await rt.promise;
        if (cancelled) return;
        setAspect(vp.width / vp.height);
        setLoaded(url);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        if (/cancel/i.test(msg)) return;
        setFailure({ url, message: msg });
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [drawing.url, drawing.kind]);

  React.useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // page box fitted inside the container at scale 1
  const fit = React.useMemo(() => {
    if (!aspect || !size.w || !size.h) return { w: 0, h: 0, ox: 0, oy: 0 };
    const w = Math.min(size.w, size.h * aspect);
    const h = w / aspect;
    return { w, h, ox: (size.w - w) / 2, oy: (size.h - h) / 2 };
  }, [aspect, size]);

  const clamp = React.useCallback(
    (v: View): View => {
      const s = Math.min(MAX, Math.max(MIN, v.s));
      const maxX = Math.max(0, (fit.w * s - size.w) / 2 + fit.ox * (s > 1 ? 1 : 0)) + (s > 1 ? size.w * 0.3 : 0);
      const maxY = Math.max(0, (fit.h * s - size.h) / 2) + (s > 1 ? size.h * 0.3 : 0);
      return { s, x: Math.min(maxX, Math.max(-maxX, v.x)), y: Math.min(maxY, Math.max(-maxY, v.y)) };
    },
    [fit, size],
  );
  const apply = React.useCallback(
    (fn: (v: View) => View, anim = false) => {
      setAnimate(anim);
      setView((v) => {
        const n = clamp(fn(v));
        if (n.s !== v.s) onZoom?.(n.s);
        return n;
      });
    },
    [clamp, onZoom],
  );
  const zoomBy = (k: number) => apply((v) => ({ s: v.s * k, x: v.x * k, y: v.y * k }), true);
  const reset = () => apply(() => ({ s: 1, x: 0, y: 0 }), true);

  // wheel zoom about the cursor (native listener: React's wheel is passive)
  React.useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const px = e.clientX - r.left - r.width / 2;
      const py = e.clientY - r.top - r.height / 2;
      const k = Math.exp(-e.deltaY * 0.0016);
      apply((v) => {
        const s = Math.min(MAX, Math.max(MIN, v.s * k));
        const f = s / v.s;
        return { s, x: px - (px - v.x) * f, y: py - (py - v.y) * f };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [apply]);

  // pan to an item's region whenever a selection is made anywhere in the app
  const itemsRef = React.useRef(items);
  React.useEffect(() => {
    itemsRef.current = items;
  }, [items]);
  React.useEffect(
    () =>
      useSelection.subscribe((sel, prev) => {
        if (sel.tick === prev.tick || !sel.itemId || !fit.w) return;
        const it = itemsRef.current.find((i) => i.id === sel.itemId);
        if (!it?.region) return;
        const cx = (it.region.x + it.region.w / 2 - 0.5) * fit.w;
        const cy = (it.region.y + it.region.h / 2 - 0.5) * fit.h;
        apply((v) => {
          const z = Math.max(v.s, 1.6);
          return { s: z, x: -cx * z, y: -cy * z };
        }, true);
      }),
    [apply, fit.w, fit.h],
  );

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true;
    if (d.moved) apply((v) => ({ s: v.s, x: d.vx + dx, y: d.vy + dy }));
  };
  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved || !pinning || !onAddPin || !wrap.current) return;
    const r = wrap.current.getBoundingClientRect();
    const px = (e.clientX - r.left - r.width / 2 - view.x) / view.s / fit.w + 0.5;
    const py = (e.clientY - r.top - r.height / 2 - view.y) / view.s / fit.h + 0.5;
    if (px < 0 || px > 1 || py < 0 || py > 1) return;
    onAddPin({ page: 1, x: Math.max(0, px - 0.015), y: Math.max(0, py - 0.02), w: 0.03, h: 0.04 });
    setPinning(false);
  };
  const onKey = (e: React.KeyboardEvent) => {
    const step = 40;
    if (e.key === "+" || e.key === "=") zoomBy(1.25);
    else if (e.key === "-") zoomBy(0.8);
    else if (e.key === "0") reset();
    else if (e.key === "ArrowLeft") apply((v) => ({ ...v, x: v.x + step }));
    else if (e.key === "ArrowRight") apply((v) => ({ ...v, x: v.x - step }));
    else if (e.key === "ArrowUp") apply((v) => ({ ...v, y: v.y + step }));
    else if (e.key === "ArrowDown") apply((v) => ({ ...v, y: v.y - step }));
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  // modeled outline in page units (1000 wide)
  const reg = drawing.registration;
  const overlay = React.useMemo(() => {
    if (!outline || !reg || !plan?.outline || !aspect) return null;
    const U = 1000;
    const V = U / reg.aspect;
    const ox = reg.originX * U;
    const oy = reg.originY * V;
    const k = reg.scale * U;
    const seen = new Set<string>();
    const holes = plan.operations
      .flatMap((o) => o.locators ?? [])
      .filter((l) => l.kind === "hole" && l.radius)
      .filter((l) => {
        const key = `${l.position[0].toFixed(2)},${l.position[1].toFixed(2)},${l.radius}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    return { U, V, ox, oy, k, holes };
  }, [outline, reg, plan, aspect]);

  const pins = comments.filter((c) => c.region && !c.resolved);

  return (
    <div
      ref={wrap}
      tabIndex={0}
      role="group"
      aria-label={`Source drawing ${drawing.fileName}. Drag to pan, scroll to zoom. Plus and minus zoom, arrows pan, zero resets.`}
      onKeyDown={onKey}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => (drag.current = null)}
      className={cn("well relative isolate min-h-[240px] touch-none select-none overflow-hidden", pinning ? "cursor-crosshair" : "cursor-grab active:cursor-grabbing", className)}
    >
      <div
        className="absolute left-1/2 top-1/2"
        style={{
          width: fit.w || "100%",
          height: fit.h || "100%",
          transform: `translate(-50%, -50%) translate(${view.x}px, ${view.y}px) scale(${view.s})`,
          transition: animate ? "transform .28s cubic-bezier(.22,1,.36,1)" : "none",
          visibility: state === "ready" ? "visible" : "hidden",
        }}
      >
        <canvas ref={canvas} className="block size-full rounded-[3px] shadow-[0_6px_30px_rgba(0,0,0,.6)]" aria-hidden />

        {overlay && (
          <svg viewBox={`0 0 ${overlay.U} ${overlay.V}`} className="pointer-events-none absolute inset-0 size-full" style={{ opacity: outlineOpacity }} aria-hidden>
            <g fill="none" stroke="#C0841A" strokeWidth={2.4 / Math.sqrt(view.s)} vectorEffect="non-scaling-stroke">
              {plan?.outline?.kind === "circle" ? (
                <circle cx={overlay.ox} cy={overlay.oy} r={(plan.outline.diameter / 2) * overlay.k} />
              ) : plan?.outline ? (
                <rect
                  x={overlay.ox - (plan.outline.width / 2) * overlay.k}
                  y={overlay.oy - (plan.outline.height / 2) * overlay.k}
                  width={plan.outline.width * overlay.k}
                  height={plan.outline.height * overlay.k}
                />
              ) : null}
            </g>
            <g fill="rgba(214,150,30,.30)" stroke="#B36B00" strokeWidth={2}>
              {overlay.holes.map((l, i) => (
                <circle key={i} cx={overlay.ox + l.position[0] * overlay.k} cy={overlay.oy - l.position[1] * overlay.k} r={(l.radius ?? 0) * overlay.k} vectorEffect="non-scaling-stroke" />
              ))}
            </g>
          </svg>
        )}

        {items.map((it) => {
          if (!it.region) return null;
          const sel = it.id === itemId;
          const band = confidenceBand(it.confidence);
          return (
            <button
              key={it.id}
              type="button"
              aria-label={`${it.id} ${it.label}: ${it.value}. ${it.status.replace("_", " ")}, confidence ${it.confidence.toFixed(2)}`}
              aria-pressed={sel}
              title={`${it.id} · ${it.label}: ${it.value}`}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => select({ itemId: it.id, featureId: it.featureId ?? null })}
              className={cn(
                "absolute rounded-[3px] border-2 transition-[box-shadow,border-color,background-color] duration-150",
                heatmap ? HEAT[band] : STATUS_BOX[it.status],
                sel && "z-10 !border-[#b8860b] !bg-[#d6af6b]/25 shadow-[0_0_0_3px_rgba(214,175,107,.55),0_0_18px_rgba(214,175,107,.7)]",
              )}
              style={{ left: `${it.region.x * 100}%`, top: `${it.region.y * 100}%`, width: `${it.region.w * 100}%`, height: `${it.region.h * 100}%`, borderWidth: Math.max(1, 2 / view.s) }}
            />
          );
        })}

        {pins.map((c, i) => (
          <span
            key={c.id}
            title={`${c.author}: ${c.body}`}
            className="num absolute grid size-5 -translate-y-1/2 translate-x-1/2 place-items-center rounded-full border border-[#1b1206] bg-[#d6af6b] text-[10px] font-bold text-[#1b1206] shadow-md"
            style={{ left: `${((c.region as Region).x + (c.region as Region).w) * 100}%`, top: `${(c.region as Region).y * 100}%`, transform: `translate(-50%,-50%) scale(${1 / view.s})` }}
          >
            {i + 1}
          </span>
        ))}
      </div>

      {state === "loading" && (
        <div className="absolute inset-0 grid place-items-center" role="status">
          <div className="flex flex-col items-center gap-3">
            <div className="skel h-28 w-40" />
            <span className="text-sm text-muted-foreground">Rendering the drawing…</span>
          </div>
        </div>
      )}
      {state === "error" && (
        <div className="absolute inset-0 grid place-items-center p-6">
          <div role="alert" className="max-w-sm rounded-xl border border-danger/50 bg-danger/10 p-4">
            <p className="text-sm font-semibold text-danger">The drawing could not be rendered</p>
            <p className="mt-1 text-[13px] text-text/90">{error}</p>
          </div>
        </div>
      )}

      <div className="absolute left-2 top-2 z-10 flex items-center gap-1.5" role="toolbar" aria-label="Drawing tools" onPointerDown={(e) => e.stopPropagation()}>
        <button type="button" className="btn btn-icon btn-sm glass-raised rounded-lg text-muted-foreground hover:text-text" aria-label="Zoom out" title="Zoom out (-)" onClick={() => zoomBy(0.8)}>
          <Minus className="size-4" aria-hidden />
        </button>
        <span className="num glass-raised grid h-[30px] min-w-12 place-items-center rounded-lg px-1.5 text-xs text-text">{Math.round(view.s * 100)}%</span>
        <button type="button" className="btn btn-icon btn-sm glass-raised rounded-lg text-muted-foreground hover:text-text" aria-label="Zoom in" title="Zoom in (+)" onClick={() => zoomBy(1.25)}>
          <Plus className="size-4" aria-hidden />
        </button>
        <button type="button" className="btn btn-icon btn-sm glass-raised rounded-lg text-muted-foreground hover:text-text" aria-label="Fit drawing" title="Fit (0)" onClick={reset}>
          <Scan className="size-4" aria-hidden />
        </button>
        {onAddPin && (
          <button
            type="button"
            className="btn btn-icon btn-sm glass-raised rounded-lg text-muted-foreground hover:text-text"
            aria-label="Pin a comment to a spot on the drawing"
            title="Pin a comment to a spot on the drawing"
            aria-pressed={pinning}
            onClick={() => setPinning((p) => !p)}
          >
            <MessageSquarePlus className="size-4" aria-hidden />
          </button>
        )}
      </div>
      {pinning && (
        <div className="glass-raised absolute bottom-12 left-1/2 z-10 -translate-x-1/2 px-3 py-1.5 text-xs text-text" role="status">
          Click the spot on the drawing to pin a comment.
        </div>
      )}
      <div className="pointer-events-none absolute inset-x-2 bottom-2 z-10 flex flex-wrap items-center justify-end gap-1.5">
        {heatmap && <Stamp tone="warn">Confidence heatmap</Stamp>}
        {overlay && <Stamp tone="gold">Modeled outline</Stamp>}
        <span className="num rounded-md border border-line bg-[#0d0919]/85 px-1.5 py-0.5 text-[11px] text-muted-foreground">
          {drawing.fileName} · {drawing.kind.toUpperCase()}
          {drawing.sizeBytes ? ` · ${fmtBytes(drawing.sizeBytes)}` : ""}
        </span>
        {isSample && <SampleBadge />}
      </div>
    </div>
  );
}
