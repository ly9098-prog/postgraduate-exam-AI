"use client";

import { useMemo, useState, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  FileQuestion,
  Search,
  ChevronRight,
  BookOpen,
  BarChart3,
  Tag,
  Hash,
  Layers,
  Clock,
  Pencil,
  Trash2,
  Save,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { MathFormula } from "@/components/ui/math-formula";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest, toQuery } from "@/lib/api/client";
import type {
  AdminQuestion,
  AdminQuestionDetail,
  AdminQuestionImportSummary,
  BatchResult,
  PaginatedResponse,
  QuestionEditRequest,
  QuestionVersion,
  QuestionVersionDetail,
} from "@/lib/api/types";

const reviewStatuses = ["", "pending", "re_pending", "approved", "rejected"];
const activeOptions = [
  { label: "全部状态", value: "" },
  { label: "启用", value: "true" },
  { label: "停用", value: "false" },
];

type ConfirmState =
  | { action: "single-approve"; id: number }
  | { action: "batch-approve" | "batch-delete" }
  | { action: "delete"; id: number }
  | null;

function textFromContent(content: Record<string, unknown> | string | null | undefined) {
  if (!content) return "";
  if (typeof content === "string") return content;
  const candidate = content.stem ?? content.text ?? content.question ?? content.title;
  if (typeof candidate === "string") return candidate;
  return JSON.stringify(content, null, 2);
}

function renderJson(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function renderDiff(label: string, current: unknown, previous: unknown) {
  const cur = renderJson(current);
  const prev = renderJson(previous);
  const changed = cur !== prev;
  return (
    <section key={label} className="space-y-1">
      <p className="font-semibold text-[var(--ink)]">{label}</p>
      {changed ? (
        <div className="space-y-1 rounded-2xl border border-[var(--color-warning)] bg-[var(--color-warning-light)] p-3">
          <p className="text-xs font-semibold text-[var(--color-warning)]">变更前</p>
          <pre className="whitespace-pre-wrap text-xs text-[var(--color-text-secondary)] line-through">{prev}</pre>
          <p className="text-xs font-semibold text-[var(--color-success)]">变更后</p>
          <pre className="whitespace-pre-wrap text-xs text-[var(--color-success)]">{cur}</pre>
        </div>
      ) : (
        <pre className="whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-xs text-[var(--color-text-secondary)]">{cur}</pre>
      )}
    </section>
  );
}

function statusTone(status: string) {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  if (status === "re_pending") return "warning";
  return "primary";
}

function duplicateStatusTone(status: string | null | undefined) {
  if (status === "possible_duplicate") return "warning";
  if (status === "normal") return "success";
  return "neutral";
}

function renderDuplicateInfo(importRecord: AdminQuestionImportSummary | null | undefined) {
  if (!importRecord) return null;
  const status = importRecord.duplicate_status || "normal";
  const isSuspicious = status === "possible_duplicate";
  return (
    <section className="blueprint-panel relative overflow-hidden rounded-3xl border border-[rgba(196,154,107,0.42)] bg-[var(--color-warning-light)] shadow-[var(--shadow-crisp)]">
      <span className="absolute left-0 top-0 h-full w-1 bg-[var(--color-warning)]" aria-hidden="true" />
      <div className="relative z-10">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[rgba(196,154,107,0.28)] bg-white/55 px-4 py-3 backdrop-blur-sm">
          <div className="min-w-0">
            <p className="font-mono text-[10px] uppercase tracking-[0.32em] text-[var(--color-text-hint)]">Duplicate scan</p>
            <p className="mt-1 font-display text-lg font-bold text-[var(--ink)]">重复检测</p>
          </div>
          <StatusBadge tone={duplicateStatusTone(status)}>{status}</StatusBadge>
        </div>
        <div className="space-y-3 px-4 py-4">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl border border-[rgba(91,123,154,0.18)] bg-[rgba(255,253,248,0.72)] p-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--color-text-hint)]">题目 hash</p>
              <p className="mt-1 break-all font-mono text-xs text-[var(--ink)]">{importRecord.question_hash || "—"}</p>
            </div>
            <div className="rounded-2xl border border-[rgba(91,123,154,0.18)] bg-[rgba(255,253,248,0.72)] p-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--color-text-hint)]">重复正式题</p>
              <p className="mt-1 font-mono text-xs text-[var(--ink)]">{importRecord.duplicate_of_question_id ? `#${importRecord.duplicate_of_question_id}` : "—"}</p>
            </div>
            <div className="rounded-2xl border border-[rgba(91,123,154,0.18)] bg-[rgba(255,253,248,0.72)] p-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--color-text-hint)]">重复导入项</p>
              <p className="mt-1 font-mono text-xs text-[var(--ink)]">{importRecord.duplicate_of_import_id ? `#${importRecord.duplicate_of_import_id}` : "—"}</p>
            </div>
          </div>
          <p className="rounded-2xl border border-[rgba(91,123,154,0.14)] bg-white/55 px-3 py-2 text-xs text-[var(--color-text-secondary)]">
            {isSuspicious ? "需要人工核对来源关系" : "未发现重复关联"}
          </p>
        </div>
      </div>
    </section>
  );
}

/** Difficulty pill */
function DifficultyBadge({ difficulty }: { difficulty: number | string | null | undefined }) {
  const d = Number(difficulty) || 0;
  const colors = [
    "bg-emerald-50 text-emerald-700 border-emerald-200",
    "bg-green-50 text-green-700 border-green-200",
    "bg-amber-50 text-amber-700 border-amber-200",
    "bg-orange-50 text-orange-700 border-orange-200",
    "bg-red-50 text-red-700 border-red-200",
  ];
  const idx = Math.min(Math.max(Math.round(d) - 1, 0), colors.length - 1);
  const label = ["简单", "较易", "中等", "较难", "困难"];
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${colors[idx]}`}>
      <BarChart3 className="h-3 w-3" />
      {label[idx] ?? d}
    </span>
  );
}

/** Type badge */
const TYPE_LABELS: Record<string, string> = {
  single_choice: "单选题",
  multiple_choice: "多选题",
  true_false: "判断题",
  fill_blank: "填空题",
  multi_blank_choice: "多空选择",
  subjective: "问答题",
};

function TypeBadge({ type: t }: { type: string | null | undefined }) {
  const label = TYPE_LABELS[t ?? ""] ?? t ?? "未知";
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-white/80 px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-text-secondary)]">
      <Layers className="h-3 w-3" />
      {label}
    </span>
  );
}

export default function QuestionsPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const [filters, setFilters] = useState({ subject: "", review_status: "", is_active: "", question_type: "", keyword: "", year: "" });
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [page, setPage] = useState(1);
  const [selectedQuestionId, setSelectedQuestionId] = useState<number | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<QuestionEditRequest>({});

  const canWrite = hasPermission(permissions, "question:write");
  const canDelete = hasPermission(permissions, "question:delete");

  const queryParams = useMemo(
    () => ({
      page,
      page_size: 20,
      subject: filters.subject,
      review_status: filters.review_status,
      is_active: filters.is_active,
      question_type: filters.question_type,
      keyword: filters.keyword,
      year: filters.year,
    }),
    [page, filters],
  );

  const questions = useQuery({
    queryKey: ["questions", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<AdminQuestion>>(`/questions${toQuery(queryParams)}`),
    retry: false,
  });

  const detail = useQuery({
    queryKey: ["questions", selectedQuestionId, "detail"],
    queryFn: () => apiRequest<AdminQuestionDetail>(`/questions/${selectedQuestionId}`),
    enabled: selectedQuestionId !== null,
    retry: false,
  });

  const versions = useQuery({
    queryKey: ["questions", selectedQuestionId, "versions"],
    queryFn: () => apiRequest<PaginatedResponse<QuestionVersion>>(`/questions/${selectedQuestionId}/versions${toQuery({ page: 1, page_size: 20 })}`),
    enabled: selectedQuestionId !== null,
    retry: false,
  });

  const versionDetail = useQuery({
    queryKey: ["questions", selectedQuestionId, "versions", selectedVersion],
    queryFn: () => apiRequest<QuestionVersionDetail>(`/questions/${selectedQuestionId}/versions/${selectedVersion}`),
    enabled: selectedQuestionId !== null && selectedVersion !== null,
    retry: false,
  });

  const reviewMutation = useMutation({
    mutationFn: async (state: Exclude<ConfirmState, null>) => {
      if (state.action === "single-approve") return apiRequest<AdminQuestion>(`/questions/${state.id}/approve`, { method: "POST" });
      if (state.action === "batch-approve") return apiRequest<BatchResult>("/questions/batch-approve", { method: "POST", body: JSON.stringify({ ids: Array.from(selectedIds) }) });
      if (state.action === "batch-delete") return apiRequest<BatchResult>("/questions/batch-delete", { method: "POST", body: JSON.stringify({ ids: Array.from(selectedIds) }) });
      if (state.action === "delete") return apiRequest<{ status: string }>(`/questions/${state.id}`, { method: "DELETE" });
      throw new Error("未知操作");
    },
    onSuccess: (result, variables: Exclude<ConfirmState, null>) => {
      if (variables.action === "delete") {
        setMessage(`题目 #${variables.id} 已删除。`);
        setSelectedQuestionId(null);
      } else if ("id" in result) {
        setMessage(`操作成功，题目 #${result.id} 已处理。`);
      } else {
        const r = result as BatchResult;
        const successIds = r.success_ids ?? r.successIds ?? [];
        const failedItems = r.failed_items ?? r.failedItems ?? [];
        const failures = failedItems.length
          ? `失败 ${failedItems.length} 条：${failedItems.map((item) => `#${item.id} ${item.error}`).join("；")}`
          : "无失败项";
        setMessage(`批量操作完成，成功 ${successIds.length} 条，${failures}。`);
      }
      setSelectedIds(new Set());
      setConfirmState(null);
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
    },
  });

  const updateMutation = useMutation({
    mutationFn: async () => {
      if (!selectedQuestionId) throw new Error("未选中题目");
      return apiRequest<AdminQuestion>(`/questions/${selectedQuestionId}`, {
        method: "PATCH",
        body: JSON.stringify(editForm),
      });
    },
    onSuccess: () => {
      setMessage("题目已更新。");
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["questions"] });
      queryClient.invalidateQueries({ queryKey: ["questions", selectedQuestionId] });
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "更新失败，请稍后重试。");
    },
  });

  const items = questions.data?.items ?? [];
  const allChecked = items.length > 0 && items.every((item) => selectedIds.has(item.id));
  const selectedQuestion = detail.data;

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };

  const toggleAll = () => {
    setSelectedIds(() => {
      if (allChecked) return new Set();
      return new Set(items.map((item) => item.id));
    });
  };

  const toggleOne = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openDetail = (id: number) => {
    setSelectedQuestionId(id);
    setSelectedVersion(null);
    setEditing(false);
    setEditForm({});
  };

  const startEditing = () => {
    if (!selectedQuestion) return;
    // Pre-fill form from current question data
    const content = selectedQuestion.content;
    const stem = textFromContent(content);
    setEditForm({
      subject: selectedQuestion.subject || "",
      question_type: selectedQuestion.question_type || "",
      difficulty: selectedQuestion.difficulty,
      answer: selectedQuestion.answer || "",
      analysis: selectedQuestion.analysis || "",
      options: selectedQuestion.options ?? undefined,
      content: { ...content, stem },
      knowledge_points: selectedQuestion.knowledge_points ?? undefined,
    });
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
    setEditForm({});
  };

  const confirmDescription = (() => {
    if (confirmState?.action === "delete" || confirmState?.action === "batch-delete") return "删除后题目将从题库永久移除，此操作不可撤销。";
    return "确认后将提交审核通过操作。";
  })();

  const countByStatus = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of items) {
      const s = item.review_status || "pending";
      counts[s] = (counts[s] || 0) + 1;
    }
    return counts;
  }, [items]);

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">Questions</p>
        <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">题目管理</h2>
      </div>

      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">题目列表</h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">题库中全部正式题目，支持筛选、批量审核、详情查看。</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" disabled={selectedIds.size === 0} onClick={() => setConfirmState({ action: "batch-approve" })}>
                <CheckCircle2 className="h-4 w-4" />
                批量通过
              </Button>
              {canDelete && (
                <Button variant="danger" disabled={selectedIds.size === 0} onClick={() => setConfirmState({ action: "batch-delete" })}>
                  <Trash2 className="h-4 w-4" />
                  批量删除
                </Button>
              )}
            </div>
          </div>

          {/* Search + filters */}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <label className="relative xl:col-span-2">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input className="pl-9" placeholder="搜索题干 / 科目" value={filters.keyword} onChange={(event) => updateFilter("keyword", event.target.value)} />
            </label>
            <Input placeholder="科目" value={filters.subject} onChange={(event) => updateFilter("subject", event.target.value)} />
            <Input placeholder="题型" value={filters.question_type} onChange={(event) => updateFilter("question_type", event.target.value)} />
            <Input placeholder="年份" value={filters.year} onChange={(event) => updateFilter("year", event.target.value)} />
            <select className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={filters.review_status} onChange={(event) => updateFilter("review_status", event.target.value)}>
              {reviewStatuses.map((status) => (
                <option key={status || "all"} value={status}>{status || "全部审核"}</option>
              ))}
            </select>
            <select className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={filters.is_active} onChange={(event) => updateFilter("is_active", event.target.value)}>
              {activeOptions.map((option) => (
                <option key={option.value || "all"} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {message ? (
            <div role="status" aria-live="polite" className="fixed right-6 top-6 z-[60] max-w-sm rounded-2xl border border-[var(--color-success)] bg-white px-5 py-4 text-sm font-medium text-[var(--ink)] shadow-[var(--shadow-floating)]">
              {message}
            </div>
          ) : null}

          {/* Stats bar */}
          {items.length > 0 ? (
            <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-white/60 px-4 py-2.5 text-xs text-[var(--color-text-secondary)]">
              <span className="flex items-center gap-1.5 font-medium text-[var(--ink)]">
                <Hash className="h-3.5 w-3.5" />
                共 {items.length} 题
              </span>
              {Object.entries(countByStatus).map(([status, count]) => (
                <StatusBadge key={status} tone={statusTone(status)}>
                  {status} {count}
                </StatusBadge>
              ))}
            </div>
          ) : null}

          {/* Select all */}
          <label className="inline-flex items-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-2.5 text-sm text-[var(--color-text-secondary)] transition hover:bg-white">
            <input type="checkbox" checked={allChecked} onChange={toggleAll} className="h-4 w-4 rounded border-[var(--color-border)] text-[var(--color-primary)]" />
            <span className="font-medium">选择当前页全部题目</span>
            {selectedIds.size > 0 && (
              <span className="ml-1 rounded-md bg-[var(--color-primary-light)] px-2 py-0.5 text-[11px] font-semibold text-[var(--color-primary-dark)]">
                已选 {selectedIds.size}
              </span>
            )}
          </label>

          {/* Question list */}
          {items.map((question) => {
            const stemText = textFromContent(question.content) || `题目 #${question.id}`;
            return (
              <div
                key={question.id}
                className="group relative rounded-2xl border border-[var(--color-border)] bg-white/70 transition hover:border-[var(--color-primary-light)] hover:bg-white hover:shadow-sm"
              >
                <div className="flex items-start gap-3 p-4">
                  {/* Checkbox */}
                  <div className="flex shrink-0 items-center pt-1">
                    <input type="checkbox" checked={selectedIds.has(question.id)} onChange={() => toggleOne(question.id)} className="h-4 w-4 rounded border-[var(--color-border)] text-[var(--color-primary)]" />
                  </div>

                  {/* Content */}
                  <div className="min-w-0 flex-1 space-y-2.5">
                    {/* Badge row */}
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge tone={statusTone(question.review_status)}>{question.review_status || "pending"}</StatusBadge>
                      {question.is_active ? (
                        <span className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700">
                          启用
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-white/80 px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-text-hint)]">
                          停用
                        </span>
                      )}
                      {question.subject && (
                        <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-primary-light)] px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-primary-dark)]">
                          <BookOpen className="h-3 w-3" />
                          {question.subject}
                        </span>
                      )}
                      <TypeBadge type={question.question_type} />
                      <DifficultyBadge difficulty={question.difficulty} />
                    </div>

                    {/* Stem */}
                    <div className="whitespace-pre-wrap leading-relaxed text-[var(--ink)]">
                      <MathFormula text={stemText} />
                    </div>

                    {/* Footer metadata */}
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-text-hint)]">
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        #{question.id}
                      </span>
                      {question.year && (
                        <span className="inline-flex items-center gap-1">
                          <Tag className="h-3 w-3" />
                          {question.year}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex shrink-0 items-start gap-2 opacity-60 transition group-hover:opacity-100">
                    <Button variant="secondary" onClick={() => openDetail(question.id)} className="h-9 gap-1.5 px-3 text-xs font-medium">
                      <FileQuestion className="h-4 w-4" />
                      详情
                      <ChevronRight className="h-3 w-3" />
                    </Button>
                    <Button variant="secondary" onClick={() => setConfirmState({ action: "single-approve", id: question.id })} className="h-9 px-3 text-xs font-medium">
                      通过
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}

          {!questions.isLoading && items.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <FileQuestion className="h-12 w-12 text-[var(--color-text-hint)]" />
              <p className="text-sm text-[var(--color-text-hint)]">暂无题目</p>
              <p className="text-xs text-[var(--color-text-hint)]">尝试调整筛选条件</p>
            </div>
          ) : null}

          {questions.isError ? (
            <div className="rounded-2xl border border-[var(--color-danger-light)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
              题目接口当前不可用，若 router 未挂载则属于后端阻塞。
            </div>
          ) : null}

          {/* Pagination */}
          {questions.data && questions.data.total_pages > 1 ? (
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[var(--blueprint-line)] bg-white/80 px-5 py-3 shadow-[var(--shadow-crisp)]">
              <span className="font-display text-sm tracking-wide text-[var(--color-text-secondary)]">
                <span className="font-semibold text-[var(--ink)]">{questions.data.total}</span> 道题目
                <span className="mx-2 text-[var(--color-text-hint)]">/</span>
                <span className="text-[var(--color-text-hint)]">第 </span>
                <span className="font-semibold text-[var(--ink)]">{questions.data.page}</span>
                <span className="text-[var(--color-text-hint)]"> / {questions.data.total_pages} 页</span>
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="inline-flex h-9 items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
                  上一页
                </button>
                {Array.from({ length: Math.min(questions.data.total_pages, 5) }, (_, i) => {
                  const start = Math.max(1, Math.min(page - 2, questions.data.total_pages - 4));
                  const p = start + i;
                  if (p > questions.data.total_pages) return null;
                  const isActive = p === page;
                  return (
                    <button
                      key={p}
                      disabled={isActive}
                      onClick={() => setPage(p)}
                      className={
                        isActive
                          ? "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-primary-dark)] bg-[var(--color-primary)] text-sm font-bold text-white shadow-[var(--shadow-crisp)]"
                          : "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-white/80 text-sm font-medium text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]"
                      }
                    >
                      {p}
                    </button>
                  );
                })}
                <button
                  disabled={page >= (questions.data?.total_pages ?? 1)}
                  onClick={() => setPage((p) => p + 1)}
                  className="inline-flex h-9 items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                >
                  下一页
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
                </button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* Detail drawer */}
      {selectedQuestionId !== null ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.28)]" onClick={() => setSelectedQuestionId(null)}>
          <aside className="h-full w-full max-w-3xl overflow-y-auto bg-white p-6 shadow-[var(--shadow-floating)]" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">
                {editing ? "编辑题目" : "题目详情"}
                {!editing && <span className="ml-2 font-mono text-base text-[var(--color-text-hint)]">#{selectedQuestionId}</span>}
              </h3>
              <div className="flex items-center gap-2">
                {!editing && canWrite && (
                  <Button variant="secondary" onClick={startEditing}>
                    <Pencil className="h-4 w-4" />
                    编辑
                  </Button>
                )}
                {!editing && canDelete && (
                  <Button variant="danger" onClick={() => setConfirmState({ action: "delete", id: selectedQuestionId })}>
                    <Trash2 className="h-4 w-4" />
                    删除
                  </Button>
                )}
                <Button variant="ghost" onClick={() => setSelectedQuestionId(null)}>关闭</Button>
              </div>
            </div>

            {selectedQuestion ? (
              editing ? (
                /* ===== Edit form ===== */
                <div className="mt-6 space-y-5">
                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">科目</p>
                      <Input value={editForm.subject ?? ""} onChange={(e) => setEditForm({ ...editForm, subject: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">题型</p>
                      <Input value={editForm.question_type ?? ""} onChange={(e) => setEditForm({ ...editForm, question_type: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">难度</p>
                      <select
                        className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                        value={editForm.difficulty ?? 3}
                        onChange={(e) => setEditForm({ ...editForm, difficulty: Number(e.target.value) })}
                      >
                        {[1, 2, 3, 4, 5].map((d) => (
                          <option key={d} value={d}>{d} - {["简单", "较易", "中等", "较难", "困难"][d - 1]}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-[var(--color-text-secondary)]">题干</p>
                    <textarea
                      className="min-h-32 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm"
                      value={textFromContent(editForm.content) ?? ""}
                      onChange={(e) => setEditForm({ ...editForm, content: { ...editForm.content, stem: e.target.value } })}
                    />
                  </div>

                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-[var(--color-text-secondary)]">选项 (JSON)</p>
                    <textarea
                      className="min-h-24 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 font-mono text-xs"
                      value={editForm.options ? JSON.stringify(editForm.options, null, 2) : ""}
                      onChange={(e) => {
                        try {
                          setEditForm({ ...editForm, options: JSON.parse(e.target.value) });
                        } catch {
                          // Allow invalid JSON while typing
                        }
                      }}
                    />
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">答案</p>
                      <Input value={editForm.answer ?? ""} onChange={(e) => setEditForm({ ...editForm, answer: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">知识点 (JSON)</p>
                      <input
                        className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 font-mono text-xs"
                        value={editForm.knowledge_points ? JSON.stringify(editForm.knowledge_points) : ""}
                        onChange={(e) => {
                          try {
                            setEditForm({ ...editForm, knowledge_points: JSON.parse(e.target.value) });
                          } catch {
                            // Allow invalid JSON while typing
                          }
                        }}
                      />
                    </div>
                  </div>

                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-[var(--color-text-secondary)]">解析</p>
                    <textarea
                      className="min-h-24 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm"
                      value={editForm.analysis ?? ""}
                      onChange={(e) => setEditForm({ ...editForm, analysis: e.target.value })}
                    />
                  </div>

                  <div className="flex justify-end gap-3">
                    <Button variant="secondary" onClick={cancelEditing}>
                      <X className="h-4 w-4" />
                      取消
                    </Button>
                    <Button variant="primary" onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>
                      <Save className="h-4 w-4" />
                      {updateMutation.isPending ? "保存中..." : "保存修改"}
                    </Button>
                  </div>
                </div>
              ) : (
                /* ===== Detail view ===== */
                <div className="mt-6 space-y-5 text-sm">
                  {renderDuplicateInfo(selectedQuestion.import_record)}

                  {/* Stem with math rendering */}
                  <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                    <p className="mb-2 font-semibold text-[var(--ink)]">题干</p>
                    <div className="whitespace-pre-wrap font-sans leading-relaxed text-[var(--color-text-secondary)]">
                      <MathFormula text={textFromContent(selectedQuestion.content)} />
                    </div>
                  </section>

                  {[
                    ["选项", renderJson(selectedQuestion.options)],
                    ["答案", selectedQuestion.answer],
                    ["解析", selectedQuestion.analysis],
                    ["知识点", renderJson(selectedQuestion.knowledge_points)],
                    ["难度", selectedQuestion.difficulty],
                  ].map(([label, value]) => (
                    <section key={String(label)} className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                      <p className="font-semibold text-[var(--ink)]">{label}</p>
                      {(label === "选项" || label === "解析") ? (
                        <div className="mt-2 whitespace-pre-wrap font-sans leading-relaxed text-[var(--color-text-secondary)]">
                          <MathFormula text={String(renderJson(value))} />
                        </div>
                      ) : (
                        <pre className="mt-2 whitespace-pre-wrap font-sans text-[var(--color-text-secondary)]">{renderJson(value)}</pre>
                      )}
                    </section>
                  ))}

                  <section className="rounded-2xl border border-[var(--color-border)] p-4">
                    <p className="font-semibold text-[var(--ink)]">版本历史</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(versions.data?.items ?? []).map((version) => (
                        <Button key={version.id} variant={selectedVersion === version.version ? "primary" : "secondary"} onClick={() => setSelectedVersion(version.version)}>
                          v{version.version}
                        </Button>
                      ))}
                    </div>
                    {versionDetail.data ? (
                      <div className="mt-4 space-y-4">
                        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                          <p className="font-semibold text-[var(--ink)]">对比基线：当前题目 vs v{versionDetail.data.version} 历史快照</p>
                        </div>
                        {renderDiff("题干", textFromContent(selectedQuestion.content), textFromContent(versionDetail.data.content))}
                        {renderDiff("选项", selectedQuestion.options ?? null, versionDetail.data.options ?? null)}
                        {renderDiff("答案", selectedQuestion.answer, versionDetail.data.answer)}
                        {renderDiff("解析", selectedQuestion.analysis ?? null, versionDetail.data.analysis ?? null)}
                        {renderDiff("难度", selectedQuestion.difficulty, versionDetail.data.difficulty)}
                        {renderDiff("知识点", selectedQuestion.knowledge_points ?? null, versionDetail.data.knowledge_points ?? null)}
                        <details className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                          <summary className="cursor-pointer font-semibold text-[var(--ink)]">原始 JSON</summary>
                          <pre className="mt-4 max-h-80 overflow-auto text-xs text-[var(--color-text-secondary)]">
                            {JSON.stringify(versionDetail.data, null, 2)}
                          </pre>
                        </details>
                      </div>
                    ) : null}
                  </section>
                </div>
              )
            ) : (
              <p className="mt-6 text-sm text-[var(--color-text-secondary)]">正在加载详情...</p>
            )}
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmState !== null}
        title={
          confirmState?.action === "delete" || confirmState?.action === "batch-delete"
            ? "确认删除题目"
            : "确认审核操作"
        }
        description={confirmDescription}
        confirmText={
          confirmState?.action === "delete" || confirmState?.action === "batch-delete" ? "删除" : "提交"
        }
        danger={Boolean(confirmState && (confirmState.action === "delete" || confirmState.action === "batch-delete"))}
        loading={reviewMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => {
          if (!confirmState) return;
          reviewMutation.mutate(confirmState);
        }}
      />
    </div>
  );
}
