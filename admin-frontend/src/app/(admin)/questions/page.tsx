"use client";

import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
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
  Tag,
  Layers,
  Clock,
  Copy,
  Pencil,
  Trash2,
  Save,
  X,
  RotateCcw,
  SlidersHorizontal,
  Star,
  ArrowLeft,
  ArrowLeftRight,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MathFormula } from "@/components/ui/math-formula";
import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { MultiBlankQuestionOptions, QuestionOptions } from "@/components/question-options";
import { QuestionImageField } from "@/components/questions/question-image-field";
import { QuestionAnalysis } from "@/components/questions/question-analysis";
import { QuestionAnalysisEditor } from "@/components/questions/question-analysis-editor";
import { QuestionKnowledgePointsDisplay, QuestionKnowledgePointsEditor } from "@/components/questions/question-knowledge-points-editor";
import { QuestionVersionPicker } from "@/components/questions/question-version-picker";
import { useAuthStore } from "@/lib/auth/auth-store";
import {
  normalizeBlankOptionGroups,
  normalizeQuestionOptions,
  parseMultiBlankChoiceAnswer,
  resolveBlankOptionGroupsValue,
  resolveQuestionBlankOptionGroups,
  resolveQuestionOptions,
  updateMultiBlankChoiceAnswer,
} from "@/lib/question-options";
import { hasPermission } from "@/lib/permissions/permissions";
import { buildVersionLabels } from "./question-version-labels";
import { resolveAssetUrl } from "@/lib/asset-url";
import { CustomSelect } from "@/components/ui/custom-select";
import { QUESTION_TYPE_OPTIONS, canonicalizeQuestionType, formatUnknownType } from "@/lib/question-types";
import { normalizeStructuredTableSegment } from "@/lib/structured-table";
import { looksLikeProgrammingCode } from "@/lib/math-text";
import { exportQuestions } from "./question-api";

import { useQuestionExport } from "./hooks/use-question-export";
import { useQuestionDelete, type QuestionDeleteIntent } from "./hooks/use-question-delete";
import { useQuestionUpdate } from "./hooks/use-question-update";
import { useQuestionImmediateMutations } from "./hooks/use-question-immediate-mutations";
import { useQuestionEditor } from "./hooks/use-question-editor";
import { useQuestionFilterInteractions } from "./hooks/use-question-filter-interactions";
import { useQuestionDetailNavigation } from "./hooks/use-question-detail-navigation";
import { useQuestionSelection } from "./hooks/use-question-selection";
import {
  resolveQuestionSafeLastPage,
  useQuestionPagination,
} from "./hooks/use-question-pagination";
import { useQuestionSubjectOptions } from "./hooks/use-question-subject-options";
import { useQuestionMenus } from "./hooks/use-question-menus";
import { useQuestionCopy } from "./hooks/use-question-copy";
import { useQuestionVersionHistory } from "./hooks/use-question-version-history";
import { addQuestionCodeSegment, replaceQuestionSegments } from "./question-segment-editing";
import { QuestionCodeEditor } from "./components/question-code-editor";
import { QuestionOptionEditor } from "./components/question-option-editor";
import { QuestionTableEditors } from "./components/question-table-editors";
import { DifficultyBadge } from "./components/question-difficulty-badge";
import { TypeBadge } from "./components/question-type-badge";
import { CustomCheckbox } from "./components/question-custom-checkbox";
import { QuestionAnswerDisplay } from "./components/question-answer-display";
import { QuestionSecondaryInfo } from "./components/question-secondary-info";
import { QuestionVersionComparison } from "./components/question-version-comparison";
import { questionDetailOptions } from "./question-queries";
import { useQuestionDetail, useQuestionList } from "./hooks/use-question-queries";

import { buildQuestionListHref, positiveInt, type QuestionListFilters } from "./question-list-state";
import {
  codeSegmentText,
  comparableText,
  contentSegments,
  isCodeSegment,
  isPlainImageSegment,
  textForStemEditor,
  textFromContent,
} from "./question-content-editing";
import { optionsToKeyValueList } from "./question-option-editing";
import {
  comparableAssetUrl,
  fallbackQuestionImageUrls,
  isMultiBlankChoice,
  isMultiBlankMultipleChoice,
  isMultiChoice,
  normalizedChoiceAnswerKeys,
} from "./question-display-helpers";
import { buildExportPayload } from "./question-export-payload";
import { buildQuestionDeleteFeedback } from "./question-delete-feedback";

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

type ConfirmState = QuestionDeleteIntent | null;

export default function QuestionsPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const permissions = useAuthStore((state) => state.permissions);
  const subjectOptions = useQuestionSubjectOptions();
  const {
    filters,
    page,
    pageSize,
    queryParams,
    setFilters,
    setPage,
    setPageSize,
  } = useQuestionPagination(searchParams);
  const [isDetailDrawerOpen, setIsDetailDrawerOpen] = useState(false);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);
  const editorCallbacks = useRef<{
    setEditing: (value: boolean) => void;
    setEditForm: (value: Record<string, unknown>) => void;
  }>({ setEditing: () => {}, setEditForm: () => {} });
  const detailScrollRef = useRef<HTMLDivElement | null>(null);
  const {
    menus,
    commonFilterMenuRef,
    moreFilterRef,
    exportMenuRef,
    toggleMenu,
    closeCommonFilterMenu,
    closeAllMenus,
  } = useQuestionMenus();

  const canWrite = hasPermission(permissions, "question:write");
  const canDelete = hasPermission(permissions, "question:delete");

  const questions = useQuestionList(queryParams);
  const safeLastPage = resolveQuestionSafeLastPage(questions.data?.total_pages);

  useEffect(() => {
    if (page > safeLastPage) setPage(safeLastPage);
  }, [page, safeLastPage, setPage]);

  const items = useMemo(
    () => questions.data?.items ?? [],
    [questions.data?.items],
  );
  const {
    selectedIds,
    allChecked,
    clearSelection,
    toggleAll,
    toggleOne,
  } = useQuestionSelection({ items });

  const {
    selectedQuestionId,
    selectedQuestionIdRef,
    setSelectedQuestionId,
    selectQuestion,
    openDetail,
    prefetchDetail,
  } = useQuestionDetailNavigation({
    initialSelectedQuestionId: positiveInt(searchParams.get("selected_id")),
    items,
    isFetching: questions.isFetching,
    setEditing: value => editorCallbacks.current.setEditing(value),
    setEditForm: value => editorCallbacks.current.setEditForm(value),
    openDetailDrawer: setIsDetailDrawerOpen,
    prefetch: id => {
      void queryClient.prefetchQuery({
        ...questionDetailOptions(id),
        staleTime: 30_000,
      });
    },
    onScrollTop: () => detailScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" }),
    requestAnimationFrame: callback => window.requestAnimationFrame(callback),
    cancelAnimationFrame: frame => window.cancelAnimationFrame(frame),
  });

  const detail = useQuestionDetail(selectedQuestionId);
  const { exportingFormat, exportQuestion: handleExport } = useQuestionExport({
    buildPayload: useCallback(
      (format: "csv" | "docx") => buildExportPayload(format, filters, selectedIds),
      [filters, selectedIds],
    ),
    download: {
      createObjectURL: blob => URL.createObjectURL(blob),
      revokeObjectURL: url => URL.revokeObjectURL(url),
      createAnchor: () => document.createElement("a"),
      appendAnchor: anchor => document.body.appendChild(anchor),
      removeAnchor: anchor => anchor.remove(),
      clickAnchor: anchor => anchor.click(),
      setTimeout: (callback, delay) => window.setTimeout(callback, delay),
    },
    request: exportQuestions,
    closeMenus: closeAllMenus,
    onMessage: setMessage,
  });
  const {
    versions,
    baseVersionDetail,
    compareVersionDetail,
    baseVersion,
    compareVersion,
    versionHistoryOpen,
    setBaseVersion,
    setCompareVersion,
    toggleVersionHistory,
    swapVersions,
  } = useQuestionVersionHistory(selectedQuestionId);
  const {
    editing, setEditing, editForm, setEditForm, editStemText, setEditStemText,
    dirty, unsavedIntent, setUnsavedIntent, startEditing, cancelEditing,
    closeDetailDrawer, finishCancelEditing, finishCloseDetailDrawer,
  } = useQuestionEditor(detail.data, {
    isDetailDrawerOpen, setIsDetailDrawerOpen, confirmState, detailScrollRef,
  });

  useEffect(() => {
    editorCallbacks.current.setEditing = setEditing;
    editorCallbacks.current.setEditForm = setEditForm;
  }, [setEditForm, setEditing]);

  const deleteMutation = useQuestionDelete(selectedIds, {
    onDeleted: (result, variables) => {
      const feedback = buildQuestionDeleteFeedback({
        result,
        intent: variables,
        selectedQuestionId,
      });
      setMessage(feedback.message);
      if (feedback.closeDetailDrawer) {
        setSelectedQuestionId(null);
        setIsDetailDrawerOpen(false);
      }
      if (feedback.clearSelection) {
        clearSelection();
        setConfirmState(null);
      }
    },
    onError: (error) => {
      setMessage(
        error instanceof Error ? error.message : "删除失败，请稍后重试。",
      );
    },
  });

  const updateMutation = useQuestionUpdate({
    questionId: selectedQuestionId,
    baseline: detail.data,
    form: editForm,
    stemText: editStemText,
  }, {
    onSaved: () => {
      setMessage("题目已更新。");
      setEditing(false);
    },
    onError: (error) => {
      setMessage(
        error instanceof Error ? error.message : "更新失败，请稍后重试。",
      );
    },
  });

  useEffect(() => {
    const nextHref = buildQuestionListHref(filters, page, pageSize, selectedQuestionId);
    const currentHref = `${window.location.pathname}${window.location.search}`;
    if (currentHref !== nextHref) {
      window.history.replaceState(window.history.state, "", nextHref);
    }
  }, [filters, page, pageSize, selectedQuestionId]);

  const hasActiveFilters = Boolean(
    filters.subject_id ||
      filters.question_type ||
      filters.year ||
      filters.is_active !== "true" ||
      filters.keyword ||
      filters.difficulty ||
      filters.import_batch_id ||
      filters.knowledge_point_id,
  );
  const selectedQuestion = detail.data;
  const {
    copyingQuestion,
    copyQuestion: handleCopyQuestion,
  } = useQuestionCopy(selectedQuestion, setMessage);
  const copyQuestionButton = (
    <button
      type="button"
      onClick={handleCopyQuestion}
      disabled={!selectedQuestion || copyingQuestion}
      aria-label="复制题干和选项"
      aria-busy={copyingQuestion}
      title="复制题干和选项（保留 LaTeX）"
      className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-40"
    >
      <Copy className="h-4 w-4" aria-hidden="true" />
    </button>
  );
  const baseVersionData =
    baseVersion === "current" ? selectedQuestion : baseVersionDetail.data;
  const compareVersionData =
    compareVersion === "current" ? selectedQuestion : compareVersionDetail.data;
  // placeholderData 会在新版本到达前保留上一份详情，因此标签也跟随"当前实际展示的数据"
  // 而不是提前切到新版本号，避免短暂出现"新标签 + 旧内容"的错觉。
  const { baseVersionLabel, compareVersionLabel, versionComparisonLoading, pendingVersionLabel } =
    buildVersionLabels({
      base: baseVersion,
      compare: compareVersion,
      baseDetail: baseVersionDetail,
      compareDetail: compareVersionDetail,
    });
  const editingSegments = useMemo(
    () => contentSegments(editForm.content),
    [editForm.content],
  );
  const editingFallbackStemImageUrls = useMemo(
    () =>
      fallbackQuestionImageUrls(
        selectedQuestion?.content,
        selectedQuestion?.image_url,
      ),
    [selectedQuestion?.content, selectedQuestion?.image_url],
  );
  const unresolvedEditingTableCount = useMemo(
    () => editingSegments.reduce((count, segment) => {
      const table = normalizeStructuredTableSegment(segment);
      return count + (table?.requires_review ? 1 : 0);
    }, 0),
    [editingSegments],
  );
  const emptyEditingCodeCount = useMemo(
    () => editingSegments.reduce((count, segment) => {
      if (!isCodeSegment(segment)) return count;
      return count + (comparableText(codeSegmentText(segment)) ? 0 : 1);
    }, 0),
    [editingSegments],
  );

  const replaceEditingSegments = useCallback(
    (segments: Array<Record<string, unknown>>) => {
      setEditForm((current) => replaceQuestionSegments(current, segments));
    },
    [setEditForm],
  );

  const addEditingCodeSegment = useCallback(() => {
    setEditForm(addQuestionCodeSegment);
  }, [setEditForm]);

  const {
    handleQuestionMutated,
    prepareImmediateQuestionMutation,
  } = useQuestionImmediateMutations({
    questionId: selectedQuestionId,
    question: selectedQuestion,
    dirty,
    form: editForm,
    stemText: editStemText,
    unresolvedTableCount: unresolvedEditingTableCount,
    emptyCodeCount: emptyEditingCodeCount,
  }, {
    setForm: setEditForm,
    setStemText: setEditStemText,
    setMessage,
  }, selectedQuestionIdRef);

  const updateFilter = (key: keyof QuestionListFilters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
    // 与公式库保持一致：筛选刷新时保留详情上下文，等新列表返回后再自动校正选中项。
    clearSelection();
    setIsDetailDrawerOpen(false);
  };

  const {
    keywordInput,
    importBatchInput,
    searchDebouncing,
    handleKeywordChange,
    handleImportBatchChange,
    handleResetFilters,
    handlePageSizeChange,
    applyFilterPreset,
    handleSaveCurrentFilters,
    handleApplySavedFilters,
  } = useQuestionFilterInteractions({
    initialFilters: filters,
    onFilterChanged: updateFilter,
    onFilterPresetApplied: (next) => {
      setFilters(next);
      setPage(1);
      clearSelection();
      setIsDetailDrawerOpen(false);
      closeCommonFilterMenu();
    },
    onPageSizeChanged: (nextPageSize) => {
      setPageSize(nextPageSize);
      setPage(1);
    },
    onMessage: (nextMessage) => {
      setMessage(nextMessage);
      closeCommonFilterMenu();
    },
    getStorage: () => window.localStorage,
  });

  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(() => setMessage(null), 3800);
    return () => window.clearTimeout(timer);
  }, [message]);

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
                      toggleMenu("isCommonFilterOpen");
                    }}
                    aria-expanded={menus.isCommonFilterOpen}
                    aria-haspopup="menu"
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
                  >
                    常用筛选
                    <ChevronDown
                      className={`h-4 w-4 text-[var(--color-text-hint)] transition ${menus.isCommonFilterOpen ? "rotate-180" : ""}`}
                    />
                  </button>
                  {menus.isCommonFilterOpen ? (
                    <div className="absolute left-0 top-full z-30 mt-2 min-w-[176px] animate-drop-in overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white p-1.5 shadow-[var(--shadow-floating)]">
                      <button
                        type="button"
                        onClick={() => applyFilterPreset({})}
                        className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                      >
                        全部有效题目
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
                  onClick={() => handleSaveCurrentFilters(filters)}
                  className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
                >
                  <Star className="h-4 w-4 text-[var(--color-text-secondary)]" />
                  保存筛选
                </button>
              </div>
            </div>

            {filters.knowledge_point_id ? (
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-2 text-sm text-blue-800">
                <span className="font-semibold">覆盖率跳转筛选</span>
                <span>知识点 #{filters.knowledge_point_id}</span>
                <button type="button" className="rounded-lg px-2 py-1 text-xs font-semibold hover:bg-blue-100" onClick={() => updateFilter("knowledge_point_id", "")}>清除</button>
              </div>
            ) : null}

            <div className="rounded-[1.35rem] border border-[var(--color-border)] bg-white/90 px-5 py-3 shadow-[0_8px_24px_rgba(40,60,90,0.05)]">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1.16fr_1fr_1fr_0.92fr_1fr_auto] xl:items-center">
                <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    科目
                  </span>
                  <div className="min-w-0 flex-1">
                    <CustomSelect
                      className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
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
                      className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
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
                      className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
                      value={filters.is_active}
                      onChange={(v) => updateFilter("is_active", v)}
                      options={activeOptions}
                    />
                  </div>
                </div>

                <label className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-3 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    年份
                  </span>
                  <input
                    inputMode="numeric"
                    className="h-9 min-w-0 flex-1 border-0 bg-transparent px-0 text-sm text-[var(--color-text-primary)] outline-none shadow-none placeholder:text-[var(--color-text-hint)] focus:border-0 focus:outline-none focus:ring-0"
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
                      className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
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
                      toggleMenu("isMoreFilterOpen");
                    }}
                    aria-expanded={menus.isMoreFilterOpen}
                    aria-haspopup="dialog"
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
                  >
                    <SlidersHorizontal className="h-4 w-4 text-[var(--color-text-secondary)]" />
                    更多条件
                  </button>
                  {menus.isMoreFilterOpen ? (
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
                    toggleMenu("isExportOpen");
                  }}
                  aria-expanded={menus.isExportOpen}
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
                    className={`h-4 w-4 transition ${menus.isExportOpen ? "rotate-180" : ""}`}
                  />
                </Button>
                {menus.isExportOpen ? (
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
                key={`${filters.subject_id}-${filters.question_type}-${filters.is_active}-${filters.year}-${filters.difficulty}-${filters.keyword}-${filters.import_batch_id}-${filters.knowledge_point_id}-${page}-${pageSize}`}
                className="stagger-enter space-y-2.5"
              >
              {items.map((question) => {
                const stemText =
                  textForStemEditor(question.content) || `题目 #${question.id}`;
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
                            {looksLikeProgrammingCode(stemText) ? stemText : <MathFormula text={stemText} />}
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
              <div className="flex h-full min-h-0 flex-col overflow-hidden border-l border-slate-200 bg-white p-5">
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
                    <div className="sticky top-0 z-10 -mx-1 flex items-start justify-between gap-4 border-b border-slate-200 bg-white/96 px-1 pb-4 pt-0.5 backdrop-blur supports-[backdrop-filter]:bg-white/88">
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
                      <div className="flex shrink-0 items-center gap-1.5">
                        {copyQuestionButton}
                        <Button
                          variant="secondary"
                          onClick={() => setIsDetailDrawerOpen(true)}
                          className="shrink-0 rounded-lg border-slate-200 bg-white shadow-none transition hover:bg-slate-50"
                        >
                          <FileQuestion className="h-4 w-4" />
                          完整详情
                        </Button>
                      </div>
                    </div>

                    <section className="rounded-lg border border-slate-200 bg-slate-50/60 p-4">
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
                          preserveCodeText
                        />
                      </div>
                    </section>

                    <section className="rounded-xl border border-slate-200 bg-white p-4">
                      <p className="font-semibold text-[var(--ink)]">选项</p>
                      <div className="mt-3">
                        {isMultiBlankChoice(selectedQuestion.question_type) ? (
                          <MultiBlankQuestionOptions
                            groups={resolveQuestionBlankOptionGroups(selectedQuestion)}
                          />
                        ) : (
                          <QuestionOptions
                            options={normalizeQuestionOptions(resolveQuestionOptions(selectedQuestion))}
                          />
                        )}
                      </div>
                    </section>

                    <section className="rounded-xl border border-slate-200 bg-white p-4">
                      <p className="font-semibold text-slate-950">答案</p>
                      <div className="mt-2 inline-flex min-h-9 items-center rounded-md bg-slate-50 px-2.5 py-1.5 text-sm font-semibold leading-6 text-slate-800">
                        <QuestionAnswerDisplay
                          questionType={selectedQuestion.question_type}
                          answer={selectedQuestion.answer}
                        />
                      </div>
                    </section>

                    <section className="rounded-xl border border-slate-200 bg-white p-4">
                      <p className="font-semibold text-slate-950">解析</p>
                      <div className="mt-3">
                        <QuestionAnalysis value={selectedQuestion.analysis} compact />
                      </div>
                    </section>

                    <QuestionSecondaryInfo question={selectedQuestion} />

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

      {message ? (
        <div className="fixed right-6 top-24 z-[60] max-w-[calc(100vw-3rem)] animate-fade-in">
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
              onClick={clearSelection}
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
          className="fixed inset-0 z-40 flex justify-end bg-slate-950/25 backdrop-blur-[1px] animate-fade-in"
          onClick={closeDetailDrawer}
        >
          <aside
            role="dialog"
            aria-modal="true"
            aria-label={editing ? "编辑题目" : "题目详情"}
            className="question-detail-drawer h-full w-full max-w-[880px] overflow-y-auto overscroll-contain border-l border-slate-200/80 bg-white shadow-[-18px_0_52px_rgba(15,23,42,0.12)] animate-drop-in"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="sticky top-0 z-20 flex min-h-16 flex-col items-stretch justify-between gap-3 border-b border-slate-200/80 bg-white/95 px-4 py-3 backdrop-blur-xl sm:flex-row sm:items-center sm:gap-4 sm:px-7">
              <div className="flex min-w-0 items-center gap-3">
                {editing ? (
                  <button
                    type="button"
                    onClick={cancelEditing}
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
                    aria-label="返回题目详情"
                  >
                    <ArrowLeft className="h-4 w-4" />
                  </button>
                ) : null}
                <div className="min-w-0">
                  <div className="flex items-center gap-2.5">
                    <h3 className="truncate text-[17px] font-semibold tracking-[-0.01em] text-slate-950">
                      {editing ? "编辑题目" : "题目详情"}
                    </h3>
                    {editing && dirty ? (
                      <span className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">未保存</span>
                    ) : null}
                    {!editing ? (
                      <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] font-medium text-slate-500">
                        #{selectedQuestionId}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    {editing ? "修改题目内容、知识点与解析模块" : "查看题目内容与结构化解析信息"}
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5 self-end sm:self-auto">
                {!editing ? copyQuestionButton : null}
                {!editing && canWrite ? (
                  <Button variant="secondary" size="sm" onClick={startEditing} className="border-slate-200 bg-white shadow-none">
                    <Pencil className="h-3.5 w-3.5" />
                    编辑
                  </Button>
                ) : null}
                {!editing && canDelete ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-slate-500 hover:bg-red-50 hover:text-red-600"
                    onClick={() =>
                      setConfirmState({
                        action: "delete",
                        id: selectedQuestionId,
                      })
                    }
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </Button>
                ) : null}
                <button
                  type="button"
                  onClick={closeDetailDrawer}
                  className="grid h-9 w-9 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-900"
                  aria-label="关闭题目详情"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </header>

            {selectedQuestion ? (
              editing ? (
                /* ===== Edit form ===== */
                <div className="question-drawer-edit px-7 pb-24 pt-1">
                  <section className="border-b border-slate-200 py-5">
                    <div className="grid gap-x-4 gap-y-3 md:grid-cols-3">
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        科目
                      </p>
                      <CustomSelect
                        value={String(editForm.subject_id ?? "")}
                        onChange={(v) => setEditForm({ ...editForm, subject_id: v ? Number(v) : null })}
                        options={subjectOptions.map((s) => ({ label: s.name, value: String(s.id) }))}
                        placeholder="选择科目"
                        clearable={false}
                        className="rounded-lg border-slate-200 bg-slate-50/60 shadow-none hover:border-slate-400"
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
                        className="rounded-lg border-slate-200 bg-slate-50/60 shadow-none hover:border-slate-400"
                      />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        难度
                      </p>
                      <CustomSelect
                        value={String(editForm.difficulty ?? 3)}
                        onChange={(v) => setEditForm({ ...editForm, difficulty: Number(v) })}
                        options={["简单", "较易", "中等", "较难", "困难"].map((label, index) => ({ label, value: String(index + 1) }))}
                        clearable={false}
                        className="rounded-lg border-slate-200 bg-slate-50/60 shadow-none hover:border-slate-400"
                      />
                    </div>
                    </div>
                  </section>

                  <section className="border-b border-slate-200 py-5">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-950">题干</p>
                        <p className="mt-1 text-[11px] text-slate-400">编辑题目正文、代码块与题干图片</p>
                      </div>
                    </div>
                    <textarea
                      wrap="soft"
                      spellCheck={false}
                      className="min-h-36 w-full resize-y overflow-x-hidden whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-3 text-sm leading-7 text-slate-800 outline-none transition [overflow-wrap:anywhere] placeholder:text-slate-300 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
                      value={editStemText}
                      onChange={(e) => setEditStemText(e.target.value)}
                    />
                    <div className="mt-4">
                      <p className="mb-2 text-xs font-medium text-slate-500">题干图片</p>
                    {editingSegments.some(isPlainImageSegment) ||
                    editingFallbackStemImageUrls.length > 0 ? (
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
                                beforeDirtyMutation={prepareImmediateQuestionMutation}
                                addLabel="更换图片"
                                onMutated={handleQuestionMutated}
                              />
                            </div>
                          ) : null,
                        )}
                        {editingFallbackStemImageUrls.map((url, index) => (
                          <div key={`legacy-${url}-${index}`} className="w-full max-w-xl">
                            <QuestionImageField
                              questionId={selectedQuestionId!}
                              target="stem"
                              valueUrl={url}
                              canDelete
                              dirty={dirty}
                              beforeDirtyMutation={prepareImmediateQuestionMutation}
                              addLabel="更换图片"
                              onMutated={handleQuestionMutated}
                            />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <QuestionImageField
                        questionId={selectedQuestionId!}
                        target="stem"
                        dirty={dirty}
                        beforeDirtyMutation={prepareImmediateQuestionMutation}
                        addLabel="插入题干图片"
                        onMutated={handleQuestionMutated}
                      />
                    )}
                    </div>
                  </section>

                  <QuestionTableEditors
                    segments={editingSegments}
                    onReplace={replaceEditingSegments}
                  />
                  <QuestionCodeEditor
                    segments={editingSegments}
                    onReplace={replaceEditingSegments}
                    onAdd={addEditingCodeSegment}
                  />

                  <QuestionOptionEditor
                    editForm={editForm}
                    editStemText={editStemText}
                    setEditForm={setEditForm}
                    selectedQuestionId={selectedQuestionId!}
                    dirty={dirty}
                    beforeDirtyMutation={prepareImmediateQuestionMutation}
                    onMutated={handleQuestionMutated}
                  />

                  {/* Answer editor */}
                  {isMultiBlankChoice(editForm.question_type ?? "") ? (
                    (() => {
                      const groups = normalizeBlankOptionGroups(
                        resolveBlankOptionGroupsValue(editForm.content),
                      );
                      const multiSelect = isMultiBlankMultipleChoice(
                        editForm.question_type ?? "",
                      );
                      const parsedAnswer = parseMultiBlankChoiceAnswer(editForm.answer);
                      const parsedAnswerMap = new Map(
                        parsedAnswer.map((item) => [item.blankId, item.optionKey]),
                      );
                      const blankIds =
                        groups.length > 0
                          ? groups.map((group) => group.id)
                          : parsedAnswer.map((item) => item.blankId);

                      return (
                        <section className="border-b border-slate-200 py-5">
                          <div className="mb-4">
                            <p className="text-sm font-semibold text-slate-950">答案</p>
                            <p className="mt-1 text-[11px] text-slate-400">
                              {multiSelect
                                ? "点击选项可快速多选或取消；也可手动填写多个字母（如 A,C）"
                                : "点击选项可快速填入单选答案；再次点击已选项可清空"}
                            </p>
                          </div>

                          {blankIds.length > 0 ? (
                            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
                              {blankIds.map((blankId, index) => {
                                const group = groups.find((g) => g.id === blankId);
                                const currentLetters = (parsedAnswerMap.get(blankId) ?? "")
                                  .split(",")
                                  .map((l) => l.trim().toUpperCase())
                                  .filter(Boolean);
                                return (
                                <div
                                  key={`${blankId}-${index}`}
                                  className="flex items-center gap-4 border-b border-slate-100 px-4 py-3 last:border-b-0"
                                >
                                  <span className="w-8 shrink-0 text-sm font-medium text-slate-900">
                                    {blankId}
                                  </span>
                                  <div className="min-w-0 flex-1 space-y-2">
                                    {group && group.options.length > 0 ? (
                                      <div className="flex flex-wrap items-center gap-1.5">
                                        {group.options.map((opt) => {
                                          const normalizedKey = opt.key.trim().toUpperCase();
                                          const selected = currentLetters.includes(normalizedKey);
                                          return (
                                            <button
                                              key={opt.key}
                                              type="button"
                                              className={`inline-flex h-8 min-w-9 items-center justify-center rounded-md border px-3 text-sm font-medium transition ${
                                                selected
                                                  ? "border-slate-900 bg-slate-900 text-white"
                                                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-900"
                                              }`}
                                              title={opt.text ? `${opt.key}. ${opt.text}` : `选择 ${opt.key}`}
                                              aria-pressed={selected}
                                              onClick={() =>
                                                setEditForm((current) => ({
                                                  ...current,
                                                  answer: updateMultiBlankChoiceAnswer(
                                                    current.answer,
                                                    blankIds,
                                                    blankId,
                                                    !multiSelect && selected ? "" : normalizedKey,
                                                    multiSelect,
                                                  ),
                                                }))
                                              }
                                            >
                                              {opt.key}
                                            </button>
                                          );
                                        })}
                                      </div>
                                    ) : null}
                                    <Input
                                      value={parsedAnswerMap.get(blankId) ?? ""}
                                      aria-label={`${blankId} 答案`}
                                      placeholder={multiSelect ? "如 A,C" : "如 A"}
                                      className="h-8 max-w-32 border-slate-200 bg-slate-50/60 text-center text-xs shadow-none focus:bg-white"
                                      onChange={(e) =>
                                        setEditForm((current) => ({
                                          ...current,
                                          answer: updateMultiBlankChoiceAnswer(
                                            current.answer,
                                            blankIds,
                                            blankId,
                                            e.target.value,
                                          ),
                                        }))
                                      }
                                    />
                                  </div>
                                </div>
                                );
                              })}
                            </div>
                          ) : (
                            <Input
                              value={editForm.answer ?? ""}
                              className="border-slate-200 bg-slate-50/60 shadow-none focus:bg-white"
                              onChange={(e) =>
                                setEditForm({ ...editForm, answer: e.target.value })
                              }
                            />
                          )}
                        </section>
                      );
                    })()
                  ) : optionsToKeyValueList(editForm.options).length > 0 ? (
                    <section className="border-b border-slate-200 py-5">
                      <div className="mb-4">
                        <p className="text-sm font-semibold text-slate-950">答案</p>
                        <p className="mt-1 text-[11px] text-slate-400">快速选择正确选项，也可直接编辑答案内容</p>
                      </div>
                      <p className="mb-2 text-[11px] font-medium text-slate-500">快速选择</p>
                      {editForm.question_type &&
                      isMultiChoice(editForm.question_type) ? (
                        <p className="mb-2 text-[10px] text-[var(--color-text-hint)]">
                          多选：单击切换各选项，以逗号分隔
                        </p>
                      ) : null}
                      <div className="mb-3 flex flex-wrap gap-2">
                        {optionsToKeyValueList(editForm.options).map((opt) => {
                          const normalizedKey = opt.key.trim().toUpperCase();
                          const selected = isMultiChoice(
                            editForm.question_type ?? "",
                          )
                            ? normalizedChoiceAnswerKeys(editForm.answer).includes(normalizedKey)
                            : String(editForm.answer ?? "").trim().toUpperCase() === normalizedKey;
                          return (
                            <button
                              key={opt.key}
                              type="button"
                              className={`inline-flex h-8 min-w-9 items-center justify-center rounded-md border px-3 text-sm font-medium transition ${
                                selected
                                  ? "border-slate-900 bg-slate-900 text-white"
                                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-900"
                              }`}
                              onClick={() => {
                                if (
                                  isMultiChoice(editForm.question_type ?? "")
                                ) {
                                  const keys = normalizedChoiceAnswerKeys(editForm.answer);
                                  const next = keys.includes(normalizedKey)
                                    ? keys.filter((key) => key !== normalizedKey)
                                    : [...keys, normalizedKey];
                                  setEditForm({
                                    ...editForm,
                                    answer: next.join(","),
                                  });
                                } else {
                                  setEditForm({
                                    ...editForm,
                                    answer: selected ? "" : normalizedKey,
                                  });
                                }
                              }}
                            >
                              {opt.key}
                            </button>
                          );
                        })}
                      </div>
                      <div className="mt-4 space-y-1.5">
                        <p className="text-[11px] font-medium text-slate-500">答案内容</p>
                        <Input
                          value={editForm.answer ?? ""}
                          className="border-slate-200 bg-slate-50/60 shadow-none focus:bg-white"
                          onChange={(e) =>
                            setEditForm({ ...editForm, answer: e.target.value })
                          }
                        />
                      </div>
                    </section>
                  ) : (
                    <section className="border-b border-slate-200 py-5">
                      <p className="mb-3 text-sm font-semibold text-slate-950">答案</p>
                      <div>
                        <Input
                          value={editForm.answer ?? ""}
                          className="border-slate-200 bg-slate-50/60 shadow-none focus:bg-white"
                          onChange={(e) =>
                            setEditForm({ ...editForm, answer: e.target.value })
                          }
                        />
                      </div>
                    </section>
                  )}

                  <QuestionKnowledgePointsEditor
                    value={editForm.knowledge_points ?? []}
                    onChange={(knowledgePoints) =>
                      setEditForm((current) => ({
                        ...current,
                        knowledge_points: knowledgePoints,
                      }))
                    }
                  />

                  <QuestionAnalysisEditor
                    value={editForm.analysis ?? ""}
                    onChange={(analysis) =>
                      setEditForm((current) => ({ ...current, analysis }))
                    }
                  />

                  {unresolvedEditingTableCount > 0 ? (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      仍有 {unresolvedEditingTableCount} 个结构化表格需要人工核验。请检查单元格和合并关系，并点击“标记人工已核验”后再保存。
                    </div>
                  ) : null}
                  {emptyEditingCodeCount > 0 ? (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      仍有 {emptyEditingCodeCount} 个代码块正文为空。请输入代码内容，或删除空代码块后再保存。
                    </div>
                  ) : null}

                  <div className="sticky bottom-0 z-10 -mx-7 -mb-24 mt-8 flex justify-end gap-2 border-t border-slate-200 bg-white/96 px-7 py-4 shadow-[0_-12px_30px_rgba(15,23,42,0.04)] backdrop-blur-xl">
                    <Button variant="secondary" className="min-w-24 border-slate-200 bg-white shadow-none" onClick={cancelEditing}>
                      <X className="h-4 w-4" />
                      取消
                    </Button>
                    <Button
                      variant="primary"
                      className="min-w-28 shadow-none"
                      onClick={() => updateMutation.mutate()}
                      disabled={!dirty || updateMutation.isPending || unresolvedEditingTableCount > 0 || emptyEditingCodeCount > 0}
                    >
                      <Save className="h-4 w-4" />
                      {updateMutation.isPending ? "保存中..." : "保存修改"}
                    </Button>
                  </div>
                </div>
              ) : (
                /* ===== Detail view ===== */
                <div className="question-drawer-detail px-7 py-6 text-sm">
                  <section className="border-b border-slate-200 pb-6">
                    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-950">
                        题干
                      </p>
                      <div className="flex flex-wrap items-center gap-2">
                        <TypeBadge type={selectedQuestion.question_type} />
                        <DifficultyBadge
                          difficulty={selectedQuestion.difficulty}
                        />
                      </div>
                    </div>
                    <div className="whitespace-pre-wrap text-[15px] leading-7 text-slate-700">
                      <QuestionContentRenderer
                        content={selectedQuestion.content}
                        fallbackText={textFromContent(selectedQuestion.content)}
                        showTableMetadata
                        preserveCodeText
                      />
                    </div>
                  </section>

                  {/* ── Legacy/fallback question images ── */}
                  {(() => {
                    // Structured content already renders image segments above.
                    // `image_url` is a legacy mirror on many records; rendering
                    // both produced duplicate images in the detail drawer.
                    const fallbackUrls = fallbackQuestionImageUrls(
                      selectedQuestion.content,
                      selectedQuestion.image_url,
                    );
                    if (fallbackUrls.length === 0) return null;
                    return (
                      <section className="border-b border-slate-200 py-6">
                        <p className="mb-3 text-sm font-semibold text-slate-950">其他题目图片</p>
                        <div className="grid gap-3">
                          {fallbackUrls.map((raw, idx) => {
                            const src = resolveAssetUrl(raw) || raw;
                            return (
                              <a
                                key={`${comparableAssetUrl(raw)}-${idx}`}
                                href={src}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="group/img relative block overflow-hidden rounded-xl border border-[var(--color-border)]/50 bg-[var(--color-bg-input)]/30 focus:outline-none focus:ring-2 focus:ring-slate-300"
                                aria-label={`在新窗口查看题目图片 ${idx + 1}`}
                              >
                                <img
                                  src={src}
                                  alt={`题目图片 ${idx + 1}`}
                                  className="max-w-full cursor-zoom-in rounded-lg transition-transform duration-300 group-hover/img:scale-[1.02]"
                                  style={{ maxHeight: "400px", width: "auto", objectFit: "contain" }}
                                  onError={(e) => {
                                    const target = e.currentTarget;
                                    target.style.display = "none";
                                    target.closest("a")?.classList.add("hidden");
                                  }}
                                />
                                <div className="pointer-events-none absolute inset-0 rounded-xl ring-1 ring-inset ring-black/5" />
                              </a>
                            );
                          })}
                        </div>
                      </section>
                    );
                  })()}

                  <section className="border-b border-slate-200 py-6">
                    <p className="text-sm font-semibold text-slate-950">
                      选项
                    </p>
                    <div className="mt-3">
                      {isMultiBlankChoice(selectedQuestion.question_type) ? (
                        <MultiBlankQuestionOptions
                          groups={resolveQuestionBlankOptionGroups(selectedQuestion)}
                        />
                      ) : (
                        <QuestionOptions
                          options={normalizeQuestionOptions(
                            resolveQuestionOptions(selectedQuestion),
                          )}
                        />
                      )}
                    </div>
                  </section>

                  <section className="border-b border-slate-200 py-6">
                    <p className="text-sm font-semibold text-slate-950">
                      答案
                    </p>
                    <div className="mt-3 inline-flex min-h-10 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[15px] font-semibold leading-6 text-slate-800">
                      <QuestionAnswerDisplay
                        questionType={selectedQuestion.question_type}
                        answer={selectedQuestion.answer}
                      />
                    </div>
                  </section>

                  <section className="border-b border-slate-200 py-6">
                    <p className="text-sm font-semibold text-slate-950">
                      解析
                    </p>
                    <div className="mt-3">
                      <QuestionAnalysis value={selectedQuestion.analysis} />
                    </div>
                  </section>

                  <section className="border-b border-slate-200 py-6">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-950">知识点与难度</p>
                      <DifficultyBadge difficulty={selectedQuestion.difficulty} />
                    </div>
                    <QuestionKnowledgePointsDisplay value={selectedQuestion.knowledge_points} />
                  </section>

                  <section className="py-6">
                    <button
                      type="button"
                      onClick={toggleVersionHistory}
                      className="flex w-full items-center justify-between gap-4 rounded-lg px-1 py-1 text-left transition hover:bg-slate-50"
                      aria-expanded={versionHistoryOpen}
                    >
                      <div>
                        <p className="text-sm font-semibold text-slate-950">版本历史</p>
                        <p className="mt-1 text-[11px] leading-5 text-slate-400">
                          可按时间、修改人或修改原因查找，并支持任意两个版本对比。
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-medium text-slate-500">
                          {versions.data?.total ?? 0} 个版本
                        </span>
                        <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${versionHistoryOpen ? "rotate-180" : ""}`} />
                      </div>
                    </button>

                    {versionHistoryOpen ? (
                      <div className="mt-4 animate-fade-in">
                        {(versions.data?.total ?? 0) === 0 && !versions.isFetching ? (
                          <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-5 text-center text-xs text-slate-400">
                            暂无历史版本
                          </div>
                        ) : (
                          <>
                            <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-3">
                              <div className="grid items-end gap-3 md:grid-cols-[minmax(0,1fr)_44px_minmax(0,1fr)]">
                                <div className="min-w-0">
                                  <p className="mb-2 px-0.5 text-[11px] font-medium text-slate-500">基准版本</p>
                                  <QuestionVersionPicker
                                    value={baseVersion}
                                    onChange={setBaseVersion}
                                    versions={versions.data?.items ?? []}
                                    disabledValue={compareVersion}
                                    loading={versions.isFetching && !versions.data}
                                  />
                                </div>
                                <Button
                                  type="button"
                                  variant="secondary"
                                  size="sm"
                                  className="h-10 w-11 rounded-xl p-0 shadow-none"
                                  disabled={compareVersion === null}
                                  title="交换对比版本"
                                  aria-label="交换基准版本和对比版本"
                                  onClick={swapVersions}
                                >
                                  <ArrowLeftRight className="h-4 w-4" />
                                </Button>
                                <div className="min-w-0">
                                  <p className="mb-2 px-0.5 text-[11px] font-medium text-slate-500">对比版本</p>
                                  <QuestionVersionPicker
                                    value={compareVersion}
                                    onChange={setCompareVersion}
                                    versions={versions.data?.items ?? []}
                                    disabledValue={baseVersion}
                                    disabled={compareVersion === null && !versions.isFetching && (versions.data?.total ?? 0) === 0}
                                    loading={versions.isFetching && !versions.data}
                                  />
                                </div>
                              </div>
                              <p className="mt-3 text-[10px] leading-5 text-slate-400">
                                可按日期精确筛选，也可按“今天 / 本周 / 上周 / 更早”浏览；支持搜索版本号、修改人或修改原因。切换版本时会保留当前对比区域，避免页面跳动。
                              </p>
                            </div>

                            <QuestionVersionComparison
                              enabled={compareVersion !== null}
                              questionType={selectedQuestion.question_type}
                              left={baseVersionData}
                              right={compareVersionData}
                              leftTitle={baseVersionLabel}
                              rightTitle={compareVersionLabel}
                              loading={versionComparisonLoading}
                              pendingLabel={pendingVersionLabel}
                            />
                          </>
                        )}
                      </div>
                    ) : null}
                  </section>

                  <QuestionSecondaryInfo question={selectedQuestion} />
                </div>
              )
            ) : detail.isError ? (
              <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 px-7 text-center">
                <AlertCircle className="h-8 w-8 text-red-400" />
                <div>
                  <p className="text-sm font-semibold text-red-700">题目详情加载失败</p>
                  <p className="mt-1 text-xs text-slate-400">请检查网络连接后重试。</p>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="border-slate-200 bg-white shadow-none"
                  onClick={() => detail.refetch()}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  重新加载
                </Button>
              </div>
            ) : (
              <div className="space-y-3 px-7 py-6">
                <div className="h-16 animate-pulse rounded-xl bg-slate-100" />
                <div className="h-32 animate-pulse rounded-xl bg-slate-100/80" />
                <div className="h-24 animate-pulse rounded-xl bg-slate-100/60" />
              </div>
            )}
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={unsavedIntent !== null}
        title={unsavedIntent === "close-drawer" ? "关闭题目编辑？" : "放弃当前修改？"}
        description={
          unsavedIntent === "close-drawer"
            ? "当前题目还有未保存修改。关闭后这些修改不会保留。"
            : "当前题目还有未保存修改。返回详情后这些修改不会保留。"
        }
        confirmText="放弃修改"
        danger
        onCancel={() => setUnsavedIntent(null)}
        onConfirm={() => {
          if (unsavedIntent === "close-drawer") finishCloseDetailDrawer();
          else if (unsavedIntent === "cancel-edit") finishCancelEditing();
        }}
      />

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
