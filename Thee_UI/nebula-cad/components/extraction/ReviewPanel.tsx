"use client";

import * as React from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronRight, ClipboardList, Download, GitCompare, History, MessageSquare, Pencil, ScrollText, Undo2, X } from "lucide-react";
import { ConfidenceBar, EmptyState, ErrorState, Glass, Modal, RelTime, SampleBadge, Segmented, Stamp, StatusStamp, TableSkeleton } from "@/components/shared";
import { useAddComment, useAudit, useBuildPlan, useComments, useExtraction, useRecordExport, useResolveComment, useReviewItem, useRevisions } from "@/lib/api/hooks";
import { downloadJson, fmtNum } from "@/lib/format";
import { Collapse } from "@/components/shared/motion";
import { rowVariants } from "@/lib/motion";
import type { BuildOperation, ExtractionItem, Revision } from "@/lib/schemas";
import { useSelection, useUi, type ReviewTab } from "@/lib/store";
import { cn } from "@/lib/utils";
import { countMismatches, riskOrder } from "@/lib/validation";

/* ---------------------------------------------------------------- extraction review */

function ItemRow({ item, projectId }: { item: ExtractionItem; projectId: string }) {
  const sel = useSelection((s) => s.itemId === item.id);
  const select = useSelection((s) => s.select);
  const review = useReviewItem(projectId);
  const [editing, setEditing] = React.useState(false);
  const [value, setValue] = React.useState(item.review.editedValue ?? item.value);
  const d = item.review.decision;
  const shown = d === "edited" && item.review.editedValue ? item.review.editedValue : item.value;
  const act = (decision: "approved" | "rejected" | "pending") => review.mutate({ itemId: item.id, decision });

  return (
    <motion.li
      layout="position"
      variants={rowVariants}
      initial="hidden"
      animate="show"
      exit="exit"
      data-selected={sel}
      className={cn(
        "rounded-xl border p-2.5 transition-colors",
        sel ? "border-gold/60 bg-gold/[0.07]" : item.status === "conflict" ? "border-danger/50 bg-danger/[0.07]" : item.status === "needs_review" ? "border-warn/40 bg-warn/[0.05]" : "border-line/50 bg-surface-raised/20",
      )}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() => select({ itemId: item.id, featureId: item.featureId ?? null })}
          aria-pressed={sel}
          title="Show on the drawing and the model"
          className="min-w-0 flex-1 rounded-md text-left"
        >
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="num text-[11px] text-muted-foreground">{item.id}</span>
            <span className="text-[13px] font-semibold text-text">{item.label}</span>
            <span className="text-[10px] uppercase tracking-wider text-faint">{item.kind}</span>
            {item.critical && <Stamp tone="muted" title="A critical item: an error here caps the rubric">Critical</Stamp>}
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className={cn("num text-sm font-medium", d === "rejected" ? "text-faint line-through" : "text-gold-hi")}>{shown}</span>
            {d === "edited" && <span className="num text-xs text-faint line-through">{item.value}</span>}
            <ConfidenceBar value={item.confidence} />
          </span>
        </button>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <StatusStamp status={item.status} />
          {d !== "pending" && <StatusStamp status={d} />}
        </div>
      </div>
      {item.flag && <p className={cn("mt-2 rounded-lg px-2 py-1.5 text-xs leading-5", item.status === "conflict" ? "bg-danger/10 text-[#ffc2cd]" : "bg-warn/10 text-[#ffd4ab]")}>{item.flag}</p>}
      {editing ? (
        <form
          className="mt-2 flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!value.trim()) return;
            review.mutate({ itemId: item.id, decision: "edited", editedValue: value.trim() });
            setEditing(false);
          }}
        >
          <input className="field field-sm num" value={value} onChange={(e) => setValue(e.target.value)} autoFocus aria-label={`Corrected value for ${item.label}`} />
          <button type="submit" className="btn btn-sm btn-primary">Save</button>
          <button type="button" className="btn btn-sm btn-quiet" onClick={() => setEditing(false)}>Cancel</button>
        </form>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <button type="button" className="btn btn-sm btn-ghost" disabled={review.isPending || d === "approved"} onClick={() => act("approved")}>
            <Check className="size-3.5" aria-hidden /> Approve
          </button>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>
            <Pencil className="size-3.5" aria-hidden /> Edit
          </button>
          <button type="button" className="btn btn-sm btn-ghost" disabled={review.isPending || d === "rejected"} onClick={() => act("rejected")}>
            <X className="size-3.5" aria-hidden /> Reject
          </button>
          {d !== "pending" && (
            <button type="button" className="btn btn-sm btn-quiet" onClick={() => act("pending")} title="Clear the review decision">
              <Undo2 className="size-3.5" aria-hidden /> Undo
            </button>
          )}
          {item.review.by && (
            <span className="ml-auto text-[11px] text-faint">
              {item.review.by}
              {item.review.at && <> · <RelTime iso={item.review.at} className="text-[11px] text-faint" /></>}
            </span>
          )}
        </div>
      )}
    </motion.li>
  );
}

function ExtractionReview({ projectId }: { projectId: string }) {
  const q = useExtraction(projectId);
  const select = useSelection((s) => s.select);
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.isLoading) return <TableSkeleton rows={6} />;
  if (!q.data)
    return (
      <EmptyState
        icon={<ClipboardList />}
        title="No extraction for this project"
        body="This drawing has not been processed by the pipeline, so there is nothing to review. No values are invented for it."
      />
    );
  const ex = q.data;
  const items = riskOrder(ex.items);
  const bad = countMismatches(ex);
  const groups = { conflict: 0, needs_review: 0, verified: 0 };
  for (const i of ex.items) groups[i.status]++;
  const reviewed = ex.items.filter((i) => i.review.decision !== "pending").length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-2 overflow-hidden rounded-xl border border-line/60">
        <table className="w-full text-xs" aria-label="Count checks: drawing callout, extraction and model">
          <thead>
            <tr className="bg-surface-raised/40 text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="px-2 py-1.5 text-left font-semibold">Count check</th>
              <th className="px-2 py-1.5 text-right font-semibold">Drawing</th>
              <th className="px-2 py-1.5 text-right font-semibold">Extracted</th>
              <th className="px-2 py-1.5 text-right font-semibold">Model</th>
            </tr>
          </thead>
          <tbody>
            {ex.countChecks.map((c) => {
              const wrong = bad.includes(c);
              return (
                <tr key={c.feature} className={cn("border-t border-line/40", wrong && "bg-danger/15")}>
                  <td className="px-2 py-1.5">
                    <button type="button" className="rounded text-left font-medium hover:text-gold-hi" onClick={() => c.evidenceItemId && select({ itemId: c.evidenceItemId, featureId: ex.items.find((i) => i.id === c.evidenceItemId)?.featureId ?? null })}>
                      {c.feature} {wrong && <span className="font-bold text-danger">· MISMATCH</span>}
                    </button>
                  </td>
                  <td className="num px-2 py-1.5 text-right text-sm font-semibold">{c.drawingCount ?? "n/a"}</td>
                  <td className={cn("num px-2 py-1.5 text-right text-sm font-semibold", wrong && "text-danger")}>{c.extractedCount}</td>
                  <td className={cn("num px-2 py-1.5 text-right text-sm font-semibold", wrong && "text-danger")}>{c.modeledCount ?? "n/a"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mb-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        {groups.conflict > 0 && <Stamp tone="danger">Conflict · {groups.conflict}</Stamp>}
        {groups.needs_review > 0 && <Stamp tone="warn">Needs review · {groups.needs_review}</Stamp>}
        <Stamp tone="muted">Verified · {groups.verified}</Stamp>
        <span className="num ml-auto">{reviewed} of {ex.items.length} reviewed</span>
      </div>
      <ul className="-mr-1 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1" aria-label="Extracted items, riskiest first">
        <AnimatePresence initial={false}>
          {items.map((i) => (
            <ItemRow key={i.id} item={i} projectId={projectId} />
          ))}
        </AnimatePresence>
      </ul>
    </div>
  );
}

/* ---------------------------------------------------------------- build plan */

export function OperationRow({ op, child }: { op: BuildOperation; child?: boolean }) {
  const [open, setOpen] = React.useState(false);
  const sel = useSelection((s) => s.featureId === op.featureId);
  const select = useSelection((s) => s.select);
  return (
    <li className={cn("rounded-lg border", sel ? "border-gold/50 bg-gold/[0.06]" : "border-line/40", child && "ml-5")}>
      <div className="flex items-center gap-2 px-2 py-1.5">
        <button type="button" className="btn btn-icon btn-sm btn-quiet size-6" aria-expanded={open} aria-label={`${open ? "Collapse" : "Expand"} ${op.name}`} onClick={() => setOpen((o) => !o)}>
          <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} aria-hidden />
        </button>
        <span className="num w-10 shrink-0 text-[11px] text-muted-foreground">{op.id}</span>
        <button type="button" className="min-w-0 flex-1 truncate rounded text-left text-[13px] font-medium hover:text-gold-hi" onClick={() => select({ featureId: op.featureId, itemId: null })} aria-pressed={sel}>
          {op.name}
        </button>
        <span className="hidden text-[10px] uppercase tracking-wider text-faint sm:inline">{op.type}</span>
        <StatusStamp status={op.status} />
      </div>
      <Collapse open={open}>
        <div className="border-t border-line/40 px-3 py-2">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
            {Object.entries(op.params).map(([k, v]) => (
              <React.Fragment key={k}>
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="num text-text">{typeof v === "number" ? fmtNum(v, Number.isInteger(v) ? 0 : 3) : String(v)}</dd>
              </React.Fragment>
            ))}
            <dt className="text-muted-foreground">feature</dt>
            <dd className="num text-text">{op.featureId}</dd>
          </dl>
          {op.note && <p className="mt-2 rounded-md bg-warn/10 px-2 py-1.5 text-xs leading-5 text-[#ffd4ab]">{op.note}</p>}
        </div>
      </Collapse>
    </li>
  );
}

function BuildPlanReport({ projectId }: { projectId: string }) {
  const q = useBuildPlan(projectId);
  const rec = useRecordExport(projectId);
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.isLoading) return <TableSkeleton rows={6} />;
  if (!q.data) return <EmptyState icon={<ScrollText />} title="No build plan" body="A build plan appears after the pipeline plans the part. This project has not been processed." />;
  const plan = q.data;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="num">{plan.operations.length} operations · {plan.units}</span>
        <button
          type="button"
          className="btn btn-sm btn-ghost ml-auto"
          onClick={() => {
            downloadJson(plan, `${plan.id}_build_plan.json`);
            rec.mutate("build plan (JSON)");
          }}
        >
          <Download className="size-3.5" aria-hidden /> Export JSON
        </button>
      </div>
      <ol className="-mr-1 flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1" aria-label="Build operations in order">
        {plan.operations.map((op) => (
          <OperationRow key={op.id} op={op} />
        ))}
      </ol>
    </div>
  );
}

/* ---------------------------------------------------------------- comments */

function CommentsPanel({ projectId }: { projectId: string }) {
  const q = useComments(projectId);
  const add = useAddComment(projectId);
  const resolve = useResolveComment(projectId);
  const itemId = useSelection((s) => s.itemId);
  const select = useSelection((s) => s.select);
  const [body, setBody] = React.useState("");
  const open = q.data?.filter((c) => !c.resolved) ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!body.trim()) return;
          add.mutate({ body: body.trim(), itemId: itemId ?? undefined });
          setBody("");
        }}
      >
        <textarea className="field" rows={2} value={body} onChange={(e) => setBody(e.target.value)} placeholder={itemId ? `Comment on ${itemId}…` : "Add a comment. Select an item first to attach it, or use the pin tool on the drawing."} aria-label="New comment" />
        <button type="submit" className="btn btn-sm btn-outline self-end" disabled={!body.trim() || add.isPending}>
          <MessageSquare className="size-3.5" aria-hidden /> Add comment{itemId ? ` on ${itemId}` : ""}
        </button>
      </form>
      {q.isLoading ? (
        <TableSkeleton rows={3} />
      ) : q.data?.length === 0 ? (
        <EmptyState icon={<MessageSquare />} title="No comments" body="Comments can be attached to an extracted item or pinned to a spot on the drawing." className="py-6" />
      ) : (
        <ul className="-mr-1 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
          {q.data?.map((c) => {
            const n = open.filter((o) => o.region).indexOf(c) + 1;
            return (
              <li key={c.id} className={cn("rounded-lg border border-line/50 p-2.5", c.resolved && "opacity-60")}>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  {c.region && !c.resolved && n > 0 && <span className="num grid size-5 place-items-center rounded-full bg-gold text-[10px] font-bold text-on-gold">{n}</span>}
                  <span className="font-medium text-text">{c.author}</span>
                  <RelTime iso={c.at} />
                  {c.itemId && (
                    <button type="button" className="num rounded text-gold hover:underline" onClick={() => select({ itemId: c.itemId })}>
                      {c.itemId}
                    </button>
                  )}
                  <button type="button" className="btn btn-sm btn-quiet ml-auto h-6" onClick={() => resolve.mutate({ commentId: c.id, resolved: !c.resolved })}>
                    {c.resolved ? "Reopen" : "Resolve"}
                  </button>
                </div>
                <p className="mt-1 text-[13px] leading-5 text-text/90">{c.body}</p>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- revisions */

function RevisionCompare({ a, b }: { a: Revision; b: Revision }) {
  const rows: [string, string | number, string | number][] = [
    ["Holes", a.metrics.holes, b.metrics.holes],
    ["Operations", a.metrics.features, b.metrics.features],
    ["Volume (cm³)", a.metrics.volumeCm3.toFixed(2), b.metrics.volumeCm3.toFixed(2)],
    ["Checks passed", a.metrics.checksPassed, b.metrics.checksPassed],
    ["Checks failed", a.metrics.checksFailed, b.metrics.checksFailed],
    ...a.parameters.map((p): [string, string | number, string | number] => [`${p.name} (${p.unit})`, p.value, b.parameters.find((q) => q.name === p.name)?.value ?? "n/a"]),
  ];
  return (
    <table className="dtable">
      <thead>
        <tr>
          <th>Metric</th>
          <th className="r">{a.label}</th>
          <th className="r">{b.label}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([k, x, y]) => (
          <tr key={k} className={String(x) !== String(y) ? "bg-gold/[0.07]" : undefined}>
            <td>{k}</td>
            <td className="num r">{x}</td>
            <td className={cn("num r", String(x) !== String(y) && "font-semibold text-gold-hi")}>{y}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RevisionsPanel({ projectId }: { projectId: string }) {
  const q = useRevisions(projectId);
  const [open, setOpen] = React.useState(false);
  const [ai, setAi] = React.useState(1);
  const [bi, setBi] = React.useState(0);
  if (q.isLoading) return <TableSkeleton rows={3} />;
  const revs = q.data ?? [];
  if (!revs.length) return <EmptyState icon={<History />} title="No revisions" body="Each pipeline run that produces a model is kept as a revision you can compare." />;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <button type="button" className="btn btn-sm btn-outline self-start" disabled={revs.length < 2} onClick={() => setOpen(true)}>
        <GitCompare className="size-3.5" aria-hidden /> Compare two revisions
      </button>
      <ul className="flex flex-col gap-2 overflow-y-auto">
        {revs.map((r) => (
          <li key={r.id} className="rounded-lg border border-line/50 p-2.5">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-semibold">{r.label}</span>
              <RelTime iso={r.createdAt} />
              <span className="num ml-auto text-xs text-muted-foreground">{r.metrics.holes} holes · {r.metrics.volumeCm3.toFixed(1)} cm³</span>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{r.summary}</p>
          </li>
        ))}
      </ul>
      <Modal open={open} onOpenChange={setOpen} title="Compare revisions" description="Rows that differ are highlighted." wide>
        <div className="flex flex-wrap gap-3">
          {[
            ["Left", ai, setAi],
            ["Right", bi, setBi],
          ].map(([label, v, set]) => (
            <label key={label as string} className="flex items-center gap-2 text-xs text-muted-foreground">
              {label as string}
              <select className="field field-sm w-48" value={v as number} onChange={(e) => (set as (n: number) => void)(Number(e.target.value))}>
                {revs.map((r, i) => (
                  <option key={r.id} value={i}>{r.label}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
        {revs[ai] && revs[bi] && <RevisionCompare a={revs[ai]} b={revs[bi]} />}
      </Modal>
    </div>
  );
}

/* ---------------------------------------------------------------- audit */

function AuditPanel({ projectId }: { projectId: string }) {
  const q = useAudit(projectId);
  if (q.isLoading) return <TableSkeleton rows={4} />;
  if (!q.data?.length) return <EmptyState icon={<History />} title="No audit events" body="Every approval, edit, rejection, override, export and sign-off is recorded here with who and when." />;
  return (
    <ol className="-mr-1 flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1" aria-label="Audit trail, newest first">
      {q.data.map((e) => (
        <li key={e.id} className="rounded-lg border border-line/40 px-2.5 py-2">
          <div className="flex items-center gap-2 text-xs">
            <span className="font-medium text-text">{e.actor}</span>
            <span className="num rounded bg-surface-raised/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">{e.action.replaceAll("_", " ")}</span>
            <RelTime iso={e.at} className="ml-auto" />
          </div>
          <p className="mt-1 text-[13px] leading-5 text-text/90">{e.summary}</p>
          {e.reason && <p className="mt-1 text-xs leading-5 text-muted-foreground">Reason: {e.reason}</p>}
        </li>
      ))}
    </ol>
  );
}

/* ---------------------------------------------------------------- panel */

export function ReviewPanel({ projectId, className }: { projectId: string; className?: string }) {
  const tab = useUi((s) => s.reviewTab);
  const set = useUi((s) => s.set);
  const { data: ex } = useExtraction(projectId);
  const { data: comments } = useComments(projectId);
  const nOpen = comments?.filter((c) => !c.resolved).length ?? 0;
  return (
    <Glass as="section" className={cn("flex min-h-0 flex-col p-3", className)} aria-label="Review">
      <div className="flex items-center gap-2 pb-2">
        <h2 className="text-base font-semibold">Review</h2>
        {ex?.isSample && <SampleBadge className="ml-auto" />}
      </div>
      <Segmented<ReviewTab>
        label="Review section"
        size="sm"
        className="mb-3 flex w-full [&>button]:flex-1"
        value={tab}
        onChange={(v) => set({ reviewTab: v })}
        options={[
          { value: "extraction", label: "Extraction" },
          { value: "plan", label: "Plan" },
          { value: "comments", label: nOpen ? `Notes ${nOpen}` : "Notes" },
          { value: "revisions", label: "Revs" },
          { value: "audit", label: "Audit" },
        ]}
      />
      {tab === "extraction" && <ExtractionReview projectId={projectId} />}
      {tab === "plan" && <BuildPlanReport projectId={projectId} />}
      {tab === "comments" && <CommentsPanel projectId={projectId} />}
      {tab === "revisions" && <RevisionsPanel projectId={projectId} />}
      {tab === "audit" && <AuditPanel projectId={projectId} />}
    </Glass>
  );
}
