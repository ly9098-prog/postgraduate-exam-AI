"use client";

import { useMemo, useState, useCallback, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FileQuestion,
  Search,
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
  SlidersHorizontal,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MathFormula } from "@/components/ui/math-formula";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest, toQuery } from "@/lib/api/client";
import type {
  AdminQuestion,
  AdminQuestionDetail,
  AdminQuestionImportSummary,
  PaginatedResponse,
  QuestionEditRequest,
  QuestionVersion,
  QuestionVersionDetail,
} from "@/lib/api/types";

const activeOptions = [
  { label: "全部状态", value: "" },
  { label: "启用", value: "true" },
  { label: "停用", value: "false" },
];

type ConfirmState =
  | { action: "batch-delete" }
  | { action: "delete"; id: number }
  | null;

type BatchDeleteResult = {
  success_ids?: number[];
  successIds?: number[];
  failed_items?: Array<{ id: number; error: string }>;
  failedItems?: Array<{ id: number; error: string }>;
};

function textFromContent(
  content: Record<string, unknown> | string | null | undefined,
) {
  if (!content) return "";
  if (typeof content === "string") return content;
  const candidate =
    content.stem ?? content.text ?? content.question ?? content.title;
  if (typeof candidate === "string") return candidate;
  return JSON.stringify(content, null, 2);
}

function renderJson(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return String(value);
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
          <p className="text-xs font-semibold text-[var(--color-warning)]">
            变更前
          </p>
          <pre className="whitespace-pre-wrap text-xs text-[var(--color-text-secondary)] line-through">
            {prev}
          </pre>
          <p className="text-xs font-semibold text-[var(--color-success)]">
            变更后
          </p>
          <pre className="whitespace-pre-wrap text-xs text-[var(--color-success)]">
            {cur}
          </pre>
        </div>
      ) : (
        <pre className="whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-xs text-[var(--color-text-secondary)]">
          {cur}
        </pre>
      )}
    </section>
  );
}

function isMultiChoice(questionType: string): boolean {
  return /多选|多空|多项/i.test(questionType);
}

function optionsToKeyValueList(
  options: Record<string, unknown> | null | undefined,
): Array<{ key: string; text: string }> {
  if (!options) return [];
  return Object.entries(options).map(([key, value]) => ({
    key,
    text: typeof value === "string" ? value : JSON.stringify(value),
  }));
}

type QuestionWithImport = AdminQuestion & {
  import_record?: AdminQuestionImportSummary | null;
};

function renderSecondaryQuestionInfo(question: QuestionWithImport) {
  const importRecord = question.import_record;
  return (
    <details className="rounded-2xl border border-[var(--color-border)] bg-white/55 p-4 text-sm">
      <summary className="cursor-pointer list-none">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-semibold text-[var(--ink)]">辅助信息</p>
            <p className="mt-1 text-xs text-[var(--color-text-hint)]">
              科目、年份、启用状态与导入关联信息
            </p>
          </div>
        </div>
      </summary>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {[
          ["科目", question.subject_name || "—"],
          ["年份", question.year || "—"],
          ["启用状态", question.is_active ? "启用" : "停用"],
          ["题目 ID", `#${question.id}`],
        ].map(([label, value]) => (
          <div
            key={String(label)}
            className="rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)] px-3 py-2"
          >
            <p className="text-[11px] text-[var(--color-text-hint)]">
              {label}
            </p>
            <p className="mt-1 break-words text-sm font-medium text-[var(--color-text-secondary)]">
              {value}
            </p>
          </div>
        ))}
      </div>

      {importRecord ? (
        <div className="mt-3 rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)] p-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <p className="text-[11px] text-[var(--color-text-hint)]">
                题目 hash
              </p>
              <p className="mt-1 break-all font-mono text-xs text-[var(--color-text-secondary)]">
                {importRecord.question_hash || "—"}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--color-text-hint)]">
                正式题关联
              </p>
              <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)]">
                {importRecord.duplicate_of_question_id
                  ? `#${importRecord.duplicate_of_question_id}`
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--color-text-hint)]">
                导入项关联
              </p>
              <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)]">
                {importRecord.duplicate_of_import_id
                  ? `#${importRecord.duplicate_of_import_id}`
                  : "—"}
              </p>
            </div>
          </div>
        </div>
      ) : null}
    </details>
  );
}

/** Difficulty pill */
function DifficultyBadge({
  difficulty,
}: {
  difficulty: number | string | null | undefined;
}) {
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
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${colors[idx]}`}
    >
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
  const [filters, setFilters] = useState({
    subject_id: "",
    is_active: "",
    question_type: "",
    keyword: "",
    year: "",
  });
  const [subjectOptions, setSubjectOptions] = useState<
    Array<{ id: number; code: string; name: string }>
  >([]);
  useEffect(() => {
    apiRequest<
      Array<{
        id: number;
        code: string;
        name: string;
        path: string;
        level: number;
      }>
    >("/imports/subject-options")
      .then(setSubjectOptions)
      .catch(() => {});
  }, []);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [page, setPage] = useState(1);
  const [selectedQuestionId, setSelectedQuestionId] = useState<number | null>(
    null,
  );
  const [isDetailDrawerOpen, setIsDetailDrawerOpen] = useState(false);
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
      subject_id: filters.subject_id,
      is_active: filters.is_active,
      question_type: filters.question_type,
      keyword: filters.keyword,
      year: filters.year,
    }),
    [page, filters],
  );

  const questions = useQuery({
    queryKey: ["questions", queryParams],
    queryFn: () =>
      apiRequest<PaginatedResponse<AdminQuestion>>(
        `/questions${toQuery(queryParams)}`,
      ),
    retry: false,
  });

  const detail = useQuery({
    queryKey: ["questions", selectedQuestionId, "detail"],
    queryFn: () =>
      apiRequest<AdminQuestionDetail>(`/questions/${selectedQuestionId}`),
    enabled: selectedQuestionId !== null,
    retry: false,
  });

  const versions = useQuery({
    queryKey: ["questions", selectedQuestionId, "versions"],
    queryFn: () =>
      apiRequest<PaginatedResponse<QuestionVersion>>(
        `/questions/${selectedQuestionId}/versions${toQuery({ page: 1, page_size: 20 })}`,
      ),
    enabled: selectedQuestionId !== null,
    retry: false,
  });

  const versionDetail = useQuery({
    queryKey: ["questions", selectedQuestionId, "versions", selectedVersion],
    queryFn: () =>
      apiRequest<QuestionVersionDetail>(
        `/questions/${selectedQuestionId}/versions/${selectedVersion}`,
      ),
    enabled: selectedQuestionId !== null && selectedVersion !== null,
    retry: false,
  });

  const deleteMutation = useMutation({
    mutationFn: async (state: Exclude<ConfirmState, null>) => {
      if (state.action === "batch-delete")
        return apiRequest<BatchDeleteResult>("/questions/batch-delete", {
          method: "POST",
          body: JSON.stringify({ ids: Array.from(selectedIds) }),
        });
      return apiRequest<{ status: string }>(`/questions/${state.id}`, {
        method: "DELETE",
      });
    },
    onSuccess: (result, variables: Exclude<ConfirmState, null>) => {
      if (variables.action === "delete") {
        setMessage(`题目 #${variables.id} 已删除。`);
        setSelectedQuestionId(null);
        setIsDetailDrawerOpen(false);
      } else {
        const r = result as BatchDeleteResult;
        const successIds = r.success_ids ?? r.successIds ?? [];
        const failedItems = r.failed_items ?? r.failedItems ?? [];
        const failures = failedItems.length
          ? `失败 ${failedItems.length} 条：${failedItems.map((item) => `#${item.id} ${item.error}`).join("；")}`
          : "无失败项";
        setMessage(`批量删除完成，成功 ${successIds.length} 条，${failures}。`);
      }
      setSelectedIds(new Set());
      setConfirmState(null);
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    onError: (error) => {
      setMessage(
        error instanceof Error ? error.message : "删除失败，请稍后重试。",
      );
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
      queryClient.invalidateQueries({
        queryKey: ["questions", selectedQuestionId],
      });
    },
    onError: (error) => {
      setMessage(
        error instanceof Error ? error.message : "更新失败，请稍后重试。",
      );
    },
  });

  const items = useMemo(
    () => questions.data?.items ?? [],
    [questions.data?.items],
  );
  const allChecked =
    items.length > 0 && items.every((item) => selectedIds.has(item.id));
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

  const selectQuestion = useCallback((id: number) => {
    setSelectedQuestionId(id);
    setSelectedVersion(null);
    setEditing(false);
    setEditForm({});
  }, []);

  const openDetail = useCallback(
    (id: number) => {
      selectQuestion(id);
      setIsDetailDrawerOpen(true);
    },
    [selectQuestion],
  );

  const startEditing = () => {
    if (!selectedQuestion) return;
    // Pre-fill form from current question data
    const content = selectedQuestion.content;
    const stem = textFromContent(content);
    setEditForm({
      subject_id: selectedQuestion.subject_id ?? null,
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

  const confirmDescription =
    confirmState?.action === "batch-delete"
      ? "删除后这些题目将从题库永久移除，此操作不可撤销。"
      : "删除后该题目将从题库永久移除，此操作不可撤销。";

  return (
    <div className="space-y-6 pb-24">
      <Card className="overflow-visible">
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">
                正式题库
              </h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                点击题目查看题干、选项、答案与解析；详情面板用于编辑、版本对比或删除。
              </p>
            </div>
            {canDelete && (
              <Button
                variant="danger"
                disabled={selectedIds.size === 0}
                onClick={() => setConfirmState({ action: "batch-delete" })}
              >
                <Trash2 className="h-4 w-4" />
                批量删除
              </Button>
            )}
          </div>

          <div className="rounded-3xl border border-[var(--color-border)] bg-white/65 p-3 shadow-sm backdrop-blur">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(260px,1fr)_180px_150px_120px_130px]">
              <label className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
                <Input
                  className="pl-9"
                  placeholder="搜索题干 / 科目"
                  value={filters.keyword}
                  onChange={(event) =>
                    updateFilter("keyword", event.target.value)
                  }
                />
              </label>
              <select
                className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                value={filters.subject_id}
                onChange={(e) => updateFilter("subject_id", e.target.value)}
              >
                <option value="">全部科目</option>
                {subjectOptions.map((s) => (
                  <option key={s.id} value={String(s.id)}>
                    {s.name}
                  </option>
                ))}
              </select>
              <Input
                placeholder="题型"
                value={filters.question_type}
                onChange={(event) =>
                  updateFilter("question_type", event.target.value)
                }
              />
              <Input
                placeholder="年份"
                value={filters.year}
                onChange={(event) => updateFilter("year", event.target.value)}
              />
              <select
                className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                value={filters.is_active}
                onChange={(event) =>
                  updateFilter("is_active", event.target.value)
                }
              >
                {activeOptions.map((option) => (
                  <option key={option.value || "all"} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-5">
          {message ? (
            <div
              role="status"
              aria-live="polite"
              className="fixed right-6 top-6 z-[60] max-w-sm rounded-2xl border border-[var(--color-success)] bg-white px-5 py-4 text-sm font-medium text-[var(--ink)] shadow-[var(--shadow-floating)]"
            >
              {message}
            </div>
          ) : null}

          {items.length > 0 ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-border)] bg-white/60 px-4 py-3 text-xs text-[var(--color-text-secondary)]">
              <div className="flex flex-wrap items-center gap-3">
                <span className="flex items-center gap-1.5 font-medium text-[var(--ink)]">
                  <Hash className="h-3.5 w-3.5" />
                  当前页 {items.length} 题
                </span>
              </div>
              <label className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white/80 px-3 py-2 text-sm text-[var(--color-text-secondary)] transition hover:bg-white">
                <input
                  type="checkbox"
                  checked={allChecked}
                  onChange={toggleAll}
                  className="h-4 w-4 rounded border-[var(--color-border)] text-[var(--color-primary)]"
                />
                <span className="font-medium">选择当前页</span>
                {selectedIds.size > 0 && (
                  <span className="rounded-md bg-[var(--color-primary-light)] px-2 py-0.5 text-[11px] font-semibold text-[var(--color-primary-dark)]">
                    {selectedIds.size}
                  </span>
                )}
              </label>
            </div>
          ) : null}

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_520px]">
            <section className="space-y-3">
              {questions.isLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 4 }, (_, index) => (
                    <div
                      key={index}
                      className="h-36 animate-pulse rounded-[1.6rem] border border-[var(--color-border)] bg-white/60"
                    />
                  ))}
                </div>
              ) : null}

              {items.map((question) => {
                const stemText =
                  textFromContent(question.content) || `题目 #${question.id}`;
                const isSelected = selectedQuestionId === question.id;
                return (
                  <article
                    key={question.id}
                    className={`group relative overflow-hidden rounded-[1.6rem] border bg-white/78 shadow-sm transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-card)] ${
                      isSelected
                        ? "border-[var(--color-primary)] ring-4 ring-[var(--color-primary-light)]"
                        : "border-[var(--color-border)] hover:border-[var(--color-primary-light)] hover:bg-white"
                    }`}
                  >
                    <span
                      className="absolute left-0 top-0 h-full w-1 bg-[var(--color-primary)]"
                      aria-hidden="true"
                    />
                    <div className="flex items-start gap-3 p-4 pl-5">
                      <input
                        aria-label={`选择题目 #${question.id}`}
                        type="checkbox"
                        checked={selectedIds.has(question.id)}
                        onChange={() => toggleOne(question.id)}
                        className="mt-1 h-4 w-4 shrink-0 rounded border-[var(--color-border)] text-[var(--color-primary)]"
                      />

                      <button
                        type="button"
                        onClick={() => selectQuestion(question.id)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <TypeBadge type={question.question_type} />
                          <DifficultyBadge difficulty={question.difficulty} />
                        </div>

                        <div className="mt-3 line-clamp-4 rounded-2xl border border-[var(--color-border)] bg-[var(--porcelain)] px-4 py-3 text-sm leading-7 text-[var(--ink)]">
                          <MathFormula text={stemText} />
                        </div>

                        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-text-hint)]">
                          <span className="inline-flex items-center gap-1 font-mono">
                            <Clock className="h-3 w-3" />#{question.id}
                          </span>
                          {question.subject_name && (
                            <span className="inline-flex items-center gap-1">
                              <BookOpen className="h-3 w-3" />
                              {question.subject_name}
                            </span>
                          )}
                          {question.year && (
                            <span className="inline-flex items-center gap-1">
                              <Tag className="h-3 w-3" />
                              {question.year}
                            </span>
                          )}
                          <span>{question.is_active ? "启用" : "停用"}</span>
                        </div>
                      </button>

                      <div className="flex shrink-0 flex-col gap-2">
                        <Button
                          variant="secondary"
                          onClick={() => openDetail(question.id)}
                          className="h-9 gap-1.5 px-3 text-xs font-medium xl:hidden"
                        >
                          <FileQuestion className="h-4 w-4" />
                          详情
                        </Button>
                      </div>
                    </div>
                  </article>
                );
              })}

              {!questions.isLoading && items.length === 0 ? (
                <div className="flex flex-col items-center gap-3 rounded-[1.6rem] border border-dashed border-[var(--color-border)] bg-white/60 py-16 text-center">
                  <FileQuestion className="h-12 w-12 text-[var(--color-text-hint)]" />
                  <p className="text-sm font-semibold text-[var(--color-text-secondary)]">
                    暂无题目
                  </p>
                  <p className="text-xs text-[var(--color-text-hint)]">
                    尝试调整筛选条件
                  </p>
                </div>
              ) : null}

              {questions.isError ? (
                <div className="rounded-2xl border border-[var(--color-danger-light)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
                  题目接口当前不可用，若 router 未挂载则属于后端阻塞。
                </div>
              ) : null}
            </section>

            <aside className="hidden xl:block">
              <div className="sticky top-6 h-[calc(100dvh-3rem)] overflow-y-auto rounded-[2rem] border border-[var(--color-border)] bg-white/85 p-5 shadow-[var(--shadow-card)] backdrop-blur">
                {selectedQuestionId === null ? (
                  <div className="flex h-full min-h-[520px] flex-col items-center justify-center text-center">
                    <div className="flex h-16 w-16 items-center justify-center rounded-3xl border border-[var(--color-border)] bg-[var(--porcelain)] text-[var(--color-text-hint)] shadow-sm">
                      <SlidersHorizontal className="h-8 w-8" />
                    </div>
                    <p className="mt-5 font-display text-2xl font-bold text-[var(--ink)]">
                      选择一道题目
                    </p>
                    <p className="mt-2 max-w-xs text-sm leading-6 text-[var(--color-text-secondary)]">
                      在左侧点击题目查看内容；需要编辑、删除或查看完整版本对比时，再打开详情面板。
                    </p>
                  </div>
                ) : selectedQuestion ? (
                  <div className="space-y-5">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="font-mono text-xs uppercase tracking-[0.28em] text-[var(--color-text-hint)]">
                          Question
                        </p>
                        <h3 className="mt-2 font-display text-2xl font-bold text-[var(--ink)]">
                          题目 #{selectedQuestion.id}
                        </h3>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <TypeBadge type={selectedQuestion.question_type} />
                          <DifficultyBadge
                            difficulty={selectedQuestion.difficulty}
                          />
                        </div>
                      </div>
                      <Button
                        variant="secondary"
                        onClick={() => setIsDetailDrawerOpen(true)}
                        className="shrink-0"
                      >
                        <FileQuestion className="h-4 w-4" />
                        完整详情
                      </Button>
                    </div>

                    <section className="rounded-[1.6rem] border border-[var(--color-primary-light)] bg-[var(--porcelain)] p-5 shadow-sm">
                      <p className="mb-3 flex items-center justify-between gap-3 font-semibold text-[var(--ink)]">
                        <span>题干</span>
                        <span className="font-mono text-[11px] font-normal text-[var(--color-text-hint)]">
                          #{selectedQuestion.id}
                        </span>
                      </p>
                      <div className="whitespace-pre-wrap text-base leading-8 text-[var(--ink)]">
                        <MathFormula
                          text={textFromContent(selectedQuestion.content)}
                        />
                      </div>
                    </section>

                    <section className="rounded-[1.6rem] border border-[var(--color-border)] bg-white/80 p-4">
                      <p className="font-semibold text-[var(--ink)]">选项</p>
                      <div className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap text-sm leading-7 text-[var(--color-text-secondary)]">
                        <MathFormula text={renderJson(selectedQuestion.options)} />
                      </div>
                    </section>

                    <section className="rounded-[1.6rem] border border-[var(--color-success-light)] bg-[var(--color-success-light)] p-4">
                      <p className="font-semibold text-[var(--color-success)]">
                        答案
                      </p>
                      <div className="mt-2 whitespace-pre-wrap text-base font-semibold leading-7 text-[var(--ink)]">
                        <MathFormula text={selectedQuestion.answer || "—"} />
                      </div>
                    </section>

                    <section className="rounded-[1.6rem] border border-[var(--color-border)] bg-white/80 p-4">
                      <p className="font-semibold text-[var(--ink)]">解析</p>
                      <div className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap text-sm leading-7 text-[var(--color-text-secondary)]">
                        <MathFormula text={selectedQuestion.analysis || "—"} />
                      </div>
                    </section>

                    <section className="rounded-[1.6rem] border border-[var(--color-border)] bg-white/70 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="font-semibold text-[var(--ink)]">
                          版本历史
                        </p>
                        <span className="text-xs text-[var(--color-text-hint)]">
                          {versions.data?.items?.length ?? 0} 个版本
                        </span>
                      </div>
                      <div className="mt-3 space-y-2">
                        {(versions.data?.items ?? [])
                          .slice(0, 6)
                          .map((version) => (
                            <button
                              key={version.id}
                              type="button"
                              onClick={() =>
                                setSelectedVersion(version.version)
                              }
                              className={`flex w-full items-center justify-between rounded-2xl border px-3 py-2 text-left text-sm transition ${
                                selectedVersion === version.version
                                  ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                                  : "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)] hover:border-[var(--color-primary-light)]"
                              }`}
                            >
                              <span className="font-semibold">
                                v{version.version}
                              </span>
                              <span className="text-xs text-[var(--color-text-hint)]">
                                {version.created_at
                                  ? new Date(
                                      version.created_at,
                                    ).toLocaleDateString()
                                  : "历史快照"}
                              </span>
                            </button>
                          ))}
                        {(versions.data?.items ?? []).length === 0 ? (
                          <p className="rounded-2xl border border-dashed border-[var(--color-border)] bg-[var(--porcelain)] px-3 py-4 text-center text-sm text-[var(--color-text-hint)]">
                            暂无版本记录
                          </p>
                        ) : null}
                      </div>
                    </section>

                    {renderSecondaryQuestionInfo(selectedQuestion)}

                    <div className="flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-4">
                      {canWrite ? (
                        <Button
                          variant="secondary"
                          onClick={() => {
                            startEditing();
                            setIsDetailDrawerOpen(true);
                          }}
                        >
                          <Pencil className="h-4 w-4" />
                          编辑
                        </Button>
                      ) : null}
                      {canDelete ? (
                        <Button
                          variant="danger"
                          onClick={() =>
                            setConfirmState({
                              action: "delete",
                              id: selectedQuestion.id,
                            })
                          }
                        >
                          <Trash2 className="h-4 w-4" />
                          删除
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ) : (
                  <div className="flex h-full min-h-[420px] items-center justify-center text-sm text-[var(--color-text-secondary)]">
                    正在加载详情...
                  </div>
                )}
              </div>
            </aside>
          </div>

          {questions.data && questions.data.total_pages > 1 ? (
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[var(--blueprint-line)] bg-white/80 px-5 py-3 shadow-[var(--shadow-crisp)]">
              <span className="font-display text-sm tracking-wide text-[var(--color-text-secondary)]">
                <span className="font-semibold text-[var(--ink)]">
                  {questions.data.total}
                </span>{" "}
                道题目
                <span className="mx-2 text-[var(--color-text-hint)]">/</span>
                <span className="text-[var(--color-text-hint)]">第 </span>
                <span className="font-semibold text-[var(--ink)]">
                  {questions.data.page}
                </span>
                <span className="text-[var(--color-text-hint)]">
                  {" "}
                  / {questions.data.total_pages} 页
                </span>
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="inline-flex h-9 items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                >
                  <svg
                    className="h-3.5 w-3.5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M15 19l-7-7 7-7"
                    />
                  </svg>
                  上一页
                </button>
                {Array.from(
                  { length: Math.min(questions.data.total_pages, 5) },
                  (_, i) => {
                    const start = Math.max(
                      1,
                      Math.min(page - 2, questions.data.total_pages - 4),
                    );
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
                  },
                )}
                <button
                  disabled={page >= (questions.data?.total_pages ?? 1)}
                  onClick={() => setPage((p) => p + 1)}
                  className="inline-flex h-9 items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                >
                  下一页
                  <svg
                    className="h-3.5 w-3.5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M9 5l7 7-7 7"
                    />
                  </svg>
                </button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {selectedIds.size > 0 ? (
        <div className="fixed bottom-6 left-1/2 z-50 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-3 rounded-2xl border border-[var(--blueprint-line)] bg-[var(--ink)] px-5 py-3 text-white shadow-[var(--shadow-floating)]">
          <span className="text-sm font-semibold">
            已选择 {selectedIds.size} 道题
          </span>
          <button
            type="button"
            onClick={() => setSelectedIds(new Set())}
            className="min-h-10 rounded-xl px-3 py-2 text-xs font-semibold text-white/70 transition hover:bg-white/10 hover:text-white"
          >
            清空
          </button>
          {canDelete ? (
            <Button
              variant="danger"
              onClick={() => setConfirmState({ action: "batch-delete" })}
            >
              <Trash2 className="h-4 w-4" />
              批量删除
            </Button>
          ) : null}
        </div>
      ) : null}

      {/* Detail drawer */}
      {isDetailDrawerOpen && selectedQuestionId !== null ? (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.42)] backdrop-blur-[2px]"
          onClick={() => setIsDetailDrawerOpen(false)}
        >
          <aside
            className="h-full w-full max-w-3xl overflow-y-auto bg-white p-6 shadow-[var(--shadow-floating)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">
                {editing ? "编辑题目" : "题目详情"}
                {!editing && (
                  <span className="ml-2 font-mono text-base text-[var(--color-text-hint)]">
                    #{selectedQuestionId}
                  </span>
                )}
              </h3>
              <div className="flex items-center gap-2">
                {!editing && canWrite && (
                  <Button variant="secondary" onClick={startEditing}>
                    <Pencil className="h-4 w-4" />
                    编辑
                  </Button>
                )}
                {!editing && canDelete && (
                  <Button
                    variant="danger"
                    onClick={() =>
                      setConfirmState({
                        action: "delete",
                        id: selectedQuestionId,
                      })
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                    删除
                  </Button>
                )}
                <Button
                  variant="ghost"
                  onClick={() => setIsDetailDrawerOpen(false)}
                >
                  关闭
                </Button>
              </div>
            </div>

            {selectedQuestion ? (
              editing ? (
                /* ===== Edit form ===== */
                <div className="mt-6 space-y-5">
                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        科目
                      </p>
                      <select
                        className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                        value={editForm.subject_id ?? ""}
                        onChange={(e) =>
                          setEditForm({
                            ...editForm,
                            subject_id: e.target.value
                              ? Number(e.target.value)
                              : null,
                          })
                        }
                      >
                        <option value="">未设置</option>
                        {subjectOptions.map((s) => (
                          <option key={s.id} value={String(s.id)}>
                            {s.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        题型
                      </p>
                      <Input
                        value={editForm.question_type ?? ""}
                        onChange={(e) =>
                          setEditForm({
                            ...editForm,
                            question_type: e.target.value,
                          })
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        难度
                      </p>
                      <select
                        className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                        value={editForm.difficulty ?? 3}
                        onChange={(e) =>
                          setEditForm({
                            ...editForm,
                            difficulty: Number(e.target.value),
                          })
                        }
                      >
                        {[1, 2, 3, 4, 5].map((d) => (
                          <option key={d} value={d}>
                            {d} -{" "}
                            {["简单", "较易", "中等", "较难", "困难"][d - 1]}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                      题干
                    </p>
                    <textarea
                      className="min-h-32 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm"
                      value={textFromContent(editForm.content) ?? ""}
                      onChange={(e) =>
                        setEditForm({
                          ...editForm,
                          content: {
                            ...editForm.content,
                            stem: e.target.value,
                          },
                        })
                      }
                    />
                  </div>

                  {/* Options inline editor */}
                  {(() => {
                    const optList = optionsToKeyValueList(editForm.options);
                    return (
                      <section className="rounded-xl border border-[var(--color-border)]/60 bg-white/80 p-4 shadow-sm">
                        <p className="mb-3 text-xs font-semibold text-[var(--color-text-secondary)]">
                          选项
                        </p>
                        {optList.length === 0 ? (
                          <p className="text-sm text-[var(--color-text-hint)]">
                            暂无可编辑选项
                          </p>
                        ) : (
                          <div className="space-y-2">
                            {optList.map((opt, index) => (
                              <div
                                key={index}
                                className="flex items-center gap-2"
                              >
                                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--color-primary-light)] text-[10px] font-bold text-[var(--color-primary-dark)]">
                                  {opt.key}
                                </span>
                                <input
                                  className="h-9 flex-1 rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15"
                                  value={opt.text}
                                  onChange={(e) => {
                                    const next = {
                                      ...editForm.options,
                                    } as Record<string, string>;
                                    next[opt.key] = e.target.value;
                                    setEditForm({ ...editForm, options: next });
                                  }}
                                />
                              </div>
                            ))}
                          </div>
                        )}
                      </section>
                    );
                  })()}

                  {/* Answer quick-select */}
                  {optionsToKeyValueList(editForm.options).length > 0 ? (
                    <section className="rounded-xl border border-[var(--color-border)]/60 bg-white/80 p-4 shadow-sm">
                      <p className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">
                        快速选择答案
                      </p>
                      {editForm.question_type &&
                      isMultiChoice(editForm.question_type) ? (
                        <p className="mb-2 text-[10px] text-[var(--color-text-hint)]">
                          多选：单击切换各选项，以逗号分隔
                        </p>
                      ) : null}
                      <div className="mb-3 flex flex-wrap gap-2">
                        {optionsToKeyValueList(editForm.options).map((opt) => {
                          const selected = isMultiChoice(
                            editForm.question_type ?? "",
                          )
                            ? (editForm.answer ?? "")
                                .split(/[,，\s]+/)
                                .includes(opt.key)
                            : editForm.answer === opt.key;
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
                                if (
                                  isMultiChoice(editForm.question_type ?? "")
                                ) {
                                  const keys = (editForm.answer ?? "")
                                    .split(/[,，\s]+/)
                                    .filter(Boolean);
                                  const next = keys.includes(opt.key)
                                    ? keys.filter((k) => k !== opt.key)
                                    : [...keys, opt.key];
                                  setEditForm({
                                    ...editForm,
                                    answer: next.join(","),
                                  });
                                } else {
                                  setEditForm({
                                    ...editForm,
                                    answer:
                                      editForm.answer === opt.key
                                        ? ""
                                        : opt.key,
                                  });
                                }
                              }}
                            >
                              {opt.key}
                            </button>
                          );
                        })}
                      </div>
                      <div className="space-y-1">
                        <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                          答案
                        </p>
                        <Input
                          value={editForm.answer ?? ""}
                          onChange={(e) =>
                            setEditForm({ ...editForm, answer: e.target.value })
                          }
                        />
                      </div>
                    </section>
                  ) : (
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        答案
                      </p>
                      <Input
                        value={editForm.answer ?? ""}
                        onChange={(e) =>
                          setEditForm({ ...editForm, answer: e.target.value })
                        }
                      />
                    </div>
                  )}

                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                      知识点 (JSON)
                    </p>
                    <input
                      className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 font-mono text-xs"
                      value={
                        editForm.knowledge_points
                          ? JSON.stringify(editForm.knowledge_points)
                          : ""
                      }
                      onChange={(e) => {
                        try {
                          setEditForm({
                            ...editForm,
                            knowledge_points: JSON.parse(e.target.value),
                          });
                        } catch {
                          // Allow invalid JSON while typing
                        }
                      }}
                    />
                  </div>

                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                      解析
                    </p>
                    <textarea
                      className="min-h-24 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm"
                      value={editForm.analysis ?? ""}
                      onChange={(e) =>
                        setEditForm({ ...editForm, analysis: e.target.value })
                      }
                    />
                  </div>

                  <div className="flex justify-end gap-3">
                    <Button variant="secondary" onClick={cancelEditing}>
                      <X className="h-4 w-4" />
                      取消
                    </Button>
                    <Button
                      variant="primary"
                      onClick={() => updateMutation.mutate()}
                      disabled={updateMutation.isPending}
                    >
                      <Save className="h-4 w-4" />
                      {updateMutation.isPending ? "保存中..." : "保存修改"}
                    </Button>
                  </div>
                </div>
              ) : (
                /* ===== Detail view ===== */
                <div className="mt-6 space-y-5 text-sm">
                  <section className="rounded-[1.7rem] border border-[var(--color-primary-light)] bg-[var(--porcelain)] p-5 shadow-sm">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                      <p className="font-display text-xl font-bold text-[var(--ink)]">
                        题干
                      </p>
                      <div className="flex flex-wrap items-center gap-2">
                        <TypeBadge type={selectedQuestion.question_type} />
                        <DifficultyBadge
                          difficulty={selectedQuestion.difficulty}
                        />
                      </div>
                    </div>
                    <div className="whitespace-pre-wrap font-sans text-base leading-8 text-[var(--ink)]">
                      <MathFormula
                        text={textFromContent(selectedQuestion.content)}
                      />
                    </div>
                  </section>

                  <section className="rounded-[1.7rem] border border-[var(--color-border)] bg-white/80 p-5">
                    <p className="font-display text-lg font-bold text-[var(--ink)]">
                      选项
                    </p>
                    <div className="mt-3 whitespace-pre-wrap font-sans leading-7 text-[var(--color-text-secondary)]">
                      <MathFormula
                        text={renderJson(selectedQuestion.options)}
                      />
                    </div>
                  </section>

                  <section className="rounded-[1.7rem] border border-[var(--color-success-light)] bg-[var(--color-success-light)] p-5">
                    <p className="font-display text-lg font-bold text-[var(--color-success)]">
                      答案
                    </p>
                    <div className="mt-3 whitespace-pre-wrap font-sans text-base font-semibold leading-7 text-[var(--ink)]">
                      <MathFormula text={selectedQuestion.answer || "—"} />
                    </div>
                  </section>

                  <section className="rounded-[1.7rem] border border-[var(--color-border)] bg-white/80 p-5">
                    <p className="font-display text-lg font-bold text-[var(--ink)]">
                      解析
                    </p>
                    <div className="mt-3 whitespace-pre-wrap font-sans leading-7 text-[var(--color-text-secondary)]">
                      <MathFormula text={selectedQuestion.analysis || "—"} />
                    </div>
                  </section>

                  <details className="rounded-[1.7rem] border border-[var(--color-border)] bg-white/70 p-5">
                    <summary className="cursor-pointer list-none font-display text-lg font-bold text-[var(--ink)]">
                      知识点与难度
                    </summary>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                        <p className="font-semibold text-[var(--ink)]">知识点</p>
                        <pre className="mt-2 whitespace-pre-wrap font-sans text-[var(--color-text-secondary)]">
                          {renderJson(selectedQuestion.knowledge_points)}
                        </pre>
                      </section>
                      <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                        <p className="font-semibold text-[var(--ink)]">难度</p>
                        <pre className="mt-2 whitespace-pre-wrap font-sans text-[var(--color-text-secondary)]">
                          {renderJson(selectedQuestion.difficulty)}
                        </pre>
                      </section>
                    </div>
                  </details>

                  <section className="rounded-[1.7rem] border border-[var(--color-border)] p-5">
                    <p className="font-display text-lg font-bold text-[var(--ink)]">
                      版本历史
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(versions.data?.items ?? []).map((version) => (
                        <Button
                          key={version.id}
                          variant={
                            selectedVersion === version.version
                              ? "primary"
                              : "secondary"
                          }
                          onClick={() => setSelectedVersion(version.version)}
                        >
                          v{version.version}
                        </Button>
                      ))}
                    </div>
                    {versionDetail.data ? (
                      <div className="mt-4 space-y-4">
                        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                          <p className="font-semibold text-[var(--ink)]">
                            对比基线：当前题目 vs v{versionDetail.data.version}{" "}
                            历史快照
                          </p>
                        </div>
                        {renderDiff(
                          "题干",
                          textFromContent(selectedQuestion.content),
                          textFromContent(versionDetail.data.content),
                        )}
                        {renderDiff(
                          "选项",
                          selectedQuestion.options ?? null,
                          versionDetail.data.options ?? null,
                        )}
                        {renderDiff(
                          "答案",
                          selectedQuestion.answer,
                          versionDetail.data.answer,
                        )}
                        {renderDiff(
                          "解析",
                          selectedQuestion.analysis ?? null,
                          versionDetail.data.analysis ?? null,
                        )}
                        {renderDiff(
                          "难度",
                          selectedQuestion.difficulty,
                          versionDetail.data.difficulty,
                        )}
                        {renderDiff(
                          "知识点",
                          selectedQuestion.knowledge_points ?? null,
                          versionDetail.data.knowledge_points ?? null,
                        )}
                        <details className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                          <summary className="cursor-pointer font-semibold text-[var(--ink)]">
                            原始 JSON
                          </summary>
                          <pre className="mt-4 max-h-80 overflow-auto text-xs text-[var(--color-text-secondary)]">
                            {JSON.stringify(versionDetail.data, null, 2)}
                          </pre>
                        </details>
                      </div>
                    ) : null}
                  </section>

                  {renderSecondaryQuestionInfo(selectedQuestion)}
                </div>
              )
            ) : (
              <p className="mt-6 text-sm text-[var(--color-text-secondary)]">
                正在加载详情...
              </p>
            )}
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmState !== null}
        title="确认删除题目"
        description={confirmDescription}
        confirmText="删除"
        danger
        loading={deleteMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => {
          if (!confirmState) return;
          deleteMutation.mutate(confirmState);
        }}
      />
    </div>
  );
}
