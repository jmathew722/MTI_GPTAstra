"use client";

import * as React from "react";
import { SHORTCUTS } from "@/components/shell/Overlays";
import { Glass, PageHeader } from "@/components/shared";
import { DEFAULT_CRITERIA } from "@/lib/rubric";

const TOC = [
  ["scope", "1. Scope"],
  ["pipeline", "2. Processing pipeline"],
  ["verification", "3. Verification model"],
  ["validation", "4. Validation checks"],
  ["rubric", "5. Grading rubric"],
  ["cost", "6. Pipeline cost model"],
  ["data", "7. Data sources and interface"],
  ["shortcuts", "8. Keyboard shortcuts"],
  ["licenses", "9. Software licenses"],
] as const;

const CHECKS: [string, string, string][] = [
  ["Feature counts", "Critical", "For each counted feature (for example, holes), compares three values: the quantity stated in the drawing callout, the number of instances located during extraction, and the number of instances in the built model. Any disagreement is a failure."],
  ["Dimension deltas", "Critical", "Measures each extracted dimension on the built model and compares the difference with the tolerance of that dimension."],
  ["Rebuild errors", "Critical", "Forces a rebuild of the SolidWorks part. Any rebuild error is a failure."],
  ["Bounding box", "Major", "Compares the overall envelope of the model with the overall dimensions on the drawing."],
  ["Sketch definition", "Major", "Requires every sketch in the feature tree to be fully defined."],
  ["Watertight geometry", "Major", "Requires the exported mesh to be a closed solid with positive volume."],
  ["Unit consistency", "Minor", "Requires the drawing unit note, the extraction units and the SolidWorks document units to agree."],
];

const LICENSES: [string, string, string][] = [
  ["occt-import-js", "LGPL-2.1", "WebAssembly build of OpenCASCADE Technology. Reads STEP, IGES and BREP files in the browser. Loaded as separate, unmodified files (public/occt-import-js.js and public/occt-import-js.wasm), which may be replaced by the user."],
  ["GSAP", "GSAP standard license", "Licensed for use, including plugins, under the GreenSock standard license. The license excludes tools that compete with Webflow's visual animation builder. This application is not such a tool."],
  ["pdf.js (pdfjs-dist)", "Apache-2.0", "Renders the source drawing."],
  ["axe-core", "MPL-2.0", "Accessibility testing only. Not delivered to users."],
  ["Playwright", "Apache-2.0", "Automated testing only. Not delivered to users."],
  ["Next.js, React, Tailwind CSS, shadcn/ui, Base UI, Motion, three.js, React Three Fiber, drei, react-postprocessing, TanStack Query, Table and Virtual, Zustand, Zod, Recharts, react-dropzone, react-hook-form, @react-pdf/renderer, Sonner, cmdk, Vitest", "MIT", "Used without modification."],
  ["Lucide", "ISC", "Icon set."],
  ["Inter, JetBrains Mono", "SIL Open Font License 1.1", "Fonts, hosted with the application by next/font at build time."],
];

function H({ id, children }: { id: string; children: React.ReactNode }) {
  return <h2 id={id} className="scroll-mt-24 border-b border-line/50 pb-2 text-lg font-semibold">{children}</h2>;
}

function Scroll({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={label}>
      {children}
    </div>
  );
}

export default function DocsPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Docs" description="Technical reference for the 2D to 3D CAD pipeline interface: processing stages, verification, grading and cost." />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="On this page" className="glass-flat top-[92px] self-start p-3 lg:sticky">
          <div className="eyebrow px-2 pb-2">Contents</div>
          <ul className="flex flex-col">
            {TOC.map(([id, label]) => (
              <li key={id}>
                <a href={`#${id}`} className="block rounded-lg px-2 py-1.5 text-[13px] text-muted-foreground hover:bg-surface-raised/40 hover:text-text">{label}</a>
              </li>
            ))}
          </ul>
        </nav>
        <Glass flat as="section" className="flex max-w-[86ch] flex-col gap-4 p-6 text-sm leading-6 text-text/90">
          <H id="scope">1. Scope</H>
          <p>
            This application is the operator interface for a pipeline that converts a two-dimensional engineering drawing into a SolidWorks part. It presents the extracted data, the generated model and the verification results, and it records the review decisions of the operator. It does not perform extraction or modeling itself; those operations are performed by the pipeline service.
          </p>
          <p>
            The pipeline can produce a geometrically valid model that does not conform to the drawing, for example a model with fewer holes than the drawing specifies. The interface is therefore organized around comparing the model with the source drawing and recording the result of that comparison.
          </p>

          <H id="pipeline">2. Processing pipeline</H>
          <ol className="list-decimal space-y-1.5 pl-5">
            <li><strong>Analyze Drawing.</strong> The sheet is prepared and read as a whole to identify the views, the title block, the notes and any global callouts.</li>
            <li><strong>Extract Features.</strong> A vision model returns structured data: dimensions, holes, features, tolerances and units. Each item carries a confidence value and the region of the sheet from which it was read. A planner converts the data into an ordered build plan.</li>
            <li><strong>Generate CAD Model.</strong> The build plan drives SolidWorks to construct the part with a feature tree. The pipeline saves the part as a <span className="num">.sldprt</span> file and writes an STL file of the same part in the same output folder. The STL file is the format displayed by the model viewer.</li>
            <li><strong>Validate Geometry.</strong> The built part is measured and compared with the drawing and with the extracted data. The results are the checks listed in section 4.</li>
          </ol>
          <p>An operator then reviews the extracted items, compares the drawing with the model, grades the part and records a sign-off.</p>

          <H id="verification">3. Verification model</H>
          <p>The interface applies the following rules in every view.</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>Confidence is a measure of reading quality. It is not evidence of correctness and is never presented as verification.</li>
            <li>A check that did not run has the status <em>Not run</em>. It is excluded from the pass rate and is never counted as passed.</li>
            <li>A critical check that failed, or did not run, blocks export of the model files until the check is resolved or overridden.</li>
            <li>An override requires a written reason of at least 10 characters. The reviewer name, time and reason are stored in the audit trail. An override does not change the status of the check.</li>
            <li>A critical mismatch caps the release status at <em>Needs rework</em>, regardless of the numerical score, until it is overridden with a recorded reason.</li>
          </ul>

          <H id="validation">4. Validation checks</H>
          <Scroll label="Validation checks table, scrolls horizontally">
            <table className="dtable min-w-[560px]">
              <thead><tr><th>Check</th><th>Severity</th><th>Definition</th></tr></thead>
              <tbody>
                {CHECKS.map(([n, s, d]) => (
                  <tr key={n}><td className="!h-auto py-2 align-top font-medium">{n}</td><td className="!h-auto py-2 align-top">{s}</td><td className="!h-auto py-2 text-[13px] leading-5 text-muted-foreground">{d}</td></tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <p>Status values: <strong>Passed</strong> (the check ran and met its limits), <strong>Warning</strong> (the check ran and requires attention), <strong>Failed</strong> (the check ran and did not meet its limits), <strong>Not run</strong> (no result exists).</p>

          <H id="rubric">5. Grading rubric</H>
          <p>The rubric grades a generated part against its source drawing. Each criterion is assigned a level from 4 (Exemplary) to 1 (Insufficient), or 0 (Missing) when the supporting evidence does not exist. The points for a criterion are weight × level ÷ 4. The weights of a template must sum to 100.</p>
          <Scroll label="Rubric criteria table, scrolls horizontally">
            <table className="dtable min-w-[480px]">
              <thead><tr><th>Criterion</th><th className="r">Weight</th><th>Scored by</th></tr></thead>
              <tbody>
                {DEFAULT_CRITERIA.map((c) => (
                  <tr key={c.key}><td className="font-medium">{c.label}</td><td className="num r">{c.weight}</td><td className="capitalize text-muted-foreground">{c.scoredBy}</td></tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <p>Automatic criteria are computed from the validation checks. Evidence that did not run is scored 0. Reviewer criteria that have not been scored contribute 0 points and prevent sign-off.</p>
          <p>Grade bands: A for a total of 90 or more, B for 80 or more, C for 70 or more, and Needs rework below 70. The release status is <em>Approved</em> (total of 80 or more, no reviewer comments, no override), <em>Approved with notes</em>, or <em>Needs rework</em>.</p>
          <p><strong>Hard-fail conditions.</strong> A feature count that does not match the drawing, a critical dimension outside its tolerance, or a rebuild error caps the release status at Needs rework. The cap is lifted only by an override with a recorded reason.</p>

          <H id="cost">6. Pipeline cost model</H>
          <p>The cost of a run is the sum over all stages of the following terms.</p>
          <pre tabIndex={0} aria-label="Pipeline cost formula" className="well num overflow-x-auto p-3 text-xs leading-6">{`cost = (input_tokens / 1e6) * input_rate
     + (output_tokens / 1e6) * output_rate
     + vision_calls * vision_call_rate
     + (compute_seconds / 3600) * compute_rate`}</pre>
          <p>The backend reports raw usage (tokens, vision calls, compute seconds). The interface applies the rates stored in Settings. The default rates are assumptions and must be verified against current provider pricing; a notice remains visible until the operator confirms them. If the backend reports a billed cost, that value should be displayed in place of the computed value.</p>
          <p>A monthly budget may be set in Settings. A warning is shown when the month-to-date cost reaches 80 % of the budget, and an error state is shown at 100 %.</p>
          <p>Part manufacturing cost and automation return on investment are not part of this version.</p>

          <H id="data">7. Data sources and interface</H>
          <p>
            By default the application runs against a mock adapter that serves three synthetic projects. All values supplied by the mock adapter are labeled <em>Sample data</em>. Controls that require a backend to function are labeled <em>Demo</em>. The sample drawings and models are generated by <span className="num">npm run gen:samples</span>; no customer drawing is included.
          </p>
          <p>
            To use the pipeline service, set <span className="num">NEXT_PUBLIC_API_MODE=http</span> and <span className="num">NEXT_PUBLIC_API_BASE_URL</span> in <span className="num">.env.local</span>. The service shall implement the endpoints defined in <span className="num">docs/API_CONTRACT.md</span>. Each response is validated against its schema before it is displayed; a response that does not conform is reported as an error.
          </p>
          <p>A drawing uploaded while the mock adapter is active is stored for the browser session only. It is not processed, and no extracted data is generated for it.</p>

          <H id="shortcuts">8. Keyboard shortcuts</H>
          <ul className="grid gap-x-8 sm:grid-cols-2">
            {SHORTCUTS.map((s) => (
              <li key={s.label} className="flex items-center justify-between gap-4 border-b border-line/40 py-1.5 text-[13px]">
                <span>{s.label}</span>
                <span className="flex shrink-0 gap-1">{s.keys.map((k, i) => (k === "…" ? <span key={i}>…</span> : <kbd key={i}>{k}</kbd>))}</span>
              </li>
            ))}
          </ul>

          <H id="licenses">9. Software licenses</H>
          <Scroll label="Software licenses table, scrolls horizontally">
            <table className="dtable min-w-[560px]">
              <thead><tr><th>Component</th><th>License</th><th>Notes</th></tr></thead>
              <tbody>
                {LICENSES.map(([n, l, d]) => (
                  <tr key={n}><td className="!h-auto max-w-[260px] py-2 align-top font-medium">{n}</td><td className="!h-auto whitespace-nowrap py-2 align-top">{l}</td><td className="!h-auto py-2 text-[13px] leading-5 text-muted-foreground">{d}</td></tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <p className="text-[13px] text-muted-foreground">
            LGPL notice: occt-import-js and OpenCASCADE Technology are distributed under the GNU Lesser General Public License, version 2.1. Source code is available at github.com/kovacsv/occt-import-js and dev.opencascade.org. The two files in <span className="num">public/</span> may be replaced with a user-built version.
          </p>
        </Glass>
      </div>
    </div>
  );
}
