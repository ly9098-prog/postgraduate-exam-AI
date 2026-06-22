"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, Check, CheckCircle2, ChevronDown, Code2, Eye, FileText, Save, Search, Sparkles, X, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { MathFormula } from "@/components/ui/math-formula";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { AdminImportCompleteResponse, BatchCompleteResponse, ImportActionResponse, ImportQuestionItem, PaginatedResponse } from "@/lib/api/types";

type ConfirmState =
  | { action: "approve"; id: number }
  | { action: "reject"; id: number }
  | { action: "batch-approve" }
  | { action: "batch-reject" }
  | { action: "low-risk-batch-approve" }
  | null;

type BatchActionResult = {
  affected_count: number;
  errors?: Array<{ id: number; message: string }>;
};

type EditState = {
  subject: string;
  question_type: string;
  stem: string;
  options: Array<{ key: string; text: string }>;
  answer: string;
  analysis: string;
};

function parseOptionsToEditable(item: ImportQuestionItem | null | undefined): Array<{ key: string; text: string }> {
  if (!item) return [];
  const raw = item.raw_data;
  const source = item.parsed_options ?? raw?.options ?? raw?.parsed_options ?? raw?.option_text ?? raw?.optionText ?? null;
  if (!source || (Array.isArray(source) && source.length === 0)) {
    if (item.question_type === "multi_blank_choice") {
      const groups = item.parsed_content?.blank_option_groups ?? raw?.blank_option_groups;
      if (Array.isArray(groups)) {
        const result: Array<{ key: string; text: string; _groupId?: string }> = [];
        for (const group of groups) {
          if (!group || typeof group !== "object") continue;
          const g = group as Record<string, unknown>;
          const groupId = String(g.id ?? "");
          const opts = g.options;
          if (Array.isArray(opts)) {
            for (const opt of opts) {
              if (opt && typeof opt === "object") {
                const o = opt as Record<string, unknown>;
                const key = String(o.key ?? "");
                const text = String(o.text ?? "");
                if (key && text) result.push({ key, text });
              }
            }
          } else if (opts && typeof opts === "object") {
            for (const [key, text] of Object.entries(opts as Record<string, unknown>)) {
              if (key && text) result.push({ key, text: String(text) });
            }
          }
        }
        return result;
      }
    }
    return [];
  }
  if (Array.isArray(source)) {
    return source
      .map((entry, index) => {
        if (typeof entry === "string") {
          const key = String.fromCharCode(65 + index);
          return { key, text: entry };
        }
        if (entry && typeof entry === "object") {
          const obj = entry as Record<string, unknown>;
          const key = String(obj.key ?? obj.label ?? obj.name ?? String.fromCharCode(65 + index));
          const text = String(obj.text ?? obj.content ?? obj.value ?? obj.stem ?? "");
          return { key, text };
        }
        return { key: String.fromCharCode(65 + index), text: "" };
      })
      .filter((opt) => opt.key && opt.text);
  }
  if (typeof source === "object") {
    return Object.entries(source as Record<string, unknown>)
      .map(([key, value]) => ({ key, text: typeof value === "string" ? value : String(value ?? "") }))
      .filter((opt) => opt.key && opt.text);
  }
  return [];
}

function isMultiChoice(questionType: string): boolean {
  return /多选|多空|多项/i.test(questionType);
}

function textFromImport(item: ImportQuestionItem | null | undefined) {
  if (!item) return "";
  const content = item.parsed_content;
  const raw = item.raw_data;
  const candidate = content?.stem ?? content?.text ?? content?.question ?? raw?.stem ?? raw?.text ?? raw?.question;
  if (typeof candidate === "string") return candidate;
  return "";
}

function renderJson(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function completeSuggestionFromItem(item: ImportQuestionItem | null | undefined) {
  const suggestion = item?.ai_metadata?.complete_suggestion;
  if (suggestion && typeof suggestion === "object" && !Array.isArray(suggestion)) return suggestion as Record<string, unknown>;
  return null;
}

function stringSuggestion(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

const ALL_BATCH_FIELDS = ["answer", "analysis", "knowledge_points", "difficulty", "subject", "question_type", "stem", "options", "tips", "tags"];

const STATUS_OPTIONS = [
  { value: "pending", label: "待审核" },
  { value: "approved", label: "已通过" },
  { value: "rejected", label: "已驳回" },
  { value: "published", label: "已发布" },
  { value: "", label: "全部状态" },
] as const;

function statusTone(status: string) {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  if (status === "published") return "primary";
  return "warning";
}

function editStateFromItem(item: ImportQuestionItem): EditState {
  return {
    subject: item.subject || "",
    question_type: item.question_type || "",
    stem: textFromImport(item),
    options: parseOptionsToEditable(item),
    answer: item.parsed_answer || "",
    analysis: item.parsed_analysis || "",
  };
}

async function _batchExecute<T>(ids: number[], concurrency: number, fn: (id: number) => Promise<T>): Promise<PromiseSettledResult<T>[]> {
  const results: PromiseSettledResult<T>[] = [];
  for (let i = 0; i < ids.length; i += concurrency) {
    const chunk = ids.slice(i, i + concurrency);
    const settled = await Promise.allSettled(chunk.map(fn));
    results.push(...settled);
  }
  return results;
}

export default function ImportReviewPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const batchIdParam = searchParams.get("batch_id") || "";
  const [filters, setFilters] = useState({ batch_id: "", status: "pending", subject: "", source_type: "", keyword: "", risk_level: "" });
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [completedItem, setCompletedItem] = useState<ImportQuestionItem | null>(null);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 5000);
    return () => clearTimeout(t);
  }, [message]);
  const [detailView, setDetailView] = useState<"formatted" | "json">("formatted");
  const [editing, setEditing] = useState(false);
  const editSnapshotRef = useRef("");

  const [showBatchComplete, setShowBatchComplete] = useState(false);
  const [batchFields, setBatchFields] = useState<string[]>(["answer", "analysis", "knowledge_points", "difficulty"]);
  const [batchStrategy, setBatchStrategy] = useState<"fill_empty" | "force_overwrite">("fill_empty");
  const [batchResult, setBatchResult] = useState<BatchCompleteResponse | null>(null);
  const [executing, setExecuting] = useState(false);
  const [draftRestored, setDraftRestored] = useState(false);
  const [autoSaveHint, setAutoSaveHint] = useState<string | null>(null);

  const DRAFT_KEY = "batch-complete-draft";

  const saveDraft = (fields: string[], strategy: string) => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ fields, strategy, savedAt: Date.now() }));
    } catch { /* quota exceeded, silently ignore */ }
  };

  const clearDraft = () => {
    try { localStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ }
  };

  const loadDraft = (): { fields: string[]; strategy: string } | null => {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed?.fields)) return null;
      return { fields: parsed.fields, strategy: parsed.strategy === "force_overwrite" ? "force_overwrite" : "fill_empty" };
    } catch { return null; }
  };

  // restore draft on mount
  useEffect(() => {
    const draft = loadDraft();
    if (draft) {
      setBatchFields(draft.fields);
      setBatchStrategy(draft.strategy as "fill_empty" | "force_overwrite");
      setDraftRestored(true);
    }
  }, []);

  // auto-save when form changes
  useEffect(() => {
    if (!showBatchComplete) return;
    saveDraft(batchFields, batchStrategy);
    setAutoSaveHint("已自动保存草稿");
  }, [batchFields, batchStrategy, showBatchComplete]);

  // clear auto-save hint after 3s
  useEffect(() => {
    if (!autoSaveHint) return;
    const t = setTimeout(() => setAutoSaveHint(null), 3000);
    return () => clearTimeout(t);
  }, [autoSaveHint]);

  const queryParams = useMemo(
    () => ({ page: 1, page_size: 50, batch_id: filters.batch_id || batchIdParam, status: filters.status, subject: filters.subject, source_type: filters.source_type, keyword: filters.keyword, risk_level: filters.risk_level || undefined }),
    [batchIdParam, filters],
  );

  const queue = useQuery({
    queryKey: ["import-review-queue", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<ImportQuestionItem>>(`/imports/review-queue${toQuery(queryParams)}`),
    retry: false,
  });

  const items = queue.data?.items ?? [];
  const queuedPreviewItem = items.find((item) => item.id === previewId) ?? null;
  const previewItem = completedItem?.id === previewId ? completedItem : queuedPreviewItem;
  const completeSuggestion = completeSuggestionFromItem(previewItem);
  const answerSuggestion = stringSuggestion(completeSuggestion?.answer);
  const allChecked = items.length > 0 && items.every((item) => selectedIds.has(item.id));

  const actionMutation = useMutation({
    mutationFn: async (state: Exclude<ConfirmState, null>) => {
      if (state.action === "approve") {
        try {
          return await apiRequest<ImportActionResponse>(`/imports/questions/${state.id}/approve`, { method: "POST" });
        } catch (e) {
          throw new Error(`题目 #${state.id} 审核通过失败：${e instanceof Error ? e.message : "未知错误"}`);
        }
      }
      if (state.action === "reject") {
        try {
          return await apiRequest<ImportActionResponse>(`/imports/questions/${state.id}/reject`, { method: "POST", body: JSON.stringify({ reason: rejectReason }) });
        } catch (e) {
          throw new Error(`题目 #${state.id} 驳回失败：${e instanceof Error ? e.message : "未知错误"}`);
        }
      }
      if (state.action === "batch-approve") {
        if (selectedIds.size > 0) {
          const ids = Array.from(selectedIds);
          const settled = await _batchExecute(ids, 6, (id) =>
            apiRequest<ImportActionResponse>(`/imports/questions/${id}/approve`, { method: "POST" })
          );
          const errors: Array<{ id: number; message: string }> = [];
          let affected = 0;
          settled.forEach((r, i) => {
            if (r.status === "fulfilled") { affected++; }
            else { errors.push({ id: ids[i], message: r.reason instanceof Error ? r.reason.message : String(r.reason) }); }
          });
          return { affected_count: affected, errors } as BatchActionResult;
        }
        return apiRequest<ImportActionResponse>(`/imports/${filters.batch_id}/approve`, { method: "POST" });
      }
      if (state.action === "batch-reject") {
        if (selectedIds.size > 0) {
          const ids = Array.from(selectedIds);
          const settled = await _batchExecute(ids, 6, (id) =>
            apiRequest<ImportActionResponse>(`/imports/questions/${id}/reject`, { method: "POST", body: JSON.stringify({ reason: rejectReason }) })
          );
          const errors: Array<{ id: number; message: string }> = [];
          let affected = 0;
          settled.forEach((r, i) => {
            if (r.status === "fulfilled") { affected++; }
            else { errors.push({ id: ids[i], message: r.reason instanceof Error ? r.reason.message : String(r.reason) }); }
          });
          return { affected_count: affected, errors } as BatchActionResult;
        }
        return apiRequest<ImportActionResponse>(`/imports/${filters.batch_id}/reject`, { method: "POST", body: JSON.stringify({ reason: rejectReason }) });
      }
      if (state.action === "low-risk-batch-approve") {
        const bid = filters.batch_id || batchIdParam;
        if (!bid) throw new Error("请先选择导入批次");
        const res = await apiRequest<{ affected_count: number; skipped_count: number; skipped_reasons: string[] }>(
          `/imports/${bid}/approve-low-risk`, { method: "POST" }
        );
        return res;
      }
      // no other actions handled here (publish is on the history page)
      throw new Error("未知操作");
    },
    onSuccess: (result, variables) => {
      if (variables.action === "approve") {
        setMessage(`导入题目 #${variables.id} 已通过审核。`);
      } else if (variables.action === "reject") {
        setMessage(`导入题目 #${variables.id} 已驳回。`);
      } else if (variables.action === "batch-approve") {
        const affected = "affected_count" in result ? result.affected_count : 0;
        const errors = "errors" in result ? (result as BatchActionResult).errors : undefined;
        if (errors && errors.length > 0) {
          const failedIds = errors.map((e) => `#${e.id}`).join("、");
          setMessage(`批量审核通过部分完成：成功 ${affected}，失败 ${errors.length}（${failedIds}）。`);
        } else {
          setMessage(`批量审核通过完成，影响 ${affected} 条导入题目。`);
        }
      } else if (variables.action === "batch-reject") {
        const affected = "affected_count" in result ? result.affected_count : 0;
        const errors = "errors" in result ? (result as BatchActionResult).errors : undefined;
        if (errors && errors.length > 0) {
          const failedIds = errors.map((e) => `#${e.id}`).join("、");
          setMessage(`批量驳回部分完成：成功 ${affected}，失败 ${errors.length}（${failedIds}）。`);
        } else {
          setMessage(`批量驳回完成，影响 ${affected} 条导入题目。`);
        }
      } else if (variables.action === "low-risk-batch-approve") {
        const res = result as { affected_count: number; skipped_count: number; skipped_reasons: string[] };
        const msg = `低风险批量通过完成：通过 ${res.affected_count} 题，跳过 ${res.skipped_count} 题`;
        setMessage(res.skipped_count > 0 ? `${msg}（部分高风险/需检查题已跳过）` : msg);
      }
      setSelectedIds(new Set());
      setConfirmState(null);
      setRejectReason("");
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["import-batches"] });
      if (variables.action !== "reject" && variables.action !== "batch-reject") {
        queryClient.invalidateQueries({ queryKey: ["questions"] });
      }
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
    },
  });

  const updateMutation = useMutation({
    mutationFn: async () => {
      if (!previewId || !editState) throw new Error("请选择要编辑的题目");
      const { options, ...rest } = editState;
      const body = {
        ...rest,
        options: options.map((o) => ({ key: o.key, text: o.text })),
      };
      return apiRequest<ImportQuestionItem>(`/imports/questions/${previewId}`, { method: "PUT", body: JSON.stringify(body) });
    },
    onSuccess: (result) => {
      setMessage(`导入题目 #${result.id} 已保存。`);
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "保存失败，请稍后重试。");
    },
  });

  const completeMutation = useMutation({
    mutationFn: async (id: number) => {
      try {
        return await apiRequest<AdminImportCompleteResponse>(`/imports/questions/${id}/complete`, { method: "POST" });
      } catch (e) {
        throw new Error(`题目 #${id} 补全失败：${e instanceof Error ? e.message : "未知错误"}`);
      }
    },
    onSuccess: (result) => {
      const missingFields = result.missing.length > 0 ? `（补全字段：${result.missing.join("、")}）` : "";
      setMessage(
        result.missing.length === 0
          ? "当前题目信息已完整，无需补全。"
          : `AI 补全完成${missingFields}，请复核后保存/通过。`,
      );
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      setPreviewId(result.item.id);
      setCompletedItem(result.item);
      setEditState(editStateFromItem(result.item));
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "AI 补全失败，请稍后重试。");
    },
  });

  const toggleBatchField = (field: string) => {
    setDraftRestored(false);
    setBatchFields((prev) => (prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field]));
  };

  const executeBatchComplete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) {
      setMessage("请先选择需要补全的题目。");
      return;
    }
    if (batchFields.length === 0) {
      setMessage("请选择至少一个补全字段。");
      return;
    }
    setExecuting(true);
    setBatchResult(null);
    try {
      const result = await apiRequest<BatchCompleteResponse>("/imports/questions/batch-complete", {
        method: "POST",
        body: JSON.stringify({ import_ids: ids, fields: batchFields, strategy: batchStrategy }),
      });
      setBatchResult(result);
      clearDraft();
      const failedItems = result.items.filter((i) => i.status === "failed");
      const failedIdStr = failedItems.length > 0 ? `（${failedItems.map((i) => `#${i.import_id}`).join("、")}）` : "";
      setMessage(`批量补全完成：成功 ${result.succeeded}，失败 ${result.failed}，跳过 ${result.skipped}${failedIdStr}`);
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "批量补全失败，请稍后重试。");
    } finally {
      setExecuting(false);
    }
  };

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setSelectedIds(new Set());
    setPreviewId(null);
    setCompletedItem(null);
    setEditState(null);
  };

  const toggleAll = () => {
    setSelectedIds(() => (allChecked ? new Set() : new Set(items.map((item) => item.id))));
  };

  const toggleOne = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openPreview = (item: ImportQuestionItem) => {
    setPreviewId(item.id);
    setCompletedItem(null);
    const snapshot = editStateFromItem(item);
    setEditState(snapshot);
    editSnapshotRef.current = JSON.stringify(snapshot);
    setEditing(false);
    setDetailView("formatted");
  };

  const closeDrawer = () => {
    if (editing && editState && JSON.stringify(editState) !== editSnapshotRef.current) {
      if (!window.confirm("有未保存的修改，确定关闭吗？")) return;
    }
    setPreviewId(null);
    setCompletedItem(null);
    setEditState(null);
    setEditing(false);
  };

  const startEditing = () => {
    if (!previewId) return;
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditState(previewItem ? editStateFromItem(previewItem) : null);
    setEditing(false);
  };

  useEffect(() => {
    if (previewId === null) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDrawer();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [previewId, editing, editState]);

  const canBatchOperate = items.length > 0 && (selectedIds.size > 0 || Boolean(filters.batch_id || batchIdParam));

  return (
    <div className="space-y-6">
      <style>{`
@keyframes loadingBar { 0% { transform: translateX(-100%); } 50% { transform: translateX(100%); } 100% { transform: translateX(300%); } }
@keyframes slideInRight { from { transform: translateX(100%); } to { transform: translateX(0); } }
@keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@keyframes inkSpread { 0% { transform: scale(0.3); opacity: 0.8; } 50% { transform: scale(1); opacity: 0.4; } 100% { transform: scale(1.3); opacity: 0; } }
@keyframes stampPop { 0% { transform: scale(0.8) rotate(-3deg); opacity: 0; } 60% { transform: scale(1.05) rotate(0.5deg); opacity: 1; } 100% { transform: scale(1) rotate(0deg); opacity: 1; } }
.animate-slide-in { animation: slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
.animate-fade-up { animation: fadeUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) both; }
.animate-ink-spread { animation: inkSpread 1.5s ease-out infinite; }
.drawer-section-delay-1 { animation-delay: 0.05s; }
.drawer-section-delay-2 { animation-delay: 0.1s; }
.drawer-section-delay-3 { animation-delay: 0.15s; }
.drawer-section-delay-4 { animation-delay: 0.2s; }
.drawer-section-delay-5 { animation-delay: 0.25s; }
.bg-noise { background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E"); background-size: 128px 128px; }
`}</style>
      {message ? (
        <div role="status" aria-live="polite" className="fixed right-6 top-6 z-[60] max-w-sm animate-rise-in rounded-2xl border border-[var(--color-success)]/30 bg-white px-5 py-4 shadow-[var(--shadow-floating)]">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--color-success-light)]">
              <CheckCircle2 className="h-4 w-4 text-[var(--color-success)]" />
            </div>
            <p className="text-sm font-medium text-[var(--ink)]">{message}</p>
          </div>
          <button aria-label="关闭提示" className="absolute right-3 top-3 text-[var(--color-text-hint)] hover:text-[var(--ink)] transition" onClick={() => setMessage(null)}>✕</button>
        </div>
      ) : null}
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">待审核题目</h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">审核 question_imports 暂存题目，通过后再发布到正式题库。</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <div className="flex items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/60 p-1">
                <Button variant="secondary" className="h-8 px-3 text-xs" disabled={!canBatchOperate} onClick={() => setConfirmState({ action: "batch-approve" })}>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  批量通过
                </Button>
                <Button variant="secondary" className="h-8 px-3 text-xs" disabled={!(filters.batch_id || batchIdParam)} onClick={() => setConfirmState({ action: "low-risk-batch-approve" })}>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  批量通过低风险
                </Button>
                <Button variant="danger" className="h-8 px-3 text-xs" disabled={!canBatchOperate} onClick={() => setConfirmState({ action: "batch-reject" })}>
                  <XCircle className="h-3.5 w-3.5" />
                  批量驳回
                </Button>
                <Button
                  variant="secondary"
                  className="h-8 px-3 text-xs"
                  disabled={selectedIds.size === 0}
                  onClick={() => { setShowBatchComplete(true); setBatchResult(null); }}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  AI 批量补全
                </Button>
              </div>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <label className="relative xl:col-span-2">
              <span className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]">关键词搜索</span>
              <Search className="absolute left-3 top-[34px] h-4 w-4 text-[var(--color-text-hint)]" />
              <Input className="pl-9" placeholder="搜索题干 / OCR 原文" value={filters.keyword} onChange={(event) => updateFilter("keyword", event.target.value)} />
            </label>
            <label className="space-y-1.5">
              <span className="block text-xs font-medium text-[var(--color-text-secondary)]">批次 ID</span>
              <Input placeholder="输入批次 ID" value={filters.batch_id || batchIdParam} onChange={(event) => updateFilter("batch_id", event.target.value)} />
            </label>
            <label className="space-y-1.5">
              <span className="block text-xs font-medium text-[var(--color-text-secondary)]">科目</span>
              <Input placeholder="输入科目" value={filters.subject} onChange={(event) => updateFilter("subject", event.target.value)} />
            </label>
            <label className="space-y-1.5">
              <span className="block text-xs font-medium text-[var(--color-text-secondary)]">风险等级</span>
              <div className="relative">
                <select
                  className="flex h-11 w-full items-center rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-sm text-[var(--color-text-primary)] outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/20"
                  value={filters.risk_level}
                  onChange={(event) => updateFilter("risk_level", event.target.value)}
                >
                  <option value="">全部</option>
                  <option value="high">高风险</option>
                  <option value="medium">需检查</option>
                  <option value="low">低风险</option>
                </select>
              </div>
            </label>
            <label className="space-y-1.5">
              <span className="block text-xs font-medium text-[var(--color-text-secondary)]">审核状态</span>
              <div className="relative">
                <button
                  type="button"
                  className="flex h-11 w-full items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-sm text-[var(--color-text-primary)] outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/20"
                  onClick={() => setStatusDropdownOpen((v) => !v)}
                  onBlur={() => setTimeout(() => setStatusDropdownOpen(false), 150)}
                >
                  <span className="flex-1 text-left">{STATUS_OPTIONS.find((o) => o.value === filters.status)?.label}</span>
                  <ChevronDown className={`h-4 w-4 text-[var(--color-text-hint)] transition-transform ${statusDropdownOpen ? "rotate-180" : ""}`} />
                </button>
                {statusDropdownOpen ? (
                  <div className="absolute left-0 right-0 top-full z-20 mt-1 overflow-hidden rounded-xl border border-[var(--color-border)] bg-white py-1 shadow-lg">
                    {STATUS_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        className={`flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm transition hover:bg-[var(--color-primary-light)]/40 ${
                          filters.status === opt.value
                            ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold"
                            : "text-[var(--color-text-primary)]"
                        }`}
                        onMouseDown={(e) => { e.preventDefault(); updateFilter("status", opt.value); setStatusDropdownOpen(false); }}
                      >
                        {filters.status === opt.value ? (
                          <Check className="h-4 w-4 shrink-0 text-[var(--color-primary)]" />
                        ) : (
                          <span className="inline-block w-4 shrink-0" />
                        )}
                        {opt.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </label>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <section className="space-y-3">
              <label className="flex cursor-pointer items-center gap-2.5 rounded-xl border border-[var(--color-border)] bg-white/60 px-4 py-2.5 text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)]/30 hover:bg-white/90 select-none group">
                <span className="relative flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 border-[var(--color-border)] bg-white transition-all group-hover:border-[var(--color-primary)]/50 [&:has(input:checked)]:border-[var(--color-primary)] [&:has(input:checked)]:bg-[var(--color-primary)]">
                  <input type="checkbox" checked={allChecked} onChange={toggleAll} className="peer absolute inset-0 cursor-pointer opacity-0" />
                  <Check className="h-3.5 w-3.5 text-white opacity-0 transition-opacity peer-checked:opacity-100" />
                </span>
                全选当前结果
                {selectedIds.size > 0 ? <span className="ml-auto rounded-full bg-[var(--color-primary-light)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-primary-dark)]">已选 {selectedIds.size} 题</span> : null}
              </label>
              {items.map((item, index) => (
                <article
                  key={item.id}
                  className="rounded-2xl border border-[var(--color-border)] bg-white/85 p-4 transition-all hover:border-[var(--color-primary)]/30 hover:shadow-sm animate-rise-in"
                  style={{ animationDelay: `${(index % 20) * 30}ms` }}
                >
                  {/* Top bar: checkbox + ID + status badges */}
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <label className="group relative flex shrink-0 cursor-pointer items-center gap-2">
                        <span className="flex h-5 w-5 items-center justify-center rounded-md border-2 border-[var(--color-border)] bg-white transition-all group-hover:border-[var(--color-primary)]/50 [&:has(input:checked)]:border-[var(--color-primary)] [&:has(input:checked)]:bg-[var(--color-primary)]">
                          <input
                            type="checkbox"
                            checked={selectedIds.has(item.id)}
                            onChange={() => toggleOne(item.id)}
                            className="peer absolute inset-0 cursor-pointer opacity-0"
                          />
                          <Check className="h-3.5 w-3.5 text-white opacity-0 transition-opacity peer-checked:opacity-100" />
                        </span>
                      </label>
                      <span className="shrink-0 font-mono text-xs text-[var(--color-text-hint)]">#{item.id}</span>
                      <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
                      {item.duplicate_status ? (
                        <StatusBadge tone={item.duplicate_status === "possible_duplicate" ? "warning" : "neutral"}>
                          {item.duplicate_status === "possible_duplicate" ? "疑似重复" : item.duplicate_status}
                        </StatusBadge>
                      ) : null}
                    </div>
                  </div>

                  {/* Risk badges + Metadata pills */}
                  <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                    {/* Risk level badge */}
                    {item.risk_level === "high" ? (
                      <span className="rounded-md bg-red-100 px-2 py-0.5 text-[11px] font-bold text-red-700">高风险</span>
                    ) : item.risk_level === "medium" ? (
                      <span className="rounded-md bg-amber-100 px-2 py-0.5 text-[11px] font-bold text-amber-700">需检查</span>
                    ) : item.risk_level === "low" ? (
                      <span className="rounded-md bg-green-100 px-2 py-0.5 text-[11px] font-medium text-green-700">低风险</span>
                    ) : null}
                    {/* AI answer flag */}
                    {item.ai_answer_flag ? (
                      <span className="rounded-md bg-orange-100 px-2 py-0.5 text-[11px] font-bold text-orange-700">AI 答案</span>
                    ) : null}
                    {/* Answer missing flag */}
                    {(!item.parsed_answer || item.parsed_answer.trim() === "") && item.risk_level !== "low" ? (
                      <span className="rounded-md bg-red-100 px-2 py-0.5 text-[11px] font-bold text-red-700">答案缺失</span>
                    ) : null}
                    {item.subject ? (
                      <span className="rounded-md bg-[var(--color-primary-light)] px-2 py-0.5 text-[11px] font-semibold text-[var(--color-primary-dark)]">{item.subject}</span>
                    ) : (
                      <span className="text-xs text-[var(--color-text-hint)]">未分类</span>
                    )}
                    <span className="text-xs text-[var(--color-text-secondary)]">{item.question_type || "未标注题型"}</span>
                    <span className="max-w-[160px] truncate font-mono text-[10px] text-[var(--color-text-hint)]" title={item.batch_id}>{item.batch_id}</span>
                  </div>
                  {/* Risk reasons */}
                  {item.risk_reasons && item.risk_reasons.length > 0 ? (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {item.risk_reasons.slice(0, 3).map((reason, ri) => (
                        <span key={ri} className="rounded bg-red-50/80 px-1.5 py-0.5 text-[10px] text-red-600">{reason}</span>
                      ))}
                      {item.risk_reasons.length > 3 ? (
                        <span className="rounded bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-400">+{item.risk_reasons.length - 3}</span>
                      ) : null}
                    </div>
                  ) : null}

                  {/* Stem */}
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-[var(--ink)] line-clamp-2">
                    {textFromImport(item) || <span className="italic text-[var(--color-text-hint)]">导入题目 #{item.id}</span>}
                  </p>

                  {/* Action bar */}
                  <div className="mt-3 flex items-center gap-1.5 border-t border-[var(--color-border)]/50 pt-3">
                    <Button variant="ghost" className="h-8 px-2.5 text-xs" onClick={() => openPreview(item)}>
                      <Eye className="h-3.5 w-3.5" />
                      预览详情
                    </Button>
                    <div className="ml-auto flex items-center gap-1.5">
                      <Button variant="ghost" className="h-8 w-8 p-0" disabled={item.status !== "pending" || completeMutation.isPending} onClick={() => completeMutation.mutate(item.id)} title="AI 补全">
                        {completeMutation.isPending ? (
                          <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--color-border)] border-t-[var(--color-primary)]" />
                        ) : (
                          <Sparkles className="h-3.5 w-3.5" />
                        )}
                      </Button>
                      <Button variant="secondary" className="h-8 px-3 text-xs" disabled={item.status === "published"} onClick={() => setConfirmState({ action: "approve", id: item.id })}>
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        通过
                      </Button>
                      <Button variant="danger" className="h-8 px-3 text-xs" disabled={item.status === "published"} onClick={() => setConfirmState({ action: "reject", id: item.id })}>
                        <XCircle className="h-3.5 w-3.5" />
                        驳回
                      </Button>
                    </div>
                  </div>
                </article>
              ))}
              {!queue.isLoading && items.length === 0 ? <p className="py-10 text-center text-sm text-[var(--color-text-hint)]">暂无待审核题目</p> : null}
              {queue.isError ? <p className="text-sm text-[var(--color-danger)]">待审核接口当前不可用。</p> : null}
            </section>
        </CardContent>
      </Card>

      {/* ── Scholar's Study Detail Drawer ── */}
      {previewId !== null && previewItem && editState ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.38)] backdrop-blur-[1px]" role="presentation" onClick={closeDrawer}>
          <aside role="dialog" aria-modal="true" aria-labelledby="drawer-title"
            className="flex h-full w-full max-w-3xl flex-col overflow-y-auto shadow-[var(--shadow-floating)] animate-slide-in bg-noise"
            style={{
              background: 'var(--color-bg)',
              backgroundImage: 'linear-gradient(var(--blueprint-line) 1px, transparent 1px), linear-gradient(90deg, var(--blueprint-line) 1px, transparent 1px), url("data:image/svg+xml,%3Csvg viewBox=\'0 0 256 256\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'n\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.9\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23n)\' opacity=\'0.025\'/%3E%3C/svg%3E")',
              backgroundSize: '24px 24px, 24px 24px, 128px 128px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* ===== Sticky Header ===== */}
            <div className="sticky top-0 z-10 border-b border-[var(--color-border)] bg-[var(--color-bg)]/95 px-6 py-5 backdrop-blur-xl">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2.5 mb-1">
                    <span className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-white/70 px-2 py-0.5 font-mono text-[11px] text-[var(--color-text-hint)] shadow-sm">
                      #{previewItem.id}
                    </span>
                    <span className="h-3 w-px bg-[var(--color-border)]" />
                    <span className="text-xs text-[var(--color-text-secondary)]">
                      {(() => {
                        try { return new Date(previewItem.created_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" }); }
                        catch { return ""; }
                      })()}
                    </span>
                  </div>
                  <h4 id="drawer-title" className="font-display text-2xl font-bold tracking-tight text-[var(--ink)]">
                    题目审校
                  </h4>
                  <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">审核 AI 补全结果，确认后通过或编辑保存</p>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  {/* View toggle */}
                  <div className="flex overflow-hidden rounded-lg border border-[var(--color-border)] bg-white/80 p-0.5 shadow-sm">
                    <button
                      type="button"
                      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-semibold transition-all ${
                        detailView === "formatted"
                          ? "bg-[var(--color-primary)] text-white shadow-sm"
                          : "bg-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-primary-dark)]"
                      }`}
                      onClick={() => setDetailView("formatted")}
                    >
                      <FileText className="h-3 w-3" />
                      文本
                    </button>
                    <button
                      type="button"
                      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-semibold transition-all ${
                        detailView === "json"
                          ? "bg-[var(--color-primary)] text-white shadow-sm"
                          : "bg-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-primary-dark)]"
                      }`}
                      onClick={() => setDetailView("json")}
                    >
                      <Code2 className="h-3 w-3" />
                      JSON
                    </button>
                  </div>
                  {editing ? (
                    <>
                      <Button className="h-7 px-2.5 text-[11px]" variant="secondary" disabled={updateMutation.isPending || previewItem.status === "published"} onClick={() => updateMutation.mutate()}>
                        <Save className="h-3 w-3" />
                        {updateMutation.isPending ? "保存中..." : "保存"}
                      </Button>
                      <Button className="h-7 px-2.5 text-[11px]" variant="ghost" onClick={cancelEditing}>
                        <X className="h-3 w-3" />
                        取消
                      </Button>
                    </>
                  ) : (
                    <>
                      <button
                        disabled={completeMutation.isPending || previewItem.status !== "pending"}
                        onClick={() => completeMutation.mutate(previewItem.id)}
                        className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-bold tracking-wider transition-all ${
                          completeMutation.isPending
                            ? "bg-[var(--color-primary)]/10 text-[var(--color-primary-dark)] cursor-wait"
                            : "bg-[var(--color-primary)] text-white shadow-sm hover:bg-[var(--color-primary-dark)] hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-40 disabled:pointer-events-none"
                        }`}
                      >
                        {completeMutation.isPending ? (
                          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-[var(--color-primary)] border-t-transparent" />
                        ) : (
                          <Sparkles className="h-3 w-3" />
                        )}
                        {completeMutation.isPending ? "审校中" : "AI 审校"}
                      </button>
                      <Button className="h-7 px-2.5 text-[11px]" variant="secondary" onClick={startEditing}>
                        <FileText className="h-3 w-3" />
                        编辑
                      </Button>
                    </>
                  )}
                  <button
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--color-text-hint)] transition hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)]"
                    onClick={closeDrawer}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
              {/* Badge row */}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <StatusBadge tone={statusTone(previewItem.status)}>{previewItem.status}</StatusBadge>
                {editState.subject ? (
                  <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-primary-light)] px-2 py-0.5 text-[11px] font-semibold text-[var(--color-primary-dark)]">{editState.subject}</span>
                ) : null}
                {editState.question_type ? (
                  <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-white/80 px-2 py-0.5 text-[11px] font-medium text-[var(--color-text-secondary)]">{editState.question_type}</span>
                ) : null}
                {previewItem.duplicate_status ? (
                  <StatusBadge tone={previewItem.duplicate_status === "possible_duplicate" ? "warning" : "neutral"}>
                    {previewItem.duplicate_status === "possible_duplicate" ? "疑似重复" : previewItem.duplicate_status}
                  </StatusBadge>
                ) : null}
                {/* Risk badges */}
                {previewItem.risk_level === "high" ? (
                  <span className="rounded-md bg-red-100 px-2 py-0.5 text-[11px] font-bold text-red-700">高风险</span>
                ) : previewItem.risk_level === "medium" ? (
                  <span className="rounded-md bg-amber-100 px-2 py-0.5 text-[11px] font-bold text-amber-700">需检查</span>
                ) : previewItem.risk_level === "low" ? (
                  <span className="rounded-md bg-green-100 px-2 py-0.5 text-[11px] font-medium text-green-700">低风险</span>
                ) : null}
                {previewItem.ai_answer_flag ? (
                  <span className="rounded-md bg-orange-100 px-2 py-0.5 text-[11px] font-bold text-orange-700">AI 答案</span>
                ) : null}
              </div>
              {/* Risk reasons */}
              {previewItem.risk_reasons && previewItem.risk_reasons.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {previewItem.risk_reasons.map((reason, ri) => (
                    <span key={ri} className="rounded bg-red-50/80 px-1.5 py-0.5 text-[10px] text-red-600">{reason}</span>
                  ))}
                </div>
              ) : null}
              {/* Action buttons row */}
              <div className="mt-3 flex items-center gap-2">
                <Button variant="primary" className="h-8 px-3 text-xs" disabled={previewItem.status === "published"} onClick={() => setConfirmState({ action: "approve", id: previewItem.id })}>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  通过
                </Button>
                <Button variant="danger" className="h-8 px-3 text-xs" disabled={previewItem.status === "published"} onClick={() => setConfirmState({ action: "reject", id: previewItem.id })}>
                  <XCircle className="h-3.5 w-3.5" />
                  驳回
                </Button>
              </div>
            </div>

            {/* ===== Content ===== */}
            <div className="relative flex-1 px-6 py-5 space-y-5">
              {completeMutation.isPending ? (
                <div className="absolute inset-0 z-10 flex items-center justify-center bg-[var(--color-bg)]/70 backdrop-blur-sm">
                  <div className="flex flex-col items-center gap-5">
                    {/* Ink spread animation */}
                    <div className="relative flex items-center justify-center">
                      <div className="absolute h-20 w-20 rounded-full border border-[var(--color-primary)]/10 animate-ink-spread" />
                      <div className="absolute h-14 w-14 rounded-full border border-[var(--color-primary)]/20 animate-ink-spread" style={{ animationDelay: "0.3s" }} />
                      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-white shadow-[0_0_20px_rgba(91,123,154,0.15)]">
                        <Sparkles className="h-5 w-5 text-[var(--color-primary)]" />
                      </div>
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-semibold text-[var(--color-text-secondary)]">AI 正在审校</p>
                      <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">分析题目结构，生成补全建议</p>
                    </div>
                  </div>
                </div>
              ) : null}

              {detailView === "formatted" && !editing ? (
                <>
                  {/* ── Stem Card ── */}
                  <section className="animate-fade-up drawer-section-delay-1 rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
                    <div className="flex items-center gap-2.5 mb-3">
                      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-primary)]/10">
                        <span className="text-xs font-bold text-[var(--color-primary)]" style={{ fontFamily: "'Georgia', serif" }}>题</span>
                      </span>
                      <span className="text-sm font-semibold text-[var(--ink)]">题干</span>
                    </div>
                    <div className="ml-9 whitespace-pre-wrap leading-relaxed text-[var(--color-text-secondary)]">
                      <MathFormula text={editState.stem || "（空）"} />
                    </div>
                  </section>

                  {/* ── Segments (math_image / table_markdown / source_region) ── */}
                  {(() => {
                    const pc = previewItem?.parsed_content as Record<string, unknown> | undefined;
                    const segments = (pc?.segments as Array<Record<string, unknown>> | undefined) ?? [];
                    if (segments.length === 0) return null;
                    return (
                      <section className="animate-fade-up rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
                        <div className="flex items-center gap-2.5 mb-3">
                          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-purple-50">
                            <span className="text-xs font-bold text-purple-600" style={{ fontFamily: "'Georgia', serif" }}>片</span>
                          </span>
                          <span className="text-sm font-semibold text-[var(--ink)]">内容片段</span>
                        </div>
                        <div className="ml-9 space-y-3">
                          {segments.map((seg, si) => {
                            const segType = String(seg.type ?? "");
                            if (segType === "math_image") {
                              return (
                                <div key={si} className="rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/50 p-3">
                                  <div className="flex items-center gap-2 mb-2">
                                    <span className="text-xs font-semibold text-[var(--color-text-secondary)]">公式截图</span>
                                    {seg.requires_review ? (
                                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700">公式需核对</span>
                                    ) : null}
                                    {((): React.ReactNode => {
                                      const conf = seg.confidence;
                                      const confText = typeof conf === "number" ? `${(conf * 100).toFixed(0)}%` : conf != null ? String(conf) : null;
                                      return confText ? (
                                        <span className="text-[10px] text-[var(--color-text-hint)]">置信度: {confText}</span>
                                      ) : null;
                                    })()}
                                  </div>
                                  {seg.url ? (
                                    <img
                                      src={String(seg.url)}
                                      alt={String(seg.alt ?? "公式截图")}
                                      className="max-w-full rounded-lg border border-[var(--color-border)]"
                                      style={{ maxHeight: "240px" }}
                                    />
                                  ) : (
                                    <div className="rounded-lg border border-dashed border-amber-300 bg-amber-50/50 px-3 py-4 text-center text-xs text-amber-700">
                                      {seg.upload_failed
                                        ? "公式截图生成失败，请核对 OCR 文本"
                                        : "公式截图（暂未生成）"}
                                    </div>
                                  )}
                                  {seg.source_page ? (
                                    <p className="mt-1 text-[10px] text-[var(--color-text-hint)]">第 {String(seg.source_page)} 页</p>
                                  ) : null}
                                </div>
                              );
                            }
                            if (segType === "table_markdown") {
                              return (
                                <div key={si} className="rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/50 p-3">
                                  <div className="flex items-center gap-2 mb-2">
                                    <span className="text-xs font-semibold text-[var(--color-text-secondary)]">表格内容</span>
                                    {seg.requires_review ? (
                                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700">需核对</span>
                                    ) : null}
                                    {((): React.ReactNode => {
                                      const conf = seg.confidence;
                                      const confText = typeof conf === "number" ? `${(conf * 100).toFixed(0)}%` : conf != null ? String(conf) : null;
                                      return confText ? (
                                        <span className="text-[10px] text-[var(--color-text-hint)]">置信度: {confText}</span>
                                      ) : null;
                                    })()}
                                  </div>
                                  {seg.markdown ? (
                                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--color-border)]/50 bg-white p-3 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{String(seg.markdown)}</pre>
                                  ) : (
                                    <p className="text-xs text-[var(--color-text-hint)]">（表格文本内容）</p>
                                  )}
                                </div>
                              );
                            }
                            return null;
                          })}
                        </div>
                      </section>
                    );
                  })()}

                  {/* ── Options Card ── */}
                  {editState.question_type === "multi_blank_choice" ? (
                    <section className="animate-fade-up drawer-section-delay-2 rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
                      <div className="flex items-center gap-2.5 mb-3">
                        <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ backgroundColor: "rgba(196,154,107,0.12)" }}>
                          <span className="text-xs font-bold" style={{ color: "#c49a6b", fontFamily: "'Georgia', serif" }}>选</span>
                        </span>
                        <span className="text-sm font-semibold text-[var(--ink)]">选项</span>
                      </div>
                      <div className="ml-9">
                        {(() => {
                          const groups = previewItem?.parsed_content?.blank_option_groups ?? previewItem?.raw_data?.blank_option_groups;
                          const groupList: Array<{ id?: string; options?: Array<{ key: string; text: string }> }> = Array.isArray(groups) ? groups : [];
                          return groupList.length > 0 ? (
                            <div className="space-y-3">
                              {groupList.map((group, gi) => (
                                <div key={gi} className="rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/50 p-3">
                                  <p className="mb-2 text-[11px] font-semibold text-[var(--color-text-hint)]">空 {group.id ?? gi + 1}</p>
                                  <div className="space-y-1.5">
                                    {group.options?.map((opt, oi) => (
                                      <div key={oi} className="flex items-center gap-2">
                                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--color-primary-light)] text-[10px] font-bold text-[var(--color-primary-dark)]">{opt.key}</span>
                                        <span className="text-sm text-[var(--color-text-secondary)]"><MathFormula text={opt.text} /></span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : <p className="text-sm text-[var(--color-text-hint)]">（无分组选项数据）</p>;
                        })()}
                      </div>
                    </section>
                  ) : (
                    <section className="animate-fade-up drawer-section-delay-2 rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
                      <div className="flex items-center gap-2.5 mb-3">
                        <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ backgroundColor: "rgba(196,154,107,0.12)" }}>
                          <span className="text-xs font-bold" style={{ color: "#c49a6b", fontFamily: "'Georgia', serif" }}>选</span>
                        </span>
                        <span className="text-sm font-semibold text-[var(--ink)]">选项</span>
                      </div>
                      <div className="ml-9">
                        {editState.options.length === 0 ? (
                          <p className="text-sm text-[var(--color-text-hint)]">（无选项）</p>
                        ) : (
                          <div className="space-y-2">
                            {editState.options.map((opt) => (
                              <div key={opt.key} className="flex items-center gap-3">
                                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--color-primary-light)] text-xs font-bold text-[var(--color-primary-dark)]">{opt.key}</span>
                                <span className="text-sm text-[var(--color-text-secondary)]"><MathFormula text={opt.text} /></span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </section>
                  )}

                  {/* ── Answer Card ── */}
                  <section className="animate-fade-up drawer-section-delay-3 rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
                    <div className="flex items-center gap-2.5 mb-3">
                      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-success)]/10">
                        <span className="text-xs font-bold text-[var(--color-success)]" style={{ fontFamily: "'Georgia', serif" }}>答</span>
                      </span>
                      <span className="text-sm font-semibold text-[var(--ink)]">答案</span>
                      {previewItem.ai_answer_flag ? (
                        <span className="rounded-md bg-orange-100 px-2 py-0.5 text-[10px] font-bold text-orange-700 ml-auto">AI 补全</span>
                      ) : null}
                    </div>
                    <div className="ml-9">
                      {(previewItem.ai_answer_flag && (!editState.answer || editState.answer === "（空）")) ? (
                        <div className="mb-2 rounded-lg border border-red-200 bg-red-50/60 px-3 py-2 text-xs text-red-700">答案异常，需人工确认</div>
                      ) : previewItem.ai_answer_flag ? (
                        <div className="mb-2 rounded-lg border border-orange-200 bg-orange-50/60 px-3 py-2 text-xs text-orange-700">答案由 AI 补全，请核对原题</div>
                      ) : (!editState.answer || editState.answer === "（空）") ? (
                        <div className="mb-2 rounded-lg border border-red-200 bg-red-50/60 px-3 py-2 text-xs text-red-700">答案缺失，需人工确认</div>
                      ) : null}
                      <span className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-success)]/20 bg-[var(--color-success)]/5 px-3 py-1 font-mono text-sm font-bold text-[var(--color-success)]">
                        {editState.answer || "（空）"}
                      </span>
                    </div>
                  </section>

                  {/* ── Analysis Card ── */}
                  <section className="animate-fade-up drawer-section-delay-4 rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
                    <div className="flex items-center gap-2.5 mb-3">
                      <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ backgroundColor: "rgba(107,155,107,0.1)" }}>
                        <span className="text-xs font-bold" style={{ color: "#6b9b6b", fontFamily: "'Georgia', serif" }}>析</span>
                      </span>
                      <span className="text-sm font-semibold text-[var(--ink)]">解析</span>
                    </div>
                    <div className="ml-9">
                      {editState.analysis ? (
                        <div className="whitespace-pre-wrap leading-relaxed text-[var(--color-text-secondary)]">
                          <MathFormula text={editState.analysis} />
                        </div>
                      ) : (
                        <p className="text-sm text-[var(--color-text-hint)]">（无解析）</p>
                      )}
                    </div>
                  </section>

                  {/* ── OCR Raw Data ── */}
                  {previewItem.raw_data ? (
                    <section className="animate-fade-up drawer-section-delay-5 rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
                      <details className="group">
                        <summary className="flex cursor-pointer items-center gap-2.5 text-sm font-semibold text-[var(--color-text-secondary)] transition hover:text-[var(--ink)] [&::-webkit-details-marker]:hidden">
                          <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ backgroundColor: "rgba(154,122,186,0.1)" }}>
                            <span className="text-xs font-bold" style={{ color: "#9a7aba", fontFamily: "'Georgia', serif" }}>原</span>
                          </span>
                          <span>OCR 原文 / 导入原始信息</span>
                          <span className="ml-auto inline-block text-[10px] transition-transform group-open:rotate-90 opacity-50">▶</span>
                        </summary>
                        <div className="mt-3 ml-9 space-y-3">
                          {(() => {
                            const rd = previewItem.raw_data as Record<string, unknown>;
                            const rawText = rd.raw_text || rd.ocr_text || rd.text || rd.stem || null;
                            if (rawText && typeof rawText === "string") {
                              return (
                                <div className="rounded-xl border border-[var(--color-border)]/50 bg-[var(--color-bg-input)]/70 p-3">
                                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{rawText}</pre>
                                </div>
                              );
                            }
                            return (
                              <div>
                                <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-xl border border-[var(--color-border)]/50 bg-[var(--color-bg-input)]/70 p-3 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{JSON.stringify(previewItem.raw_data, null, 2)}</pre>
                              </div>
                            );
                          })()}
                        </div>
                      </details>
                    </section>
                  ) : (
                    <section className="animate-fade-up drawer-section-delay-5 rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
                      <div className="flex items-center gap-2.5">
                        <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ backgroundColor: "rgba(154,122,186,0.1)" }}>
                          <span className="text-xs font-bold" style={{ color: "#9a7aba", fontFamily: "'Georgia', serif" }}>原</span>
                        </span>
                        <span className="text-sm font-semibold text-[var(--color-text-secondary)]">OCR 原文</span>
                        <span className="ml-auto text-xs text-[var(--color-text-hint)]">暂无 OCR 原文</span>
                      </div>
                    </section>
                  )}

                  {/* ── Source Region Image ── */}
                  {(() => {
                    const pc = previewItem?.parsed_content as Record<string, unknown> | undefined;
                    const srcRegion = pc?.source_region as Record<string, unknown> | undefined;
                    const srcPage = pc?.source_page;
                    if (!srcRegion && !srcPage) return null;
                    return (
                      <section className="animate-fade-up rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
                        <details className="group">
                          <summary className="flex cursor-pointer items-center gap-2.5 text-sm font-semibold text-[var(--color-text-secondary)] transition hover:text-[var(--ink)] [&::-webkit-details-marker]:hidden">
                            <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ backgroundColor: "rgba(154,122,186,0.1)" }}>
                              <span className="text-xs font-bold" style={{ color: "#9a7aba", fontFamily: "'Georgia', serif" }}>图</span>
                            </span>
                            <span>原图对照</span>
                            {srcPage ? <span className="text-[10px] text-[var(--color-text-hint)]">第 {String(srcPage)} 页</span> : null}
                            <span className="ml-auto inline-block text-[10px] transition-transform group-open:rotate-90 opacity-50">▶</span>
                          </summary>
                          <div className="mt-3 ml-9 space-y-3">
                            {srcRegion?.image_url ? (
                              <img
                                src={String(srcRegion.image_url)}
                                alt="题目区域截图"
                                className="max-w-full rounded-lg border border-[var(--color-border)]"
                                style={{ maxHeight: "400px" }}
                              />
                            ) : srcRegion?.page_image_url ? (
                              <img
                                src={String(srcRegion.page_image_url)}
                                alt="原页截图"
                                className="max-w-full rounded-lg border border-[var(--color-border)]"
                                style={{ maxHeight: "400px" }}
                              />
                            ) : (
                              <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50/50 px-3 py-4 text-center text-xs text-[var(--color-text-hint)]">
                                无原图对照
                                {srcRegion?.bbox ? (
                                  <p className="mt-1 text-[10px]">定位信息：bbox={JSON.stringify(srcRegion.bbox)}</p>
                                ) : null}
                              </div>
                            )}
                          </div>
                        </details>
                      </section>
                    );
                  })()}

                  {/* ── AI Suggestion Stamp ── */}
                  {completeSuggestion ? (
                    <section className="animate-fade-up drawer-section-delay-5 rounded-2xl border border-[var(--color-primary)]/20 bg-gradient-to-br from-[var(--color-primary-light)]/60 to-white/90 p-5 shadow-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2.5">
                          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-primary)] shadow-sm">
                            <Sparkles className="h-4 w-4 text-white" />
                          </div>
                          <div>
                            <p className="text-sm font-bold text-[var(--color-primary-dark)]">AI 补全建议</p>
                            <p className="text-[10px] text-[var(--color-text-hint)]">由语言模型自动生成，请复核后采纳</p>
                          </div>
                        </div>
                        {answerSuggestion ? (
                          <button
                            onClick={() => { setEditState((prev) => prev ? { ...prev, answer: answerSuggestion } : prev); }}
                            className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-primary)]/30 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-[var(--color-primary-dark)] shadow-sm transition hover:bg-[var(--color-primary)] hover:text-white"
                          >
                            应用答案
                          </button>
                        ) : null}
                      </div>
                      <div className="mt-3 rounded-xl border border-[var(--color-primary)]/10 bg-white/80 p-3">
                        <pre className="max-h-36 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{renderJson(completeSuggestion)}</pre>
                      </div>
                    </section>
                  ) : null}
                </>
              ) : detailView === "json" && !editing ? (
                /* ── JSON View ── */
                <div className="space-y-3">
                  {[
                    { title: "基础信息", accent: "#5b7b9a", data: { id: previewItem.id, batch_id: previewItem.batch_id, source_type: previewItem.source_type, subject: previewItem.subject, question_type: previewItem.question_type, status: previewItem.status, ai_generated: previewItem.ai_generated, ai_answer_flag: previewItem.ai_answer_flag, created_at: previewItem.created_at, updated_at: previewItem.updated_at } },
                    { title: "解析数据", accent: "#6b9b6b", data: { parsed_content: previewItem.parsed_content, parsed_options: previewItem.parsed_options, parsed_answer: previewItem.parsed_answer, parsed_analysis: previewItem.parsed_analysis } },
                    { title: "重复检测", accent: "#c49a6b", data: { duplicate_status: previewItem.duplicate_status, duplicate_of_question_id: previewItem.duplicate_of_question_id, duplicate_of_import_id: previewItem.duplicate_of_import_id, question_hash: previewItem.question_hash } },
                    { title: "OCR / AI 原始数据", accent: "#9a7aba", data: { raw_data: previewItem.raw_data, ai_metadata: previewItem.ai_metadata } },
                  ].map(({ title, accent, data }) => (
                    <section key={title} className="animate-fade-up rounded-xl border border-[var(--color-border)]/60 bg-white/80 shadow-sm" style={{ animationDelay: "0.03s" }}>
                      <details className="group" open>
                        <summary className="flex cursor-pointer items-center gap-2.5 border-b border-[var(--color-border)]/30 px-4 py-3 text-xs font-semibold text-[var(--color-text-secondary)] transition hover:text-[var(--ink)] [&::-webkit-details-marker]:hidden">
                          <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded" style={{ backgroundColor: `${accent}18` }}>
                            <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: accent }} />
                          </span>
                          {title}
                          <span className="ml-auto inline-block text-[10px] transition-transform group-open:rotate-90 opacity-50">▶</span>
                        </summary>
                        <div className="px-4 pb-3 pt-2">
                          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-xl border border-[var(--color-border)]/50 bg-[var(--color-bg-input)]/70 p-3 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{renderJson(data)}</pre>
                        </div>
                      </details>
                    </section>
                  ))}
                </div>
              ) : (
                /* ── Edit Mode ── */
                <div className="space-y-5">
                  {/* Subject / Type */}
                  <div className="grid gap-3 md:grid-cols-2 animate-fade-up drawer-section-delay-1">
                    <div className="space-y-1">
                      <label className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-secondary)]">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]/60" />
                        科目
                      </label>
                      <Input placeholder="科目" value={editState.subject} onChange={(event) => setEditState({ ...editState, subject: event.target.value })} />
                    </div>
                    <div className="space-y-1">
                      <label className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-secondary)]">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]/60" />
                        题型
                      </label>
                      <Input placeholder="题型" value={editState.question_type} onChange={(event) => setEditState({ ...editState, question_type: event.target.value })} />
                    </div>
                  </div>
                  {/* Stem edit */}
                  <label className="block space-y-1.5 animate-fade-up drawer-section-delay-2">
                    <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-secondary)]">
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]/60" />
                      题干
                    </span>
                    <textarea className="min-h-36 w-full rounded-xl border border-[var(--color-border)] bg-white/90 px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15" value={editState.stem} onChange={(event) => setEditState({ ...editState, stem: event.target.value })} />
                  </label>

                  {/* Options edit */}
                  <section className="animate-fade-up drawer-section-delay-3 rounded-xl border border-[var(--color-border)]/60 bg-white/80 p-4 shadow-sm">
                    <div className="mb-3 flex items-center gap-2">
                      <span className="flex h-6 w-6 items-center justify-center rounded-md" style={{ backgroundColor: "rgba(196,154,107,0.12)" }}>
                        <span className="text-[10px] font-bold" style={{ color: "#c49a6b" }}>选</span>
                      </span>
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">选项</p>
                    </div>
                    {editState.question_type === "multi_blank_choice" ? (
                      <div className="space-y-3">
                        {(() => {
                          const groups = previewItem?.parsed_content?.blank_option_groups ?? previewItem?.raw_data?.blank_option_groups;
                          const groupList: Array<{ id?: string; options?: Array<{ key: string; text: string }> }> = Array.isArray(groups) ? groups : [];
                          return groupList.length > 0 ? groupList.map((group, gi) => (
                            <div key={gi} className="rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/50 p-3">
                              <p className="mb-2 text-xs font-semibold text-[var(--color-text-hint)]">空 {group.id ?? gi + 1}</p>
                              <div className="space-y-1.5">
                                {group.options?.map((opt, oi) => (
                                  <div key={oi} className="flex items-center gap-2">
                                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--color-primary-light)] text-[10px] font-bold text-[var(--color-primary-dark)]">{opt.key}</span>
                                    <span className="text-sm text-[var(--color-text-secondary)]">{opt.text}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )) : null;
                        })()}
                        <p className="rounded-lg border border-amber-200/60 bg-amber-50/40 px-3 py-2 text-[11px] text-amber-700">多空选择题选项由导入管线管理，如需修改请<button type="button" className="mx-1 underline font-semibold hover:text-amber-900" onClick={() => setDetailView("json")}>切换到 JSON 视图</button>编辑 parsed_content.blank_option_groups。</p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {editState.options.length === 0 ? <p className="text-sm text-[var(--color-text-hint)]">暂无可编辑选项</p> : null}
                        {editState.options.map((opt, index) => (
                          <div key={index} className="flex items-center gap-2">
                            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--color-primary-light)] text-xs font-bold text-[var(--color-primary-dark)]">{opt.key}</span>
                            <input
                              className="h-9 flex-1 rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15"
                              value={opt.text}
                              onChange={(event) => {
                                const next = [...editState.options];
                                next[index] = { ...next[index], text: event.target.value };
                                setEditState({ ...editState, options: next });
                              }}
                            />
                          </div>
                        ))}
                      </div>
                    )}
                  </section>

                  {/* Answer & Analysis edit */}
                  <section className="animate-fade-up drawer-section-delay-4 rounded-xl border border-[var(--color-border)]/60 bg-white/80 p-4 shadow-sm">
                    <div className="mb-3 flex items-center gap-2">
                      <span className="flex h-6 w-6 items-center justify-center rounded-md" style={{ backgroundColor: "rgba(107,155,107,0.12)" }}>
                        <span className="text-[10px] font-bold text-[var(--color-success)]">签</span>
                      </span>
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">答案与解析</p>
                    </div>
                    <p className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">快速选择答案</p>
                    {editState.question_type === "multi_blank_choice" ? <p className="mb-2 text-[10px] text-[var(--color-text-hint)]">多空选择题：单击切换各空答案，以逗号分隔</p> : null}
                    {editState.options.length === 0 ? <p className="mb-2 text-sm text-[var(--color-text-hint)]">请先编辑选项</p> : null}
                    {editState.options.length > 0 ? (
                      <div className="mb-4 flex flex-wrap gap-2">
                        {editState.options.map((opt) => {
                          const selected = isMultiChoice(editState.question_type)
                            ? editState.answer.split(/[,，\s]+/).includes(opt.key)
                            : editState.answer === opt.key;
                          return (
                            <button
                              key={opt.key}
                              type="button"
                              className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3.5 text-sm font-medium transition ${
                                selected
                                  ? "border-[var(--color-success)] bg-[var(--color-success)] text-white shadow-sm"
                                  : "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)] hover:border-[var(--color-success)] hover:text-[var(--color-success)]"
                              }`}
                              onClick={() => {
                                if (isMultiChoice(editState.question_type)) {
                                  const keys = editState.answer.split(/[,，\s]+/).filter(Boolean);
                                  const next = keys.includes(opt.key) ? keys.filter((k) => k !== opt.key) : [...keys, opt.key];
                                  setEditState({ ...editState, answer: next.join(",") });
                                } else {
                                  setEditState({ ...editState, answer: editState.answer === opt.key ? "" : opt.key });
                                }
                              }}
                            >
                              {opt.key}
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                    <label className="mb-3 block space-y-1">
                      <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-secondary)]">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-success)]/60" />
                        答案
                      </span>
                      <Input value={editState.answer} onChange={(event) => setEditState({ ...editState, answer: event.target.value })} />
                      {editState.question_type === "multi_blank_choice" ? <p className="mt-1 text-[10px] text-amber-600">多空选择题答案格式：各空答案用逗号分隔（如 A,B 表示第1空选A、第2空选B）</p> : null}
                    </label>
                    <label className="block space-y-1">
                      <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-secondary)]">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-success)]/60" />
                        解析
                      </span>
                      <textarea className="min-h-24 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15" value={editState.analysis} onChange={(event) => setEditState({ ...editState, analysis: event.target.value })} />
                    </label>
                  </section>

                  {/* AI suggestion in edit mode */}
                  {completeSuggestion ? (
                    <section className="animate-fade-up drawer-section-delay-5 rounded-2xl border border-[var(--color-primary)]/20 bg-gradient-to-br from-[var(--color-primary-light)]/60 to-white/90 p-4 shadow-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-primary)] shadow-sm">
                            <Sparkles className="h-3.5 w-3.5 text-white" />
                          </div>
                          <p className="text-sm font-bold text-[var(--color-primary-dark)]">AI 补全建议</p>
                        </div>
                        {answerSuggestion ? (
                          <button
                            onClick={() => setEditState({ ...editState, answer: answerSuggestion })}
                            className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-primary)]/30 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-[var(--color-primary-dark)] shadow-sm transition hover:bg-[var(--color-primary)] hover:text-white"
                          >
                            应用答案
                          </button>
                        ) : null}
                      </div>
                      <pre className="mt-3 max-h-36 overflow-auto whitespace-pre-wrap rounded-xl border border-[var(--color-primary)]/10 bg-white/80 p-3 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{renderJson(completeSuggestion)}</pre>
                    </section>
                  ) : null}
                </div>
              )}
            </div>
          </aside>
        </div>
      ) : null}

      {showBatchComplete ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.28)]" role="presentation" onClick={() => { if (!executing) { setShowBatchComplete(false); } }}>
          <aside role="dialog" aria-modal="true" className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white shadow-[var(--shadow-floating)]" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="sticky top-0 z-10 border-b border-[var(--color-border)] bg-white/95 px-6 py-4 backdrop-blur-xl">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h4 className="font-display text-xl font-bold text-[var(--ink)]">AI 批量补全</h4>
                  <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                    已选 <span className="font-semibold text-[var(--ink)]">{selectedIds.size}</span> 题
                    {batchResult ? ` · 完成 ${batchResult.succeeded} / 失败 ${batchResult.failed} / 跳过 ${batchResult.skipped}` : ""}
                  </p>
                  {draftRestored && !batchResult ? (
                    <p className="mt-1 flex items-center gap-1 text-xs text-amber-600">
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
                      已恢复上次编辑内容
                    </p>
                  ) : null}
                  {autoSaveHint ? (
                    <p className="mt-1 text-xs text-emerald-600">{autoSaveHint}</p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {!batchResult ? (
                    <Button variant="ghost" className="h-7 px-2 text-[11px] text-[var(--color-text-hint)]" onClick={() => { clearDraft(); setDraftRestored(false); setBatchFields(["answer", "analysis", "knowledge_points", "difficulty"]); setBatchStrategy("fill_empty"); setAutoSaveHint("草稿已清空"); }}>
                      清空草稿
                    </Button>
                  ) : null}
                  <button className="shrink-0 rounded-lg p-1.5 text-[var(--color-text-hint)] hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)] transition disabled:opacity-40" onClick={() => { if (!executing) setShowBatchComplete(false); }} disabled={executing}>
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>
              {executing ? (
                <div className="absolute bottom-0 left-0 right-0 z-20 h-0.5 overflow-hidden bg-[var(--color-primary)]/10">
                  <div className="h-full w-1/2 rounded-full bg-[var(--color-primary)]" style={{ animation: "loadingBar 1.2s cubic-bezier(0.4, 0, 0.2, 1) infinite" }} />
                </div>
              ) : null}
            </div>

            <div className="relative flex-1 px-6 py-5 space-y-6">
              {executing ? (
                <div className="absolute inset-0 z-10 rounded-xl bg-white/70 backdrop-blur-[1px] flex items-center justify-center">
                  <div className="flex flex-col items-center gap-2 rounded-xl bg-white/90 px-5 py-4 shadow-sm">
                    <span className="inline-block h-6 w-6 animate-spin rounded-full border-[3px] border-[var(--color-border)] border-t-[var(--color-primary)]" />
                    <span className="text-sm text-[var(--color-text-secondary)]">正在 AI 补全，请勿关闭</span>
                  </div>
                </div>
              ) : null}
              {!batchResult ? (
                <>
                  {/* Strategy */}
                  <section className="space-y-3">
                    <p className="text-sm font-semibold text-[var(--ink)]">补全策略</p>
                    <div className="flex gap-3">
                      <label className={`flex flex-1 cursor-pointer items-center gap-3 rounded-xl border-2 p-4 transition ${batchStrategy === "fill_empty" ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/20" : "border-[var(--color-border)] bg-white/60 hover:border-[var(--color-primary)]/30"}`}>
                        <input type="radio" name="strategy" value="fill_empty" checked={batchStrategy === "fill_empty"} onChange={() => { setDraftRestored(false); setBatchStrategy("fill_empty"); }} className="sr-only" />
                        <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${batchStrategy === "fill_empty" ? "border-[var(--color-primary)]" : "border-[var(--color-border)]"}`}>
                          {batchStrategy === "fill_empty" ? <span className="h-2.5 w-2.5 rounded-full bg-[var(--color-primary)]" /> : null}
                        </span>
                        <div>
                          <p className="text-sm font-semibold text-[var(--ink)]">仅补全空字段</p>
                          <p className="text-xs text-[var(--color-text-secondary)]">只填充当前为空的内容，已有数据保留</p>
                        </div>
                      </label>
                      <label className={`flex flex-1 cursor-pointer items-center gap-3 rounded-xl border-2 p-4 transition ${batchStrategy === "force_overwrite" ? "border-amber-500 bg-amber-50/40" : "border-[var(--color-border)] bg-white/60 hover:border-amber-400/30"}`}>
                        <input type="radio" name="strategy" value="force_overwrite" checked={batchStrategy === "force_overwrite"} onChange={() => { setDraftRestored(false); setBatchStrategy("force_overwrite"); }} className="sr-only" />
                        <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${batchStrategy === "force_overwrite" ? "border-amber-500" : "border-[var(--color-border)]"}`}>
                          {batchStrategy === "force_overwrite" ? <span className="h-2.5 w-2.5 rounded-full bg-amber-500" /> : null}
                        </span>
                        <div>
                          <p className="text-sm font-semibold text-[var(--ink)]">强制重新生成</p>
                          <p className="text-xs text-[var(--color-text-secondary)]">重新生成并覆盖指定字段的内容</p>
                        </div>
                      </label>
                    </div>
                  </section>

                  {/* Field selection */}
                  <section className="space-y-3">
                    <p className="text-sm font-semibold text-[var(--ink)]">补全字段</p>
                    <p className="text-xs text-[var(--color-text-secondary)]">选择需要 AI 补全的字段（至少选一项）</p>
                    <label className="flex cursor-pointer items-center gap-2.5 rounded-xl border border-[var(--color-border)] bg-white/60 px-3.5 py-2.5 text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)]/30 hover:bg-white/90 select-none">
                      <span className="relative flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 border-[var(--color-border)] bg-white transition-all [&:has(input:checked)]:border-[var(--color-primary)] [&:has(input:checked)]:bg-[var(--color-primary)]">
                        <input
                          type="checkbox"
                          checked={ALL_BATCH_FIELDS.every(f => batchFields.includes(f))}
                          onChange={() => setBatchFields(batchFields.length === ALL_BATCH_FIELDS.length ? [] : [...ALL_BATCH_FIELDS])}
                          className="peer absolute inset-0 cursor-pointer opacity-0"
                        />
                        <Check className="h-3.5 w-3.5 text-white opacity-0 transition-opacity peer-checked:opacity-100" />
                      </span>
                      全选
                      <span className="ml-auto rounded-full bg-[var(--color-primary-light)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-primary-dark)]">已选 {batchFields.length}/{ALL_BATCH_FIELDS.length}</span>
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      {ALL_BATCH_FIELDS.map((value) => {
                        const labels: Record<string, string> = {
                          answer: "题目答案", analysis: "题目解析", knowledge_points: "知识点",
                          difficulty: "难度等级", subject: "科目", question_type: "题型",
                          stem: "题干修复", options: "选项格式化", tips: "解题技巧", tags: "题目标签",
                        };
                        return (
                        <label key={value} className={`flex cursor-pointer items-center gap-2.5 rounded-xl border px-3.5 py-2.5 transition ${
                          batchFields.includes(value)
                            ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/15"
                            : "border-[var(--color-border)] bg-white/60 hover:border-[var(--color-primary)]/30"
                        }`}>
                          <span className={`relative flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition ${
                            batchFields.includes(value)
                              ? "border-[var(--color-primary)] bg-[var(--color-primary)]"
                              : "border-[var(--color-border)] bg-white"
                          }`}>
                            <input type="checkbox" checked={batchFields.includes(value)} onChange={() => toggleBatchField(value)} className="peer absolute inset-0 cursor-pointer opacity-0" />
                            <Check className={`h-3.5 w-3.5 text-white transition-opacity ${batchFields.includes(value) ? "opacity-100" : "opacity-0"}`} />
                          </span>
                          <span className="text-sm text-[var(--ink)]">{labels[value]}</span>
                        </label>
                      );
                    })}
                    </div>
                  </section>
                </>
              ) : (
                /* Results */
                <section className="space-y-3">
                  <div className="flex items-center gap-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-[var(--color-text-secondary)]">成功</span>
                      <span className="text-xl font-bold text-[var(--color-success)]">{batchResult.succeeded}</span>
                    </div>
                    <div className="h-8 w-px bg-[var(--color-border)]" />
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-[var(--color-text-secondary)]">失败</span>
                      <span className="text-xl font-bold text-[var(--color-danger)]">{batchResult.failed}</span>
                    </div>
                    <div className="h-8 w-px bg-[var(--color-border)]" />
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-[var(--color-text-secondary)]">跳过</span>
                      <span className="text-xl font-bold text-[var(--color-text-hint)]">{batchResult.skipped}</span>
                    </div>
                  </div>
                  {batchResult.items.filter((i) => i.status !== "success").length > 0 ? (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">失败/跳过明细</p>
                      {batchResult.items.filter((i) => i.status !== "success").map((item) => (
                        <div
                          key={item.import_id}
                          className={`rounded-xl border px-4 py-3 text-sm ${
                            item.status === "failed"
                              ? "border-[var(--color-danger)]/40 bg-[var(--color-danger-light)]/30"
                              : "border-[var(--color-border)] bg-white/60"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            {item.status === "failed" ? (
                              <AlertTriangle className="h-4 w-4 shrink-0 text-[var(--color-danger)]" />
                            ) : null}
                            <span className="font-mono text-xs text-[var(--color-text-hint)]">#{item.import_id}</span>
                            <span className={`text-xs font-medium ${item.status === "failed" ? "text-[var(--color-danger)]" : "text-[var(--color-text-hint)]"}`}>
                              {item.status === "failed" ? "失败" : "跳过"}
                            </span>
                          </div>
                          {item.error ? (
                            <p className={`mt-1.5 whitespace-pre-wrap text-xs leading-relaxed ${
                              item.status === "failed" ? "text-[var(--color-danger)]" : "text-[var(--color-text-secondary)]"
                            }`}>
                              {item.error}
                            </p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </section>
              )}
            </div>

            {/* Footer actions */}
            <div className="sticky bottom-0 border-t border-[var(--color-border)] bg-white/95 px-6 py-4 backdrop-blur-xl">
              <div className="flex items-center justify-end gap-2">
                {batchResult ? (
                  <Button variant="primary" onClick={() => { setShowBatchComplete(false); setBatchResult(null); }}>
                    完成
                  </Button>
                ) : (
                  <>
                    <Button variant="ghost" onClick={() => setShowBatchComplete(false)} disabled={executing}>
                      取消
                    </Button>
                    <Button variant="primary" disabled={executing || batchFields.length === 0} onClick={executeBatchComplete}>
                      {executing ? (
                        <>
                          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                          补全中...
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-4 w-4" />
                          执行补全
                        </>
                      )}
                    </Button>
                  </>
                )}
              </div>
            </div>
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmState !== null}
        title={confirmState?.action === "low-risk-batch-approve" ? "批量通过低风险题" : confirmState?.action?.includes("reject") ? "驳回导入题目" : "通过导入题目"}
        description={
          confirmState?.action === "low-risk-batch-approve"
              ? `将自动通过当前批次中所有低风险题（risk_level=low）并跳过高风险和需检查题。高风险和需检查题不会被通过。`
              : confirmState?.action === "batch-approve" && selectedIds.size > 0
                ? `将对已选的 ${selectedIds.size} 条导入题目执行批量通过操作。`
                : confirmState?.action === "batch-reject" && selectedIds.size > 0
                  ? `将对已选的 ${selectedIds.size} 条导入题目执行批量驳回操作。`
                  : "操作会更新 question_imports 暂存审核状态。"
        }
        confirmText={confirmState?.action === "low-risk-batch-approve" ? "批量通过低风险" : confirmState?.action?.includes("reject") ? "驳回" : "通过"}
        danger={Boolean(confirmState?.action.includes("reject"))}
        loading={actionMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => confirmState && actionMutation.mutate(confirmState)}
      >
        {confirmState?.action === "reject" || confirmState?.action === "batch-reject" ? (
          <Input placeholder="驳回原因" value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} />
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
