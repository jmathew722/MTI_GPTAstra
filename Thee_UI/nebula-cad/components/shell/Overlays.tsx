"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import { AlertTriangle, ArrowRight, Bell, BookOpen, Box, CheckCircle2, Download, FolderClosed, Keyboard, PanelRight, Play, Search, Wallet } from "lucide-react";
import { ContextRailContent } from "./ContextRail";
import { SidebarContent, TOP_NAV, useFocusedProjectId, useSideNav } from "./Navigation";
import { EmptyState, Modal, RelTime, SampleBadge } from "@/components/shared";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { IS_MOCK } from "@/lib/api";
import { useMarkNotificationsRead, useNotifications, useProjects } from "@/lib/api/hooks";
import { WORKSPACE_TABS, useSettings, useUi } from "@/lib/store";
import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------- command palette */

const itemCls =
  "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-text/90 data-[selected=true]:bg-gold/12 data-[selected=true]:text-gold-hi";

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const set = useUi((s) => s.set);
  const router = useRouter();
  const { data: projects } = useProjects();
  const focused = useFocusedProjectId();
  const side = useSideNav();
  const go = (href: string) => {
    set({ paletteOpen: false });
    router.push(href);
  };
  const run = (fn: () => void) => {
    set({ paletteOpen: false });
    fn();
  };
  const pages = [...TOP_NAV, ...side.filter((s) => !TOP_NAV.some((t) => t.label === s.label)).map((s) => ({ href: s.href, label: s.label }))];

  return (
    <Dialog open={open} onOpenChange={(o) => set({ paletteOpen: o })}>
      <DialogContent showCloseButton={false} className="glass-flat top-[18%] translate-y-0 gap-0 overflow-hidden border-line bg-[#191229] p-0 text-text ring-0 sm:max-w-xl">
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <DialogDescription className="sr-only">Jump to a project or page, run an action, or switch a workspace tab.</DialogDescription>
        <Command label="Command palette" loop>
          <div className="flex items-center gap-2 border-b border-line/60 px-3">
            <Search className="size-4 text-muted-foreground" aria-hidden />
            <Command.Input
              autoFocus
              placeholder="Jump to a project, run an action, switch a tab…"
              className="h-12 w-full bg-transparent text-sm text-text outline-none placeholder:text-faint"
            />
            <kbd>esc</kbd>
          </div>
          <Command.List className="max-h-[52dvh] overflow-y-auto p-2 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.12em] [&_[cmdk-group-heading]]:text-muted-foreground">
            <Command.Empty className="px-3 py-6 text-center text-[13px] text-muted-foreground">Nothing matches. Try a part number or a page name.</Command.Empty>
            <Command.Group heading="Projects">
              {projects?.map((p) => (
                <Command.Item key={p.id} value={`project ${p.name} ${p.partNumber}`} onSelect={() => go(`/projects/${p.id}`)} className={itemCls}>
                  <FolderClosed className="size-4 text-gold" aria-hidden />
                  <span className="flex-1 truncate">{p.name}</span>
                  <span className="num text-xs text-muted-foreground">
                    {p.partNumber} · Rev {p.revision}
                  </span>
                </Command.Item>
              ))}
            </Command.Group>
            <Command.Group heading="Actions">
              <Command.Item value="action new run generate cad upload drawing" onSelect={() => go("/automation")} className={itemCls}>
                <Play className="size-4 text-gold" aria-hidden /> New run: generate CAD from a drawing
              </Command.Item>
              {focused && (
                <>
                  <Command.Item value="action open viewer full screen" onSelect={() => go(`/viewer/${focused}`)} className={itemCls}>
                    <Box className="size-4 text-gold" aria-hidden /> Open the focused model full screen
                  </Command.Item>
                  <Command.Item
                    value="action export center download deliverables"
                    onSelect={() => {
                      go(`/projects/${focused}`);
                      setTimeout(() => useUi.getState().set({ exportOpen: true }), 350);
                    }}
                    className={itemCls}
                  >
                    <Download className="size-4 text-gold" aria-hidden /> Export center for the focused project
                  </Command.Item>
                </>
              )}
              <Command.Item value="action toggle context rail" onSelect={() => run(() => set({ railOpen: !useUi.getState().railOpen }))} className={itemCls}>
                <PanelRight className="size-4 text-gold" aria-hidden /> Toggle the context rail <kbd className="ml-auto">]</kbd>
              </Command.Item>
              <Command.Item value="action keyboard shortcuts help" onSelect={() => run(() => set({ shortcutsOpen: true }))} className={itemCls}>
                <Keyboard className="size-4 text-gold" aria-hidden /> Keyboard shortcuts <kbd className="ml-auto">?</kbd>
              </Command.Item>
            </Command.Group>
            <Command.Group heading="Workspace tabs">
              {WORKSPACE_TABS.map((t, i) => (
                <Command.Item
                  key={t}
                  value={`tab ${t}`}
                  onSelect={() => {
                    set({ workspaceTab: t, paletteOpen: false });
                    if (focused && !/^\/(dashboard|projects\/)/.test(window.location.pathname)) router.push(`/projects/${focused}`);
                    setTimeout(() => document.getElementById("workspace-tabs")?.scrollIntoView({ behavior: "smooth", block: "start" }), 350);
                  }}
                  className={itemCls}
                >
                  <ArrowRight className="size-4 text-gold" aria-hidden /> {t} <kbd className="ml-auto">{i + 1}</kbd>
                </Command.Item>
              ))}
            </Command.Group>
            <Command.Group heading="Pages">
              {pages.map((p) => (
                <Command.Item key={p.label} value={`page ${p.label}`} onSelect={() => go(p.href)} className={itemCls}>
                  <BookOpen className="size-4 text-muted-foreground" aria-hidden /> {p.label}
                </Command.Item>
              ))}
              <Command.Item value="page library" onSelect={() => go("/library")} className={itemCls}>
                <BookOpen className="size-4 text-muted-foreground" aria-hidden /> Library
              </Command.Item>
              <Command.Item value="page welcome landing" onSelect={() => go("/welcome")} className={itemCls}>
                <BookOpen className="size-4 text-muted-foreground" aria-hidden /> Welcome page
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

/* ---------------------------------------------------------------- shortcuts */

export const SHORTCUTS: { keys: string[]; label: string }[] = [
  { keys: ["⌘", "K"], label: "Open the command palette (Ctrl K on Windows)" },
  { keys: ["?"], label: "Show this cheat sheet" },
  { keys: ["G", "D"], label: "Go to Dashboard" },
  { keys: ["G", "P"], label: "Go to Projects" },
  { keys: ["G", "A"], label: "Go to Automation" },
  { keys: ["G", "M"], label: "Go to Models" },
  { keys: ["G", "L"], label: "Go to Pipelines" },
  { keys: ["G", "S"], label: "Go to Settings" },
  { keys: ["1", "…", "6"], label: "Switch workspace tab (Parameters … Rubric)" },
  { keys: ["]"], label: "Toggle the context rail" },
  { keys: ["F"], label: "Viewer: fit the model (when the viewer has focus)" },
  { keys: ["R"], label: "Viewer: reset the camera (when the viewer has focus)" },
  { keys: ["Esc"], label: "Close dialogs, clear the current selection" },
];

export function ShortcutsDialog() {
  const open = useUi((s) => s.shortcutsOpen);
  const set = useUi((s) => s.set);
  return (
    <Modal open={open} onOpenChange={(o) => set({ shortcutsOpen: o })} title="Keyboard shortcuts" description="Shortcuts are ignored while you are typing in a field.">
      <ul className="flex flex-col">
        {SHORTCUTS.map((s) => (
          <li key={s.label} className="flex items-center justify-between gap-4 border-b border-line/40 py-2 last:border-0">
            <span className="text-[13px] text-text/90">{s.label}</span>
            <span className="flex shrink-0 items-center gap-1">
              {s.keys.map((k, i) => (k === "…" ? <span key={i} className="text-muted-foreground">…</span> : <kbd key={i}>{k}</kbd>))}
            </span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}

/* ---------------------------------------------------------------- notifications */

const NOTE_ICON = {
  run_finished: <CheckCircle2 className="size-4 text-gold" aria-hidden />,
  validation_failed: <AlertTriangle className="size-4 text-danger" aria-hidden />,
  budget_warning: <Wallet className="size-4 text-warn" aria-hidden />,
  review_needed: <AlertTriangle className="size-4 text-warn" aria-hidden />,
};

export function NotificationCenter() {
  const open = useUi((s) => s.notificationsOpen);
  const set = useUi((s) => s.set);
  const { data } = useNotifications();
  const mark = useMarkNotificationsRead();
  const unread = data?.filter((n) => !n.read).length ?? 0;
  return (
    <Sheet open={open} onOpenChange={(o) => set({ notificationsOpen: o })}>
      <SheetContent side="right" className="w-[min(92vw,400px)] gap-0 border-line bg-[#171128] p-0 text-text sm:max-w-[400px]">
        <SheetHeader className="border-b border-line/60 p-4">
          <SheetTitle className="flex items-center gap-2 text-base font-semibold text-text">
            <Bell className="size-4 text-gold" aria-hidden /> Notifications {IS_MOCK && <SampleBadge />}
          </SheetTitle>
          <SheetDescription className="text-xs text-muted-foreground">
            Driven by pipeline events: runs finishing, validation failures, budget warnings.
          </SheetDescription>
        </SheetHeader>
        <div className="flex items-center justify-between px-4 py-2">
          <span className="text-xs text-muted-foreground">{unread} unread</span>
          <button type="button" className="btn btn-sm btn-quiet" disabled={!unread} onClick={() => mark.mutate()}>
            Mark all read
          </button>
        </div>
        <ul className="flex-1 overflow-y-auto px-2 pb-4">
          {data?.length === 0 && <EmptyState icon={<Bell />} title="Nothing yet" body="You will be told here when a run finishes or a validation check fails." />}
          {data?.map((n) => {
            const body = (
              <>
                <span className="mt-0.5 shrink-0">{NOTE_ICON[n.kind]}</span>
                <span className="min-w-0 flex-1">
                  <span className={cn("block text-[13px] font-medium", n.read ? "text-text/80" : "text-text")}>{n.title}</span>
                  <span className="block text-xs leading-5 text-muted-foreground">{n.body}</span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1">
                  <RelTime iso={n.at} />
                  {!n.read && <span className="size-2 rounded-full bg-gold" aria-label="Unread" />}
                </span>
              </>
            );
            return (
              <li key={n.id}>
                {n.projectId ? (
                  <Link href={`/projects/${n.projectId}`} onClick={() => set({ notificationsOpen: false })} className="flex items-start gap-3 rounded-lg px-2 py-2.5 hover:bg-surface-raised/40">
                    {body}
                  </Link>
                ) : (
                  <div className="flex items-start gap-3 px-2 py-2.5">{body}</div>
                )}
              </li>
            );
          })}
        </ul>
      </SheetContent>
    </Sheet>
  );
}

/* ---------------------------------------------------------------- drawers */

export function NavDrawer() {
  const open = useUi((s) => s.navDrawerOpen);
  const set = useUi((s) => s.set);
  const close = () => set({ navDrawerOpen: false });
  return (
    <Sheet open={open} onOpenChange={(o) => set({ navDrawerOpen: o })}>
      <SheetContent side="left" className="w-[min(86vw,300px)] gap-0 border-line bg-[#171128] p-3 text-text sm:max-w-[300px]">
        <SheetHeader className="p-1 pb-3">
          <SheetTitle className="text-sm font-semibold tracking-[0.2em] text-text">
            NEBULA <span className="text-gold">CAD</span>
          </SheetTitle>
          <SheetDescription className="sr-only">Navigation</SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <SidebarContent onNavigate={close} />
          <div className="mt-3 flex gap-2 border-t border-line/50 pt-3">
            <Link href="/models" onClick={close} className="btn btn-sm btn-ghost flex-1">
              Models
            </Link>
            <Link href="/docs" onClick={close} className="btn btn-sm btn-ghost flex-1">
              Docs
            </Link>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function RailSheet() {
  const open = useUi((s) => s.railSheetOpen);
  const set = useUi((s) => s.set);
  return (
    <Sheet open={open} onOpenChange={(o) => set({ railSheetOpen: o })}>
      <SheetContent side="right" className="w-[min(92vw,380px)] gap-0 overflow-y-auto border-line bg-[#120d20] p-4 text-text sm:max-w-[380px]">
        <SheetHeader className="p-0 pb-3">
          <SheetTitle className="text-base font-semibold text-text">Context</SheetTitle>
          <SheetDescription className="sr-only">Project overview, performance and activity</SheetDescription>
        </SheetHeader>
        <ContextRailContent flat />
      </SheetContent>
    </Sheet>
  );
}

/* ---------------------------------------------------------------- onboarding tour */

const TOUR = [
  {
    title: "This tool fails quietly. The UI is built to make that loud.",
    body: "The pipeline can hand you a confident but wrong model. Every screen puts mismatches, low confidence and unverified results first.",
  },
  {
    title: "Start with the flange",
    body: "Flange_Adapter is seeded with the real failure: the drawing calls out 10 holes, extraction located 8. Open it to see the banner, the blocked export and the capped rubric.",
  },
  {
    title: "Compare, review, sign off",
    body: "On a project page the drawing and the model sit side by side. Click any extracted item to see where it came from. Approve, edit or reject each one, then grade the part in the Rubric tab.",
  },
  {
    title: "You are looking at sample data",
    body: "Everything marked SAMPLE DATA is synthetic. Set NEXT_PUBLIC_API_MODE=http to connect the real pipeline. Press ⌘K any time to jump around, or ? for shortcuts.",
  },
];

export function OnboardingTour() {
  const done = useSettings((s) => s.tourDone);
  const setSettings = useSettings((s) => s.set);
  const [step, setStep] = React.useState(0);
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => {
    // Skipped under automation (navigator.webdriver) so tests and screenshots are not covered by it.
    if (!done && !navigator.webdriver) {
      const t = setTimeout(() => setOpen(true), 1800);
      return () => clearTimeout(t);
    }
  }, [done]);
  const finish = () => {
    setOpen(false);
    setSettings({ tourDone: true });
  };
  const s = TOUR[step];
  return (
    <Modal open={open} onOpenChange={(o) => (o ? setOpen(true) : finish())} title={s.title}>
      <p className="text-sm leading-6 text-text/90">{s.body}</p>
      <div className="flex items-center justify-between gap-3">
        <div className="flex gap-1.5" aria-label={`Step ${step + 1} of ${TOUR.length}`}>
          {TOUR.map((_, i) => (
            <span key={i} className={cn("h-1.5 w-6 rounded-full", i === step ? "bg-gold" : "bg-surface-raised")} />
          ))}
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn btn-sm btn-quiet" onClick={finish}>
            Skip
          </button>
          {step < TOUR.length - 1 ? (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => setStep(step + 1)}>
              Next
            </button>
          ) : (
            <Link href="/projects/fl-2210" className="btn btn-sm btn-primary" onClick={finish}>
              Open the flange
            </Link>
          )}
        </div>
      </div>
    </Modal>
  );
}
