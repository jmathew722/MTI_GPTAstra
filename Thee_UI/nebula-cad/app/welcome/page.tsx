"use client";

import * as React from "react";
import Link from "next/link";
import { motion } from "motion/react";
import { ArrowRight, Eye, FileSearch, Hammer, Play, ScanLine, ShieldCheck } from "lucide-react";
import { EnergyWaves, NumberTicker } from "@/components/hero/Hero";
import { Logo } from "@/components/shell/Atmosphere";
import { SampleBadge, Stamp } from "@/components/shared";
import { ModelViewer } from "@/components/viewer";
import { IS_MOCK } from "@/lib/api";
import { useBuildPlan, useExtraction, useKpis, useProject } from "@/lib/api/hooks";
import { SAMPLE_PROJECT_IDS } from "@/lib/data/seed";
import { fmtSeconds } from "@/lib/format";
import { dur, ease } from "@/lib/motion";

const reveal = {
  initial: { opacity: 0, y: 24 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, margin: "-80px" },
  transition: { duration: dur.entrance, ease: ease.out },
} as const;

const STEPS = [
  { icon: <ScanLine />, title: "Analyze the drawing", body: "A scanned sheet, sometimes forty years old, is read as a whole: views, title block, notes and global callouts." },
  { icon: <FileSearch />, title: "Extract the features", body: "Dimensions, holes, tolerances and units come back as structured data, each with a confidence and the spot on the sheet it came from." },
  { icon: <Hammer />, title: "Generate the model", body: "An ordered build plan drives SolidWorks to a real part with a full, editable feature tree." },
  { icon: <ShieldCheck />, title: "Validate the geometry", body: "Counts, dimensions and the envelope are measured on the built part and compared with the drawing." },
];

const fInt = (n: number) => String(Math.round(n));
const fPct = (n: number) => `${(n * 100).toFixed(0)}%`;

export default function WelcomePage() {
  const id = SAMPLE_PROJECT_IDS.flange;
  const { data: project } = useProject(IS_MOCK ? id : null);
  const { data: plan } = useBuildPlan(IS_MOCK ? id : null);
  const { data: ex } = useExtraction(IS_MOCK ? id : null);
  const { data: kpis } = useKpis();
  const expected = ex?.countChecks.flatMap((c) => c.expectedPositions ?? []).map(([x, y, r]) => ({ x, y, r }));
  const [diff, setDiff] = React.useState(true);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-24 px-4 pb-24 sm:px-6">
      <header className="flex items-center gap-3 py-5">
        <Logo />
        <span className="text-lg font-semibold tracking-[0.22em]">2D TO 3D <span className="text-gold">CAD</span></span>
        <Link href="/dashboard" className="btn btn-outline ml-auto">Open the app <ArrowRight className="size-4" aria-hidden /></Link>
      </header>

      <main id="main" className="flex flex-col gap-24">
        <section className="relative overflow-hidden rounded-[28px] border border-line bg-[#120d20]/70 px-6 py-16 sm:px-12 sm:py-24" aria-label="Introduction">
          <EnergyWaves className="absolute inset-0 size-full opacity-80" />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-[#0f0a1c] via-[#0f0a1c]/80 to-transparent" aria-hidden />
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease: ease.out }} className="relative max-w-2xl">
            <div className="eyebrow text-gold">Design automation for legacy drawings</div>
            <h1 className="mt-3 text-4xl font-bold leading-[1.05] tracking-[-0.02em] sm:text-6xl">
              From drawings to <span className="bg-gradient-to-b from-[#F5E6CB] to-[#D6AF6B] bg-clip-text text-transparent">CAD</span>, with the mistakes in plain sight.
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-7 text-text/85">
              An AI pipeline turns a scanned 2D drawing into a SolidWorks part. 2D to 3D CAD is where an engineer checks that the part is right before anyone trusts it.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/automation" className="btn btn-lg btn-primary"><Play className="size-4 fill-current" aria-hidden /> Generate CAD</Link>
              <Link href={`/projects/${id}`} className="btn btn-lg btn-outline"><Eye className="size-4" aria-hidden /> See a failure it caught</Link>
            </div>
          </motion.div>
        </section>

        <section aria-labelledby="how">
          <motion.div {...reveal}>
            <div className="eyebrow text-gold">How it works</div>
            <h2 id="how" className="mt-2 text-3xl font-semibold tracking-tight">Four stages, then a person.</h2>
          </motion.div>
          <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <motion.li key={s.title} {...reveal} transition={{ ...reveal.transition, delay: i * 0.08 }} className="glass-flat lift p-5">
                <div className="flex items-center gap-3">
                  <span className="num grid size-8 place-items-center rounded-full border border-gold/50 bg-gold/10 text-sm font-bold text-gold-hi">{i + 1}</span>
                  <span className="text-gold [&_svg]:size-6 [&_svg]:stroke-[1.6]">{s.icon}</span>
                </div>
                <h3 className="mt-4 text-base font-semibold">{s.title}</h3>
                <p className="mt-1 text-[13px] leading-6 text-muted-foreground">{s.body}</p>
              </motion.li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="demo" className="grid items-center gap-8 lg:grid-cols-[1fr_1.25fr]">
          <motion.div {...reveal}>
            <div className="eyebrow text-gold">Live viewer</div>
            <h2 id="demo" className="mt-2 text-3xl font-semibold tracking-tight">It looked right. It had 8 holes. The drawing says 10.</h2>
            <p className="mt-4 text-[15px] leading-7 text-text/85">
              The tool does not fail loudly. It fails quietly, with a clean model and a high confidence score. This is that model: orbit it. The red rings mark the holes the drawing calls for and the model does not have.
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button type="button" className="btn btn-ghost" aria-pressed={diff} onClick={() => setDiff((d) => !d)}>Show what is missing</button>
              <Link href={`/projects/${id}`} className="btn btn-outline">Open the full review <ArrowRight className="size-4" aria-hidden /></Link>
            </div>
          </motion.div>
          <motion.div {...reveal} className="h-[420px]">
            {IS_MOCK ? (
              <ModelViewer modelUrl={project?.modelUrl} fileName="flange.stl" plan={plan} expected={expected?.length ? expected : undefined} showDiff={diff} specKey="flange" isSample allowLoad={false} compact className="size-full" />
            ) : (
              <div className="well grid size-full place-items-center p-6 text-center text-sm text-muted-foreground">Open a project in the app to inspect a real model.</div>
            )}
          </motion.div>
        </section>

        <section aria-labelledby="numbers">
          <motion.div {...reveal} className="flex items-center gap-3">
            <h2 id="numbers" className="text-3xl font-semibold tracking-tight">By the numbers</h2>
            {kpis?.isSample && <SampleBadge />}
          </motion.div>
          <motion.dl {...reveal} className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              ["Models generated", kpis?.modelsGenerated, fInt],
              ["Checks that ran and passed", kpis?.validationRate, fPct],
              ["Average build time", kpis?.avgBuildSeconds, fmtSeconds],
              ["Pipeline errors", kpis?.pipelineErrors, fInt],
            ].map(([label, value, format]) => (
              <div key={label as string} className="glass-flat p-5">
                <dd className="num text-4xl font-semibold text-gold-hi">
                  {typeof value === "number" ? <NumberTicker value={value} format={format as (n: number) => string} /> : "–"}
                </dd>
                <dt className="mt-1 text-[13px] text-muted-foreground">{label as string}</dt>
              </div>
            ))}
          </motion.dl>
          <p className="mt-3 text-xs text-faint">{kpis?.isSample ? "These figures come from the bundled sample runs, not from production." : "Live figures from the connected pipeline."}</p>
        </section>

        <section aria-labelledby="trust" className="grid gap-4 lg:grid-cols-3">
          <motion.div {...reveal} className="lg:col-span-3">
            <div className="eyebrow text-gold">Trust, by construction</div>
            <h2 id="trust" className="mt-2 text-3xl font-semibold tracking-tight">Nothing is called verified until it is.</h2>
          </motion.div>
          {[
            ["A check that did not run says so", "“Not run” is its own state. It is never rolled into a pass rate, and a not-run critical check blocks export.", <Stamp key="s" tone="dashed">Not run</Stamp>],
            ["Overrides carry a name and a reason", "A blocked export or a capped grade can be released only by a reviewer who writes down why. It lands in the audit trail and the report.", <Stamp key="s" tone="warn">Overridden</Stamp>],
            ["Every number traces to the sheet", "Click an extracted value to see the region of the drawing it was read from and the feature it built.", <Stamp key="s" tone="gold">Source linked</Stamp>],
          ].map(([t, b, stamp], i) => (
            <motion.div key={t as string} {...reveal} transition={{ ...reveal.transition, delay: i * 0.08 }} className="glass-flat p-5">
              {stamp}
              <h3 className="mt-3 text-base font-semibold">{t}</h3>
              <p className="mt-1 text-[13px] leading-6 text-muted-foreground">{b}</p>
            </motion.div>
          ))}
        </section>

        <motion.section {...reveal} className="glass-flat glass-active flex flex-col items-center gap-4 px-6 py-12 text-center" aria-label="Get started">
          <h2 className="text-3xl font-semibold tracking-tight">Start with one drawing.</h2>
          <p className="max-w-xl text-[15px] leading-7 text-text/85">Upload a PDF, see the estimated cost and time, and review the result side by side with the sheet it came from.</p>
          <Link href="/automation" className="btn btn-lg btn-primary"><Play className="size-4 fill-current" aria-hidden /> Generate CAD</Link>
        </motion.section>
      </main>
    </div>
  );
}
