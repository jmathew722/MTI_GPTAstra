"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  DEFAULT_MFG_RATES,
  DEFAULT_PIPELINE_RATES,
  DEFAULT_ROI,
  type MfgRates,
  type PipelineRates,
  type RoiAssumptions,
} from "@/lib/cost";
import type { MaterialKey, Units } from "@/lib/schemas";

export const WORKSPACE_TABS = ["Parameters", "Features", "Validation", "Cost", "Logs", "Rubric"] as const;
export type WorkspaceTab = (typeof WORKSPACE_TABS)[number];
export type CompareMode = "split" | "overlay" | "diff";
export type ReviewTab = "extraction" | "plan" | "comments" | "revisions" | "audit";

interface SettingsState {
  reviewerName: string;
  units: Units;
  defaultMaterial: MaterialKey;
  density: "comfortable" | "compact";
  motion: "full" | "reduced";
  pipelineRates: PipelineRates;
  mfgRates: MfgRates;
  roi: RoiAssumptions;
  monthlyBudget: number;
  tourDone: boolean;
  focusedProjectId: string | null;
  set: (patch: Partial<Omit<SettingsState, "set" | "resetRates">>) => void;
  resetRates: () => void;
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      reviewerName: "Sample Reviewer",
      units: "mm",
      defaultMaterial: "steel",
      density: "comfortable",
      motion: "full",
      pipelineRates: DEFAULT_PIPELINE_RATES,
      mfgRates: DEFAULT_MFG_RATES,
      roi: DEFAULT_ROI,
      monthlyBudget: 25,
      tourDone: false,
      focusedProjectId: null,
      set: (patch) => set(patch),
      resetRates: () => set({ pipelineRates: DEFAULT_PIPELINE_RATES, mfgRates: DEFAULT_MFG_RATES, roi: DEFAULT_ROI }),
    }),
    { name: "nebula-settings-v1" },
  ),
);

interface UiState {
  railOpen: boolean;
  railSheetOpen: boolean;
  navDrawerOpen: boolean;
  paletteOpen: boolean;
  shortcutsOpen: boolean;
  notificationsOpen: boolean;
  exportOpen: boolean;
  workspaceTab: WorkspaceTab;
  compareMode: CompareMode;
  reviewTab: ReviewTab;
  heatmap: boolean;
  set: (patch: Partial<Omit<UiState, "set">>) => void;
}

export const useUi = create<UiState>()((set) => ({
  railOpen: true,
  railSheetOpen: false,
  navDrawerOpen: false,
  paletteOpen: false,
  shortcutsOpen: false,
  notificationsOpen: false,
  exportOpen: false,
  workspaceTab: "Parameters",
  compareMode: "split",
  reviewTab: "extraction",
  heatmap: false,
  set: (patch) => set(patch),
}));

interface SelectionState {
  itemId: string | null;
  featureId: string | null;
  checkId: string | null;
  /** bumps whenever a selection is made, so viewers can re-focus even on the same id */
  tick: number;
  select: (s: { itemId?: string | null; featureId?: string | null; checkId?: string | null }) => void;
  clear: () => void;
}

export const useSelection = create<SelectionState>()((set) => ({
  itemId: null,
  featureId: null,
  checkId: null,
  tick: 0,
  select: (s) =>
    set((prev) => ({
      itemId: s.itemId === undefined ? prev.itemId : s.itemId,
      featureId: s.featureId === undefined ? prev.featureId : s.featureId,
      checkId: s.checkId === undefined ? prev.checkId : s.checkId,
      tick: prev.tick + 1,
    })),
  clear: () => set((p) => ({ itemId: null, featureId: null, checkId: null, tick: p.tick + 1 })),
}));

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}
