"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type ItemReviewInput, type SignOffInput } from "./index";
import type { Region, RubricEntry, RubricTemplate, StartRunInput } from "@/lib/schemas";
import { useSettings } from "@/lib/store";

const k = {
  system: ["system"] as const,
  kpis: ["kpis"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  sub: (id: string, what: string) => ["project", id, what] as const,
  runs: ["runs"] as const,
  run: (id: string) => ["run", id] as const,
  logs: (id: string) => ["logs", id] as const,
  templates: ["templates"] as const,
  notifications: ["notifications"] as const,
  monthly: ["monthly"] as const,
};

export const useSystemStatus = () => useQuery({ queryKey: k.system, queryFn: () => api.getSystemStatus(), refetchInterval: 5000 });
export const useKpis = () => useQuery({ queryKey: k.kpis, queryFn: () => api.getKpis() });
export const useProjects = () => useQuery({ queryKey: k.projects, queryFn: () => api.listProjects() });
export const useProject = (id?: string | null) =>
  useQuery({ queryKey: k.project(id ?? ""), queryFn: () => api.getProject(id as string), enabled: Boolean(id), retry: false });

const sub = <T>(what: string, fn: (id: string) => Promise<T>) =>
  function useSub(id?: string | null) {
    return useQuery({ queryKey: k.sub(id ?? "", what), queryFn: () => fn(id as string), enabled: Boolean(id), retry: false });
  };

export const useDrawing = sub("drawing", (id) => api.getDrawing(id));
export const useExtraction = sub("extraction", (id) => api.getExtraction(id));
export const useBuildPlan = sub("buildPlan", (id) => api.getBuildPlan(id));
export const useParameters = sub("parameters", (id) => api.getParameters(id));
export const useValidation = sub("validation", (id) => api.getValidation(id));
export const useCost = sub("cost", (id) => api.getCost(id));
export const useRubricScore = sub("rubric", (id) => api.getRubricScore(id));
export const useRevisions = sub("revisions", (id) => api.listRevisions(id));
export const useAudit = sub("audit", (id) => api.listAudit(id));
export const useComments = sub("comments", (id) => api.listComments(id));
export const useExports = sub("exports", (id) => api.listExports(id));

export const useMonthlyCost = () => useQuery({ queryKey: k.monthly, queryFn: () => api.getMonthlyCost() });
export const useTemplates = () => useQuery({ queryKey: k.templates, queryFn: () => api.listRubricTemplates() });
export const useNotifications = () => useQuery({ queryKey: k.notifications, queryFn: () => api.listNotifications(), refetchInterval: 6000 });

const live = (status?: string) => status === "running" || status === "queued";

export const useRuns = () =>
  useQuery({
    queryKey: k.runs,
    queryFn: () => api.listRuns(),
    refetchInterval: (q) => (q.state.data?.some((r) => live(r.status)) ? 1500 : false),
  });

export const useRun = (runId?: string | null) =>
  useQuery({
    queryKey: k.run(runId ?? ""),
    queryFn: () => api.getRun(runId as string),
    enabled: Boolean(runId),
    retry: false,
    refetchInterval: (q) => (live(q.state.data?.status) ? 700 : false),
  });

export const useLogs = (runId?: string | null, isLive = false) =>
  useQuery({ queryKey: k.logs(runId ?? ""), queryFn: () => api.getLogs(runId as string), enabled: Boolean(runId), refetchInterval: isLive ? 1500 : false });

function fail(e: unknown) {
  toast.error(e instanceof Error ? e.message : "Something went wrong.");
}

function invalidateProject(qc: QueryClient, id: string) {
  qc.invalidateQueries({ queryKey: k.project(id) });
  qc.invalidateQueries({ queryKey: k.projects });
  qc.invalidateQueries({ queryKey: k.kpis });
}

const useBy = () => useSettings((s) => s.reviewerName);

export function useReviewItem(projectId: string) {
  const qc = useQueryClient();
  const by = useBy();
  return useMutation({
    mutationFn: (v: { itemId: string } & Omit<ItemReviewInput, "by">) => api.reviewExtractionItem(projectId, v.itemId, { ...v, by }),
    onSuccess: () => invalidateProject(qc, projectId),
    onError: fail,
  });
}

export function useUpdateParameter(projectId: string) {
  const qc = useQueryClient();
  const by = useBy();
  return useMutation({
    mutationFn: (v: { paramId: string; value: number }) => api.updateParameter(projectId, v.paramId, v.value, by),
    onSuccess: () => invalidateProject(qc, projectId),
    onError: fail,
  });
}

export function useOverrideCheck(projectId: string) {
  const qc = useQueryClient();
  const by = useBy();
  return useMutation({
    mutationFn: (v: { checkId: string; reason: string | null }) =>
      v.reason === null ? api.clearOverride(projectId, v.checkId, by) : api.overrideCheck(projectId, v.checkId, by, v.reason),
    onSuccess: (_d, v) => {
      invalidateProject(qc, projectId);
      toast.success(v.reason === null ? "Override removed." : "Override recorded in the audit trail.");
    },
    onError: fail,
  });
}

export function useSaveRubric(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: { entries?: RubricEntry[]; templateId?: string }) => api.saveRubricScore(projectId, patch),
    onSuccess: (data) => qc.setQueryData(k.sub(projectId, "rubric"), data),
    onError: fail,
  });
}

export function useRubricGateOverride(projectId: string) {
  const qc = useQueryClient();
  const by = useBy();
  return useMutation({
    mutationFn: (reason: string | null) => api.overrideRubricGate(projectId, by, reason),
    onSuccess: () => invalidateProject(qc, projectId),
    onError: fail,
  });
}

export function useSignOff(projectId: string) {
  const qc = useQueryClient();
  const by = useBy();
  return useMutation({
    mutationFn: (v: Omit<SignOffInput, "by">) => api.signOff(projectId, { ...v, by }),
    onSuccess: () => {
      invalidateProject(qc, projectId);
      toast.success("Sign-off recorded.");
    },
    onError: fail,
  });
}

export function useSaveTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (t: RubricTemplate) => api.saveRubricTemplate(t),
    onSuccess: () => qc.invalidateQueries({ queryKey: k.templates }),
    onError: fail,
  });
}
export function useDeleteTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteRubricTemplate(id),
    onSuccess: () => qc.invalidateQueries(),
    onError: fail,
  });
}

export function useAddComment(projectId: string) {
  const qc = useQueryClient();
  const author = useBy();
  return useMutation({
    mutationFn: (v: { body: string; region?: Region; itemId?: string }) => api.addComment(projectId, { ...v, author }),
    onSuccess: () => invalidateProject(qc, projectId),
    onError: fail,
  });
}
export function useResolveComment(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { commentId: string; resolved: boolean }) => api.resolveComment(projectId, v.commentId, v.resolved),
    onSuccess: () => invalidateProject(qc, projectId),
    onError: fail,
  });
}

export function useCloneProject() {
  const qc = useQueryClient();
  const by = useBy();
  return useMutation({
    mutationFn: (id: string) => api.cloneProject(id, by),
    onSuccess: () => qc.invalidateQueries({ queryKey: k.projects }),
    onError: fail,
  });
}

export function useRecordExport(projectId: string) {
  const qc = useQueryClient();
  const by = useBy();
  return useMutation({
    mutationFn: (what: string) => api.recordExport(projectId, by, what),
    onSuccess: () => qc.invalidateQueries({ queryKey: k.sub(projectId, "audit") }),
  });
}

export function useStartRun() {
  const qc = useQueryClient();
  const by = useBy();
  return useMutation({
    mutationFn: (v: { input: StartRunInput; files: File[] }) => api.startRun(v.input, v.files, by),
    onSuccess: () => qc.invalidateQueries(),
    onError: fail,
  });
}
export function useCancelRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => api.cancelRun(id), onSuccess: () => qc.invalidateQueries(), onError: fail });
}
export function useRetryRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.retryRun(id),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast.success(`${r.id} started.`);
    },
    onError: fail,
  });
}

export function useMarkNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => api.markNotificationsRead(), onSuccess: () => qc.invalidateQueries({ queryKey: k.notifications }) });
}

export function useResetSampleData() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.resetSampleData?.();
    },
    onSuccess: () => {
      qc.invalidateQueries();
      toast.success("Sample data restored.");
    },
  });
}

/** When a run finishes, everything about its project may have changed. */
export function useInvalidateAll() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}
