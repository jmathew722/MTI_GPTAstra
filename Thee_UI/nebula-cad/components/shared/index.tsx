"use client";

import * as React from "react";
import { AlertTriangle, Check, Circle, CircleDashed, FlaskConical, Loader2, RefreshCw, WifiOff, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { absTime, relTime } from "@/lib/format";
import { confidenceBand } from "@/lib/validation";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/* ------------------------------------------------------------------ badges */

export function SampleBadge({ className, label = "Sample data" }: { className?: string; label?: string }) {
  return (
    <span
      title="This card is fed by the mock adapter. Values are synthetic."
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 rounded-md border border-violet/50 bg-violet/10 px-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-[#cdb8ff]",
        className,
      )}
    >
      <FlaskConical className="size-3" aria-hidden />
      {label}
    </span>
  );
}

export function DemoTag({ className, title }: { className?: string; title?: string }) {
  return (
    <span
      title={title ?? "Demo: this control is not connected to a backend."}
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded-md border border-dashed border-warn/70 bg-warn/10 px-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-warn",
        className,
      )}
    >
      Demo
    </span>
  );
}

export type StampTone = "success" | "danger" | "warn" | "notice" | "gold" | "violet" | "muted" | "dashed";

const TONE: Record<StampTone, string> = {
  success: "border-success/60 bg-success/10 text-success",
  danger: "border-danger/70 bg-danger/10 text-danger",
  warn: "border-warn/70 bg-warn/10 text-warn",
  notice: "border-notice/60 bg-notice/10 text-notice",
  gold: "border-gold/60 bg-gold/10 text-gold-hi",
  violet: "border-violet/50 bg-violet/10 text-[#cdb8ff]",
  muted: "border-line bg-surface-raised/40 text-muted-foreground",
  dashed: "border-dashed border-faint/80 bg-transparent text-muted-foreground",
};

/** Outlined inspection stamp: always a glyph and a word, never color alone. */
export function Stamp({
  tone,
  children,
  icon,
  className,
  title,
}: {
  tone: StampTone;
  children: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-[22px] shrink-0 items-center gap-1 whitespace-nowrap rounded-md border px-1.5 text-[10px] font-bold uppercase tracking-[0.1em]",
        TONE[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

const ic = "size-3";
const STATUS: Record<string, { tone: StampTone; label: string; icon: React.ReactNode }> = {
  passed: { tone: "success", label: "Passed", icon: <Check className={ic} aria-hidden /> },
  failed: { tone: "danger", label: "Failed", icon: <X className={ic} aria-hidden /> },
  warning: { tone: "warn", label: "Warning", icon: <AlertTriangle className={ic} aria-hidden /> },
  not_run: { tone: "dashed", label: "Not run", icon: <CircleDashed className={ic} aria-hidden /> },
  verified: { tone: "muted", label: "Verified", icon: <Check className={ic} aria-hidden /> },
  needs_review: { tone: "warn", label: "Needs review", icon: <AlertTriangle className={ic} aria-hidden /> },
  conflict: { tone: "danger", label: "Conflict", icon: <X className={ic} aria-hidden /> },
  pending: { tone: "dashed", label: "Pending", icon: <Circle className={ic} aria-hidden /> },
  queued: { tone: "dashed", label: "Queued", icon: <Circle className={ic} aria-hidden /> },
  running: { tone: "gold", label: "Running", icon: <Loader2 className={cn(ic, "animate-spin")} aria-hidden /> },
  done: { tone: "gold", label: "Complete", icon: <Check className={ic} aria-hidden /> },
  succeeded: { tone: "gold", label: "Complete", icon: <Check className={ic} aria-hidden /> },
  skipped: { tone: "dashed", label: "Skipped", icon: <CircleDashed className={ic} aria-hidden /> },
  cancelled: { tone: "dashed", label: "Cancelled", icon: <X className={ic} aria-hidden /> },
  approved: { tone: "success", label: "Approved", icon: <Check className={ic} aria-hidden /> },
  approved_with_notes: { tone: "success", label: "Approved with notes", icon: <Check className={ic} aria-hidden /> },
  needs_rework: { tone: "danger", label: "Needs rework", icon: <X className={ic} aria-hidden /> },
  draft: { tone: "dashed", label: "Draft", icon: <Circle className={ic} aria-hidden /> },
  edited: { tone: "gold", label: "Edited", icon: <Check className={ic} aria-hidden /> },
  rejected: { tone: "danger", label: "Rejected", icon: <X className={ic} aria-hidden /> },
  built: { tone: "muted", label: "Built", icon: <Check className={ic} aria-hidden /> },
  built_derived: { tone: "warn", label: "Built · derived", icon: <AlertTriangle className={ic} aria-hidden /> },
  excluded: { tone: "danger", label: "Excluded", icon: <X className={ic} aria-hidden /> },
  critical: { tone: "danger", label: "Critical", icon: null },
  major: { tone: "warn", label: "Major", icon: null },
  minor: { tone: "muted", label: "Minor", icon: null },
};

export function StatusStamp({ status, className, label }: { status: string; className?: string; label?: string }) {
  const s = STATUS[status] ?? { tone: "muted" as StampTone, label: status, icon: null };
  return (
    <Stamp tone={s.tone} icon={s.icon} className={className}>
      {label ?? s.label}
    </Stamp>
  );
}

/** Confidence is a reading quality, not verification: a high value stays neutral, never green. */
export function ConfidenceBar({ value, className }: { value: number; className?: string }) {
  const band = confidenceBand(value);
  const color = band === "high" ? "bg-muted-foreground" : band === "medium" ? "bg-warn" : "bg-danger";
  const text = band === "high" ? "text-muted-foreground" : band === "medium" ? "text-warn" : "text-danger";
  return (
    <span className={cn("inline-flex items-center gap-2", className)} title={`Model confidence ${value.toFixed(2)} (${band}). Confidence is not verification.`}>
      <span className="relative h-1.5 w-12 overflow-hidden rounded-full bg-surface-raised" aria-hidden>
        <span className={cn("absolute inset-y-0 left-0 rounded-full", color)} style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className={cn("num text-xs", text)}>{value.toFixed(2)}</span>
    </span>
  );
}

/* ------------------------------------------------------------------ layout */

export const Glass = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & { flat?: boolean; as?: "div" | "section" | "aside" | "header" }>(
  function Glass({ className, flat, as: Tag = "div", ...props }, ref) {
    return <Tag ref={ref} className={cn(flat ? "glass-flat" : "glass", className)} {...props} />;
  },
);

export function CardHeader({
  icon,
  title,
  subtitle,
  right,
  sample,
  className,
  as: H = "h2",
}: {
  icon?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  right?: React.ReactNode;
  sample?: boolean;
  className?: string;
  as?: "h2" | "h3";
}) {
  return (
    <div className={cn("flex min-w-0 items-center gap-3", className)}>
      {icon && <span className="grid size-8 shrink-0 place-items-center text-gold [&_svg]:size-5">{icon}</span>}
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <H className="min-w-0 truncate text-base font-semibold leading-6 text-text">{title}</H>
          {sample && <SampleBadge className="ml-auto" />}
        </div>
        {subtitle && <div className="truncate text-xs text-muted-foreground">{subtitle}</div>}
      </div>
      {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  sample,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: string;
  sample?: boolean;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1 text-gold">{eyebrow}</div>}
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold leading-8 tracking-tight">{title}</h1>
          {sample && <SampleBadge />}
        </div>
        {description && <p className="mt-1 max-w-[70ch] text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/* ------------------------------------------------------------------ states */

export function EmptyState({
  icon,
  title,
  body,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  body?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 px-6 py-10 text-center", className)}>
      {icon && <div className="mb-1 grid size-11 place-items-center rounded-xl border border-line bg-surface-raised/40 text-muted-foreground [&_svg]:size-5">{icon}</div>}
      <p className="text-sm font-medium text-text">{title}</p>
      {body && <p className="max-w-[46ch] text-[13px] text-muted-foreground">{body}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry, className, title = "Could not load this" }: { error: unknown; onRetry?: () => void; className?: string; title?: string }) {
  const offline = typeof navigator !== "undefined" && !navigator.onLine;
  const message = error instanceof Error ? error.message : "Unknown error.";
  return (
    <div role="alert" className={cn("m-3 flex flex-col items-start gap-2 rounded-xl border border-danger/50 bg-danger/10 p-4", className)}>
      <div className="flex items-center gap-2 text-sm font-semibold text-danger">
        {offline ? <WifiOff className="size-4" aria-hidden /> : <AlertTriangle className="size-4" aria-hidden />}
        {offline ? "You are offline" : title}
      </div>
      <p className="text-[13px] text-text/90">{offline ? "Reconnect, then retry. Nothing was lost." : message}</p>
      {onRetry && (
        <button type="button" className="btn btn-sm btn-ghost" onClick={onRetry}>
          <RefreshCw className="size-3.5" aria-hidden /> Retry
        </button>
      )}
    </div>
  );
}

export function Skel({ className }: { className?: string }) {
  return <div className={cn("skel", className)} aria-hidden />;
}

export function TableSkeleton({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2 p-4", className)} role="status" aria-label="Loading">
      <Skel className="h-4 w-1/3" />
      {Array.from({ length: rows }, (_, i) => (
        <Skel key={i} className="h-7 w-full" />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ small parts */

export function RelTime({ iso, className }: { iso: string; className?: string }) {
  const [now, setNow] = React.useState<number | null>(null);
  React.useEffect(() => {
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  return (
    <time dateTime={iso} title={absTime(iso)} className={cn("num whitespace-nowrap text-xs text-muted-foreground", className)} suppressHydrationWarning>
      {now === null ? "" : relTime(iso, now)}
    </time>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: React.ReactNode; disabled?: boolean; title?: string }[];
  label: string;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex rounded-[10px] border border-line bg-bg/60 p-0.5", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          disabled={o.disabled}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-lg px-2.5 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45",
            size === "sm" ? "h-6 text-xs" : "h-7 text-[13px]",
            value === o.value ? "bg-gold/15 text-gold-hi shadow-[inset_0_0_0_1px_rgba(214,175,107,.45)]" : "text-muted-foreground hover:text-text",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide,
  className,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  wide?: boolean;
  className?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => onOpenChange(o)}>
      <DialogContent
        className={cn(
          "glass-flat max-h-[88dvh] gap-4 overflow-y-auto border-line bg-[#191229] p-5 text-[13px] text-text ring-0",
          wide ? "sm:max-w-3xl" : "sm:max-w-lg",
          className,
        )}
      >
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold">{title}</DialogTitle>
          {description ? <DialogDescription className="text-[13px] text-muted-foreground">{description}</DialogDescription> : <DialogDescription className="sr-only">{title}</DialogDescription>}
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("flex flex-col gap-1", className)}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-[11px] leading-4 text-faint">{hint}</span>}
    </label>
  );
}

export function StatRow({ label, value, className }: { label: React.ReactNode; value: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-center justify-between gap-3 border-b border-line/40 py-2 last:border-0", className)}>
      <span className="text-[13px] text-muted-foreground">{label}</span>
      <span className="num text-[13px] font-medium text-text">{value}</span>
    </div>
  );
}
