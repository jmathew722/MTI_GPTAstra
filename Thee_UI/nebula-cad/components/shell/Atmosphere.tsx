"use client";

import * as React from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { DrawSVGPlugin } from "gsap/DrawSVGPlugin";
import { cn } from "@/lib/utils";
import { SPECS, holePositions, type SampleKey } from "@/lib/data/seed";

gsap.registerPlugin(useGSAP, DrawSVGPlugin);

/** Gold isometric cube mark. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={cn("size-10", className)} aria-hidden>
      <defs>
        <linearGradient id="lg-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#F5E6CB" />
          <stop offset="1" stopColor="#C99A4E" />
        </linearGradient>
        <filter id="lg-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.2" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g fill="none" stroke="url(#lg-gold)" strokeWidth="2.2" strokeLinejoin="round" filter="url(#lg-glow)">
        <path d="M24 4 41 14v20L24 44 7 34V14Z" />
        <path d="M7 14l17 10 17-10M24 24v20" />
      </g>
    </svg>
  );
}

/**
 * Fixed background: gradients, a dozen 1px stars (CSS) and thin violet lightning tracers
 * in two corners. No planet, moon, globe or other celestial body.
 * GSAP draws the tracers once, then breathes their opacity slowly.
 */
export function Nebula() {
  const ref = React.useRef<SVGSVGElement>(null);
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        if (document.documentElement.dataset.motion === "reduced") return;
        gsap.from(".arc", { drawSVG: "0%", duration: 2.4, ease: "power2.out", stagger: 0.18 });
        const breathe = gsap.to(".arc-group", { opacity: 0.45, duration: 7, ease: "sine.inOut", yoyo: true, repeat: -1, stagger: 2.5 });
        const onVis = () => (document.hidden ? breathe.pause() : breathe.resume());
        document.addEventListener("visibilitychange", onVis);
        return () => document.removeEventListener("visibilitychange", onVis);
      });
      return () => mm.revert();
    },
    { scope: ref },
  );
  return (
    <div className="nebula" aria-hidden>
      <svg ref={ref} className="absolute inset-0 size-full" preserveAspectRatio="none" viewBox="0 0 1440 900" fill="none">
        <defs>
          <linearGradient id="arc-v" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#A67CFF" stopOpacity="0" />
            <stop offset=".5" stopColor="#B994FF" stopOpacity=".8" />
            <stop offset="1" stopColor="#A67CFF" stopOpacity="0" />
          </linearGradient>
          <filter id="arc-blur">
            <feGaussianBlur stdDeviation="1.2" />
          </filter>
        </defs>
        {/* top-left corner */}
        <g className="arc-group" opacity=".8" stroke="url(#arc-v)" strokeWidth="1" strokeLinecap="round">
          <path className="arc" d="M0 148 L46 120 L70 126 L118 84 L150 90 L214 36 L252 40 L300 0" />
          <path className="arc" d="M118 84 L132 52 L170 30 L182 0" opacity=".6" />
          <path className="arc" d="M0 148 L46 120 L70 126 L118 84 L150 90 L214 36 L252 40 L300 0" strokeWidth="3" filter="url(#arc-blur)" opacity=".35" />
        </g>
        {/* bottom-right corner */}
        <g className="arc-group" opacity=".8" stroke="url(#arc-v)" strokeWidth="1" strokeLinecap="round">
          <path className="arc" d="M1440 716 L1392 748 L1366 742 L1316 796 L1280 792 L1230 852 L1196 850 L1160 900" />
          <path className="arc" d="M1316 796 L1300 834 L1262 860 L1252 900" opacity=".6" />
          <path className="arc" d="M1440 716 L1392 748 L1366 742 L1316 796 L1280 792 L1230 852 L1196 850 L1160 900" strokeWidth="3" filter="url(#arc-blur)" opacity=".35" />
        </g>
      </svg>
    </div>
  );
}

/** Small technical glyph of a part drawn from its spec; used as a project thumbnail. */
export function PartGlyph({ specKey, className, modeled = true }: { specKey?: string | null; className?: string; modeled?: boolean }) {
  const spec = specKey ? SPECS[specKey as SampleKey] : undefined;
  if (!spec)
    return (
      <svg viewBox="0 0 48 48" className={className} aria-hidden>
        <g fill="none" stroke="#ABA1BD" strokeWidth="1.6" strokeLinejoin="round">
          <path d="M24 8 38 16v16L24 40 10 32V16Z" />
          <path d="M10 16l14 8 14-8M24 24v16" />
        </g>
      </svg>
    );
  const circle = spec.outline.kind === "circle";
  const half = circle ? (spec.outline.diameter ?? 0) / 2 : Math.max(spec.outline.width ?? 0, spec.outline.height ?? 0) / 2;
  const k = 20 / half;
  const holes = holePositions(modeled ? spec.modelHoles : spec.drawingHoles);
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden>
      <g fill="rgba(214,175,107,.08)" stroke="#D6AF6B" strokeWidth="1.3">
        {circle ? (
          <circle cx="24" cy="24" r={half * k} />
        ) : (
          <rect x={24 - ((spec.outline.width ?? 0) / 2) * k} y={24 - ((spec.outline.height ?? 0) / 2) * k} width={(spec.outline.width ?? 0) * k} height={(spec.outline.height ?? 0) * k} rx="1.5" />
        )}
      </g>
      <g fill="#0B0814" stroke="#A67CFF" strokeWidth="1">
        <circle cx="24" cy="24" r={(spec.bore / 2) * k} />
        {holes.map(([x, y], i) => (
          <circle key={i} cx={24 + x * k} cy={24 - y * k} r={Math.max(1.1, (spec.modelHoles.diameter / 2) * k)} />
        ))}
      </g>
    </svg>
  );
}
