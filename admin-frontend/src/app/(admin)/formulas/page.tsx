"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  Sigma,
  Clock,
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
  ImageIcon,
  LayoutTemplate,
  Check,
  X,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { CustomCheckbox } from "@/components/ui/custom-checkbox";
import { LatexRenderer } from "@/components/ui/latex-renderer";
import { MixedLatexRenderer } from "@/components/ui/mixed-latex-renderer";
import { FormulaCategoryPicker } from "@/components/formulas/formula-category-picker";
import { FunctionPropertiesPanel } from "@/components/formulas/function-properties-panel";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { PaginatedResponse, FormulaGraphAsset } from "@/lib/api/types";
import { normalizeLatexExpression } from "@/lib/math-text";
import Link from "next/link";

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
                <LatexRenderer latex={normalizeLatexExpression(expr)} displayMode={false} />
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

export default function FormulasPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);

  const [filters, setFilters] = useState({ status: "", category_id: "", q: "", tags: "", library_type: "", graph_status: "" });
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<{
    action: string; cardId: number; title: string;
  } | null>(null);
  const [reviewReason, setReviewReason] = useState("");

  // ── Batch selection ──
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [pillVisible, setPillVisible] = useState(false);

  const canWrite = hasPermission(permissions, "formula:create");
  const canUpdate = hasPermission(permissions, "formula:update");
  const canReview = hasPermission(permissions, "formula:review");
  const canDelete = hasPermission(permissions, "formula:delete");

  const currentFilterStatus = filters.status;

  // Load list
  const queryParams = useMemo(() => ({
    page, page_size: 20,
    status: currentFilterStatus,
    category_id: filters.category_id,
    q: filters.q,
    library_type: filters.library_type || undefined,
    graph_status: filters.graph_status || undefined,
  }), [page, currentFilterStatus, filters.category_id, filters.q, filters.library_type]);

  const formulas = useQuery({
    queryKey: ["admin-formulas", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<FormulaCard>>(
      `/formulas${toQuery(queryParams)}`,
    ),
    retry: false,
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
      setShowDetail(false);
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

  const items = formulas.data?.items ?? [];
  const selectedCard = detail.data;
  const isBatchable = currentFilterStatus === "pending_review" || currentFilterStatus === "draft";

  // ── Batch selection logic ──
  const safeSelectedIds = useMemo(() => {
    if (!items.length) return selectedIds;
    const valid = new Set(items.map((c) => c.id));
    return new Set([...selectedIds].filter((id) => valid.has(id)));
  }, [items, selectedIds]);

  const allCurrentIds = useMemo(() => items.map((c) => c.id), [items]);
  const allSelected = items.length > 0 && safeSelectedIds.size === items.length;
  const indeterminate = safeSelectedIds.size > 0 && !allSelected;
  const selectedCount = safeSelectedIds.size;

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

  // ── Auto-hide floating pill after 5min idle; re-show on scroll ──
  const pillTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resetPillTimer = useCallback(() => {
    if (pillTimerRef.current) clearTimeout(pillTimerRef.current);
    setPillVisible(true);
    pillTimerRef.current = setTimeout(() => {
      setPillVisible(false);
    }, 5000);
  }, []);

  useEffect(() => {
    if (isBatchable && items.length > 0) {
      resetPillTimer();
    }
  }, [isBatchable, items.length, resetPillTimer]);

  useEffect(() => {
    if (!(isBatchable && items.length > 0)) return;
    const reShow = () => {
      if (pillTimerRef.current) clearTimeout(pillTimerRef.current);
      setPillVisible(true);
      pillTimerRef.current = setTimeout(() => setPillVisible(false), 5000);
    };
    window.addEventListener("wheel", reShow, { passive: true });
    window.addEventListener("touchmove", reShow, { passive: true });
    window.addEventListener("click", reShow, { passive: true });
    return () => {
      window.removeEventListener("wheel", reShow);
      window.removeEventListener("touchmove", reShow);
      window.removeEventListener("click", reShow);
    };
  }, [isBatchable, items.length]);

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

  return (
    <div className="space-y-6 pb-24">
      {/* ── Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-display text-[28px] font-bold leading-tight tracking-tight text-[var(--ink)]"
              style={{ fontVariationSettings: "'wght' 700" }}>
            公式库管理
          </h1>
          <p className="mt-1.5 text-sm leading-relaxed text-[var(--color-text-secondary)]">
            {canReview
              ? "管理公式卡片，审核通过后将自动发布"
              : "管理公式卡片、查看详情"
            }
          </p>
        </div>
        {canWrite && (
          <Link href="/formulas/new">
            <Button variant="primary" size="md">
              <Plus className="h-4 w-4" />
              新建公式
            </Button>
          </Link>
        )}
      </div>

      {/* ── Filters ── */}
      <Card>
        <CardHeader className="!border-0">
          <div className="rounded-2xl border border-[var(--color-border)] bg-white/65 p-3 shadow-sm">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(200px,1fr)_180px_160px_220px_160px_auto]">
              <label className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
                <Input
                  className="pl-9"
                  placeholder="搜索标题 / 别名"
                  value={filters.q}
                  onChange={(e) => updateFilter("q", e.target.value)}
                />
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
                onChange={(v) => { setPage(1); updateFilter("library_type", v); }}
                options={LIBRARY_TYPE_OPTIONS}
                placeholder="全部分类"
                clearable={false}
              />
              <FormulaCategoryPicker
                mode="filter"
                value={filters.category_id ? parseInt(filters.category_id) : null}
                onChange={(v) => updateFilter("category_id", v ? String(v) : "")}
                placeholder="全部分类"
              />
              <CustomSelect
                value={filters.graph_status}
                onChange={(v) => { setPage(1); setFilters((f) => ({ ...f, graph_status: v })); }}
                options={GRAPH_STATUS_OPTIONS}
                placeholder="图像状态"
                clearable={false}
              />
              <Link href="/formulas/new" className="shrink-0">
                <Button variant="secondary" className="w-full whitespace-nowrap">
                  <Sigma className="h-4 w-4 shrink-0" />
                  快速新建
                </Button>
              </Link>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* ── Floating toast notification ── */}
          {message && (
            <div className="fixed right-6 top-24 z-50 animate-fade-in">
              <div className="flex items-center gap-3 rounded-full border border-[var(--color-success)]/30 bg-white/90 pl-5 pr-2 py-2 shadow-lg shadow-black/8 backdrop-blur-xl">
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

          {/* ── Loading ── */}
          {formulas.isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="h-28 animate-pulse rounded-[1.6rem] border bg-white/60" />
              ))}
            </div>
          ) : null}

          {/* ── Card list ── */}
          <div className="space-y-3">
            {items.map((card) => {
              const isSelected = selectedId === card.id;
              const tagCodes = card.tags?.map((t) => t.name).join(", ") || "";
              return (
                <article
                  key={card.id}
                  className={`group relative overflow-hidden rounded-[1.6rem] border bg-white/78 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
                    isSelected ? "border-[var(--color-primary)] ring-4 ring-[var(--color-primary-light)]" : "border-[var(--color-border)]"
                  }`}
                >
                  <span className="absolute left-0 top-0 h-full w-1 bg-[var(--color-primary)]" />
                  <div className="flex items-start gap-4 p-4 pl-5">
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => { setSelectedId(card.id); setShowDetail(true); }}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedId(card.id); setShowDetail(true); } }}
                      className="min-w-0 flex-1 text-left cursor-pointer"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        {isBatchable && (
                          <CustomCheckbox
                            checked={safeSelectedIds.has(card.id)}
                            disabled={batchBusy}
                            onCheckedChange={() => toggleSelect(card.id)}
                            aria-label={`选择公式「${card.title}」`}
                            onClick={(e: MouseEvent<HTMLButtonElement>) => e.stopPropagation()}
                          />
                        )}
                        <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${STATUS_BADGE[card.status] || "bg-gray-50"}`}>
                          {STATUS_LABEL[card.status] || card.status}
                        </span>
                        {card.is_function_graph && (
                          <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-primary-light)] bg-[var(--color-primary-light)]/50 px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-primary-dark)]">
                            函数图像
                          </span>
                        )}
                        {card.graph_status && card.graph_status !== "not_applicable" && (
                          <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${GRAPH_STATUS_BADGE[card.graph_status] || "bg-gray-50"}`}>
                            {GRAPH_STATUS_LABEL[card.graph_status] || card.graph_status}
                          </span>
                        )}
                        {tagCodes && (
                          <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-white/80 px-1.5 py-0.5 text-[11px] text-[var(--color-text-secondary)]">
                            <Tag className="h-3 w-3" />
                            {tagCodes}
                          </span>
                        )}
                      </div>
                      <h4 className="mt-2 font-semibold text-[var(--ink)]"><MixedLatexRenderer text={card.title} /></h4>
                      {card.summary && (
                        <p className="mt-1 line-clamp-2 text-sm text-[var(--color-text-secondary)]">
                          <MixedLatexRenderer text={card.summary} />
                        </p>
                      )}
                      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-text-hint)]">
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" />#{card.id}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <Layers className="h-3 w-3" />
                          {card.formula_blocks?.length || 0} 个公式块
                        </span>
                        <span className="inline-flex items-center gap-1">
                          v{card.version}
                        </span>
                      </div>
                    </div>

                    <div className="flex shrink-0 flex-col gap-2">
                      {card.card_type === "function_graph" && card.graph_asset?.thumbnail_url && (
                        <div className="flex items-center justify-center">
                          <img
                            src={card.graph_asset.thumbnail_url}
                            alt=""
                            className="h-12 w-20 rounded border object-cover"
                          />
                        </div>
                      )}
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => { setSelectedId(card.id); setShowDetail(true); }}
                      >
                        <Eye className="h-3.5 w-3.5" />
                        详情
                      </Button>
                      {card.card_type === "function_graph" && (
                        <>
                          <Link href={`/formulas/${card.id}`}>
                            <Button variant="secondary" size="sm" className="w-full">
                              <LayoutTemplate className="h-3.5 w-3.5" />
                              {card.graph_status === "unconfigured" || card.graph_status === "missing"
                                ? "配置并生成"
                                : card.graph_status === "draft"
                                ? "查看预览"
                                : card.graph_status === "failed"
                                ? "重新生成"
                                : "配置图像"}
                            </Button>
                          </Link>
                          <Link href={`/formulas/${card.id}#graph-assets`}>
                            <Button variant="secondary" size="sm" className="w-full">
                              <ImageIcon className="h-3.5 w-3.5" />
                              图像管理
                            </Button>
                          </Link>
                        </>
                      )}
                    </div>
                  </div>
                </article>
              );
            })}

            {!formulas.isLoading && items.length === 0 ? (
              <div className="flex flex-col items-center gap-3 rounded-[1.6rem] border border-dashed border-[var(--color-border)] bg-white/60 py-16 text-center">
                <Sigma className="h-12 w-12 text-[var(--color-text-hint)]" />
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">暂无公式</p>
                <p className="text-xs text-[var(--color-text-hint)]">尝试调整筛选条件或新建公式卡片</p>
              </div>
            ) : null}
          </div>

          {/* ── Pagination ── */}
          {formulas.data && formulas.data.total_pages > 1 ? (
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border bg-white/80 px-5 py-3 shadow-sm">
              <span className="text-sm text-[var(--color-text-secondary)]">
                <span className="font-semibold text-[var(--ink)]">{formulas.data.total}</span> 条公式
                <span className="mx-2">/</span>第 <span className="font-semibold">{formulas.data.page}</span> / {formulas.data.total_pages} 页
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-border-light)] bg-white/80 text-sm
                             transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-primary)]
                             disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                {Array.from({ length: Math.min(formulas.data.total_pages, 5) }, (_, i) => {
                  const start = Math.max(1, Math.min(page - 2, formulas.data.total_pages - 4));
                  const p = start + i;
                  if (p > formulas.data.total_pages) return null;
                  return (
                    <button
                      key={p}
                      disabled={p === page}
                      onClick={() => setPage(p)}
                      className={`inline-flex h-9 w-9 items-center justify-center rounded-xl border text-sm font-bold shadow-sm ${
                        p === page ? "bg-[var(--color-primary)] text-white" : "bg-white/80 text-[var(--color-text-secondary)]"
                      }`}
                    >
                      {p}
                    </button>
                  );
                })}
                <button
                  disabled={page >= (formulas.data?.total_pages ?? 1)}
                  onClick={() => setPage((p) => p + 1)}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-border-light)] bg-white/80 text-sm
                             transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-primary)]
                             disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ── Floating batch action pill ── */}
      {isBatchable && items.length > 0 && !showDetail && (
        <div
          className={`fixed bottom-10 z-50 transition-all duration-400 ease-out ${
            pillVisible
              ? "translate-y-0 opacity-100"
              : "translate-y-4 opacity-0 pointer-events-none"
          }`}
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
              onClick={() => { setSelectedIds(new Set()); setPillVisible(false); }}
              className="ml-1 flex h-7 w-7 items-center justify-center rounded-full text-[var(--color-text-hint)] transition-colors hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary)]"
              aria-label="关闭"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* ── Detail drawer ── */}
      {showDetail && selectedId !== null ? (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.42)] backdrop-blur-[2px]"
          onClick={() => setShowDetail(false)}
        >
          <aside
            className="h-full w-full max-w-3xl overflow-y-auto bg-white p-6 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">
                公式详情
                <span className="ml-2 font-mono text-base text-[var(--color-text-hint)]">#{selectedId}</span>
              </h3>
              <div className="flex items-center gap-2">
                {canUpdate && (
                  <Link href={`/formulas/${selectedId}`}>
                    <Button variant="secondary">
                      <ExternalLink className="h-4 w-4" />
                      编辑
                    </Button>
                  </Link>
                )}
                <Button variant="ghost" onClick={() => setShowDetail(false)}>关闭</Button>
              </div>
            </div>

            {selectedCard ? (
              <div className="mt-6 space-y-5 text-sm">
                {/* Status + Tags */}
                <div className="flex flex-wrap items-center gap-3">
                  <span className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold ${STATUS_BADGE[selectedCard.status] || ""}`}>
                    {STATUS_LABEL[selectedCard.status] || selectedCard.status}
                  </span>
                  {selectedCard.tags?.map((t) => (
                    <span key={t.id} className="inline-flex items-center rounded-lg border border-[var(--color-border)] bg-white/60 px-2 py-1 text-[11px] text-[var(--color-text-secondary)]">
                      <Tag className="mr-1 h-3 w-3" />
                      {t.name}
                    </span>
                  ))}
                  <span className="text-xs text-[var(--color-text-hint)]">v{selectedCard.version}</span>
                </div>

                {/* Title */}
                <section className="rounded-[1.6rem] border border-[var(--color-primary-light)] bg-[var(--porcelain)] p-5">
                  <h4 className="font-display text-xl font-bold text-[var(--ink)]"><MixedLatexRenderer text={selectedCard.title} /></h4>
                  {selectedCard.summary && (
                    <p className="mt-2 text-sm leading-6 text-[var(--color-text-secondary)]"><MixedLatexRenderer text={selectedCard.summary} /></p>
                  )}
                </section>

                {/* Formula blocks */}
                <section className="rounded-[1.6rem] border border-[var(--color-border)] bg-white/80 p-5">
                  <p className="font-semibold text-[var(--ink)]">公式块</p>
                  <div className="mt-3 space-y-4">
                    {selectedCard.formula_blocks?.map((block, i) => (
                      <div key={i} className="rounded-xl border border-[var(--color-border)] bg-white p-4">
                        {block.label && <p className="mb-1 text-xs font-semibold text-[var(--color-text-hint)]">{block.label}</p>}
                        <LatexRenderer latex={normalizeLatexExpression(block.latex)} displayMode={true} />
                        {block.note && <p className="mt-1 text-xs leading-6 text-[var(--color-text-secondary)]"><MixedLatexRenderer text={block.note} /></p>}
                      </div>
                    ))}
                  </div>
                </section>

                {/* Function graph asset preview */}
                {selectedCard.card_type === "function_graph" && selectedCard.graph_asset?.thumbnail_url && (
                  <section className="rounded-[1.6rem] border border-[var(--color-border)] bg-white/80 overflow-hidden">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
                      <span className="text-sm font-semibold text-[var(--ink)]">函数图像</span>
                      {selectedCard.graph_asset?.image_url && (
                        <Button variant="ghost" size="sm" onClick={() => selectedCard.graph_asset?.image_url && window.open(selectedCard.graph_asset.image_url, "_blank")}>
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                    <div className="p-4">
                      <img
                        src={selectedCard.graph_asset.thumbnail_url}
                        alt="函数图像"
                        className="w-full h-auto max-h-60 object-contain rounded-lg border bg-white"
                      />
                    </div>
                  </section>
                )}

                {/* Function properties */}
                {selectedCard.card_type === "function_graph" && selectedCard.function_properties && (
                  <FunctionPropertiesPanel properties={selectedCard.function_properties} />
                )}

                {/* Conditions & Error Tips */}
                {selectedCard.conditions && (
                  <section className="rounded-[1.6rem] border border-amber-200 bg-amber-50/60 p-4">
                    <p className="font-semibold text-amber-800">适用条件</p>
                    <div className="mt-2 text-sm text-amber-900 whitespace-pre-wrap break-words max-w-full overflow-x-auto">
                      {renderStructuredConditions(selectedCard.conditions)}
                    </div>
                  </section>
                )}
                {selectedCard.error_tips && (
                  <section className="rounded-[1.6rem] border border-red-200 bg-red-50/60 p-4">
                    <p className="font-semibold text-red-700">易错提醒</p>
                    <div className="mt-2 text-sm leading-6 text-red-800 whitespace-pre-wrap break-words max-w-full overflow-x-auto">
                      {renderStructuredErrorTips(selectedCard.error_tips)}
                    </div>
                  </section>
                )}

                {/* Rejection reason */}
                {selectedCard.status === "rejected" && selectedCard.rejection_reason && (
                  <section className="rounded-[1.6rem] border border-red-200 bg-red-50/50 p-4">
                    <p className="font-semibold text-red-700">驳回原因</p>
                    <p className="mt-2 text-sm text-red-800">{selectedCard.rejection_reason}</p>
                  </section>
                )}

                {/* State machine actions */}
                {canReview && (
                  <div className="flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-4">
                    {selectedCard.status === "draft" && (
                      <Button onClick={() => setConfirmAction({ action: "approve", cardId: selectedCard.id, title: selectedCard.title })}>
                        <Send className="h-4 w-4" />
                        提交审核
                      </Button>
                    )}
                    {selectedCard.status === "pending_review" && (
                      <>
                        <Button variant="primary" onClick={() => setConfirmAction({ action: "approve", cardId: selectedCard.id, title: selectedCard.title })}>
                          <CheckCircle className="h-4 w-4" />
                          通过并发布
                        </Button>
                        <Button variant="danger" onClick={() => setConfirmAction({ action: "reject", cardId: selectedCard.id, title: selectedCard.title })}>
                          <XCircle className="h-4 w-4" />
                          驳回
                        </Button>
                      </>
                    )}
                    {selectedCard.status === "published" && (
                      <Button variant="secondary" onClick={() => setConfirmAction({ action: "offline", cardId: selectedCard.id, title: selectedCard.title })}>
                        <EyeOff className="h-4 w-4" />
                        下架
                      </Button>
                    )}
                    {selectedCard.status === "rejected" && (
                      <Button variant="secondary" onClick={() => setConfirmAction({ action: "restore", cardId: selectedCard.id, title: selectedCard.title })}>
                        <Send className="h-4 w-4" />
                        重新提交
                      </Button>
                    )}
                    {selectedCard.status === "offline" && (
                      <Button onClick={() => setConfirmAction({ action: "publish", cardId: selectedCard.id, title: selectedCard.title })}>
                        <Eye className="h-4 w-4" />
                        重新发布
                      </Button>
                    )}
                  </div>
                )}

                {/* Delete */}
                {canDelete && selectedCard.status !== "published" && (
                  <div className="flex gap-2 border-t border-[var(--color-border)] pt-4">
                    <Button variant="danger" onClick={() => {
                      if (confirm(`确认删除公式「${selectedCard.title}」？`)) {
                        deleteMutation.mutate(selectedCard.id);
                      }
                    }}>
                      <Trash2 className="h-4 w-4" />
                      删除
                    </Button>
                  </div>
                )}
              </div>
            ) : (
              <p className="mt-6 text-sm text-[var(--color-text-secondary)]">加载中...</p>
            )}
          </aside>
        </div>
      ) : null}

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
