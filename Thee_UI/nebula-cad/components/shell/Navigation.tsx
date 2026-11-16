"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "motion/react";
import {
  Bell,
  Box,
  FolderClosed,
  House,
  Layers,
  Library,
  Menu,
  PanelRight,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Logo, PartGlyph } from "./Atmosphere";
import { useIntro } from "./Providers";
import { SampleBadge } from "@/components/shared";
import { IS_MOCK } from "@/lib/api";
import { useNotifications, useProjects, useSystemStatus } from "@/lib/api/hooks";
import { fadeUp, slideDown, spring, stagger } from "@/lib/motion";
import { initials, useSettings, useUi } from "@/lib/store";

export const TOP_NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/projects", label: "Projects" },
  { href: "/automation", label: "Automation" },
  { href: "/models", label: "Models" },
  { href: "/pipelines", label: "Pipelines" },
  { href: "/docs", label: "Docs" },
] as const;

export function useFocusedProjectId(): string | null {
  const pathname = usePathname();
  const stored = useSettings((s) => s.focusedProjectId);
  const { data } = useProjects();
  const m = pathname.match(/^\/(?:projects|viewer)\/([^/]+)/);
  if (m) return decodeURIComponent(m[1]);
  if (stored && data?.some((p) => p.id === stored)) return stored;
  return data?.[0]?.id ?? null;
}

export function useSideNav() {
  const focused = useFocusedProjectId();
  return [
    { href: "/dashboard", label: "Dashboard", icon: House },
    { href: "/projects", label: "Projects", icon: FolderClosed },
    { href: "/automation", label: "Automation", icon: Sparkles },
    { href: focused ? `/viewer/${focused}` : "/models", label: "CAD Viewer", icon: Box, match: "/viewer" },
    { href: "/pipelines", label: "Pipelines", icon: Layers },
    { href: "/library", label: "Library", icon: Library },
    { href: "/settings", label: "Settings", icon: Settings },
  ];
}

const isActive = (pathname: string, base: string) => pathname === base || pathname.startsWith(`${base}/`);

export function TopNav() {
  const pathname = usePathname();
  const intro = useIntro();
  const set = useUi((s) => s.set);
  const railOpen = useUi((s) => s.railOpen);
  const name = useSettings((s) => s.reviewerName);
  const { data: notes } = useNotifications();
  const unread = notes?.filter((n) => !n.read).length ?? 0;

  return (
    <motion.header
      variants={slideDown}
      initial={intro ? "hidden" : false}
      animate="show"
      className="glass sticky top-3 z-40 mx-3 flex h-16 items-center gap-3 px-3 sm:mx-4 sm:px-4"
    >
      <button type="button" className="btn btn-icon btn-quiet lg:hidden" aria-label="Open navigation" onClick={() => set({ navDrawerOpen: true })}>
        <Menu className="size-5" aria-hidden />
      </button>
      <Link href="/dashboard" className="flex shrink-0 items-center gap-3 rounded-lg pr-2">
        <span className="sr-only">2D to 3D CAD, go to dashboard.</span>
        <Logo />
        <span className="hidden flex-col leading-none sm:flex lg:hidden xl:flex">
          <span className="text-[18px] font-semibold tracking-[0.16em] text-text">
            2D TO 3D <span className="text-gold">CAD</span>
          </span>
          <span className="mt-1 text-[9px] font-semibold tracking-[0.32em] text-muted-foreground">DESIGN AUTOMATION PLATFORM</span>
        </span>
      </Link>

      <nav aria-label="Primary" className="mx-auto hidden items-center gap-1 lg:flex">
        {TOP_NAV.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative rounded-[10px] px-3 py-2 text-sm font-medium transition-colors min-[1360px]:px-5",
                active ? "text-gold-hi" : "text-muted-foreground hover:text-text",
              )}
            >
              {active && <motion.span layoutId="topnav-pill" className="tab-pill" transition={spring} />}
              <span className="relative z-10">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="ml-auto flex items-center gap-1.5 lg:ml-0">
        {IS_MOCK && <SampleBadge className="hidden sm:inline-flex" label={<>Sample<span className="hidden min-[1360px]:inline">&nbsp;data mode</span></>} />}
        <button
          type="button"
          className="btn btn-ghost btn-sm hidden gap-2 pr-1.5 md:inline-flex"
          onClick={() => set({ paletteOpen: true })}
        >
          <Search className="size-4" aria-hidden />
          <span className="sr-only xl:not-sr-only xl:text-muted-foreground">Search</span>
          <kbd>⌘K</kbd>
        </button>
        <button type="button" className="btn btn-icon btn-quiet md:hidden" aria-label="Search and commands" onClick={() => set({ paletteOpen: true })}>
          <Search className="size-5" aria-hidden />
        </button>
        <button
          type="button"
          className="btn btn-icon btn-quiet relative"
          aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
          onClick={() => set({ notificationsOpen: true })}
        >
          <Bell key={unread} className={cn("size-5", unread > 0 && "bell-ring")} aria-hidden />
          {unread > 0 && <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-gold shadow-[0_0_8px_rgba(214,175,107,.9)]" aria-hidden />}
        </button>
        <button
          type="button"
          className="btn btn-icon btn-quiet hidden lg:inline-flex"
          aria-label={railOpen ? "Hide context rail" : "Show context rail"}
          aria-pressed={railOpen}
          onClick={() => {
            if (window.matchMedia("(min-width: 1440px)").matches) set({ railOpen: !railOpen });
            else set({ railSheetOpen: true });
          }}
        >
          <PanelRight className="size-5" aria-hidden />
        </button>
        <Link
          href="/settings"
          title={name}
          className="ml-1 grid size-10 place-items-center rounded-full border border-gold/60 bg-gold/10 text-sm font-semibold text-gold-hi shadow-[0_0_14px_rgba(214,175,107,.18)] transition-colors hover:bg-gold/20"
        >
          {initials(name)}
          <span className="sr-only">: settings for {name}</span>
        </Link>
      </div>
    </motion.header>
  );
}

export function SidebarContent({ compact = false, onNavigate }: { compact?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const intro = useIntro();
  const items = useSideNav();
  const { data: projects } = useProjects();
  const { data: sys } = useSystemStatus();
  const recent = projects?.slice(0, 3) ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      {!compact && <div className="eyebrow px-3 pb-2 pt-1">Workspace</div>}
      <motion.nav aria-label="Workspace" variants={stagger(0.15)} initial={intro ? "hidden" : false} animate="show" className="flex flex-col gap-0.5">
        {items.map((item) => {
          const active = isActive(pathname, item.match ?? item.href);
          const Icon = item.icon;
          return (
            <motion.div key={item.label} variants={fadeUp}>
              <Link
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                aria-label={compact ? item.label : undefined}
                title={compact ? item.label : undefined}
                className={cn(
                  "group relative flex h-10 items-center gap-3 rounded-[10px] border border-transparent text-sm font-medium transition-colors",
                  compact ? "justify-center px-0" : "px-3",
                  active ? "text-gold-hi" : "text-muted-foreground hover:bg-surface-raised/40 hover:text-text",
                )}
              >
                {active && <motion.span layoutId={compact ? "side-pill-c" : "side-pill"} className="tab-pill" transition={spring} />}
                <Icon className={cn("relative z-10 size-[18px] shrink-0", active ? "text-gold" : "")} aria-hidden />
                {!compact && <span className="relative z-10 truncate">{item.label}</span>}
              </Link>
            </motion.div>
          );
        })}
      </motion.nav>

      {!compact && (
        <>
          <div className="mx-3 my-4 h-px bg-line/60" />
          <div className="eyebrow flex items-center justify-between whitespace-nowrap px-3 pb-2">
            Recent projects {IS_MOCK && <SampleBadge label="Sample" />}
          </div>
          <ul className="flex flex-col gap-0.5">
            {recent.map((p) => (
              <li key={p.id}>
                <Link
                  href={`/projects/${p.id}`}
                  onClick={onNavigate}
                  className="flex items-center gap-3 rounded-[10px] px-3 py-1.5 transition-colors hover:bg-surface-raised/40"
                >
                  <PartGlyph specKey={p.partSpecKey} className="size-9 shrink-0" />
                  <span className="min-w-0">
                    <span className="block truncate text-[13px] font-medium text-text">{p.name}</span>
                    <span className="num block text-[11px] text-muted-foreground">
                      Rev {p.revision} · {p.partNumber}
                    </span>
                  </span>
                  {p.status === "needs_rework" && <span className="ml-auto size-2 shrink-0 rounded-full bg-danger" title="Needs rework" aria-label="Needs rework" />}
                </Link>
              </li>
            ))}
            {projects && recent.length === 0 && <li className="px-3 text-xs text-muted-foreground">No projects yet.</li>}
          </ul>
        </>
      )}

      <div className={cn("mt-auto pt-4", compact && "flex justify-center")}>
        {compact ? (
          <span
            className={cn("size-2.5 rounded-full", sys?.online ? "bg-gold shadow-[0_0_10px_rgba(214,175,107,.8)]" : "bg-danger")}
            title={sys?.online ? "System online" : "System offline"}
            aria-label={sys?.online ? "System online" : "System offline"}
          />
        ) : (
          <div className="glass-raised px-3 py-3" role="status">
            <div className="flex items-center gap-2">
              <span className={cn("size-2.5 shrink-0 rounded-full", sys?.online ? "bg-gold shadow-[0_0_10px_rgba(214,175,107,.8)]" : "bg-danger")} aria-hidden />
              <span className="whitespace-nowrap text-sm font-semibold">{sys ? (sys.online ? "System Online" : "System Offline") : "Checking…"}</span>
              {sys?.isSample && <SampleBadge label="Sample" className="ml-auto" />}
            </div>
            <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
              {[
                ["GPU", sys?.gpuUtilization !== undefined ? `${Math.round(sys.gpuUtilization * 100)}%` : "n/a"],
                ["Queue", sys?.queueDepth ?? "–"],
                ["Active", sys?.activeRuns ?? "–"],
              ].map(([k, v]) => (
                <div key={String(k)}>
                  <dt className="text-[11px] text-muted-foreground">{k}</dt>
                  <dd className="num font-medium text-text">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </div>
  );
}

export function Sidebar() {
  return (
    <>
      <aside className="glass sticky top-[92px] hidden h-[calc(100dvh-108px)] w-[248px] shrink-0 flex-col p-3 lg:flex" aria-label="Sidebar">
        <SidebarContent />
      </aside>
      <aside className="glass sticky top-[92px] hidden h-[calc(100dvh-108px)] w-16 shrink-0 flex-col p-2 md:flex lg:hidden" aria-label="Sidebar">
        <SidebarContent compact />
      </aside>
    </>
  );
}

