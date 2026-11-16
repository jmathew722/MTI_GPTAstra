"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { motion } from "motion/react";
import { Nebula } from "./Atmosphere";
import { ContextRailContent } from "./ContextRail";
import { Sidebar, TopNav } from "./Navigation";
import { CommandPalette, NavDrawer, NotificationCenter, OnboardingTour, RailSheet, ShortcutsDialog } from "./Overlays";
import { useIntro } from "./Providers";
import { PointerGlow } from "@/components/shared/motion";
import { fade } from "@/lib/motion";
import { WORKSPACE_TABS, useSelection, useUi } from "@/lib/store";
import { cn } from "@/lib/utils";

const GO: Record<string, string> = { d: "/dashboard", p: "/projects", a: "/automation", m: "/models", l: "/pipelines", s: "/settings" };

function useGlobalShortcuts() {
  const router = useRouter();
  React.useEffect(() => {
    let g = 0;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      const ui = useUi.getState();
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ui.set({ paletteOpen: !ui.paletteOpen });
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      // ignore while a dialog is open (closing dialogs may linger in the DOM during their exit animation)
      if (document.querySelector('[role="dialog"][data-open]')) return;
      const key = e.key.toLowerCase();
      if (Date.now() - g < 900 && GO[key]) {
        g = 0;
        router.push(GO[key]);
        return;
      }
      if (key === "g") {
        g = Date.now();
        return;
      }
      if (e.key === "?") ui.set({ shortcutsOpen: true });
      else if (e.key === "]") {
        if (window.matchMedia("(min-width: 1440px)").matches) ui.set({ railOpen: !ui.railOpen });
        else ui.set({ railSheetOpen: !ui.railSheetOpen });
      } else if (e.key === "Escape") useSelection.getState().clear();
      else if (/^[1-6]$/.test(e.key) && document.getElementById("workspace-tabs")) ui.set({ workspaceTab: WORKSPACE_TABS[Number(e.key) - 1] });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);
}

/** Routes that render without the application chrome. */
const BARE = [/^\/welcome/, /^\/viewer\//];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const railOpen = useUi((s) => s.railOpen);
  const intro = useIntro();
  useGlobalShortcuts();
  const bare = BARE.some((r) => r.test(pathname));
  // The workstation needs the width; the rail is one click away in a sheet there.
  const showRail = railOpen && !/^\/projects\/[^/]+/.test(pathname);

  if (bare)
    return (
      <>
        <Nebula />
        <div className="relative z-10 min-h-dvh">{children}</div>
        <CommandPalette />
        <ShortcutsDialog />
      </>
    );

  return (
    <>
      <a href="#main" className="btn btn-primary sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100]">
        Skip to content
      </a>
      <Nebula />
      <div className="relative z-10 flex min-h-dvh flex-col pb-4">
        <TopNav />
        <div className="mx-3 mt-3 flex min-w-0 flex-1 items-start gap-4 sm:mx-4">
          <Sidebar />
          <main id="main" tabIndex={-1} className="min-w-0 flex-1 outline-none">
            {children}
          </main>
          <motion.aside
            aria-label="Context rail"
            variants={fade}
            initial={intro ? "hidden" : false}
            animate="show"
            className={cn("sticky top-[92px] hidden max-h-[calc(100dvh-108px)] w-[336px] shrink-0 overflow-y-auto pr-0.5", showRail && "min-[1440px]:block")}
          >
            <ContextRailContent />
          </motion.aside>
        </div>
      </div>
      <PointerGlow />
      <CommandPalette />
      <ShortcutsDialog />
      <NotificationCenter />
      <NavDrawer />
      <RailSheet />
      <OnboardingTour />
    </>
  );
}
