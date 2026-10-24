"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  Sigma,
  Tag,
  Plus,
  ExternalLink,
  Layers,
  Trash2,
  Eye,
  EyeOff,
  Send,
  XCircle,
  CheckCircle,
  Check,
  X,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  FolderTree,
  Folder,
  RotateCcw,
  SlidersHorizontal,
  Loader2,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { CustomCheckbox } from "@/components/ui/custom-checkbox";
import { LatexRenderer } from "@/components/ui/latex-renderer";
import { formatChinaDate } from "@/lib/time";
import { MixedLatexRenderer } from "@/components/ui/mixed-latex-renderer";
import type { FormulaCategoryNode } from "@/components/formulas/formula-category-picker";
import { useAuthStore } from "@/lib/auth/auth-store";
import {
  positiveInt,
  buildFormulaListHref,
  findCategoryNode,
  pruneCategoryTree,
  sumCategoryFormulaCount,
  hasActiveFormulaFilters,
  computeSafeSelectedIds,
  computeBatchSelectionState,
  isBatchableStatus,
} from "@/lib/formula-list-utils";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { PaginatedResponse, FormulaGraphAsset } from "@/lib/api/types";
import { normalizeLatexExpression } from "@/lib/math-text";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

/* ── Structured content renderers for JSON-encoded conditions/error_tips ── */

function renderStructuredConditions(raw: string | null | undefined) {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return (
        <ul className="list-none space-y-1.5">
          {parsed.map((item, i) => {
            const expr = typeof item === 'string' ? item : item?.expression ?? ''
            const note = typeof item === 'object' && item ? (item as Record<string, string>).note ?? '' : ''
            return (
              <li key={i}>
                <MixedLatexRenderer text={expr} />
                {note && <span className="text-[var(--color-text-secondary)] ml-2">— {note}</span>}
              </li>
            )
          })}
        </ul>
      )
    }
  } catch { /* not JSON, fall through */ }
  return <MixedLatexRenderer text={raw} />
}

function renderStructuredErrorTips(raw: string | null | undefined) {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return (
        <ul className="list-disc pl-4 space-y-1">
          {parsed.map((tip, i) => (
            <li key={i}><MixedLatexRenderer text={typeof tip === 'string' ? tip : JSON.stringify(tip)} /></li>
          ))}
        </ul>
      )
    }
  } catch { /* not JSON, fall through */ }
  return <MixedLatexRenderer text={raw} />
}

/* ── Types ── */

type FormulaBlock = { label?: string | null; latex: string; note?: string | null };

type FormulaCard = {
  id: number;
  title: string;
  category_id: number;
  exam_scope: string;
  card_type: string;
  study_card_type: string;
  template_type: string;
  is_function_graph: boolean;
  summary: string | null;
  formula_blocks: FormulaBlock[];
  conditions: string | null;
  symbol_notes: string | null;
  secondary_conclusions: string | null;
  error_tips: string | null;
  examples: Array<{ question: string; short_solution: string; answer: string; error_tip?: string | null }> | null;
  status: string;
  tags: Array<{ id: number; code: string; name: string }>;
  version: number;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  aliases: string[] | null;
  source_title: string | null;
  rejection_reason: string | null;
  function_properties: Record<string, unknown> | null;
  graph_asset: FormulaGraphAsset | null;
  graph_status?: string;
  graph_last_error?: string | null;
};

type AdminFormulaCategoryNode = Omit<FormulaCategoryNode, "children"> & {
  formula_count?: number;
  subtree_formula_count?: number;
  children: AdminFormulaCategoryNode[];
};

type BatchReviewResponse = {
  items: Array<{ id: number; status: string }>;
};

/* ── Status helpers ── */

const STATUS_OPTIONS = [
  { label: "全部状态", value: "" },
  { label: "草稿", value: "draft" },
  { label: "待审核", value: "pending_review" },
  { label: "已驳回", value: "rejected" },
  { label: "已发布", value: "published" },
  { label: "已下架", value: "offline" },
];

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-gray-50 text-gray-600 border-gray-200",
  pending_review: "bg-amber-50 text-amber-700 border-amber-200",
  rejected: "bg-red-50 text-red-700 border-red-200",
  published: "bg-emerald-50 text-emerald-700 border-emerald-200",
  offline: "bg-slate-50 text-slate-600 border-slate-200",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  pending_review: "待审核",
  rejected: "已驳回",
  published: "已发布",
  offline: "已下架",
};

const STUDY_CARD_TYPE_OPTIONS = [
  { value: "", label: "全部速记类型" },
  { value: "formula", label: "公式" },
  { value: "definition", label: "定义" },
  { value: "complexity", label: "算法复杂度" },
  { value: "protocol_rule", label: "协议字段 / 规则" },
  { value: "key_conclusion", label: "高频结论" },
  { value: "confusable", label: "易混概念" },
  { value: "trap", label: "典型陷阱" },
  { value: "comparison", label: "对比卡" },
];

const STUDY_CARD_TYPE_LABEL: Record<string, string> = Object.fromEntries(
  STUDY_CARD_TYPE_OPTIONS.filter((item) => item.value).map((item) => [item.value, item.label]),
);

const LIBRARY_TYPE_OPTIONS = [
  { label: "全部分类", value: "" },
  { label: "纯公式", value: "pure_formula" },
  { label: "函数图像", value: "function_graph" },
];

const GRAPH_STATUS_OPTIONS = [
  { label: "图像状态: 全部", value: "" },
  { label: "不适用", value: "not_applicable" },
  { label: "未配置", value: "unconfigured" },
  { label: "缺少图像", value: "missing" },
  { label: "生成中", value: "generating" },
  { label: "待确认", value: "draft" },
  { label: "已完成", value: "ready" },
  { label: "生成失败", value: "failed" },
  { label: "已忽略", value: "ignored" },
];

const GRAPH_STATUS_BADGE: Record<string, string> = {
  not_applicable: "bg-gray-50 text-gray-400 border-gray-200",
  unconfigured: "bg-gray-50 text-gray-500 border-gray-200",
  missing: "bg-amber-50 text-amber-700 border-amber-200",
  generating: "bg-blue-50 text-blue-700 border-blue-200",
  draft: "bg-amber-50 text-amber-700 border-amber-200",
  ready: "bg-emerald-50 text-emerald-700 border-emerald-200",
  failed: "bg-red-50 text-red-700 border-red-200",
  ignored: "bg-gray-50 text-gray-400 border-gray-200",
};

const GRAPH_STATUS_LABEL: Record<string, string> = {
  not_applicable: "不适用",
  unconfigured: "未配置",
  missing: "缺少图像",
  generating: "生成中",
  draft: "待确认",
  ready: "已完成",
  failed: "生成失败",
  ignored: "已忽略",
};

/* ── Main page ── */

type FormulaListFilters = {
  status: string;
  category_id: string;
  q: string;
  tags: string;
  library_type: string;
  study_card_type: string;
  graph_status: string;
};

const EMPTY_FORMULA_FILTERS: FormulaListFilters = {
  status: "", category_id: "", q: "", tags: "", library_type: "", study_card_type: "", graph_status: "",
};

export default function FormulasPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const permissions = useAuthStore((state) => state.permissions);

  const [filters, setFilters] = useState<FormulaListFilters>(() => ({
    ...EMPTY_FORMULA_FILTERS,
    status: searchParams.get("status") || "",
    category_id: String(positiveInt(searchParams.get("category_id")) || ""),
    q: searchParams.get("q") || "",
    tags: searchParams.get("tags") || "",
    library_type: searchParams.get("library_type") || "",
    study_card_type: searchParams.get("study_card_type") || "",
    graph_status: searchParams.get("graph_status") || "",
  }));
  const [page, setPage] = useState(() => positiveInt(searchParams.get("page"), 1) || 1);
  const [selectedId, setSelectedId] = useState<number | null>(() => positiveInt(searchParams.get("selected_id")));
  const [message, setMessage] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<{
    action: string; cardId: number; title: string;
  } | null>(null);
  const [reviewReason, setReviewReason] = useState("");
  const [categorySearch, setCategorySearch] = useState("");
  const [searchDraft, setSearchDraft] = useState(() => searchParams.get("q") || "");
  const [searchDebouncing, setSearchDebouncing] = useState(false);
  const [expandedCategories, setExpandedCategories] = useState<Set<number>>(new Set());
  const detailScrollRef = useRef<HTMLDivElement>(null);

  // ── Batch selection ──
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);

  const canWrite = hasPermission(permissions, "formula:create");
  const canUpdate = hasPermission(permissions, "formula:update");
  const canReview = hasPermission(permissions, "formula:review");
  const canDelete = hasPermission(permissions, "formula:delete");

  const currentFilterStatus = filters.status;

  // Load list
  const queryParams = useMemo(() => ({
    page,
    page_size: 20,
    status: currentFilterStatus || undefined,
    category_id: filters.category_id ? Number(filters.category_id) : undefined,
    include_descendants: filters.category_id ? true : undefined,
    q: filters.q || undefined,
    library_type: filters.library_type || undefined,
    study_card_type: filters.study_card_type || undefined,
    graph_status: filters.graph_status || undefined,
  }), [page, currentFilterStatus, filters.category_id, filters.q, filters.library_type, filters.study_card_type, filters.graph_status]);

  const formulas = useQuery({
    queryKey: ["admin-formulas", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<FormulaCard>>(
      `/formulas${toQuery(queryParams)}`,
    ),
    placeholderData: (previousData) => previousData,
    retry: false,
  });

  const categories = useQuery({
    queryKey: ["admin-formula-categories"],
    queryFn: () => apiRequest<{ items: AdminFormulaCategoryNode[] }>("/formulas/categories"),
    staleTime: 60000,
  });

  // Detail
  const detail = useQuery({
    queryKey: ["admin-formulas", selectedId],
    queryFn: () => apiRequest<FormulaCard>(`/formulas/${selectedId}`),
    enabled: selectedId !== null,
    retry: false,
  });

  // Delete
  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiRequest<{ status: string }>(`/formulas/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      setMessage(`公式 #${id} 已删除。`);
      setSelectedId(null);
      setConfirmAction(null);
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "删除失败"),
  });

  // Review action
  const reviewMutation = useMutation({
    mutationFn: async ({ cardId, action, reason }: { cardId: number; action: string; reason?: string }) => {
      const body: Record<string, unknown> = { action };
      if (reason) body.rejection_reason = reason;
      return apiRequest<{ status: string; new_status: string }>(
        `/formulas/${cardId}/review`, { method: "POST", body: JSON.stringify(body) },
      );
    },
    onSuccess: (result) => {
      if (result.new_status === "published") {
        setMessage("审核通过，公式已自动发布。");
      } else {
        setMessage(`状态已更新为「${STATUS_LABEL[result.new_status] || result.new_status}」。`);
      }
      setConfirmAction(null);
      setReviewReason("");
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
      if (selectedId) queryClient.invalidateQueries({ queryKey: ["admin-formulas", selectedId] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "操作失败"),
  });

  // ── Batch review mutation ──
  const batchMutation = useMutation({
    mutationFn: async (body: { card_ids: number[]; action: string; rejection_reason?: string }) =>
      apiRequest<BatchReviewResponse>(`/formulas/batch-review`, {
        method: "POST", body: JSON.stringify(body),
      }),
    onSuccess: (result) => {
      const success = result.items.filter((i) => i.status === "published" || i.status === "rejected").length;
      const invalid = result.items.filter((i) => i.status === "invalid_transition" || i.status === "not_found").length;
      const parts: string[] = [];
      if (success > 0) parts.push(`成功通过并发布 ${success} 条公式`);
      if (invalid > 0) parts.push(`${invalid} 条未处理`);
      setMessage(parts.join("，") || "批量操作完成");
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const item of result.items) {
          if (item.status === "published" || item.status === "rejected") next.delete(item.id);
        }
        return next;
      });
      setConfirmAction(null);
      setReviewReason("");
      setBatchBusy(false);
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => { setMessage(e instanceof Error ? e.message : "批量操作失败"); setBatchBusy(false); },
  });

  useEffect(() => {
    const next = searchDraft.trim();
    if (next === filters.q) {
      setSearchDebouncing(false);
      return;
    }

    setSearchDebouncing(true);
    const timer = window.setTimeout(() => {
      setFilters((current) => ({ ...current, q: next }));
      setPage(1);
      setSelectedIds(new Set());
      setSearchDebouncing(false);
    }, next ? 280 : 100);
    return () => window.clearTimeout(timer);
  }, [searchDraft, filters.q]);

  const items = useMemo(() => formulas.data?.items ?? [], [formulas.data?.items]);
  const selectedCard = detail.data;
  const isBatchable = isBatchableStatus(currentFilterStatus);

  useEffect(() => {
    if (!categories.data?.items?.length) return;
    setExpandedCategories((prev) => {
      if (prev.size > 0) return prev;
      return new Set(categories.data!.items.map((item) => item.id));
    });
  }, [categories.data?.items]);

  useEffect(() => {
    if (!items.length) {
      setSelectedId(null);
      return;
    }
    if (selectedId === null || !items.some((item) => item.id === selectedId)) {
      setSelectedId(items[0].id);
    }
  }, [items, selectedId]);

  useEffect(() => {
    if (selectedId === null) return;
    const frame = window.requestAnimationFrame(() => {
      detailScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selectedId]);

  // ── Batch selection logic ──
  const safeSelectedIds = useMemo(
    () => computeSafeSelectedIds(items, selectedIds),
    [items, selectedIds],
  );

  const allCurrentIds = useMemo(() => items.map((c) => c.id), [items]);
  const { allSelected, indeterminate, selectedCount } = computeBatchSelectionState(items, selectedIds);

  const toggleSelect = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    if (allSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(allCurrentIds));
  }, [allSelected, allCurrentIds]);

  const handleBatchApprove = () => {
    setBatchBusy(true);
    batchMutation.mutate({ card_ids: Array.from(safeSelectedIds), action: "approve" });
  };

  const handleBatchReject = () => {
    const t = reviewReason.trim();
    if (!t) return;
    setBatchBusy(true);
    batchMutation.mutate({ card_ids: Array.from(safeSelectedIds), action: "reject", rejection_reason: t });
  };

  // ── Batch submit (draft → pending_review) ──
  const handleBatchSubmit = () => {
    setBatchBusy(true);
    batchMutation.mutate({ card_ids: Array.from(safeSelectedIds), action: "approve" });
  };

  // ── Batch delete (draft only) ──
  const batchDeleteMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      const results = await Promise.allSettled(
        ids.map((id) => apiRequest<{ status: string }>(`/formulas/${id}`, { method: "DELETE" }))
      );
      const successCount = results.filter((r) => r.status === "fulfilled").length;
      const failCount = results.filter((r) => r.status === "rejected").length;
      return { successCount, failCount };
    },
    onSuccess: (result) => {
      const parts: string[] = [];
      if (result.successCount > 0) parts.push(`成功删除 ${result.successCount} 条公式`);
      if (result.failCount > 0) parts.push(`${result.failCount} 条删除失败`);
      setMessage(parts.join("，") || "操作完成");
      setSelectedIds(new Set());
      setConfirmAction(null);
      setBatchBusy(false);
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => { setMessage(e instanceof Error ? e.message : "批量删除失败"); setBatchBusy(false); },
  });

  const handleBatchDelete = () => {
    setBatchBusy(true);
    batchDeleteMutation.mutate(Array.from(safeSelectedIds));
  };

  // ── Auto-dismiss toast after 4s ──
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(t);
  }, [message]);

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
    setSelectedIds(new Set());  // clear selection on filter change
  };

  const submitReview = () => {
    if (!confirmAction) return;
    reviewMutation.mutate({
      cardId: confirmAction.cardId,
      action: confirmAction.action,
      reason: confirmAction.action === "reject" ? reviewReason : undefined,
    });
  };

  const toggleCategory = (id: number) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const filteredCategoryTree = useMemo(() => {
    return pruneCategoryTree(categories.data?.items ?? [], categorySearch);
  }, [categories.data?.items, categorySearch]);

  const selectedCategory = useMemo(
    () => findCategoryNode(categories.data?.items ?? [], filters.category_id ? Number(filters.category_id) : null),
    [categories.data?.items, filters.category_id],
  );
  const totalCategoryFormulaCount = useMemo(
    () => sumCategoryFormulaCount(categories.data?.items ?? []),
    [categories.data?.items],
  );
  const hasActiveFilters = hasActiveFormulaFilters(filters);
  const listReturnHref = useMemo(
    () => buildFormulaListHref(filters, page, selectedId),
    [filters, page, selectedId],
  );

  const prefetchDetail = useCallback((id: number) => {
    void queryClient.prefetchQuery({
      queryKey: ["admin-formulas", id],
      queryFn: () => apiRequest<FormulaCard>(`/formulas/${id}`),
      staleTime: 30_000,
    });
  }, [queryClient]);

  const renderCategoryTree = (nodes: AdminFormulaCategoryNode[], depth = 0) =>
    nodes.map((node) => {
      const hasChildren = Boolean(node.children?.length);
      const isExpanded = categorySearch.trim() ? true : expandedCategories.has(node.id);
      const isSelected = filters.category_id === String(node.id);

      return (
        <div key={node.id}>
          <div
            className={`group flex items-center gap-1 rounded-lg pr-2 transition-colors ${
              isSelected ? "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]" : "hover:bg-[var(--color-bg-input)]"
            }`}
            style={{ paddingLeft: 4 + depth * 14 }}
          >
            <button
              type="button"
              onClick={() => hasChildren && toggleCategory(node.id)}
              className="flex h-8 w-6 shrink-0 items-center justify-center text-[var(--color-text-hint)]"
              aria-label={isExpanded ? "收起分类" : "展开分类"}
            >
              {hasChildren ? (
                <ChevronRight className={`h-3.5 w-3.5 transition-transform duration-200 ${isExpanded ? "rotate-90" : ""}`} />
              ) : <span className="h-3.5 w-3.5" />}
            </button>
            <button
              type="button"
              onClick={() => updateFilter("category_id", String(node.id))}
              className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left"
              title={`${node.name} (${node.code})`}
            >
              {node.node_type === "subject" ? (
                <FolderTree className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
              ) : (
                <Folder className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-hint)]" />
              )}
              <span className={`truncate text-xs ${isSelected ? "font-semibold" : "font-medium text-[var(--color-text-secondary)]"}`}>
                {node.name}
              </span>
            </button>
            <span
              className="min-w-5 text-right text-[10px] tabular-nums text-[var(--color-text-hint)]"
              title={`${node.subtree_formula_count ?? node.formula_count ?? 0} 条公式（含子分类）`}
            >
              {node.subtree_formula_count ?? node.formula_count ?? 0}
            </span>
          </div>
          {hasChildren && isExpanded ? <div className="animate-fade-in">{renderCategoryTree(node.children, depth + 1)}</div> : null}
        </div>
      );
    });

  const clearFilters = () => {
    setSearchDraft("");
    setFilters({ ...EMPTY_FORMULA_FILTERS });
    setPage(1);
    setSelectedIds(new Set());
  };

  return (
    <div className="space-y-5 pb-24">
      {/* ── Header ── */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1
            className="font-display text-[28px] font-bold leading-tight tracking-tight text-[var(--ink)]"
            style={{ fontVariationSettings: "'wght' 700" }}
          >
            408 速记卡管理
          </h1>
          <p className="mt-1.5 text-sm leading-relaxed text-[var(--color-text-secondary)]">
            {canReview ? "统一管理公式、定义、易混点、陷阱与对比卡，审核通过后自动发布" : "分类、列表与详情同屏管理 408 速记卡"}
          </p>
        </div>
        {canWrite && (
          <Link href="/formulas/new">
            <Button variant="primary" size="md">
              <Plus className="h-4 w-4" />
              新建速记卡
            </Button>
          </Link>
        )}
      </div>

      {/* ── Floating toast notification ── */}
      {message && (
        <div className="fixed right-6 top-24 z-50 animate-fade-in">
          <div className="flex items-center gap-3 rounded-full border border-[var(--color-success)]/30 bg-white/90 py-2 pl-5 pr-2 shadow-lg shadow-black/8 backdrop-blur-xl">
            <span className="text-sm font-medium text-[var(--color-text-primary)]">{message}</span>
            <button
              type="button"
              onClick={() => setMessage(null)}
              className="flex h-7 w-7 items-center justify-center rounded-full text-[var(--color-text-hint)] transition-colors hover:bg-[var(--color-success-light)] hover:text-[var(--color-success)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      <Card className="overflow-visible">
        {/* ── Workspace filters ── */}
        <div className="border-b border-[var(--color-border)] bg-white/72 p-4">
          <div className="grid gap-2 lg:grid-cols-[minmax(240px,1fr)_140px_150px_170px_155px_auto]">
            <label className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input
                className="pl-9 pr-16"
                placeholder="搜索标题 / 别名 / 速记内容"
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
              />
              <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1">
                {(searchDebouncing || (formulas.isFetching && Boolean(filters.q))) ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-text-hint)]" />
                ) : null}
                {searchDraft ? (
                  <button
                    type="button"
                    onClick={() => setSearchDraft("")}
                    className="grid h-7 w-7 place-items-center rounded-lg text-[var(--color-text-hint)] transition hover:bg-[var(--color-primary-light)] hover:text-[var(--ink)]"
                    aria-label="清空搜索"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </div>
            </label>
            <CustomSelect
              value={currentFilterStatus}
              onChange={(v) => updateFilter("status", v)}
              options={STATUS_OPTIONS}
              placeholder="全部状态"
              clearable={false}
            />
            <CustomSelect
              value={filters.library_type}
              onChange={(v) => updateFilter("library_type", v)}
              options={LIBRARY_TYPE_OPTIONS}
              placeholder="全部类型"
              clearable={false}
            />
            <CustomSelect
              value={filters.study_card_type}
              onChange={(v) => updateFilter("study_card_type", v)}
              options={STUDY_CARD_TYPE_OPTIONS}
              placeholder="全部速记类型"
              clearable={false}
            />
            <CustomSelect
              value={filters.graph_status}
              onChange={(v) => updateFilter("graph_status", v)}
              options={GRAPH_STATUS_OPTIONS}
              placeholder="图像状态"
              clearable={false}
            />
            <Button variant="secondary" onClick={clearFilters} className="whitespace-nowrap">
              <RotateCcw className="h-3.5 w-3.5" />
              重置筛选
            </Button>
          </div>
        </div>

        {/* ── Three-column management workspace ── */}
        <div className="grid min-h-[680px] xl:grid-cols-[230px_minmax(430px,1fr)_minmax(330px,0.78fr)] xl:items-stretch">
          {/* Category navigation */}
          <aside className="border-b border-[var(--color-border)] bg-[var(--porcelain)]/55 p-4 xl:self-stretch xl:border-b-0 xl:border-r">
            <div className="xl:sticky xl:top-0 xl:flex xl:h-dvh xl:min-h-0 xl:flex-col xl:overflow-hidden">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">分类目录</p>
                <p className="mt-1 text-[11px] text-[var(--color-text-hint)]">按学科层级快速定位</p>
              </div>
              {filters.category_id ? (
                <button
                  type="button"
                  onClick={() => updateFilter("category_id", "")}
                  className="text-[11px] font-medium text-[var(--color-primary)] hover:underline"
                >
                  全部
                </button>
              ) : null}
            </div>
            <label className="relative mb-3 block">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <input
                value={categorySearch}
                onChange={(e) => setCategorySearch(e.target.value)}
                placeholder="搜索分类名称 / 编码"
                className="h-9 w-full rounded-xl border border-[var(--color-border)] bg-white/80 pl-8 pr-3 text-xs outline-none transition focus:border-[var(--color-primary)]"
              />
            </label>
            <button
              type="button"
              onClick={() => updateFilter("category_id", "")}
              className={`mb-1 flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-xs font-semibold transition ${
                !filters.category_id ? "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]" : "text-[var(--color-text-secondary)] hover:bg-white"
              }`}
            >
              <span className="flex items-center gap-2"><Layers className="h-3.5 w-3.5" />全部分类</span>
              <span className="tabular-nums text-[10px] text-[var(--color-text-hint)]">{totalCategoryFormulaCount}</span>
            </button>
            <div className="max-h-[560px] space-y-0.5 overflow-y-auto pr-1 xl:min-h-0 xl:max-h-none xl:flex-1 xl:overscroll-contain">
              {categories.isLoading ? (
                <div className="space-y-2 py-2">
                  {Array.from({ length: 7 }, (_, i) => <div key={i} className="h-8 animate-pulse rounded-lg bg-white/70" />)}
                </div>
              ) : filteredCategoryTree.length ? (
                renderCategoryTree(filteredCategoryTree)
              ) : (
                <p className="py-8 text-center text-xs text-[var(--color-text-hint)]">无匹配分类</p>
              )}
            </div>
            <div className="mt-4 border-t border-[var(--color-border)] pt-3">
              <Link href="/formulas/categories">
                <Button variant="secondary" size="sm" className="w-full">
                  <FolderTree className="h-3.5 w-3.5" />
                  管理分类
                </Button>
              </Link>
            </div>
            </div>
          </aside>

          {/* Formula list */}
          <main className="min-w-0 border-b border-[var(--color-border)] p-4 xl:border-b-0 xl:border-r">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-bold text-[var(--ink)]">速记卡列表</p>
                  {selectedCategory ? (
                    <span className="rounded-md bg-[var(--color-primary-light)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-primary-dark)]">
                      {selectedCategory.name} · 含子分类
                    </span>
                  ) : null}
                  {formulas.isFetching && !formulas.isLoading ? (
                    <span className="inline-flex items-center gap-1 text-[10px] text-[var(--color-text-hint)]">
                      <Loader2 className="h-3 w-3 animate-spin" /> 更新中
                    </span>
                  ) : null}
                </div>
                <p className="mt-0.5 text-[11px] text-[var(--color-text-hint)]">
                  {formulas.isLoading ? "正在加载…" : `共 ${formulas.data?.total ?? 0} 项 · 第 ${formulas.data?.page ?? page} 页`}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {isBatchable ? (
                  <div className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-white px-2.5 py-1.5">
                    <CustomCheckbox
                      checked={allSelected}
                      indeterminate={indeterminate}
                      disabled={batchBusy}
                      onCheckedChange={toggleSelectAll}
                      aria-label="选择当前页"
                    />
                    <span className="text-[11px] text-[var(--color-text-secondary)]">全选当前页</span>
                  </div>
                ) : null}
                {hasActiveFilters ? (
                  <span className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-primary)]/20 bg-[var(--color-primary-light)]/55 px-2.5 py-1.5 text-[11px] font-medium text-[var(--color-primary-dark)]">
                    <SlidersHorizontal className="h-3 w-3" /> 筛选已生效
                  </span>
                ) : null}
              </div>
            </div>

            {formulas.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 6 }, (_, i) => <div key={i} className="h-24 animate-pulse rounded-2xl border bg-white/60" />)}
              </div>
            ) : formulas.isError ? (
              <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-red-200 bg-red-50/35 py-14 text-center animate-fade-in">
                <AlertCircle className="h-9 w-9 text-red-400" />
                <div>
                  <p className="text-sm font-semibold text-red-700">公式加载失败</p>
                  <p className="mt-1 text-xs text-red-500">请检查查询参数或后端服务后重试</p>
                </div>
                <Button variant="secondary" size="sm" onClick={() => formulas.refetch()}>重新加载</Button>
              </div>
            ) : (
              <div className={`space-y-2 transition-opacity duration-200 ${formulas.isFetching ? "opacity-70" : "opacity-100"}`}>
                <div className="stagger-enter space-y-2" key={`${filters.category_id}-${filters.status}-${filters.q}-${page}`}>
                {items.map((card) => {
                  const isSelected = selectedId === card.id;
                  const tagNames = card.tags?.map((tag) => tag.name).join(" · ") || "";
                  return (
                    <article
                      key={card.id}
                      onMouseEnter={() => prefetchDetail(card.id)}
                      className={`group rounded-2xl border transition-all duration-200 ${
                        isSelected
                          ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/35 shadow-sm ring-2 ring-[var(--color-primary-light)]"
                          : "border-[var(--color-border)] bg-white/82 hover:border-[var(--color-primary)]/45 hover:bg-white"
                      }`}
                    >
                      <div className="flex items-start gap-3 p-3">
                        {isBatchable ? (
                          <CustomCheckbox
                            checked={safeSelectedIds.has(card.id)}
                            disabled={batchBusy}
                            onCheckedChange={() => toggleSelect(card.id)}
                            aria-label={`选择公式「${card.title}」`}
                            onClick={(e: MouseEvent<HTMLButtonElement>) => e.stopPropagation()}
                          />
                        ) : null}
                        <button
                          type="button"
                          onClick={() => { setSelectedId(card.id); }}
                          className="min-w-0 flex-1 text-left"
                        >
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${STATUS_BADGE[card.status] || "bg-gray-50"}`}>
                              {STATUS_LABEL[card.status] || card.status}
                            </span>
                            <span className="inline-flex rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                              {STUDY_CARD_TYPE_LABEL[card.study_card_type] || card.study_card_type || "公式"}
                            </span>
                            {card.is_function_graph ? (
                              <span className="inline-flex rounded-md border border-[var(--color-primary-light)] bg-[var(--color-primary-light)]/60 px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-primary-dark)]">函数图像</span>
                            ) : null}
                            {card.graph_status && card.graph_status !== "not_applicable" ? (
                              <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${GRAPH_STATUS_BADGE[card.graph_status] || "bg-gray-50"}`}>
                                {GRAPH_STATUS_LABEL[card.graph_status] || card.graph_status}
                              </span>
                            ) : null}
                          </div>
                          <h3 className="mt-1.5 line-clamp-1 text-sm font-bold text-[var(--ink)]"><MixedLatexRenderer text={card.title} /></h3>
                          {card.summary ? (
                            <p className="mt-1 line-clamp-1 text-xs leading-5 text-[var(--color-text-secondary)]"><MixedLatexRenderer text={card.summary} /></p>
                          ) : null}
                          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--color-text-hint)]">
                            {tagNames ? <span className="inline-flex items-center gap-1"><Tag className="h-3 w-3" />{tagNames}</span> : null}
                            <span>#{card.id}</span>
                            <span>{card.formula_blocks?.length || 0} 个内容块</span>
                            <span>v{card.version}</span>
                            <span>{formatChinaDate(card.updated_at)}</span>
                          </div>
                        </button>
                        {card.card_type === "function_graph" && card.graph_asset?.thumbnail_url ? (
                          <img src={card.graph_asset.thumbnail_url} alt="" className="h-12 w-20 shrink-0 rounded-lg border object-cover" />
                        ) : null}
                      </div>
                    </article>
                  );
                })}
                </div>

                {!items.length ? (
                  <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-[var(--color-border)] bg-white/60 py-14 text-center animate-fade-in">
                    <Sigma className="h-10 w-10 text-[var(--color-text-hint)]" />
                    <p className="text-sm font-semibold text-[var(--color-text-secondary)]">{selectedCategory ? `「${selectedCategory.name}」下暂无匹配速记卡` : "暂无匹配速记卡"}</p>
                    <p className="max-w-sm text-xs leading-5 text-[var(--color-text-hint)]">
                      {selectedCategory ? "已同时查询当前分类及其全部子分类。可调整状态、速记类型、图像状态或搜索关键词。" : "尝试调整搜索关键词或筛选条件。"}
                    </p>
                    {hasActiveFilters ? <Button variant="secondary" size="sm" onClick={clearFilters}>清除筛选</Button> : null}
                  </div>
                ) : null}
              </div>
            )}

            {formulas.data && formulas.data.total_pages > 1 ? (
              <div className="mt-4 flex items-center justify-between gap-3 border-t border-[var(--color-border)] pt-3">
                <span className="text-[11px] text-[var(--color-text-hint)]">第 {formulas.data.page} / {formulas.data.total_pages} 页</span>
                <div className="flex items-center gap-1">
                  <button
                    disabled={page <= 1 || formulas.isFetching}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--color-border)] bg-white transition hover:border-[var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                  {Array.from({ length: Math.min(formulas.data.total_pages, 5) }, (_, i) => {
                    const startPage = Math.max(1, Math.min(page - 2, formulas.data.total_pages - 4));
                    const pageNumber = startPage + i;
                    if (pageNumber > formulas.data.total_pages) return null;
                    return (
                      <button
                        key={pageNumber}
                        onClick={() => setPage(pageNumber)}
                        disabled={formulas.isFetching}
                        className={`inline-flex h-8 min-w-8 items-center justify-center rounded-lg border px-2 text-xs font-semibold ${
                          pageNumber === page ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white" : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)]"
                        }`}
                      >
                        {pageNumber}
                      </button>
                    );
                  })}
                  <button
                    disabled={page >= formulas.data.total_pages || formulas.isFetching}
                    onClick={() => setPage((p) => p + 1)}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--color-border)] bg-white transition hover:border-[var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ) : null}
          </main>

          {/* Detail / preview */}
          <aside className="min-w-0 bg-white/62 p-4 xl:self-stretch">
            <div className="xl:sticky xl:top-0 xl:h-dvh xl:min-h-0 xl:overflow-hidden">
            {detail.isLoading && selectedId !== null ? (
              <div className="space-y-3 animate-fade-in">
                <div className="h-16 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/75" />
                <div className="h-24 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/60" />
                <div className="h-48 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/50" />
              </div>
            ) : selectedCard ? (
              <div
                ref={detailScrollRef}
                key={selectedCard.id}
                className="space-y-4 animate-fade-in xl:h-full xl:min-h-0 xl:overflow-y-auto xl:overscroll-contain xl:pr-1"
              >
                <div className="sticky top-0 z-10 -mx-1 flex items-start justify-between gap-3 rounded-xl bg-white/94 px-1 pb-2 pt-0.5 backdrop-blur supports-[backdrop-filter]:bg-white/82">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${STATUS_BADGE[selectedCard.status] || ""}`}>
                        {STATUS_LABEL[selectedCard.status] || selectedCard.status}
                      </span>
                      <span className="text-[10px] text-[var(--color-text-hint)]">#{selectedCard.id} · v{selectedCard.version}</span>
                    </div>
                    <h2 className="mt-2 text-base font-bold leading-6 text-[var(--ink)]"><MixedLatexRenderer text={selectedCard.title} /></h2>
                  </div>
                  {canUpdate ? (
                    <Link href={`/formulas/${selectedCard.id}?returnTo=${encodeURIComponent(listReturnHref)}`}>
                      <Button variant="secondary" size="sm">
                        <ExternalLink className="h-3.5 w-3.5" /> 编辑
                      </Button>
                    </Link>
                  ) : null}
                </div>

                <div className="flex flex-wrap gap-1.5">
                  {selectedCard.tags?.map((tag) => (
                    <span key={tag.id} className="inline-flex items-center rounded-md border border-[var(--color-border)] bg-white px-2 py-1 text-[10px] text-[var(--color-text-secondary)]">
                      {tag.name}
                    </span>
                  ))}
                </div>

                {selectedCard.summary ? (
                  <section className="rounded-2xl border border-[var(--color-border)] bg-white p-3">
                    <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">内容摘要</p>
                    <p className="text-xs leading-5 text-[var(--color-text-secondary)]"><MixedLatexRenderer text={selectedCard.summary} /></p>
                  </section>
                ) : null}

                <section className="rounded-2xl border border-[var(--color-border)] bg-white p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-bold text-[var(--ink)]">公式预览</p>
                    <span className="text-[10px] text-[var(--color-text-hint)]">{selectedCard.formula_blocks?.length || 0} 个公式块</span>
                  </div>
                  <div className="space-y-2">
                    {selectedCard.formula_blocks?.length ? selectedCard.formula_blocks.map((block, index) => (
                      <div key={index} className="rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)]/45 p-3">
                        {block.label ? <p className="mb-1 text-[10px] font-semibold text-[var(--color-text-hint)]">{block.label}</p> : null}
                        <LatexRenderer latex={normalizeLatexExpression(block.latex)} displayMode={true} />
                        {block.note ? <p className="mt-1 text-[10px] leading-5 text-[var(--color-text-secondary)]"><MixedLatexRenderer text={block.note} /></p> : null}
                      </div>
                    )) : (
                      <p className="py-6 text-center text-xs text-[var(--color-text-hint)]">暂无公式块</p>
                    )}
                  </div>
                </section>

                {selectedCard.card_type === "function_graph" && selectedCard.graph_asset?.thumbnail_url ? (
                  <section className="rounded-2xl border border-[var(--color-border)] bg-white p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <p className="text-xs font-bold text-[var(--ink)]">函数图像</p>
                      <span className={`rounded-md border px-1.5 py-0.5 text-[10px] ${GRAPH_STATUS_BADGE[selectedCard.graph_status || ""] || "bg-gray-50"}`}>
                        {GRAPH_STATUS_LABEL[selectedCard.graph_status || ""] || selectedCard.graph_status}
                      </span>
                    </div>
                    <img src={selectedCard.graph_asset.thumbnail_url} alt="函数图像" className="max-h-44 w-full rounded-xl border bg-white object-contain" />
                  </section>
                ) : null}

                {selectedCard.conditions ? (
                  <section className="rounded-2xl border border-amber-200 bg-amber-50/55 p-3">
                    <p className="text-xs font-bold text-amber-800">适用条件</p>
                    <div className="mt-1.5 text-xs leading-5 text-amber-900">{renderStructuredConditions(selectedCard.conditions)}</div>
                  </section>
                ) : null}

                {selectedCard.error_tips ? (
                  <section className="rounded-2xl border border-red-200 bg-red-50/45 p-3">
                    <p className="text-xs font-bold text-red-700">易错提醒</p>
                    <div className="mt-1.5 text-xs leading-5 text-red-800">{renderStructuredErrorTips(selectedCard.error_tips)}</div>
                  </section>
                ) : null}

                {selectedCard.status === "rejected" && selectedCard.rejection_reason ? (
                  <section className="rounded-2xl border border-red-200 bg-red-50/45 p-3">
                    <p className="text-xs font-bold text-red-700">驳回原因</p>
                    <p className="mt-1.5 text-xs leading-5 text-red-800">{selectedCard.rejection_reason}</p>
                  </section>
                ) : null}

                {canReview ? (
                  <div className="flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-3">
                    {selectedCard.status === "draft" ? (
                      <Button size="sm" onClick={() => setConfirmAction({ action: "approve", cardId: selectedCard.id, title: selectedCard.title })}>
                        <Send className="h-3.5 w-3.5" /> 提交审核
                      </Button>
                    ) : null}
                    {selectedCard.status === "pending_review" ? (
                      <>
                        <Button variant="primary" size="sm" onClick={() => setConfirmAction({ action: "approve", cardId: selectedCard.id, title: selectedCard.title })}>
                          <CheckCircle className="h-3.5 w-3.5" /> 通过并发布
                        </Button>
                        <Button variant="danger" size="sm" onClick={() => setConfirmAction({ action: "reject", cardId: selectedCard.id, title: selectedCard.title })}>
                          <XCircle className="h-3.5 w-3.5" /> 驳回
                        </Button>
                      </>
                    ) : null}
                    {selectedCard.status === "published" ? (
                      <Button variant="secondary" size="sm" onClick={() => setConfirmAction({ action: "offline", cardId: selectedCard.id, title: selectedCard.title })}>
                        <EyeOff className="h-3.5 w-3.5" /> 下架
                      </Button>
                    ) : null}
                    {selectedCard.status === "rejected" ? (
                      <Button variant="secondary" size="sm" onClick={() => setConfirmAction({ action: "restore", cardId: selectedCard.id, title: selectedCard.title })}>
                        <Send className="h-3.5 w-3.5" /> 重新提交
                      </Button>
                    ) : null}
                    {selectedCard.status === "offline" ? (
                      <Button size="sm" onClick={() => setConfirmAction({ action: "publish", cardId: selectedCard.id, title: selectedCard.title })}>
                        <Eye className="h-3.5 w-3.5" /> 重新发布
                      </Button>
                    ) : null}
                  </div>
                ) : null}

                {canDelete && selectedCard.status !== "published" ? (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => {
                      if (confirm(`确认删除公式「${selectedCard.title}」？`)) deleteMutation.mutate(selectedCard.id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" /> 删除
                  </Button>
                ) : null}
              </div>
            ) : detail.isError && selectedId !== null ? (
              <div className="flex h-full min-h-64 flex-col items-center justify-center gap-3 text-center animate-fade-in">
                <AlertCircle className="h-9 w-9 text-red-400" />
                <p className="text-sm font-semibold text-red-700">详情加载失败</p>
                <Button variant="secondary" size="sm" onClick={() => detail.refetch()}>重新加载</Button>
              </div>
            ) : (
              <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 text-center animate-fade-in">
                <Eye className="h-9 w-9 text-[var(--color-text-hint)]" />
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">选择一条公式查看详情</p>
                <p className="text-xs text-[var(--color-text-hint)]">详情、预览与审核操作将在此处展示</p>
              </div>
            )}
            </div>
          </aside>
        </div>
      </Card>

      {/* ── Floating batch action pill ── */}
      {isBatchable && selectedCount > 0 && (
        <div
          className="fixed bottom-10 z-50 animate-drop-in"
          style={{ left: "calc(50vw + 144px)", transform: "translateX(-50%)" }}
        >
          <div className="flex items-center gap-3 rounded-full border border-[var(--color-border-light)] bg-white/90 pl-5 pr-2 py-2 shadow-xl shadow-black/10 backdrop-blur-xl">
            <CustomCheckbox
              checked={allSelected}
              indeterminate={indeterminate}
              disabled={batchBusy}
              onCheckedChange={toggleSelectAll}
              aria-label="选择当前页"
            />
            <span className="whitespace-nowrap text-sm text-[var(--color-text-secondary)]">
              已选 <strong className="text-[var(--ink)]">{selectedCount}</strong> 项
            </span>
            <div className="flex items-center gap-2 pl-2 border-l border-[var(--color-border-light)]">
              {currentFilterStatus === "pending_review" && (
                <>
                  <Button size="sm" disabled={selectedCount === 0 || batchBusy}
                    onClick={() => setConfirmAction({ action: "batch_approve", cardId: 0, title: "" })}>
                    <Check className="h-3.5 w-3.5" /> 通过
                  </Button>
                  <Button variant="danger" size="sm" disabled={selectedCount === 0 || batchBusy}
                    onClick={() => setConfirmAction({ action: "batch_reject", cardId: 0, title: "" })}>
                    <X className="h-3.5 w-3.5" /> 驳回
                  </Button>
                </>
              )}
              {currentFilterStatus === "draft" && (
                <>
                  <Button size="sm" disabled={selectedCount === 0 || batchBusy}
                    onClick={handleBatchSubmit}>
                    <Send className="h-3.5 w-3.5" /> 提交
                  </Button>
                  <Button variant="danger" size="sm" disabled={selectedCount === 0 || batchBusy}
                    onClick={() => setConfirmAction({ action: "batch_delete", cardId: 0, title: "" })}>
                    <Trash2 className="h-3.5 w-3.5" /> 删除
                  </Button>
                </>
              )}
            </div>
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              className="ml-1 flex h-7 w-7 items-center justify-center rounded-full text-[var(--color-text-hint)] transition-colors hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary)]"
              aria-label="关闭"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* ── Single action confirm dialog ── */}
      <ConfirmDialog
        open={confirmAction !== null && !["batch_approve", "batch_reject", "batch_delete"].includes(confirmAction.action)}
        title={confirmAction?.action === "reject" ? "驳回公式" :
               confirmAction?.action === "approve" ? "通过并发布" :
               confirmAction?.action === "offline" ? "下架公式" : "确认操作"}
        description={
          confirmAction?.action === "reject"
            ? `确认驳回「${confirmAction?.title}」？需要填写驳回原因。`
            : confirmAction?.action === "approve"
            ? `审核通过后「${confirmAction?.title}」将立即发布。`
            : `确认对「${confirmAction?.title}」执行此操作？`
        }
        confirmText={confirmAction?.action === "reject" ? "驳回" :
                     confirmAction?.action === "approve" ? "通过并发布" : "确认"}
        danger={confirmAction?.action === "reject" || confirmAction?.action === "offline"}
        loading={reviewMutation.isPending}
        onCancel={() => { setConfirmAction(null); setReviewReason(""); }}
        onConfirm={submitReview}
      >
        {confirmAction?.action === "reject" && (
          <div className="mt-4">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">驳回原因</label>
            <textarea
              className="mt-1.5 min-h-20 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm
                         placeholder:text-[var(--color-text-hint)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
              placeholder="请填写驳回原因..."
              value={reviewReason}
              onChange={(e) => setReviewReason(e.target.value)}
            />
          </div>
        )}
      </ConfirmDialog>

      {/* ── Batch approve confirm ── */}
      <ConfirmDialog
        open={confirmAction?.action === "batch_approve"}
        title="批量通过并发布"
        description={`所选 ${selectedCount} 条公式审核通过后将立即发布，是否继续？`}
        confirmText="批量通过并发布"
        loading={batchBusy}
        onCancel={() => setConfirmAction(null)}
        onConfirm={handleBatchApprove}
      />

      {/* ── Batch reject confirm ── */}
      <ConfirmDialog
        open={confirmAction?.action === "batch_reject"}
        title="批量驳回"
        description={`为所选 ${selectedCount} 条公式填写驳回原因。`}
        confirmText="批量驳回"
        danger
        loading={batchBusy}
        onCancel={() => { setConfirmAction(null); setReviewReason(""); }}
        onConfirm={() => { const t = reviewReason.trim(); if (!t) return; handleBatchReject(); }}
      >
        <div className="mt-4">
          <label className="text-xs font-semibold text-[var(--color-text-secondary)]">驳回原因 *</label>
          <textarea
            className="mt-1.5 min-h-20 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm
                       placeholder:text-[var(--color-text-hint)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
            placeholder="请填写统一驳回原因..."
            value={reviewReason}
            onChange={(e) => setReviewReason(e.target.value)}
          />
          {reviewReason.trim() === "" && confirmAction?.action === "batch_reject" && (
            <p className="mt-1.5 text-xs text-red-500 flex items-center gap-1">
              <AlertCircle className="h-3 w-3" />驳回原因不能为空
            </p>
          )}
        </div>
      </ConfirmDialog>

      {/* ── Batch delete confirm ── */}
      <ConfirmDialog
        open={confirmAction?.action === "batch_delete"}
        title="批量删除"
        description={`确认删除所选 ${selectedCount} 条草稿公式？此操作不可撤销。`}
        confirmText="批量删除"
        danger
        loading={batchBusy}
        onCancel={() => setConfirmAction(null)}
        onConfirm={handleBatchDelete}
      />
    </div>
  );
}
