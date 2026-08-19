"use client";

import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  Download,
  FileQuestion,
  Filter,
  Loader2,
  AlertCircle,
  Search,
  BookOpen,
  BarChart3,
  Tag,
  Layers,
  Clock,
  Pencil,
  Trash2,
  Save,
  X,
  RotateCcw,
  SlidersHorizontal,
  Star,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MathFormula } from "@/components/ui/math-formula";
import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { StructuredTableEditor } from "@/components/structured-table-editor";
import { QuestionOptions } from "@/components/question-options";
import { QuestionImageField } from "@/components/questions/question-image-field";
import { QuestionAnalysis } from "@/components/questions/question-analysis";
import { QuickAddOptions } from "@/components/questions/quick-add-options";
import { useAuthStore } from "@/lib/auth/auth-store";
import {
  resolveQuestionOptions,
  normalizeQuestionOptions,
} from "@/lib/question-options";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest, apiRequestBlob, toQuery } from "@/lib/api/client";
import { CustomSelect } from "@/components/ui/custom-select";
import { QUESTION_TYPE_OPTIONS, getQuestionTypeLabel, canonicalizeQuestionType, formatUnknownType } from "@/lib/question-types";
import { isTableSegment, normalizeStructuredTableSegment } from "@/lib/structured-table";
import type {
  AdminQuestion,
  AdminQuestionDetail,
  AdminQuestionImportSummary,
  PaginatedResponse,
  QuestionEditRequest,
  QuestionOptionsValue,
  QuestionVersion,
  QuestionVersionDetail,
} from "@/lib/api/types";

const activeOptions = [
  { label: "全部状态", value: "" },
  { label: "启用", value: "true" },
  { label: "停用", value: "false" },
];

const difficultyOptions = [
  { label: "全部难度", value: "" },
  { label: "简单", value: "1" },
  { label: "较易", value: "2" },
  { label: "中等", value: "3" },
  { label: "较难", value: "4" },
  { label: "困难", value: "5" },
];

const pageSizeOptions = [
  { label: "20 条/页", value: "20" },
  { label: "50 条/页", value: "50" },
  { label: "100 条/页", value: "100" },
];

const KEYWORD_DEBOUNCE_MS = 300;
const IMPORT_BATCH_DEBOUNCE_MS = 450;
const BATCH_DELETE_CHUNK_SIZE = 50;

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

function contentRecord(content: unknown): Record<string, unknown> {
  return content && typeof content === "object" && !Array.isArray(content)
    ? (content as Record<string, unknown>)
    : {};
}

function contentSegments(content: unknown): Array<Record<string, unknown>> {
  const record = contentRecord(content);
  if (!Array.isArray(record.segments)) return [];
  return record.segments.filter(
    (segment): segment is Record<string, unknown> =>
      Boolean(segment) && typeof segment === "object" && !Array.isArray(segment),
  );
}

/** Only literal "image" segments are editable here; formula/table/code image
 * segments (math_image/table_image/code_image) are generated content the
 * backend upsert/remove helpers do not touch. */
function isPlainImageSegment(segment: Record<string, unknown>): boolean {
  return segment.type === "image";
}

/** text/newline segments carry the stem text. The edit form edits the stem as a
 * single textarea (content.stem/text); the text segments must be rebuilt to
 * match, or segments-based renderers (admin detail, miniprogram SEGMENTS mode)
 * keep showing the pre-edit snapshot. */
function isStemTextSegment(
  segment: Record<string, unknown> | null | undefined,
): boolean {
  return (
    !!segment &&
    typeof segment === "object" &&
    !Array.isArray(segment) &&
    (segment.type === "text" || segment.type === "newline")
  );
}

function stemTextToSegments(text: string): Array<Record<string, unknown>> {
  const lines = String(text ?? "").split("\n");
  const segments: Array<Record<string, unknown>> = [];
  lines.forEach((line, index) => {
    if (line) segments.push({ type: "text", text: line });
    if (index < lines.length - 1) segments.push({ type: "newline" });
  });
  return segments;
}

function updateStemInContent(
  content: unknown,
  newStem: string,
): Record<string, unknown> {
  const record = contentRecord(content);
  const next: Record<string, unknown> = { ...record, stem: newStem, text: newStem };
  if (record.render_mode === "segments" && Array.isArray(record.segments)) {
    const nonText = (record.segments as Array<Record<string, unknown>>).filter(
      (segment) => !isStemTextSegment(segment),
    );
    next.segments = [...stemTextToSegments(newStem), ...nonText];
  }
  return next;
}

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
  return canonicalizeQuestionType(questionType) === "multiple_choice";
}

function optionsToKeyValueList(
  options: QuestionOptionsValue | undefined,
): Array<{ key: string; text: string }> {
  if (!options) return [];
  if (typeof options === "string") {
    return normalizeQuestionOptions(options).map((o) => ({
      key: o.key,
      text: o.text ?? "",
    }));
  }
  if (Array.isArray(options)) {
    return normalizeQuestionOptions(options).map((o) => ({
      key: o.key,
      text: o.text ?? "",
    }));
  }
  return Object.entries(options).map(([key, value]) => ({
    key,
    text: typeof value === "string" ? value : richOptionText(value),
  }));
}

function richOptionText(value: unknown): string {
  if (value && typeof value === "object") {
    const text = (value as { text?: unknown }).text;
    if (typeof text === "string") return text;
  }
  return JSON.stringify(value);
}

function optionImageUrl(
  options: QuestionOptionsValue | undefined,
  key: string,
): string | null {
  if (!options || typeof options !== "object" || Array.isArray(options)) return null;
  const value = (options as Record<string, unknown>)[key];
  if (!value || typeof value !== "object") return null;
  const norm = normalizeQuestionOptions({ [key]: value });
  return norm[0]?.imageUrl ?? null;
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
          ["科目", question.subject_name || question.subject_code || "—"],
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
function TypeBadge({ type: t }: { type: string | null | undefined }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-white/80 px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-text-secondary)]">
      <Layers className="h-3 w-3" />
      {getQuestionTypeLabel(t)}
    </span>
  );
}

function CustomCheckbox({
  checked,
  onChange,
  className = "",
}: {
  checked: boolean;
  onChange: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={onChange}
      className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[4px] border transition-colors ${
        checked
          ? "border-[var(--color-primary)] bg-[var(--color-primary)]"
          : "border-[var(--color-border)] bg-white hover:border-[var(--color-text-hint)]"
      } ${className}`}
    >
      {checked && <Check className="h-3 w-3 text-white" strokeWidth={3} />}
    </button>
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
    difficulty: "",
    import_batch_id: "",
  });
  const [keywordInput, setKeywordInput] = useState(filters.keyword);
  const [searchDebouncing, setSearchDebouncing] = useState(false);
  const [importBatchInput, setImportBatchInput] = useState(filters.import_batch_id);
  const [subjectOptions, setSubjectOptions] = useState<
    Array<{ id: number; code: string; name: string }>
  >([]);
  useEffect(() => {
    type SubjectNode = {
      id: number;
      code: string;
      name: string;
      path: string;
      level: number;
      children?: SubjectNode[];
    };
    const flattenSubjects = (items: SubjectNode[]): SubjectNode[] =>
      items.flatMap((item) => [item, ...flattenSubjects(item.children ?? [])]);

    apiRequest<{ items: SubjectNode[] }>("/subjects")
      .then((response) => setSubjectOptions(flattenSubjects(response.items ?? [])))
      .catch(() => {});
  }, []);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedQuestionId, setSelectedQuestionId] = useState<number | null>(
    null,
  );
  const [isDetailDrawerOpen, setIsDetailDrawerOpen] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false);
  const [isCommonFilterMenuOpen, setIsCommonFilterMenuOpen] = useState(false);
  const [isMoreFilterOpen, setIsMoreFilterOpen] = useState(false);
  const [exportingFormat, setExportingFormat] = useState<"csv" | "docx" | null>(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<QuestionEditRequest>({});
  const exportMenuRef = useRef<HTMLDivElement | null>(null);
  const commonFilterMenuRef = useRef<HTMLDivElement | null>(null);
  const moreFilterRef = useRef<HTMLDivElement | null>(null);
  const detailScrollRef = useRef<HTMLDivElement | null>(null);

  const canWrite = hasPermission(permissions, "question:write");
  const canDelete = hasPermission(permissions, "question:delete");

  const queryParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      subject_id: filters.subject_id ? Number(filters.subject_id) : undefined,
      is_active: filters.is_active,
      question_type: filters.question_type,
      keyword: filters.keyword,
      year: filters.year,
      difficulty: filters.difficulty ? Number(filters.difficulty) : undefined,
      import_batch_id: filters.import_batch_id || undefined,
    }),
    [page, pageSize, filters],
  );

  const questions = useQuery({
    queryKey: ["questions", queryParams],
    queryFn: () =>
      apiRequest<PaginatedResponse<AdminQuestion>>(
        `/questions${toQuery(queryParams)}`,
      ),
    placeholderData: (previousData) => previousData,
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
      if (state.action === "batch-delete") {
        const ids = Array.from(selectedIds);
        const aggregate: BatchDeleteResult = { success_ids: [], failed_items: [] };

        // 后端单次批量删除最多接收 50 条；前端分块执行，避免 50/100 条每页时直接 422。
        for (let start = 0; start < ids.length; start += BATCH_DELETE_CHUNK_SIZE) {
          const chunk = ids.slice(start, start + BATCH_DELETE_CHUNK_SIZE);
          try {
            const result = await apiRequest<BatchDeleteResult>(
              "/questions/batch-delete",
              {
                method: "POST",
                body: JSON.stringify({ ids: chunk }),
              },
            );
            aggregate.success_ids?.push(
              ...(result.success_ids ?? result.successIds ?? []),
            );
            aggregate.failed_items?.push(
              ...(result.failed_items ?? result.failedItems ?? []),
            );
          } catch (error) {
            const errorText =
              error instanceof Error ? error.message : "批量删除请求失败";
            aggregate.failed_items?.push(
              ...chunk.map((id) => ({ id, error: errorText })),
            );
          }
        }
        return aggregate;
      }
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
        const failurePreview = failedItems
          .slice(0, 5)
          .map((item) => `#${item.id} ${item.error}`)
          .join("；");
        const failures = failedItems.length
          ? `失败 ${failedItems.length} 条：${failurePreview}${failedItems.length > 5 ? "；…" : ""}`
          : "无失败项";
        setMessage(`批量删除完成，成功 ${successIds.length} 条，${failures}。`);
        if (selectedQuestionId !== null && successIds.includes(selectedQuestionId)) {
          setSelectedQuestionId(null);
          setIsDetailDrawerOpen(false);
        }
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
  const hasActiveFilters = Boolean(
    filters.subject_id ||
      filters.question_type ||
      filters.year ||
      filters.is_active ||
      filters.keyword ||
      filters.difficulty ||
      filters.import_batch_id,
  );
  const allChecked =
    items.length > 0 && items.every((item) => selectedIds.has(item.id));
  const selectedQuestion = detail.data;
  const editingSegments = useMemo(
    () => contentSegments(editForm.content),
    [editForm.content],
  );
  const unresolvedEditingTableCount = useMemo(
    () => editingSegments.reduce((count, segment) => {
      const table = normalizeStructuredTableSegment(segment);
      return count + (table?.requires_review ? 1 : 0);
    }, 0),
    [editingSegments],
  );

  const replaceEditingSegments = useCallback(
    (segments: Array<Record<string, unknown>>) => {
      setEditForm((current) => {
        const currentContent = contentRecord(current.content);
        const stem = textFromContent(currentContent);
        return {
          ...current,
          content: {
            ...currentContent,
            stem,
            text: stem,
            render_mode: "segments",
            segments,
          },
        };
      });
    },
    [],
  );

  const dirty = useMemo(() => {
    if (!selectedQuestion) return false;
    const q = selectedQuestion;
    if ((editForm.answer ?? "") !== (q.answer ?? "")) return true;
    if ((editForm.analysis ?? "") !== (q.analysis ?? "")) return true;
    if ((editForm.difficulty ?? null) !== (q.difficulty ?? null)) return true;
    if ((editForm.question_type ?? "") !== (q.question_type ?? "")) return true;
    if ((editForm.subject_id ?? null) !== (q.subject_id ?? null)) return true;
    if (textFromContent(editForm.content) !== textFromContent(q.content)) return true;
    if (JSON.stringify(editForm.options ?? null) !== JSON.stringify(q.options ?? null)) return true;
    if (JSON.stringify(editForm.knowledge_points ?? null) !== JSON.stringify(q.knowledge_points ?? null)) return true;
    return false;
  }, [editForm, selectedQuestion]);

  // Called after an immediate-write image/option mutation: adopt the fresh
  // content/options so the next "保存" does not overwrite the just-written change.
  const handleQuestionMutated = useCallback(
    (question: AdminQuestion) => {
      setEditForm((current) => ({
        ...current,
        content: contentRecord(question.content),
        options: question.options ?? undefined,
      }));
      // Seed the detail cache immediately so `dirty` compares against the
      // fresh state instead of false-positiving during the refetch window.
      queryClient.setQueryData(
        ["questions", selectedQuestionId, "detail"],
        question,
      );
      queryClient.invalidateQueries({ queryKey: ["questions", selectedQuestionId] });
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    [queryClient, selectedQuestionId],
  );

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
    // 与公式库保持一致：筛选刷新时保留详情上下文，等新列表返回后再自动校正选中项。
    setSelectedIds(new Set());
    setIsDetailDrawerOpen(false);
  };

  // 搜索框防抖：停止输入 KEYWORD_DEBOUNCE_MS 后才提交 filters.keyword 并请求
  const keywordTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const importBatchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (keywordTimer.current) clearTimeout(keywordTimer.current);
      if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
    };
  }, []);

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
    if (keywordTimer.current) clearTimeout(keywordTimer.current);
    const next = value.trim();
    if (next === filters.keyword) {
      setSearchDebouncing(false);
      return;
    }
    setSearchDebouncing(true);
    if (next === "") {
      keywordTimer.current = setTimeout(() => {
        updateFilter("keyword", "");
        setSearchDebouncing(false);
      }, 100);
      return;
    }
    keywordTimer.current = setTimeout(() => {
      updateFilter("keyword", next);
      setSearchDebouncing(false);
    }, KEYWORD_DEBOUNCE_MS);
  };

  const handleImportBatchChange = (value: string) => {
    setImportBatchInput(value);
    if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
    if (value.trim() === "") {
      updateFilter("import_batch_id", "");
      return;
    }
    importBatchTimer.current = setTimeout(() => {
      updateFilter("import_batch_id", value.trim());
    }, IMPORT_BATCH_DEBOUNCE_MS);
  };

  const handleResetFilters = () => {
    if (keywordTimer.current) clearTimeout(keywordTimer.current);
    if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
    setKeywordInput("");
    setSearchDebouncing(false);
    setImportBatchInput("");
    setFilters({
      subject_id: "",
      is_active: "",
      question_type: "",
      keyword: "",
      year: "",
      difficulty: "",
      import_batch_id: "",
    });
    setPage(1);
    setSelectedIds(new Set());
    setIsDetailDrawerOpen(false);
  };

  const handlePageSizeChange = (value: string) => {
    setPageSize(Number(value) || 20);
    setPage(1);
  };

  const applyFilterPreset = (
    patch: Partial<typeof filters>,
  ) => {
    if (keywordTimer.current) clearTimeout(keywordTimer.current);
    if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
    const next = {
      subject_id: "",
      is_active: "",
      question_type: "",
      keyword: "",
      year: "",
      difficulty: "",
      import_batch_id: "",
      ...patch,
    };
    setFilters(next);
    setKeywordInput(next.keyword);
    setSearchDebouncing(false);
    setImportBatchInput(next.import_batch_id);
    setPage(1);
    setSelectedIds(new Set());
    setIsDetailDrawerOpen(false);
    setIsCommonFilterMenuOpen(false);
  };

  const handleSaveCurrentFilters = () => {
    try {
      window.localStorage.setItem(
        "admin-question-saved-filter",
        JSON.stringify(filters),
      );
      setMessage("当前筛选条件已保存到本机。 ");
    } catch {
      setMessage("筛选保存失败，请检查浏览器存储权限。 ");
    }
  };

  const handleApplySavedFilters = () => {
    try {
      const raw = window.localStorage.getItem("admin-question-saved-filter");
      if (!raw) {
        setMessage("暂无已保存的筛选条件。 ");
        setIsCommonFilterMenuOpen(false);
        return;
      }
      const parsed = JSON.parse(raw) as Partial<typeof filters>;
      applyFilterPreset(parsed);
    } catch {
      setMessage("已保存的筛选条件无法读取。 ");
      setIsCommonFilterMenuOpen(false);
    }
  };

  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(() => setMessage(null), 3800);
    return () => window.clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    const totalPages = questions.data?.total_pages;
    if (typeof totalPages !== "number") return;
    const safeLastPage = Math.max(1, totalPages);
    if (page > safeLastPage) setPage(safeLastPage);
  }, [page, questions.data?.total_pages]);

  useEffect(() => {
    if (!(isCommonFilterMenuOpen || isMoreFilterOpen || isExportMenuOpen)) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setIsCommonFilterMenuOpen(false);
      setIsMoreFilterOpen(false);
      setIsExportMenuOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isCommonFilterMenuOpen, isMoreFilterOpen, isExportMenuOpen]);

  useEffect(() => {
    if (!isCommonFilterMenuOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (
        commonFilterMenuRef.current &&
        !commonFilterMenuRef.current.contains(event.target as Node)
      ) {
        setIsCommonFilterMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isCommonFilterMenuOpen]);

  useEffect(() => {
    if (!isMoreFilterOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (
        moreFilterRef.current &&
        !moreFilterRef.current.contains(event.target as Node)
      ) {
        setIsMoreFilterOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isMoreFilterOpen]);

  useEffect(() => {
    if (!isExportMenuOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (
        exportMenuRef.current &&
        !exportMenuRef.current.contains(event.target as Node)
      ) {
        setIsExportMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isExportMenuOpen]);

  const handleExport = async (format: "csv" | "docx") => {
    try {
      setExportingFormat(format);
      setIsExportMenuOpen(false);
      const response = await apiRequestBlob("/questions/export", {
        method: "POST",
        timeoutMs: 120_000,
        body: JSON.stringify({
          format,
          ids: selectedIds.size > 0 ? Array.from(selectedIds) : undefined,
          subject_id: filters.subject_id ? Number(filters.subject_id) : undefined,
          is_active:
            filters.is_active === ""
              ? undefined
              : filters.is_active === "true",
          question_type: filters.question_type || undefined,
          keyword: keywordInput.trim() || undefined,
          year: filters.year ? Number(filters.year) : undefined,
          difficulty: filters.difficulty
            ? Number(filters.difficulty)
            : undefined,
          import_batch_id: importBatchInput.trim() || undefined,
        }),
      });
      const url = URL.createObjectURL(response.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download =
        response.filename ?? `questions-export.${format === "docx" ? "docx" : "csv"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(
        format === "csv" ? "CSV 导出已开始。" : "Word 导出已开始。",
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "导出失败，请稍后重试。",
      );
    } finally {
      setExportingFormat(null);
    }
  };

  const toggleAll = () => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allChecked) {
        items.forEach((item) => next.delete(item.id));
      } else {
        items.forEach((item) => next.add(item.id));
      }
      return next;
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

  const prefetchDetail = useCallback(
    (id: number) => {
      void queryClient.prefetchQuery({
        queryKey: ["questions", id, "detail"],
        queryFn: () => apiRequest<AdminQuestionDetail>(`/questions/${id}`),
        staleTime: 30_000,
      });
    },
    [queryClient],
  );

  useEffect(() => {
    if (!items.length) {
      if (!questions.isFetching) setSelectedQuestionId(null);
      return;
    }
    if (selectedQuestionId === null || !items.some((item) => item.id === selectedQuestionId)) {
      setSelectedQuestionId(items[0].id);
      setSelectedVersion(null);
      setEditing(false);
      setEditForm({});
    }
  }, [items, questions.isFetching, selectedQuestionId]);

  useEffect(() => {
    if (selectedQuestionId === null) return;
    const frame = window.requestAnimationFrame(() => {
      detailScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selectedQuestionId]);

  const startEditing = () => {
    if (!selectedQuestion) return;
    // Pre-fill form from current question data
    const content = selectedQuestion.content;
    const clonedContent = JSON.parse(JSON.stringify(content ?? {})) as Record<string, unknown>;
    const stem = textFromContent(clonedContent);
    const rawOpts = resolveQuestionOptions(selectedQuestion);
    let editOpts: Record<string, unknown> | undefined;
    if (rawOpts && typeof rawOpts === "object" && !Array.isArray(rawOpts)) {
      editOpts = rawOpts as Record<string, unknown>;
    } else if (rawOpts) {
      // Convert array/string to Record for editing compatibility
      const norm = normalizeQuestionOptions(rawOpts);
      editOpts = Object.fromEntries(
        norm.map((o) => [o.key, o.text ?? ""]),
      );
    }
    setEditForm({
      subject_id: selectedQuestion.subject_id ?? null,
      question_type: selectedQuestion.question_type || "",
      difficulty: selectedQuestion.difficulty,
      answer: selectedQuestion.answer || "",
      analysis: selectedQuestion.analysis || "",
      options: editOpts,
      content: { ...clonedContent, stem, text: stem },
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
    <div className="space-y-4 pb-10">
      <Card className="overflow-visible border border-[var(--color-border)] bg-white/90 shadow-[var(--shadow-card)]">
        <CardHeader className="space-y-4 pb-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">
                正式题库
              </h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                点击题目查看题干、选项、答案与解析；详情面板用于编辑、版本对比或删除。
              </p>
            </div>

          </div>

          <div className="space-y-3">
            <div className="rounded-[1.35rem] border border-[var(--color-border)] bg-white/90 px-5 py-3 shadow-[0_8px_24px_rgba(40,60,90,0.055)]">
              <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
                <label className="flex h-11 w-full min-w-0 items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-white px-4 shadow-sm transition-all duration-200 hover:border-[var(--color-primary-light)] focus-within:border-[var(--color-primary)] focus-within:shadow-[0_0_0_3px_var(--color-primary-light)] xl:w-[38%] xl:min-w-[440px] xl:max-w-[600px]">
                  <Search className="h-4 w-4 shrink-0 text-[var(--color-text-hint)]" />
                  <input
                    type="text"
                    className="h-9 min-w-0 flex-1 border-0 bg-transparent px-0 text-sm text-[var(--color-text-primary)] outline-none placeholder:text-[var(--color-text-hint)] focus:outline-none"
                    placeholder="搜索题干 / 科目 / 题目编号"
                    value={keywordInput}
                    onChange={(event) => handleKeywordChange(event.target.value)}
                  />
                  <div className="flex shrink-0 items-center gap-1">
                    {(searchDebouncing || (questions.isFetching && Boolean(filters.keyword))) ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-text-hint)]" />
                    ) : null}
                    {keywordInput ? (
                      <button
                        type="button"
                        onClick={() => handleKeywordChange("")}
                        className="grid h-7 w-7 place-items-center rounded-lg text-[var(--color-text-hint)] transition hover:bg-[var(--color-primary-light)] hover:text-[var(--ink)]"
                        aria-label="清空搜索"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </div>
                </label>

                <span
                  className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-semibold text-[var(--ink)] shadow-sm"
                  aria-label="筛选条件"
                >
                  <Filter className="h-4 w-4 text-[var(--color-primary)]" />
                  筛选
                </span>

                <Button
                  variant="ghost"
                  onClick={handleResetFilters}
                  disabled={!hasActiveFilters}
                  className="h-11 shrink-0 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm text-[var(--color-text-secondary)] shadow-sm hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)] disabled:opacity-45"
                >
                  <RotateCcw className="h-4 w-4" />
                  重置
                </Button>

                <div className="hidden h-7 w-px shrink-0 bg-[var(--color-border)] xl:block" />

                <div ref={commonFilterMenuRef} className="relative shrink-0">
                  <button
                    type="button"
                    onClick={() => {
                      setIsCommonFilterMenuOpen((open) => !open);
                      setIsMoreFilterOpen(false);
                      setIsExportMenuOpen(false);
                    }}
                    aria-expanded={isCommonFilterMenuOpen}
                    aria-haspopup="menu"
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
                  >
                    常用筛选
                    <ChevronDown
                      className={`h-4 w-4 text-[var(--color-text-hint)] transition ${isCommonFilterMenuOpen ? "rotate-180" : ""}`}
                    />
                  </button>
                  {isCommonFilterMenuOpen ? (
                    <div className="absolute left-0 top-full z-30 mt-2 min-w-[176px] animate-drop-in overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white p-1.5 shadow-[var(--shadow-floating)]">
                      <button
                        type="button"
                        onClick={() => applyFilterPreset({})}
                        className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                      >
                        全部题目
                      </button>
                      <button
                        type="button"
                        onClick={() => applyFilterPreset({ is_active: "true" })}
                        className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                      >
                        仅看已启用
                      </button>
                      <button
                        type="button"
                        onClick={() => applyFilterPreset({ difficulty: "5" })}
                        className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                      >
                        困难题目
                      </button>
                      <div className="my-1 border-t border-[var(--color-border)]" />
                      <button
                        type="button"
                        onClick={handleApplySavedFilters}
                        className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                      >
                        已保存筛选
                      </button>
                    </div>
                  ) : null}
                </div>

                <button
                  type="button"
                  onClick={handleSaveCurrentFilters}
                  className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
                >
                  <Star className="h-4 w-4 text-[var(--color-text-secondary)]" />
                  保存筛选
                </button>
              </div>
            </div>

            <div className="rounded-[1.35rem] border border-[var(--color-border)] bg-white/90 px-5 py-3 shadow-[0_8px_24px_rgba(40,60,90,0.05)]">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1.16fr_1fr_1fr_0.92fr_1fr_auto] xl:items-center">
                <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    科目
                  </span>
                  <div className="min-w-0 flex-1">
                    <CustomSelect
                      className="h-9 rounded-xl border-0 bg-transparent pl-0 pr-1 shadow-none ring-0 hover:border-transparent"
                      value={filters.subject_id}
                      onChange={(v) => updateFilter("subject_id", v)}
                      options={[
                        { label: "全部科目", value: "" },
                        ...subjectOptions.map((subject) => ({
                          label: subject.name,
                          value: String(subject.id),
                        })),
                      ]}
                    />
                  </div>
                </div>

                <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    题型
                  </span>
                  <div className="min-w-0 flex-1">
                    <CustomSelect
                      className="h-9 rounded-xl border-0 bg-transparent pl-0 pr-1 shadow-none ring-0 hover:border-transparent"
                      placeholder="全部题型"
                      value={filters.question_type}
                      onChange={(v) => updateFilter("question_type", v)}
                      options={QUESTION_TYPE_OPTIONS}
                    />
                  </div>
                </div>

                <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    状态
                  </span>
                  <div className="min-w-0 flex-1">
                    <CustomSelect
                      className="h-9 rounded-xl border-0 bg-transparent pl-0 pr-1 shadow-none ring-0 hover:border-transparent"
                      value={filters.is_active}
                      onChange={(v) => updateFilter("is_active", v)}
                      options={activeOptions}
                    />
                  </div>
                </div>

                <label className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm transition focus-within:border-[var(--color-primary-light)]">
                  <span className="mr-3 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    年份
                  </span>
                  <Input
                    inputMode="numeric"
                    className="h-9 min-w-0 border-0 bg-transparent px-0 text-sm shadow-none focus:bg-transparent focus:ring-0"
                    placeholder="选择年份"
                    value={filters.year}
                    maxLength={4}
                    onChange={(event) =>
                      updateFilter(
                        "year",
                        event.target.value.replace(/\D/g, "").slice(0, 4),
                      )
                    }
                  />
                </label>

                <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    难度
                  </span>
                  <div className="min-w-0 flex-1">
                    <CustomSelect
                      className="h-9 rounded-xl border-0 bg-transparent pl-0 pr-1 shadow-none ring-0 hover:border-transparent"
                      value={filters.difficulty}
                      onChange={(v) => updateFilter("difficulty", v)}
                      options={difficultyOptions}
                    />
                  </div>
                </div>

                <div ref={moreFilterRef} className="relative justify-self-start xl:justify-self-end">
                  <button
                    type="button"
                    onClick={() => {
                      setIsMoreFilterOpen((open) => !open);
                      setIsCommonFilterMenuOpen(false);
                      setIsExportMenuOpen(false);
                    }}
                    aria-expanded={isMoreFilterOpen}
                    aria-haspopup="dialog"
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
                  >
                    <SlidersHorizontal className="h-4 w-4 text-[var(--color-text-secondary)]" />
                    更多条件
                  </button>
                  {isMoreFilterOpen ? (
                    <div className="absolute right-0 top-full z-30 mt-2 w-[320px] animate-drop-in rounded-2xl border border-[var(--color-border)] bg-white p-4 shadow-[var(--shadow-floating)]">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        导入批次 ID
                      </p>
                      <Input
                        className="mt-2 h-10 rounded-xl border-[var(--color-border)] bg-white px-3"
                        placeholder="输入批次 ID 片段"
                        value={importBatchInput}
                        onChange={(event) =>
                          handleImportBatchChange(event.target.value)
                        }
                      />
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {message ? (
            <div className="fixed right-6 top-24 z-[60] animate-fade-in">
              <div
                role="status"
                aria-live="polite"
                className="flex max-w-sm items-center gap-3 rounded-full border border-[var(--color-success)]/30 bg-white/92 py-2 pl-5 pr-2 text-sm font-medium text-[var(--ink)] shadow-[var(--shadow-floating)] backdrop-blur-xl"
              >
                <span>{message}</span>
                <button
                  type="button"
                  onClick={() => setMessage(null)}
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-[var(--color-text-hint)] transition hover:bg-[var(--color-success-light)] hover:text-[var(--color-success)]"
                  aria-label="关闭提示"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ) : null}

          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <section className="min-w-0 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1.25rem] border border-[var(--color-border)] bg-white px-3 py-2.5 shadow-sm">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="inline-flex h-9 items-center gap-1.5 rounded-full bg-[var(--color-primary-light)] px-3 text-xs font-semibold text-[var(--color-primary-dark)]">
                <Layers className="h-3.5 w-3.5" />
                题目总览
              </span>
              <span className="inline-flex h-9 items-center rounded-full bg-[var(--porcelain)] px-3 text-xs font-semibold text-[var(--ink)]">
                当前页 {items.length} 题
              </span>
              {questions.isFetching && !questions.isLoading ? (
                <span className="inline-flex h-9 items-center gap-1.5 rounded-full px-2 text-xs font-medium text-[var(--color-text-hint)]">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  更新中
                </span>
              ) : null}
              {questions.data ? (
                <span className="inline-flex h-9 items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--color-text-secondary)]">
                  共 {questions.data.total} 题
                </span>
              ) : null}
              {hasActiveFilters ? (
                <span className="inline-flex h-9 items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--color-text-secondary)]">
                  已启用筛选
                </span>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {selectedIds.size > 0 ? (
                <span className="inline-flex h-9 items-center rounded-full bg-[var(--color-primary-light)] px-4 text-sm font-semibold text-[var(--color-primary-dark)]">
                  已选 {selectedIds.size} 项
                </span>
              ) : null}
              <button
                type="button"
                role="checkbox"
                aria-checked={allChecked}
                onClick={toggleAll}
                className="inline-flex h-9 items-center gap-2 rounded-full border border-[var(--color-border)] bg-white px-4 text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
              >
                <span
                  aria-hidden="true"
                  className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[4px] border transition-colors ${
                    allChecked
                      ? "border-[var(--color-primary)] bg-[var(--color-primary)]"
                      : "border-[var(--color-border)] bg-white"
                  }`}
                >
                  {allChecked ? (
                    <Check className="h-3 w-3 text-white" strokeWidth={3} />
                  ) : null}
                </span>
                <span className="font-medium">选择当前页</span>
              </button>
              <div ref={exportMenuRef} className="relative">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setIsExportMenuOpen((value) => !value);
                    setIsCommonFilterMenuOpen(false);
                    setIsMoreFilterOpen(false);
                  }}
                  aria-expanded={isExportMenuOpen}
                  aria-haspopup="menu"
                  disabled={!!exportingFormat}
                  className="h-9 rounded-full px-3"
                >
                  <Download className="h-4 w-4" />
                  {exportingFormat
                    ? exportingFormat === "csv"
                      ? "导出 CSV 中..."
                      : "导出 Word 中..."
                    : "导出"}
                  <ChevronDown
                    className={`h-4 w-4 transition ${isExportMenuOpen ? "rotate-180" : ""}`}
                  />
                </Button>
                {isExportMenuOpen ? (
                  <div className="absolute right-0 top-full z-20 mt-2 min-w-[160px] animate-drop-in overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white p-1.5 shadow-[var(--shadow-floating)]">
                    <button
                      type="button"
                      onClick={() => void handleExport("csv")}
                      className="flex w-full items-center rounded-xl px-3 py-2 text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                    >
                      导出 CSV
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleExport("docx")}
                      className="flex w-full items-center rounded-xl px-3 py-2 text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                    >
                      导出 Word
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
              </div>

              <div className={`space-y-2.5 transition-opacity duration-200 ${questions.isFetching && !questions.isLoading ? "opacity-70" : "opacity-100"}`}>
              {questions.isLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }, (_, index) => (
                    <div
                      key={index}
                      className="h-28 animate-pulse rounded-[1.2rem] border border-[var(--color-border)] bg-white/60"
                    />
                  ))}
                </div>
              ) : null}

              <div
                key={`${filters.subject_id}-${filters.question_type}-${filters.is_active}-${filters.year}-${filters.difficulty}-${filters.keyword}-${filters.import_batch_id}-${page}-${pageSize}`}
                className="stagger-enter space-y-2.5"
              >
              {items.map((question) => {
                const stemText =
                  textFromContent(question.content) || `题目 #${question.id}`;
                const isSelected = selectedQuestionId === question.id;
                return (
                  <article
                    key={question.id}
                    onMouseEnter={() => prefetchDetail(question.id)}
                    className={`group rounded-[1.2rem] border transition-all duration-200 ${
                      isSelected
                        ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/30 shadow-sm ring-2 ring-[var(--color-primary-light)]"
                        : "border-[var(--color-border)] bg-white/85 shadow-sm hover:border-[var(--color-primary)]/45 hover:bg-white hover:shadow-[var(--shadow-card)]"
                    }`}
                  >
                    <div className="flex items-start gap-3 px-4 py-3">
                      <CustomCheckbox
                        checked={selectedIds.has(question.id)}
                        onChange={() => toggleOne(question.id)}
                        className="mt-1"
                      />

                      <div className="min-w-0 flex-1">
                        <button
                          type="button"
                          onClick={() => selectQuestion(question.id)}
                          className="w-full text-left"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="inline-flex items-center rounded-full bg-[var(--color-primary-light)] px-2.5 py-1 text-[11px] font-semibold text-[var(--color-primary-dark)]">
                              #{String(question.id).padStart(4, "0")}
                            </span>
                            <TypeBadge type={question.question_type} />
                            <DifficultyBadge difficulty={question.difficulty} />
                            <span
                              className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                                question.is_active
                                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                                  : "border-slate-200 bg-slate-50 text-slate-500"
                              }`}
                            >
                              {question.is_active ? "已启用" : "已停用"}
                            </span>
                          </div>

                          <div className="mt-2 line-clamp-2 text-sm font-medium leading-6 text-[var(--ink)]">
                            <MathFormula text={stemText} />
                          </div>

                          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-text-hint)]">
                            {question.subject_name || question.subject_code ? (
                              <span className="inline-flex items-center gap-1">
                                <BookOpen className="h-3 w-3" />
                                {question.subject_name || question.subject_code}
                              </span>
                            ) : null}
                            {question.year ? (
                              <span className="inline-flex items-center gap-1">
                                <Tag className="h-3 w-3" />
                                {question.year} 年
                              </span>
                            ) : null}
                            {question.updated_at ? (
                              <span className="inline-flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                更新于 {question.updated_at.slice(0, 16).replace("T", " ")}
                              </span>
                            ) : null}
                          </div>
                        </button>
                      </div>

                      <Button
                        variant="ghost"
                        onClick={() => openDetail(question.id)}
                        className="mt-1 h-9 rounded-full px-3 text-xs text-[var(--color-text-secondary)] transition-all duration-200 group-hover:bg-[var(--porcelain)] group-hover:text-[var(--ink)]"
                      >
                        详情
                      </Button>
                    </div>
                  </article>
                );
              })}
              </div>

              {!questions.isLoading && !questions.isError && items.length === 0 ? (
                <div className="flex flex-col items-center gap-3 rounded-[1.6rem] border border-dashed border-[var(--color-border)] bg-white/60 py-16 text-center animate-fade-in">
                  <FileQuestion className="h-12 w-12 text-[var(--color-text-hint)]" />
                  <p className="text-sm font-semibold text-[var(--color-text-secondary)]">
                    暂无匹配题目
                  </p>
                  <p className="text-xs text-[var(--color-text-hint)]">
                    尝试调整搜索关键词或筛选条件
                  </p>
                  {hasActiveFilters ? (
                    <Button variant="secondary" size="sm" onClick={handleResetFilters}>
                      清除筛选
                    </Button>
                  ) : null}
                </div>
              ) : null}

              {questions.isError ? (
                <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-red-200 bg-red-50/45 py-12 text-center animate-fade-in">
                  <AlertCircle className="h-9 w-9 text-red-400" />
                  <div>
                    <p className="text-sm font-semibold text-red-700">题目加载失败</p>
                    <p className="mt-1 text-xs text-red-500">请检查查询条件或后端服务后重试</p>
                  </div>
                  <Button variant="secondary" size="sm" onClick={() => questions.refetch()}>
                    重新加载
                  </Button>
                </div>
              ) : null}
              </div>

              {questions.data && questions.data.total_pages > 1 ? (
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-[1.2rem] border border-[var(--color-border)] bg-white px-3 py-2.5 shadow-sm">
              <div className="flex flex-wrap items-center gap-3 text-sm text-[var(--color-text-secondary)]">
                <span>
                  共 <span className="font-semibold text-[var(--ink)]">{questions.data.total}</span> 条
                </span>
                <span>
                  第 <span className="font-semibold text-[var(--ink)]">{questions.data.page}</span> / {questions.data.total_pages} 页
                </span>
                <CustomSelect
                  className="h-10 min-w-[116px] rounded-full border-[var(--color-border)] bg-white px-3"
                  value={String(pageSize)}
                  onChange={handlePageSizeChange}
                  options={pageSizeOptions}
                  clearable={false}
                />
              </div>

              <div className="flex items-center gap-1.5">
                <button
                  disabled={page <= 1 || questions.isFetching}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="inline-flex h-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-white px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                >
                  上一页
                </button>
                {Array.from(
                  { length: Math.min(questions.data.total_pages, 5) },
                  (_, i) => {
                    const startPage = Math.max(
                      1,
                      Math.min(page - 2, questions.data.total_pages - 4),
                    );
                    const p = startPage + i;
                    if (p > questions.data.total_pages) return null;
                    const isActive = p === page;
                    return (
                      <button
                        key={p}
                        disabled={isActive || questions.isFetching}
                        onClick={() => setPage(p)}
                        className={
                          isActive
                            ? "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-primary-dark)] bg-[var(--color-primary)] text-sm font-bold text-white shadow-sm"
                            : "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-white text-sm font-medium text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]"
                        }
                      >
                        {p}
                      </button>
                    );
                  },
                )}
                <button
                  disabled={page >= (questions.data?.total_pages ?? 1) || questions.isFetching}
                  onClick={() => setPage((p) => p + 1)}
                  className="inline-flex h-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-white px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                >
                  下一页
                </button>
              </div>
            </div>
              ) : null}
            </section>

            <aside className="hidden xl:block xl:min-h-0 xl:self-stretch">
              <div className="xl:sticky xl:top-0 xl:h-dvh xl:min-h-0 xl:overflow-hidden">
              <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[1.45rem] border border-[var(--color-border)] bg-white p-5 shadow-[var(--shadow-card)]">
                {selectedQuestionId === null ? (
                  <div className="flex min-h-0 flex-1 flex-col items-center justify-center text-center animate-fade-in">
                    <div className="flex h-16 w-16 items-center justify-center rounded-3xl border border-[var(--color-border)] bg-[var(--porcelain)] text-[var(--color-text-hint)] shadow-sm">
                      <FileQuestion className="h-8 w-8" />
                    </div>
                    <p className="mt-5 text-2xl font-bold text-[var(--ink)]">
                      选择一道题目
                    </p>
                    <p className="mt-2 max-w-xs text-sm leading-6 text-[var(--color-text-secondary)]">
                      在左侧列表中选择题目，查看详情、编辑内容或进行版本对比。
                    </p>
                  </div>
                ) : selectedQuestion ? (
                  <div
                    ref={detailScrollRef}
                    key={selectedQuestion.id}
                    className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1 animate-fade-in [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
                  >
                    <div className="sticky top-0 z-10 -mx-1 flex items-start justify-between gap-4 rounded-xl bg-white/94 px-1 pb-3 pt-0.5 backdrop-blur supports-[backdrop-filter]:bg-white/82">
                      <div className="min-w-0">
                        <p className="font-mono text-xs uppercase tracking-[0.28em] text-[var(--color-text-hint)]">
                          Question
                        </p>
                        <h3 className="mt-2 text-2xl font-bold text-[var(--ink)]">
                          题目 #{selectedQuestion.id}
                        </h3>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <TypeBadge type={selectedQuestion.question_type} />
                          <DifficultyBadge difficulty={selectedQuestion.difficulty} />
                        </div>
                      </div>
                      <Button
                        variant="secondary"
                        onClick={() => setIsDetailDrawerOpen(true)}
                        className="shrink-0 rounded-full"
                      >
                        <FileQuestion className="h-4 w-4" />
                        完整详情
                      </Button>
                    </div>

                    <section className="rounded-[1.3rem] border border-[var(--color-primary-light)] bg-[var(--porcelain)] p-5 shadow-sm">
                      <p className="mb-3 flex items-center justify-between gap-3 font-semibold text-[var(--ink)]">
                        <span>题干</span>
                        <span className="font-mono text-[11px] font-normal text-[var(--color-text-hint)]">
                          #{selectedQuestion.id}
                        </span>
                      </p>
                      <div className="whitespace-pre-wrap text-base leading-8 text-[var(--ink)]">
                        <QuestionContentRenderer
                          content={selectedQuestion.content}
                          fallbackText={textFromContent(selectedQuestion.content)}
                        />
                      </div>
                    </section>

                    <section className="rounded-[1.3rem] border border-[var(--color-border)] bg-white p-4">
                      <p className="font-semibold text-[var(--ink)]">选项</p>
                      <div className="mt-3">
                        <QuestionOptions
                          options={normalizeQuestionOptions(resolveQuestionOptions(selectedQuestion))}
                        />
                      </div>
                    </section>

                    <section className="rounded-[1.3rem] border border-[var(--color-success-light)] bg-[var(--color-success-light)] p-4">
                      <p className="font-semibold text-[var(--color-success)]">答案</p>
                      <div className="mt-2 whitespace-pre-wrap text-base font-semibold leading-7 text-[var(--ink)]">
                        <MathFormula text={selectedQuestion.answer || "—"} />
                      </div>
                    </section>

                    <section className="rounded-[1.3rem] border border-[var(--color-border)] bg-white p-4">
                      <p className="font-semibold text-[var(--ink)]">解析</p>
                      <div className="mt-3">
                        <QuestionAnalysis value={selectedQuestion.analysis} compact />
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
                ) : detail.isError && selectedQuestionId !== null ? (
                  <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 text-center animate-fade-in">
                    <AlertCircle className="h-9 w-9 text-red-400" />
                    <p className="text-sm font-semibold text-red-700">详情加载失败</p>
                    <Button variant="secondary" size="sm" onClick={() => detail.refetch()}>重新加载</Button>
                  </div>
                ) : (
                  <div className="min-h-0 flex-1 space-y-3 animate-fade-in">
                    <div className="h-16 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/75" />
                    <div className="h-28 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/60" />
                    <div className="h-44 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/50" />
                  </div>
                )}
              </div>
              </div>
            </aside>
          </div>
        </CardContent>
      </Card>

      {selectedIds.size > 0 ? (
        <div className="fixed bottom-8 left-1/2 z-30 -translate-x-1/2 animate-drop-in">
          <div className="flex items-center gap-3 rounded-full border border-[var(--color-border)] bg-white/94 py-2 pl-4 pr-2 shadow-[var(--shadow-floating)] backdrop-blur-xl">
            <span className="text-sm text-[var(--color-text-secondary)]">
              已选 <strong className="text-[var(--ink)]">{selectedIds.size}</strong> 项
            </span>
            <span className="h-5 w-px bg-[var(--color-border)]" />
            {canDelete ? (
              <Button
                variant="danger"
                size="sm"
                disabled={deleteMutation.isPending}
                onClick={() => setConfirmState({ action: "batch-delete" })}
              >
                <Trash2 className="h-3.5 w-3.5" />
                批量删除
              </Button>
            ) : null}
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              className="grid h-8 w-8 place-items-center rounded-full text-[var(--color-text-hint)] transition-colors hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary)]"
              aria-label="清除选择"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      ) : null}

      {/* Detail drawer */}
      {isDetailDrawerOpen && selectedQuestionId !== null ? (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.42)] backdrop-blur-[2px] animate-fade-in"
          onClick={() => setIsDetailDrawerOpen(false)}
        >
          <aside
            className="h-full w-full max-w-3xl overflow-y-auto bg-white p-6 shadow-[var(--shadow-floating)] animate-drop-in"
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
                      <CustomSelect
                        value={String(editForm.subject_id ?? "")}
                        onChange={(v) => setEditForm({ ...editForm, subject_id: v ? Number(v) : null })}
                        options={[{ label: "未设置", value: "" }, ...subjectOptions.map((s) => ({ label: s.name, value: String(s.id) }))]}
                      />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        题型
                      </p>
                      <CustomSelect
                        value={editForm.question_type ?? ""}
                        onChange={(v) =>
                          setEditForm({
                            ...editForm,
                            question_type: v,
                          })
                        }
                        options={canonicalizeQuestionType(editForm.question_type) || !editForm.question_type
                          ? QUESTION_TYPE_OPTIONS
                          : [...QUESTION_TYPE_OPTIONS, { value: editForm.question_type!, label: formatUnknownType(editForm.question_type!), disabled: true }]
                        }
                        clearable={false}
                      />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        难度
                      </p>
                      <CustomSelect
                        value={String(editForm.difficulty ?? 3)}
                        onChange={(v) => setEditForm({ ...editForm, difficulty: Number(v) })}
                        options={[1, 2, 3, 4, 5].map((d) => ({ label: `${d} - ${["简单", "较易", "中等", "较难", "困难"][d - 1]}`, value: String(d) }))}
                      />
                    </div>
                  </div>

                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                      题干
                    </p>
                    <textarea
                      className="min-h-32 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm"
                      value={textFromContent(editForm.content) ?? ""}
                      onChange={(e) => {
                        setEditForm({
                          ...editForm,
                          content: updateStemInContent(
                            editForm.content,
                            e.target.value,
                          ),
                        });
                      }}
                    />
                  </div>

                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                      题干图片
                    </p>
                    {editingSegments.some(isPlainImageSegment) ? (
                      /* 已有图：大图直接占据插入区，hover 替换/删除；无插入按钮 */
                      <div className="space-y-3">
                        {editingSegments.map((seg, index) =>
                          isPlainImageSegment(seg) ? (
                            <div key={index} className="w-full max-w-xl">
                              <QuestionImageField
                                questionId={selectedQuestionId!}
                                target="stem"
                                valueUrl={typeof seg.url === "string" ? seg.url : null}
                                canDelete
                                dirty={dirty}
                                addLabel="更换图片"
                                onMutated={handleQuestionMutated}
                              />
                            </div>
                          ) : null,
                        )}
                      </div>
                    ) : (
                      <QuestionImageField
                        questionId={selectedQuestionId!}
                        target="stem"
                        dirty={dirty}
                        addLabel="插入题干图片"
                        onMutated={handleQuestionMutated}
                      />
                    )}
                  </div>

                  {editingSegments.some((segment) => isTableSegment(segment)) ? (
                    <div className="space-y-4">
                      {editingSegments.map((segment, segmentIndex) => {
                        const table = normalizeStructuredTableSegment(segment);
                        if (!table) return null;
                        return (
                          <StructuredTableEditor
                            key={table.table_id || segmentIndex}
                            segment={table}
                            onChange={(nextTable) => {
                              const next = [...editingSegments];
                              next[segmentIndex] = nextTable;
                              replaceEditingSegments(next);
                            }}
                            onDelete={() => {
                              replaceEditingSegments(
                                editingSegments.filter((_, index) => index !== segmentIndex),
                              );
                            }}
                          />
                        );
                      })}
                    </div>
                  ) : null}

                  {/* Options inline editor */}
                  {(() => {
                    const optList = optionsToKeyValueList(editForm.options);
                    const qtype = canonicalizeQuestionType(editForm.question_type ?? "");
                    const isChoiceType = qtype === "single_choice" || qtype === "multiple_choice";
                    return (
                      <section className="rounded-xl border border-[var(--color-border)]/60 bg-white/80 p-4 shadow-sm">
                        <p className="mb-3 text-xs font-semibold text-[var(--color-text-secondary)]">
                          选项
                        </p>
                        {optList.length === 0 ? (
                          <p className="mb-3 text-sm text-[var(--color-text-hint)]">
                            暂无可编辑选项
                          </p>
                        ) : (
                          <div className="mb-3 space-y-2">
                            {optList.map((opt, index) => {
                              const imgUrl = optionImageUrl(editForm.options, opt.key);
                              return (
                                <div key={index} className="flex items-center gap-2">
                                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--color-primary-light)] text-[10px] font-bold text-[var(--color-primary-dark)]">
                                    {opt.key}
                                  </span>
                                  <input
                                    className="h-9 min-w-0 flex-1 rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15"
                                    value={opt.text}
                                    onChange={(e) => {
                                      const currentOptions = (editForm.options ?? {}) as Record<string, unknown>;
                                      const prevValue = currentOptions[opt.key];
                                      const nextValue =
                                        prevValue && typeof prevValue === "object" && !Array.isArray(prevValue)
                                          ? { ...(prevValue as Record<string, unknown>), text: e.target.value }
                                          : e.target.value;
                                      setEditForm({
                                        ...editForm,
                                        options: { ...currentOptions, [opt.key]: nextValue },
                                      });
                                    }}
                                  />
                                  <QuestionImageField
                                    questionId={selectedQuestionId!}
                                    target={`option:${opt.key}`}
                                    valueUrl={imgUrl}
                                    canDelete={!!imgUrl}
                                    addLabel="上传图片"
                                    dirty={dirty}
                                    variant="row"
                                    onMutated={handleQuestionMutated}
                                  />
                                </div>
                              );
                            })}
                          </div>
                        )}
                        <QuickAddOptions
                          questionId={selectedQuestionId!}
                          existingKeys={optList.map((o) => o.key)}
                          disabled={!isChoiceType}
                          dirty={dirty}
                          onMutated={handleQuestionMutated}
                        />
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

                  {unresolvedEditingTableCount > 0 ? (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      仍有 {unresolvedEditingTableCount} 个结构化表格需要人工核验。请检查单元格和合并关系，并点击“标记人工已核验”后再保存。
                    </div>
                  ) : null}

                  <div className="flex justify-end gap-3">
                    <Button variant="secondary" onClick={cancelEditing}>
                      <X className="h-4 w-4" />
                      取消
                    </Button>
                    <Button
                      variant="primary"
                      onClick={() => updateMutation.mutate()}
                      disabled={updateMutation.isPending || unresolvedEditingTableCount > 0}
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
                      <QuestionContentRenderer
                        content={selectedQuestion.content}
                        fallbackText={textFromContent(selectedQuestion.content)}
                        showTableMetadata
                      />
                    </div>
                  </section>

                  {/* ── Question Images ── */}
                  {(() => {
                    const allUrls = new Map<string, string>();
                    const imageUrlField = selectedQuestion.image_url;
                    if (Array.isArray(imageUrlField)) {
                      imageUrlField.forEach((url: unknown) => {
                        const src = String(url ?? "").trim();
                        if (src) {
                          const key = src.length > 8 && src.endsWith("/") ? src.slice(0, -1) : src;
                          allUrls.set(key, src);
                        }
                      });
                    }
                    if (allUrls.size === 0) return null;
                    const entries = Array.from(allUrls.values());
                    return (
                      <section className="rounded-[1.7rem] border border-[var(--color-border)] bg-white/80 p-5 shadow-sm">
                        <p className="font-display text-lg font-bold text-[var(--ink)] mb-3">题目图片</p>
                        <div className="grid gap-3">
                          {entries.map((src: string, idx: number) => {
                            if (!src) return null;
                            return (
                              <div key={idx} className="relative group/img overflow-hidden rounded-xl border border-[var(--color-border)]/50 bg-[var(--color-bg-input)]/30">
                                <img
                                  src={src}
                                  alt={`题目图片 ${idx + 1}`}
                                  className="max-w-full cursor-zoom-in rounded-lg transition-transform duration-300 group-hover/img:scale-[1.02]"
                                  style={{ maxHeight: "400px", width: "auto", objectFit: "contain" }}
                                  onClick={() => window.open(src, "_blank")}
                                  onError={(e) => {
                                    const target = e.currentTarget;
                                    target.style.display = "none";
                                    if (target.parentElement) target.parentElement.classList.add("hidden");
                                  }}
                                />
                                <div className="absolute inset-0 rounded-xl ring-1 ring-inset ring-black/5 pointer-events-none" />
                              </div>
                            );
                          })}
                        </div>
                      </section>
                    );
                  })()}

                  <section className="rounded-[1.7rem] border border-[var(--color-border)] bg-white/80 p-5">
                    <p className="font-display text-lg font-bold text-[var(--ink)]">
                      选项
                    </p>
                    <div className="mt-3">
                      <QuestionOptions
                        options={normalizeQuestionOptions(
                          resolveQuestionOptions(selectedQuestion),
                        )}
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
                    <div className="mt-3">
                      <QuestionAnalysis value={selectedQuestion.analysis} />
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
