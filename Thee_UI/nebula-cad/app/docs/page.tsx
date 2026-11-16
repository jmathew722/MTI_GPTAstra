"use client";

import * as React from "react";
import { SHORTCUTS } from "@/components/shell/Overlays";
import { Glass, PageHeader } from "@/components/shared";
import { DENSITY_G_CM3, MATERIAL_LABEL } from "@/lib/cost";
import { DEFAULT_CRITERIA } from "@/lib/rubric";
import type { MaterialKey } from "@/lib/schemas";

const TOC = [
  ["pipeline", "How the pipeline works"],
  ["quiet-failure", "Why the UI is loud"],
  ["validation", "Validation checks"],
  ["rubric", "Rubric guide"],
  ["cost", "Cost formulas"],
  ["data", "Sample data and the backend"],
  ["shortcuts", "Keyboard shortcuts"],
  ["licenses", "Licenses"],
] as const;

const CHECKS: [string, string, string][] = [
  ["Feature counts match the drawing", "Critical", "Compares three numbers for each counted feature: the count in the drawing callout, the instances extraction located, and the instances in the built model. Any disagreement fails. This is the check that catches a confident but wrong hole count."],
  ["Dimension deltas vs tolerance", "Critical", "Measures every extracted dimension on the built model and compares the difference with that dimension's tolerance."],
  ["Rebuild errors", "Critical", "Forces a rebuild of the SolidWorks part and fails on any error."],
  ["Bounding box vs drawing", "Major", "Compares the model's overall envelope with the overall dimensions on the drawing."],
  ["Sketches fully defined", "Major", "Every sketch in the feature tree must be fully defined, so later edits behave predictably."],
  ["Watertight geometry", "Major", "The exported mesh must be a closed solid with a positive volume."],
  ["Unit consistency", "Minor", "The drawing's unit note, the extraction units and the SolidWorks document units must agree."],
];

const LICENSES: [string, string, string][] = [
  ["occt-import-js", "LGPL-2.1", "WebAssembly build of OpenCASCADE Technology, used to read STEP, IGES and BREP files in the browser. It is loaded as a separate, replaceable file (public/occt-import-js.js and .wasm) and is not modified. OpenCASCADE Technology is LGPL-2.1 with an exception."],
  ["GSAP", "GSAP standard license", "Free to use, including the plugins, under GreenSock's standard license. That license does not permit building a tool that competes with Webflow's visual animation builder; this app does not."],
  ["pdf.js (pdfjs-dist)", "Apache-2.0", "Renders the source drawing in the browser."],
  ["axe-core", "MPL-2.0", "Accessibility testing only; not shipped to users."],
  ["Playwright", "Apache-2.0", "Testing only; not shipped to users."],
  ["Next.js, React, Tailwind CSS, shadcn/ui, Base UI, Motion, three.js, React Three Fiber, drei, react-postprocessing, TanStack Query/Table/Virtual, Zustand, Zod, Recharts, react-dropzone, react-hook-form, @react-pdf/renderer, Sonner, cmdk, Vitest", "MIT", "Used unmodified."],
  ["Lucide", "ISC", "Icons."],
  ["Inter, JetBrains Mono", "SIL Open Font License 1.1", "Fonts, self-hosted at build time by next/font."],
];

function H({ id, children }: { id: string; children: React.ReactNode }) {
  return <h2 id={id} className="scroll-mt-24 border-b border-line/50 pb-2 text-lg font-semibold">{children}</h2>;
}

export default function DocsPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Docs" description="How the pipeline works, what each check means, how parts are graded and costed, and what this app is built from." />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="On this page" className="glass-flat top-[92px] self-start p-3 lg:sticky">
          <div className="eyebrow px-2 pb-2">On this page</div>
          <ul className="flex flex-col">
            {TOC.map(([id, label]) => (
              <li key={id}>
                <a href={`#${id}`} className="block rounded-lg px-2 py-1.5 text-[13px] text-muted-foreground hover:bg-surface-raised/40 hover:text-text">{label}</a>
              </li>
            ))}
          </ul>
        </nav>
        <Glass flat as="section" className="flex max-w-[86ch] flex-col gap-4 p-6 text-sm leading-6 text-text/90">
          <H id="pipeline">How the pipeline works</H>
          <ol className="list-decimal space-y-1 pl-5">
            <li><strong>Analyze Drawing.</strong> The scanned sheet is prepared and read as a whole: which views exist, where the title block and notes are, which global callouts apply.</li>
            <li><strong>Extract Features.</strong> A vision model returns structured geometry: dimensions, holes, features, tolerances and units, each with a confidence and the region of the sheet it came from. A planner turns that into an ordered build plan.</li>
            <li><strong>Generate CAD Model.</strong> The build plan drives SolidWorks to construct the part with a full feature tree. The pipeline saves the .sldprt and, beside it, an STL copy that this viewer loads.</li>
            <li><strong>Validate Geometry.</strong> The built part is measured and compared with the drawing and the extraction.</li>
          </ol>
          <p>A human then reviews the extraction, compares drawing and model, and signs off.</p>

          <H id="quiet-failure">Why the UI is loud</H>
          <p>The pipeline rarely crashes. Its dangerous failure is quiet: it hands back a clean-looking model that is wrong, for example 8 bolt holes where the drawing calls for 10, read with high confidence. So this app treats three things as always more prominent than success: a mismatch, a low-confidence reading, and a result nobody has verified.</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>Confidence is never shown as verification. A high confidence stays neutral grey.</li>
            <li>A check that did not run says “Not run”. It is never counted as passed.</li>
            <li>A failed or not-run critical check blocks export until someone overrides it with a recorded reason.</li>
            <li>The rubric cannot rise above Needs rework while a critical mismatch stands.</li>
          </ul>

          <H id="validation">Validation checks</H>
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Table, scrolls horizontally">
            <table className="dtable min-w-[560px]">
              <thead><tr><th>Check</th><th>Severity</th><th>What it does</th></tr></thead>
              <tbody>
                {CHECKS.map(([n, s, d]) => (
                  <tr key={n}><td className="!h-auto py-2 align-top font-medium">{n}</td><td className="!h-auto py-2 align-top">{s}</td><td className="!h-auto py-2 text-[13px] leading-5 text-muted-foreground">{d}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>Statuses: <strong>Passed</strong> (ran, within limits), <strong>Warning</strong> (ran, needs attention), <strong>Failed</strong> (ran, outside limits), <strong>Not run</strong> (no result exists).</p>

          <H id="rubric">Rubric guide</H>
          <p>The rubric grades a generated part against its source drawing. Each criterion gets a level from 4 (Exemplary) to 1 (Insufficient), or 0 when the evidence is missing. Points = weight × level ÷ 4. Weights must sum to 100.</p>
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Table, scrolls horizontally">
            <table className="dtable min-w-[480px]">
              <thead><tr><th>Criterion</th><th className="r">Weight</th><th>Scored by</th></tr></thead>
              <tbody>
                {DEFAULT_CRITERIA.map((c) => (
                  <tr key={c.key}><td className="font-medium">{c.label}</td><td className="num r">{c.weight}</td><td className="capitalize text-muted-foreground">{c.scoredBy}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>Bands: A at 90 and above, B at 80, C at 70, below 70 needs rework. Release status is Approved (80 or more, no notes, no override), Approved with notes, or Needs rework.</p>
          <p><strong>Hard-fail gates.</strong> A wrong feature count, a critical dimension out of tolerance, or rebuild errors cap the release status at Needs rework whatever the score. A reviewer can lift the cap only by recording a reason, which goes into the audit trail and the exported rubric.</p>

          <H id="cost">Cost formulas</H>
          <p><strong>A. Pipeline run cost</strong> = input tokens × input rate + output tokens × output rate + vision calls × call rate + compute seconds × compute rate. Rates are assumptions until you confirm them in Settings.</p>
          <p><strong>B. Manufacturing estimate.</strong></p>
          <pre tabIndex={0} aria-label="Cost formulas" className="well num overflow-x-auto p-3 text-xs leading-6">{`material_cost = part_volume_cm3 * (1 + stock_allowance) * density_g_cm3 / 1000 * price_per_kg * (1 + scrap_pct)
machining_min = (stock_volume_cm3 - part_volume_cm3) / mrr_cm3_per_min + holes * t_hole_min + features * t_feature_min
unit_cost     = (material_cost + machining_min / 60 * machine_rate + setup_cost / qty + finishing + inspection) * (1 + overhead) * (1 + margin)`}</pre>
          <p>Densities (g/cm³, physical constants): {(Object.keys(DENSITY_G_CM3) as MaterialKey[]).map((m) => `${MATERIAL_LABEL[m].toLowerCase()} ${DENSITY_G_CM3[m].toFixed(2)}`).join(", ")}. Every dollar rate is an editable estimate.</p>
          <p><strong>C. Automation ROI.</strong> savings per part = manual rebuild hours × labor rate − (pipeline cost + review minutes ÷ 60 × labor rate).</p>

          <H id="data">Sample data and the backend</H>
          <p>By default the app runs on a mock adapter with three synthetic projects. Anything fed by it carries a SAMPLE DATA badge, and controls that cannot do real work without a backend carry a Demo tag. The sample drawings and models are generated by a script; no customer drawing is included.</p>
          <p>To connect the real pipeline, set <span className="num">NEXT_PUBLIC_API_MODE=http</span> and <span className="num">NEXT_PUBLIC_API_BASE_URL</span>. The service must implement the endpoints in <span className="num">docs/API_CONTRACT.md</span>; every response is validated against its schema before it is shown.</p>

          <H id="shortcuts">Keyboard shortcuts</H>
          <ul className="grid gap-x-8 sm:grid-cols-2">
            {SHORTCUTS.map((s) => (
              <li key={s.label} className="flex items-center justify-between gap-4 border-b border-line/40 py-1.5 text-[13px]">
                <span>{s.label}</span>
                <span className="flex shrink-0 gap-1">{s.keys.map((k, i) => (k === "…" ? <span key={i}>…</span> : <kbd key={i}>{k}</kbd>))}</span>
              </li>
            ))}
          </ul>

          <H id="licenses">Licenses</H>
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Table, scrolls horizontally">
            <table className="dtable min-w-[560px]">
              <thead><tr><th>Component</th><th>License</th><th>Notes</th></tr></thead>
              <tbody>
                {LICENSES.map(([n, l, d]) => (
                  <tr key={n}><td className="!h-auto max-w-[260px] py-2 align-top font-medium">{n}</td><td className="!h-auto whitespace-nowrap py-2 align-top">{l}</td><td className="!h-auto py-2 text-[13px] leading-5 text-muted-foreground">{d}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[13px] text-muted-foreground">LGPL notice: occt-import-js and OpenCASCADE Technology are distributed under the GNU Lesser General Public License 2.1. Their source is available from github.com/kovacsv/occt-import-js and dev.opencascade.org. You may replace the two files in <span className="num">public/</span> with your own build.</p>
        </Glass>
      </div>
    </div>
  );
}
