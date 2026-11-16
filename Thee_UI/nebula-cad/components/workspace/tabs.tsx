"use client";

import * as React from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { AlertTriangle, ArrowDownToLine, ChevronRight, Copy, Link2, Lock, RotateCcw, Search, ShieldAlert, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { OperationRow } from "@/components/extraction/ReviewPanel";
import { DemoTag, EmptyState, ErrorState, Modal, RelTime, SampleBadge, Stamp, StatusStamp, TableSkeleton } from "@/components/shared";
import { useBuildPlan, useExtraction, useLogs, useOverrideCheck, useParameters, useProject, useRun, useUpdateParameter, useValidation } from "@/lib/api/hooks";
import { clockTime } from "@/lib/format";
import type { LogLevel, Parameter, ValidationCheck } from "@/lib/schemas";
import { useSelection } from "@/lib/store";
import { cn } from "@/lib/utils";
import { countMismatches, exportGate, summarize } from "@/lib/validation";

/* ================================================================ Parameters */

function ParamRow({ p, projectId }: { p: Parameter; projectId: string }) {
  const update = useUpdateParameter(projectId);
  const select = useSelection((s) => s.select);
  const sel = useSelection((s) => Boolean(p.featureId) && s.featureId === p.featureId);
  const [text, setText] = React.useState(String(p.value));
  const [history, setHistory] = React.useState<number[]>([]);
  const [flash, setFlash] = React.useState(0);
  // adjust the text when the saved value changes underneath (undo, reset, preset applied)
  const [seen, setSeen] = React.useState(p.value);
  if (seen !== p.value) {
    setSeen(p.value);
    setText(String(p.value));
  }
  const n = Number(text);
  const invalid = text.trim() === "" || !Number.isFinite(n);
  const out = !invalid && p.range ? n < p.range.min || n > p.range.max : false;
  const changed = p.value !== p.extractedValue;

  const commit = (value: number, pushHistory = true) => {
    if (value === p.value) return;
    if (pushHistory) setHistory((h) => [...h, p.value]);
    update.mutate({ paramId: p.id, value }, { onSuccess: () => setFlash((f) => f + 1) });
  };
  const onBlur = () => {
    if (invalid) return; // keep the text and the error visible; nothing is saved
    commit(n);
  };
  const digits = p.unit === "ea" ? 0 : 3;

  return (
    <tr data-selected={sel}>
      <td>
        <button type="button" className="rounded text-left font-medium hover:text-gold-hi" onClick={() => select({ featureId: p.featureId ?? null, itemId: p.sourceItemId ?? null })}>
          {p.name} {p.symbol && <span className="num text-muted-foreground">({p.symbol})</span>}
        </button>
      </td>
      <td className="r w-[150px]">
        <input
          key={flash}
          className={cn("field field-sm num w-[120px] text-right", flash > 0 && "flash-gold")}
          inputMode="decimal"
          value={text}
          aria-label={`${p.name} value in ${p.unit}`}
          aria-invalid={invalid}
          data-warn={out}
          aria-describedby={invalid || out ? `${p.id}-msg` : undefined}
          onChange={(e) => setText(e.target.value)}
          onBlur={onBlur}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") setText(String(p.value));
          }}
        />
        {(invalid || out) && (
          <div id={`${p.id}-msg`} role="alert" className={cn("mt-0.5 text-right text-[11px] leading-4", invalid ? "text-danger" : "text-warn")}>
            {invalid ? "Not a number. Not saved." : `Outside ${p.range?.min.toFixed(digits)}–${p.range?.max.toFixed(digits)}. Kept as entered.`}
          </div>
        )}
      </td>
      <td className="num text-muted-foreground">{p.unit}</td>
      <td className="num text-muted-foreground">{p.tolerance ? (p.tolerance.plus === p.tolerance.minus ? `±${p.tolerance.plus}` : `+${p.tolerance.plus}/-${p.tolerance.minus}`) : "–"}</td>
      <td className="num whitespace-nowrap text-muted-foreground">{p.range ? `[${p.range.min.toFixed(digits)}, ${p.range.max.toFixed(digits)}]` : "–"}</td>
      <td>
        {p.sourceItemId ? (
          <button type="button" className="num inline-flex items-center gap-1 rounded text-xs text-gold hover:underline" onClick={() => select({ itemId: p.sourceItemId, featureId: p.featureId ?? null })} title="Show the source on the drawing">
            <Link2 className="size-3" aria-hidden /> {p.sourceItemId}
          </button>
        ) : (
          <span className="text-faint">–</span>
        )}
        {changed && <span className="num ml-2 text-[11px] text-warn" title="Differs from the extracted value">was {p.extractedValue}</span>}
      </td>
      <td className="r whitespace-nowrap">
        <button
          type="button"
          className="btn btn-icon btn-sm btn-quiet"
          aria-label={`Undo last change to ${p.name}`}
          title="Undo last change"
          disabled={!history.length}
          onClick={() => {
            const prev = history[history.length - 1];
            setHistory((h) => h.slice(0, -1));
            commit(prev, false);
          }}
        >
          <Undo2 className="size-3.5" aria-hidden />
        </button>
        <button type="button" className="btn btn-icon btn-sm btn-quiet" aria-label={`Reset ${p.name} to the extracted value`} title={`Reset to extracted value (${p.extractedValue})`} disabled={!changed} onClick={() => commit(p.extractedValue)}>
          <RotateCcw className="size-3.5" aria-hidden />
        </button>
      </td>
    </tr>
  );
}

export function ParametersTab({ projectId }: { projectId: string }) {
  const q = useParameters(projectId);
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.isLoading) return <TableSkeleton />;
  if (!q.data?.length) return <EmptyState title="No parameters" body="Parameters come from the extraction. This project has none because its drawing has not been processed." />;
  const edited = q.data.filter((p) => p.value !== p.extractedValue).length;
  return (
    <div>
      {edited > 0 && (
        <p className="mx-3 mt-3 flex items-center gap-2 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-[#ffd4ab]" role="status">
          <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
          {edited} parameter{edited > 1 ? "s differ" : " differs"} from the extraction. The model and its validation still reflect the last run: re-run the pipeline to rebuild.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="dtable min-w-[720px]">
          <thead>
            <tr>
              <th>Parameter</th>
              <th className="r">Value</th>
              <th>Unit</th>
              <th>Tolerance</th>
              <th>Range</th>
              <th>Source</th>
              <th className="r"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {q.data.map((p) => (
              <ParamRow key={p.id} p={p} projectId={projectId} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================================================================ Features */

export function FeaturesTab({ projectId }: { projectId: string }) {
  const q = useBuildPlan(projectId);
  const { data: ex } = useExtraction(projectId);
  const clear = useSelection((s) => s.clear);
  const featureId = useSelection((s) => s.featureId);
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.isLoading) return <TableSkeleton />;
  if (!q.data) return <EmptyState title="No feature tree" body="The feature tree is read from the real build plan. This project has no build plan yet." />;
  const ops = q.data.operations;
  const roots = ops.filter((o) => !o.parentId);
  const bad = countMismatches(ex);
  return (
    <div className="grid gap-4 p-3 lg:grid-cols-[1fr_300px]">
      <div>
        <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
          <span>Select a feature to highlight it in gold in the viewer.</span>
          {featureId && (
            <button type="button" className="btn btn-sm btn-quiet ml-auto h-6" onClick={clear}>
              Clear selection
            </button>
          )}
        </div>
        <ul aria-label="Feature tree from the build plan" className="flex flex-col gap-1.5">
          {roots.map((op) => (
            <React.Fragment key={op.id}>
              <OperationRow op={op} />
              {ops.filter((c) => c.parentId === op.id).map((c) => (
                <OperationRow key={c.id} op={c} child />
              ))}
            </React.Fragment>
          ))}
        </ul>
      </div>
      <div className="glass-raised self-start p-3">
        <h3 className="text-sm font-semibold">Extracted vs modeled</h3>
        <table className="mt-2 w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="py-1 text-left font-semibold">Feature</th>
              <th className="py-1 text-right font-semibold">Drawing</th>
              <th className="py-1 text-right font-semibold">Extracted</th>
              <th className="py-1 text-right font-semibold">Modeled</th>
            </tr>
          </thead>
          <tbody>
            {ex?.countChecks.map((c) => (
              <tr key={c.feature} className={cn("border-t border-line/40", bad.includes(c) && "text-danger")}>
                <td className="py-1.5 font-medium">{c.feature}</td>
                <td className="num py-1.5 text-right">{c.drawingCount ?? "n/a"}</td>
                <td className="num py-1.5 text-right">{c.extractedCount}</td>
                <td className="num py-1.5 text-right">{c.modeledCount ?? "n/a"}</td>
              </tr>
            ))}
            <tr className="border-t border-line/40">
              <td className="py-1.5 font-medium">Build operations</td>
              <td className="py-1.5 text-right text-faint">–</td>
              <td className="num py-1.5 text-right">{ops.length}</td>
              <td className="num py-1.5 text-right">{ops.filter((o) => o.status === "built" || o.status === "built_derived").length}</td>
            </tr>
          </tbody>
        </table>
        {bad.length > 0 && <p className="mt-2 rounded-md bg-danger/10 px-2 py-1.5 text-xs leading-5 text-[#ffc2cd]">{bad.length} count mismatch{bad.length > 1 ? "es" : ""}. The model was built from the extraction, so it repeats the error.</p>}
      </div>
    </div>
  );
}

/* ================================================================ Validation */

function OverrideDialog({ check, projectId, onClose }: { check: ValidationCheck | null; projectId: string; onClose: () => void }) {
  const override = useOverrideCheck(projectId);
  const [reason, setReason] = React.useState("");
  const close = () => {
    setReason("");
    onClose();
  };
  return (
    <Modal
      open={Boolean(check)}
      onOpenChange={(o) => !o && close()}
      title="Override a critical check"
      description="An override does not change the check's result. It records that a named reviewer accepted the risk, and why."
    >
      {check && (
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            override.mutate({ checkId: check.id, reason }, { onSuccess: close });
          }}
        >
          <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-[13px] leading-5">
            <span className="num text-xs text-muted-foreground">{check.id}</span> <span className="font-semibold">{check.label}</span>
            <p className="mt-1 text-text/90">{check.detail ?? `Expected ${check.expected}, measured ${check.measured}.`}</p>
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Reason (required, at least 10 characters)</span>
            <textarea className="field" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is it acceptable to release this part despite the failure?" autoFocus />
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-sm btn-quiet" onClick={close}>Cancel</button>
            <button type="submit" className="btn btn-sm btn-danger" disabled={reason.trim().length < 10 || override.isPending}>
              <ShieldAlert className="size-3.5" aria-hidden /> Record override
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function CheckRow({ c, projectId, onOverride }: { c: ValidationCheck; projectId: string; onOverride: (c: ValidationCheck) => void }) {
  const [open, setOpen] = React.useState(c.status === "failed");
  const select = useSelection((s) => s.select);
  const clearOverride = useOverrideCheck(projectId);
  const gating = c.severity === "critical" && (c.status === "failed" || c.status === "not_run");
  return (
    <li
      className={cn(
        "rounded-xl border",
        c.status === "failed" ? "border-danger/60 bg-danger/[0.08]" : c.status === "warning" ? "border-warn/40 bg-warn/[0.05]" : c.status === "not_run" ? "border-dashed border-faint/60" : "border-line/50",
      )}
    >
      <div className="flex flex-wrap items-center gap-2 px-3 py-2.5">
        <button type="button" className="btn btn-icon btn-sm btn-quiet size-6" aria-expanded={open} aria-label={`${open ? "Collapse" : "Expand"} ${c.label}`} onClick={() => setOpen((o) => !o)}>
          <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} aria-hidden />
        </button>
        <span className="num text-[11px] text-muted-foreground">{c.id}</span>
        <span className="min-w-0 flex-1 text-[13px] font-semibold">{c.label}</span>
        <StatusStamp status={c.severity} />
        <StatusStamp status={c.status} />
        {c.override && <Stamp tone="warn" icon={<ShieldAlert className="size-3" aria-hidden />}>Overridden</Stamp>}
      </div>
      {open && (
        <div className="border-t border-line/40 px-3 py-2.5 text-[13px] leading-5">
          <p className="text-muted-foreground">{c.description}</p>
          {c.detail && <p className={cn("mt-1.5 font-medium", c.status === "failed" ? "text-[#ffc2cd]" : c.status === "warning" ? "text-[#ffd4ab]" : "text-text/90")}>{c.detail}</p>}
          {c.status === "not_run" && <p className="mt-1.5 text-muted-foreground">This check did not run, so it is not counted as passed anywhere in the app.</p>}
          {(c.expected || c.measured) && !c.rows && (
            <p className="num mt-1.5 text-xs text-muted-foreground">expected {c.expected ?? "n/a"} · measured {c.measured ?? "n/a"}</p>
          )}
          {c.rows && (
            <div className="mt-2 overflow-x-auto rounded-lg border border-line/40">
              <table className="w-full min-w-[420px] text-xs">
                <thead>
                  <tr className="bg-surface-raised/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                    <th className="px-2 py-1.5 text-left font-semibold">Item</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Expected</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Measured</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Delta</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Tolerance</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {c.rows.map((r) => (
                    <tr key={r.label} className={cn("border-t border-line/40", !r.ok && "bg-danger/15")}>
                      <td className="px-2 py-1.5 font-medium">{r.label}</td>
                      <td className="num px-2 py-1.5 text-right">{r.expected}</td>
                      <td className={cn("num px-2 py-1.5 text-right", !r.ok && "font-semibold text-danger")}>{r.measured}</td>
                      <td className="num px-2 py-1.5 text-right">{r.delta ?? "–"}</td>
                      <td className="num px-2 py-1.5 text-right text-muted-foreground">{r.tolerance ?? "–"}</td>
                      <td className={cn("px-2 py-1.5 text-right font-semibold", r.ok ? "text-muted-foreground" : "text-danger")}>{r.ok ? "ok" : "MISMATCH"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            {(c.evidence.itemIds.length > 0 || c.evidence.featureIds.length > 0) && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => select({ itemId: c.evidence.itemIds[0] ?? null, featureId: c.evidence.featureIds[0] ?? null })}>
                <Link2 className="size-3.5" aria-hidden /> Show evidence
              </button>
            )}
            {c.ranAt && <span className="text-xs text-faint">ran <RelTime iso={c.ranAt} className="text-faint" /></span>}
            <span className="flex-1" />
            {gating && !c.override && (
              <button type="button" className="btn btn-sm btn-danger" onClick={() => onOverride(c)}>
                <ShieldAlert className="size-3.5" aria-hidden /> Override with reason
              </button>
            )}
            {c.override && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => clearOverride.mutate({ checkId: c.id, reason: null })}>
                Remove override
              </button>
            )}
          </div>
          {c.override && (
            <p className="mt-2 rounded-lg border border-warn/40 bg-warn/10 px-2.5 py-2 text-xs leading-5 text-[#ffd4ab]">
              Overridden by <span className="font-semibold">{c.override.by}</span> <RelTime iso={c.override.at} className="text-[#ffd4ab]" />: “{c.override.reason}”
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function ValidationTab({ projectId }: { projectId: string }) {
  const q = useValidation(projectId);
  const [target, setTarget] = React.useState<ValidationCheck | null>(null);
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.isLoading) return <TableSkeleton />;
  const checks = q.data ?? [];
  if (!checks.length)
    return <EmptyState icon={<ShieldAlert />} title="No checks have run" body="Validation runs after the pipeline builds a model. Nothing is reported as passed until a check actually runs." />;
  const s = summarize(checks);
  const gate = exportGate(checks);
  const order = { failed: 0, not_run: 1, warning: 2, passed: 3 } as const;
  const sorted = [...checks].sort((a, b) => order[a.status] - order[b.status]);
  return (
    <div className="p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {s.failed > 0 && <Stamp tone="danger">Failed · {s.failed}</Stamp>}
        {s.notRun > 0 && <Stamp tone="dashed">Not run · {s.notRun}</Stamp>}
        {s.warning > 0 && <Stamp tone="warn">Warning · {s.warning}</Stamp>}
        <Stamp tone="success">Passed · {s.passed}</Stamp>
        <span className="num ml-auto text-xs text-muted-foreground">
          {s.passRate === null ? "nothing ran" : `${s.passed} of ${s.total - s.notRun} checks that ran passed`}
        </span>
      </div>
      <div
        role="status"
        className={cn("mb-3 flex items-start gap-2 rounded-xl border px-3 py-2.5 text-[13px] leading-5", gate.blocked ? "border-danger/60 bg-danger/10" : gate.reasons.length ? "border-warn/50 bg-warn/10" : "border-success/40 bg-success/10")}
      >
        <Lock className={cn("mt-0.5 size-4 shrink-0", gate.blocked ? "text-danger" : gate.reasons.length ? "text-warn" : "text-success")} aria-hidden />
        <div>
          <span className="font-semibold">{gate.blocked ? "Export is blocked." : gate.reasons.length ? "Export is allowed by override." : "Export is allowed."}</span>{" "}
          {gate.blocked
            ? "A critical check failed or did not run. Resolve it with a new run, or override it with a recorded reason."
            : gate.reasons.length
              ? "Every blocking check carries a recorded override."
              : "No critical check is failing and every critical check ran."}
          {gate.reasons.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-text/90">
              {gate.reasons.map((r) => (
                <li key={r.checkId}>
                  <span className="num text-xs text-muted-foreground">{r.checkId}</span> {r.text} {r.overridden && <span className="text-warn">(overridden)</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <ul className="flex flex-col gap-2" aria-label="Validation checks, failures first">
        {sorted.map((c) => (
          <CheckRow key={c.id} c={c} projectId={projectId} onOverride={setTarget} />
        ))}
      </ul>
      <OverrideDialog check={target} projectId={projectId} onClose={() => setTarget(null)} />
    </div>
  );
}

/* ================================================================ Logs */

const LEVELS: LogLevel[] = ["debug", "info", "warn", "error"];
const LEVEL_CLS: Record<LogLevel, string> = { debug: "text-faint", info: "text-[#b9c7ff]", warn: "text-warn", error: "text-danger" };

export function LogsTab({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId);
  const { data: run } = useRun(project?.lastRunId);
  const live = run?.status === "running" || run?.status === "queued";
  const q = useLogs(project?.lastRunId, live);
  const [levels, setLevels] = React.useState<Set<LogLevel>>(new Set(LEVELS));
  const [query, setQuery] = React.useState("");
  const [follow, setFollow] = React.useState(true);
  const parent = React.useRef<HTMLDivElement>(null);
  const rows = React.useMemo(() => {
    const ql = query.trim().toLowerCase();
    return (q.data ?? []).filter((l) => levels.has(l.level) && (!ql || l.message.toLowerCase().includes(ql) || (l.stage ?? "").includes(ql)));
  }, [q.data, levels, query]);
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual is not compiler-memoizable; this component is small and re-renders cheaply
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => 22, overscan: 20 });
  React.useEffect(() => {
    if (follow && rows.length) virt.scrollToIndex(rows.length - 1, { align: "end" });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- follow the tail when rows arrive
  }, [rows.length, follow]);

  if (!project?.lastRunId) return <EmptyState title="No run, no logs" body="Logs are the pipeline's real console output for a run. This project has not been run." />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const counts = Object.fromEntries(LEVELS.map((l) => [l, (q.data ?? []).filter((x) => x.level === l).length])) as Record<LogLevel, number>;
  const copy = async () => {
    const text = rows.map((l) => `${clockTime(l.at)} ${l.level.toUpperCase().padEnd(5)} ${l.stage ?? "-"} ${l.message}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast.success(`Copied ${rows.length} lines.`);
    } catch {
      toast.error("Clipboard access was denied.");
    }
  };
  return (
    <div className="p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="group" aria-label="Log levels">
          {LEVELS.map((l) => (
            <button
              key={l}
              type="button"
              className="btn btn-sm btn-ghost num h-7 px-2 text-xs"
              aria-pressed={levels.has(l)}
              onClick={() =>
                setLevels((s) => {
                  const n = new Set(s);
                  if (n.has(l)) n.delete(l);
                  else n.add(l);
                  return n;
                })
              }
            >
              <span className={LEVEL_CLS[l]}>{l}</span> {counts[l]}
            </button>
          ))}
        </div>
        <label className="relative min-w-[160px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input className="field field-sm pl-8" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search logs" aria-label="Search logs" />
        </label>
        <button type="button" className="btn btn-sm btn-ghost" aria-pressed={follow} onClick={() => setFollow((f) => !f)} title="Keep the newest line in view">
          <ArrowDownToLine className="size-3.5" aria-hidden /> Follow
        </button>
        <button type="button" className="btn btn-sm btn-ghost" onClick={copy} disabled={!rows.length}>
          <Copy className="size-3.5" aria-hidden /> Copy
        </button>
        {run?.isSample && (run.simulated ? <DemoTag title="Demo log from a simulated run" /> : <SampleBadge label="Sample log" />)}
      </div>
      <div ref={parent} className="well h-[320px] overflow-auto p-2" tabIndex={0} role="log" aria-label={`Run log, ${rows.length} lines shown`}>
        {q.isLoading ? (
          <TableSkeleton rows={8} className="p-1" />
        ) : rows.length === 0 ? (
          <EmptyState title="No lines match" body="Change the level filters or clear the search." className="py-8" />
        ) : (
          <div style={{ height: virt.getTotalSize(), position: "relative", minWidth: 760 }}>
            {virt.getVirtualItems().map((v) => {
              const l = rows[v.index];
              return (
                <div key={l.seq} className="num absolute left-0 top-0 flex w-full gap-3 whitespace-nowrap px-1 text-xs leading-[22px]" style={{ transform: `translateY(${v.start}px)`, height: v.size }}>
                  <span className="text-faint">{clockTime(l.at)}</span>
                  <span className={cn("w-11 uppercase", LEVEL_CLS[l.level])}>{l.level}</span>
                  <span className="w-16 text-muted-foreground">{l.stage ?? "-"}</span>
                  <span className={cn(l.level === "error" ? "text-[#ffc2cd]" : l.level === "warn" ? "text-[#ffd4ab]" : "text-text/90")}>{l.message}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <p className="num mt-1.5 text-[11px] text-faint">
        {run?.id} · {rows.length} of {q.data?.length ?? 0} lines{live ? " · live" : ""}
      </p>
    </div>
  );
}
