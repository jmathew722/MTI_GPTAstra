"use client";

import * as React from "react";
import Link from "next/link";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { animate, motion, useInView } from "motion/react";
import { Box, Layers, Play, ShieldCheck, Upload, Zap } from "lucide-react";
import { useIntro } from "@/components/shell/Providers";
import { ErrorState, Glass, SampleBadge, Skel } from "@/components/shared";
import { useKpis } from "@/lib/api/hooks";
import { fmtSeconds } from "@/lib/format";
import { fadeUp, stagger } from "@/lib/motion";
import { cn } from "@/lib/utils";

gsap.registerPlugin(useGSAP);

const WAVES: [string, string][] = [
  ["M0 150 C 120 120, 220 190, 340 140 S 520 60, 640 110 S 760 150, 800 90", "M0 140 C 130 170, 230 110, 350 150 S 510 110, 640 80 S 770 110, 800 120"],
  ["M0 180 C 140 150, 240 210, 360 160 S 540 90, 660 130 S 770 170, 800 120", "M0 170 C 120 200, 250 140, 370 175 S 530 130, 650 105 S 780 130, 800 150"],
  ["M0 205 C 150 185, 260 235, 380 190 S 560 125, 680 160 S 780 195, 800 150", "M0 200 C 140 225, 250 175, 390 205 S 550 160, 670 135 S 790 160, 800 180"],
];

/** Flowing violet and gold energy lines. SVG paths tweened by GSAP: slow, low contrast, behind the text. */
export function EnergyWaves({ className }: { className?: string }) {
  const ref = React.useRef<SVGSVGElement>(null);
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        if (document.documentElement.dataset.motion === "reduced") return;
        const tweens = WAVES.map(([, to], i) =>
          gsap.to(`.wave-${i}`, { attr: { d: to }, duration: 9 + i * 2.5, ease: "sine.inOut", yoyo: true, repeat: -1 }),
        );
        const onVis = () => tweens.forEach((t) => (document.hidden ? t.pause() : t.resume()));
        document.addEventListener("visibilitychange", onVis);
        return () => document.removeEventListener("visibilitychange", onVis);
      });
      return () => mm.revert();
    },
    { scope: ref },
  );
  return (
    <svg ref={ref} viewBox="0 0 800 260" preserveAspectRatio="none" className={cn("pointer-events-none", className)} aria-hidden fill="none">
      <defs>
        <linearGradient id="wave-vg" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#A67CFF" stopOpacity="0" />
          <stop offset=".35" stopColor="#A67CFF" stopOpacity=".75" />
          <stop offset=".7" stopColor="#E9C689" stopOpacity=".95" />
          <stop offset="1" stopColor="#A67CFF" stopOpacity=".15" />
        </linearGradient>
        <linearGradient id="wave-v" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#A67CFF" stopOpacity="0" />
          <stop offset=".6" stopColor="#8f63f0" stopOpacity=".6" />
          <stop offset="1" stopColor="#A67CFF" stopOpacity="0" />
        </linearGradient>
        <filter id="wave-glow" x="-10%" y="-60%" width="120%" height="220%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
        <radialGradient id="wave-haze" cx=".72" cy=".42" r=".5">
          <stop offset="0" stopColor="#D6AF6B" stopOpacity=".2" />
          <stop offset=".5" stopColor="#A67CFF" stopOpacity=".1" />
          <stop offset="1" stopColor="#A67CFF" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="800" height="260" fill="url(#wave-haze)" />
      <path className="wave-0" d={WAVES[0][0]} stroke="url(#wave-vg)" strokeWidth="7" filter="url(#wave-glow)" opacity=".7" />
      <path className="wave-0" d={WAVES[0][0]} stroke="url(#wave-vg)" strokeWidth="1.6" />
      <path className="wave-1" d={WAVES[1][0]} stroke="url(#wave-v)" strokeWidth="1.1" />
      <path className="wave-2" d={WAVES[2][0]} stroke="url(#wave-v)" strokeWidth=".8" opacity=".7" />
    </svg>
  );
}

export function Hero() {
  const intro = useIntro();
  const ref = React.useRef<HTMLDivElement>(null);
  // Spotlight (in-house, after Aceternity's idea): a soft light that follows the pointer.
  const onMove = (e: React.PointerEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--sx", `${e.clientX - r.left}px`);
    el.style.setProperty("--sy", `${e.clientY - r.top}px`);
  };
  return (
    <Glass ref={ref} as="section" onPointerMove={onMove} className="glass-solid group relative overflow-hidden" aria-label="From drawings to CAD">
      <EnergyWaves className="absolute inset-y-0 right-0 h-full w-[68%] opacity-90" />
      <div className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100" style={{ background: "radial-gradient(280px circle at var(--sx, 50%) var(--sy, 50%), rgba(214,175,107,.10), transparent 70%)" }} aria-hidden />
      <div className="pointer-events-none absolute inset-y-0 left-0 w-[62%] bg-gradient-to-r from-[#150f24] via-[#150f24]/85 to-transparent" aria-hidden />
      <motion.div variants={stagger(0.25)} initial={intro ? "hidden" : false} animate="show" className="relative z-10 flex flex-col gap-3 p-6 sm:p-7">
        <motion.div variants={fadeUp} className="eyebrow flex items-center gap-3 text-gold">
          Design automation <span className="h-px w-24 bg-gradient-to-r from-gold/70 to-transparent" aria-hidden />
        </motion.div>
        <motion.h1 variants={fadeUp} className="text-[32px] font-bold leading-[36px] tracking-[-0.02em] sm:text-[44px] sm:leading-[48px]">
          From Drawings to <span className="bg-gradient-to-b from-[#F5E6CB] to-[#D6AF6B] bg-clip-text text-transparent">CAD</span>
        </motion.h1>
        <motion.p variants={fadeUp} className="max-w-[52ch] text-[15px] leading-6 text-text/85">
          AI-driven extraction, parametric modeling, and validation. Every result is checked against its drawing before you trust it.
        </motion.p>
        <motion.div variants={fadeUp} className="mt-2 flex flex-wrap gap-3">
          <Link href="/automation" className="btn btn-lg btn-primary relative overflow-hidden">
            <Play className="size-4 fill-current" aria-hidden /> Generate CAD
          </Link>
          <Link href="/automation?step=upload" className="btn btn-lg btn-outline">
            <Upload className="size-4" aria-hidden /> Upload Drawing
          </Link>
        </motion.div>
      </motion.div>
    </Glass>
  );
}

/* ---------------------------------------------------------------- KPIs */

/** Counts up once when first seen (in-house, after Magic UI's Number Ticker). */
export function NumberTicker({ value, format, className }: { value: number; format: (n: number) => string; className?: string }) {
  const ref = React.useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const played = React.useRef(false);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!inView || played.current || document.documentElement.dataset.motion === "reduced" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.textContent = format(value);
      if (inView) played.current = true;
      return;
    }
    played.current = true;
    const c = animate(0, value, { duration: 1.1, ease: [0.22, 1, 0.36, 1], onUpdate: (v) => (el.textContent = format(v)) });
    return () => c.stop();
  }, [inView, value, format]);
  return (
    <span ref={ref} className={className}>
      {format(value)}
    </span>
  );
}

export function Sparkline({ data, className, color = "#A67CFF" }: { data: number[]; className?: string; color?: string }) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const pts = data.map((v, i) => [(i / (data.length - 1)) * 100, 26 - ((v - min) / (max - min || 1)) * 22] as const);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className={className} aria-hidden>
      <path d={`${d} L100 30 L0 30 Z`} fill={color} opacity=".12" />
      <path d={d} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const fInt = (n: number) => String(Math.round(n));
const fPct = (n: number) => `${(n * 100).toFixed(1)}%`;

export function KpiRow() {
  const intro = useIntro();
  const q = useKpis();
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} className="m-0" />;
  const k = q.data;
  const cards = k
    ? [
        { icon: <Box />, label: "Models Generated", value: k.modelsGenerated, format: fInt, trend: k.trends.modelsGenerated, tone: "" },
        { icon: <ShieldCheck />, label: "Validation Rate", value: k.validationRate, format: fPct, trend: k.trends.validationRate, tone: k.validationRate < 0.95 ? "text-warn" : "", hint: "checks that ran and passed" },
        { icon: <Zap />, label: "Avg. Build Time", value: k.avgBuildSeconds, format: fmtSeconds, trend: k.trends.avgBuildSeconds, tone: "" },
        { icon: <Layers />, label: "Pipeline Errors", value: k.pipelineErrors, format: fInt, trend: k.trends.pipelineErrors, tone: k.pipelineErrors > 0 ? "text-danger" : "" },
      ]
    : [];
  return (
    <section aria-label="Key metrics">
      {k?.isSample && (
        <div className="mb-2 flex items-center gap-2 px-1">
          <span className="eyebrow">Key metrics</span>
          <SampleBadge />
          <span className="text-[11px] text-faint">computed from the seeded sample runs</span>
        </div>
      )}
    <motion.div variants={stagger(0.45)} initial={intro ? "hidden" : false} animate="show" className="grid grid-cols-2 gap-4 xl:grid-cols-4">
      {!k
        ? [0, 1, 2, 3].map((i) => <Skel key={i} className="h-[92px] rounded-2xl" />)
        : cards.map((c) => (
            <motion.div key={c.label} variants={fadeUp} className="glass-flat lift relative overflow-hidden p-4" title={c.hint}>
              <Sparkline data={c.trend} className="absolute bottom-0 right-0 h-10 w-[55%]" />
              <div className="relative flex items-center gap-3">
                <span className="text-gold [&_svg]:size-7 [&_svg]:stroke-[1.6]">{c.icon}</span>
                <div className="min-w-0">
                  <NumberTicker value={c.value} format={c.format} className={cn("num block text-2xl font-semibold leading-7", c.tone || "text-text")} />
                  <div className="truncate text-xs text-muted-foreground">{c.label}</div>
                </div>
              </div>
            </motion.div>
          ))}
    </motion.div>
    </section>
  );
}
