import { Document, Page, StyleSheet, Text, View, pdf } from "@react-pdf/renderer";
import type { BuildPlan, ValidationCheck } from "@/lib/schemas";

/** PDF exports. Imported dynamically, so @react-pdf/renderer loads only when someone exports. */
const s = StyleSheet.create({
  page: { padding: 36, fontSize: 9.5, fontFamily: "Helvetica", color: "#1a1328", lineHeight: 1.4 },
  h1: { fontSize: 18, fontFamily: "Helvetica-Bold", marginBottom: 2 },
  sub: { fontSize: 9, color: "#5b5370", marginBottom: 12 },
  h2: { fontSize: 12, fontFamily: "Helvetica-Bold", marginTop: 14, marginBottom: 6, borderBottom: "1 solid #c9b07a", paddingBottom: 3 },
  row: { flexDirection: "row", borderBottom: "0.5 solid #ddd6e8", paddingVertical: 3 },
  head: { flexDirection: "row", borderBottom: "1 solid #1a1328", paddingVertical: 3, fontFamily: "Helvetica-Bold" },
  mono: { fontFamily: "Courier" },
  box: { border: "1 solid #b3261e", backgroundColor: "#fdecea", padding: 8, marginTop: 8 },
  ok: { border: "1 solid #2e7d32", backgroundColor: "#e8f5e9", padding: 8, marginTop: 8 },
  note: { fontSize: 8, color: "#5b5370", marginTop: 14 },
});

export interface RubricExport {
  project: { id: string; name: string; partNumber: string; revision: string };
  template: { id: string; name: string };
  total: number;
  band: string;
  releaseStatus: string;
  capped: boolean;
  gates: { id: string; reason: string; overridden: boolean }[];
  gateOverride: { by: string; reason: string; at: string } | null;
  criteria: { key: string; label: string; weight: number; level: number | null; source: string; points: number; comment: string; evidence: { notes: string[] } }[];
  signOff: { by: string; at: string; status: string; total: number; band: string } | null;
  exportedAt: string;
}

const label = (v: string) => v.replaceAll("_", " ");

function RubricSection({ d }: { d: RubricExport }) {
  return (
    <View>
      <Text style={s.h2}>Rubric: {d.template.name}</Text>
      <Text>
        Total {d.total.toFixed(1)} / 100 · Grade {d.band} · Release status: {label(d.releaseStatus)}
      </Text>
      {d.gates.length > 0 && (
        <View style={d.capped ? s.box : s.ok}>
          <Text style={{ fontFamily: "Helvetica-Bold" }}>{d.capped ? "Hard-fail cap: release status capped at Needs rework" : "Hard-fail cap overridden by a reviewer"}</Text>
          {d.gates.map((g) => (
            <Text key={g.id}>• {g.reason}</Text>
          ))}
          {d.gateOverride && (
            <Text>
              Override by {d.gateOverride.by} at {d.gateOverride.at}: {d.gateOverride.reason}
            </Text>
          )}
        </View>
      )}
      <View style={[s.head, { marginTop: 8 }]}>
        <Text style={{ width: "40%" }}>Criterion</Text>
        <Text style={{ width: "12%" }}>Weight</Text>
        <Text style={{ width: "12%" }}>Level</Text>
        <Text style={{ width: "14%" }}>Points</Text>
        <Text style={{ width: "22%" }}>Scored by</Text>
      </View>
      {d.criteria.map((c) => (
        <View key={c.key} wrap={false}>
          <View style={s.row}>
            <Text style={{ width: "40%" }}>{c.label}</Text>
            <Text style={[s.mono, { width: "12%" }]}>{c.weight}</Text>
            <Text style={[s.mono, { width: "12%" }]}>{c.level === null ? "not scored" : c.level}</Text>
            <Text style={[s.mono, { width: "14%" }]}>{c.points.toFixed(1)}</Text>
            <Text style={{ width: "22%" }}>{c.source}</Text>
          </View>
          {c.evidence.notes.map((n) => (
            <Text key={n} style={{ fontSize: 8, color: "#5b5370", marginLeft: 8 }}>
              – {n}
            </Text>
          ))}
          {c.comment ? <Text style={{ fontSize: 8, marginLeft: 8 }}>Reviewer: {c.comment}</Text> : null}
        </View>
      ))}
      <Text style={{ marginTop: 8 }}>
        {d.signOff ? `Signed off by ${d.signOff.by} at ${d.signOff.at}: ${label(d.signOff.status)}, ${d.signOff.total} (${d.signOff.band}).` : "Not signed off."}
      </Text>
    </View>
  );
}

function Header({ d, title, sample }: { d: RubricExport; title: string; sample: boolean }) {
  return (
    <View>
      <Text style={s.h1}>{title}</Text>
      <Text style={s.sub}>
        {d.project.partNumber} · {d.project.name} · Rev {d.project.revision} · exported {d.exportedAt}
        {sample ? " · SAMPLE DATA (synthetic)" : ""}
      </Text>
    </View>
  );
}

export async function renderRubricPdf(d: RubricExport, sample = true): Promise<Blob> {
  return pdf(
    <Document title={`${d.project.partNumber} rubric`}>
      <Page size="A4" style={s.page}>
        <Header d={d} title="Part grading rubric" sample={sample} />
        <RubricSection d={d} />
        <Text style={s.note}>Generated in the browser by Nebula CAD. Automatic criteria are computed from validation checks; a check that did not run scores 0.</Text>
      </Page>
    </Document>,
  ).toBlob();
}

export interface ReportExport {
  rubric: RubricExport;
  checks: ValidationCheck[];
  plan: BuildPlan | null;
  cost: { perPart: string; perBatch: string; unitCosts: { qty: number; unit: string }[]; ratesConfirmed: boolean } | null;
  sample: boolean;
}

export async function renderReportPdf(r: ReportExport): Promise<Blob> {
  const failed = r.checks.filter((c) => c.status === "failed");
  return pdf(
    <Document title={`${r.rubric.project.partNumber} report`}>
      <Page size="A4" style={s.page}>
        <Header d={r.rubric} title="Part report: build plan, validation, cost, rubric" sample={r.sample} />
        {failed.length > 0 && (
          <View style={s.box}>
            <Text style={{ fontFamily: "Helvetica-Bold" }}>{failed.length} validation check(s) failed</Text>
            {failed.map((c) => (
              <Text key={c.id}>
                • {c.id} {c.label}: {c.detail ?? `expected ${c.expected}, measured ${c.measured}`}
                {c.override ? ` (overridden by ${c.override.by}: ${c.override.reason})` : ""}
              </Text>
            ))}
          </View>
        )}
        <Text style={s.h2}>Validation</Text>
        <View style={s.head}>
          <Text style={{ width: "12%" }}>ID</Text>
          <Text style={{ width: "40%" }}>Check</Text>
          <Text style={{ width: "14%" }}>Severity</Text>
          <Text style={{ width: "14%" }}>Status</Text>
          <Text style={{ width: "20%" }}>Measured</Text>
        </View>
        {r.checks.map((c) => (
          <View key={c.id} style={s.row} wrap={false}>
            <Text style={[s.mono, { width: "12%" }]}>{c.id}</Text>
            <Text style={{ width: "40%" }}>{c.label}</Text>
            <Text style={{ width: "14%" }}>{c.severity}</Text>
            <Text style={{ width: "14%", fontFamily: "Helvetica-Bold" }}>{label(c.status)}</Text>
            <Text style={[s.mono, { width: "20%" }]}>{c.measured ?? "-"}</Text>
          </View>
        ))}
        <Text style={s.h2}>Build plan</Text>
        {r.plan ? (
          r.plan.operations.map((o) => (
            <View key={o.id} style={s.row} wrap={false}>
              <Text style={[s.mono, { width: "10%" }]}>{o.id}</Text>
              <Text style={{ width: "30%" }}>{o.name}</Text>
              <Text style={{ width: "14%" }}>{label(o.status)}</Text>
              <Text style={[s.mono, { width: "46%", fontSize: 8 }]}>
                {Object.entries(o.params)
                  .map(([k, v]) => `${k}=${v}`)
                  .join("  ")}
              </Text>
            </View>
          ))
        ) : (
          <Text>No build plan.</Text>
        )}
        <Text style={s.h2}>Cost</Text>
        {r.cost ? (
          <Text>
            Pipeline run: {r.cost.perPart} per part, {r.cost.perBatch} per batch{r.cost.ratesConfirmed ? "" : " (ASSUMPTION: rates not verified against provider pricing)"}. Manufacturing ESTIMATE per unit:{" "}
            {r.cost.unitCosts.map((u) => `qty ${u.qty} ${u.unit}`).join(", ")}.
          </Text>
        ) : (
          <Text>No cost data.</Text>
        )}
        <RubricSection d={r.rubric} />
        <Text style={s.note}>Generated in the browser by Nebula CAD.</Text>
      </Page>
    </Document>,
  ).toBlob();
}
