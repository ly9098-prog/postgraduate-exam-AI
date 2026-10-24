"use client";

import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import {
  BookOpen,
  Tag,
  Clock,
  Copy,
  Trash2,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { MathFormula } from "@/components/ui/math-formula";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { buildVersionLabels } from "./question-version-labels";
import { QuestionListFeedback } from "./question-list-feedback";
import { QuestionSideDetailPanel } from "./question-side-detail-panel";
import { QuestionDrawerHeader } from "./question-drawer-header";
import { QuestionDrawerBody } from "./question-drawer-body";
import { QuestionFilterToolbar } from "./question-filter-toolbar";
import { QuestionListToolbar } from "./question-list-toolbar";
import { CustomSelect } from "@/components/ui/custom-select";
import { looksLikeProgrammingCode } from "@/lib/math-text";
import { exportQuestions } from "./question-api";

import { useQuestionExport } from "./hooks/use-question-export";
import { useQuestionDeleteDialog } from "./hooks/use-question-delete-dialog";
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
import { useQuestionFeedback } from "./hooks/use-question-feedback";
import { useQuestionListInteractions } from "./hooks/use-question-list-interactions";
import { useQuestionListUrlSync } from "./hooks/use-question-list-url-sync";
import { useQuestionEditingProjection } from "./hooks/use-question-editing-projection";
import { useQuestionToolbarState } from "./hooks/use-question-toolbar-state";
import { DifficultyBadge } from "./components/question-difficulty-badge";
import { TypeBadge } from "./components/question-type-badge";
import { CustomCheckbox } from "./components/question-custom-checkbox";
import { questionDetailOptions } from "./question-queries";
import { useQuestionDetail, useQuestionList } from "./hooks/use-question-queries";

import { positiveInt } from "./question-list-state";
import {
  textForStemEditor,
} from "./question-content-editing";
import { buildExportPayload } from "./question-export-payload";
import { buildQuestionPaginationViewport } from "./question-pagination-viewport";

const pageSizeOptions = [
  { label: "20 条/页", value: "20" },
  { label: "50 条/页", value: "50" },
  { label: "100 条/页", value: "100" },
];

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
  const { message, setMessage, clearMessage } = useQuestionFeedback();
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
  const deleteDialog = useQuestionDeleteDialog(selectedIds, selectedQuestionId, {
    clearSelection,
    setSelectedQuestionId,
    closeDetailDrawer: () => setIsDetailDrawerOpen(false),
    onMessage: setMessage,
  });
  const {
    confirmState,
    deleteMutation,
    requestBatchDelete,
    requestDelete,
    cancelDelete,
    confirmDelete,
    deleteDescription,
  } = deleteDialog;
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

  useQuestionListUrlSync(filters, page, pageSize, selectedQuestionId, {
    getLocation: () => window.location,
    replaceState: (state, title, url) => window.history.replaceState(state, title, url),
  });

  const { hasActiveFilters } = useQuestionToolbarState(filters);
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
  // placeholderData 会在新版本到达前保留上一份详情，因此标签也跟随"当前实际展示的数据"
  // 而不是提前切到新版本号，避免短暂出现"新标签 + 旧内容"的错觉。
  const { baseVersionLabel, compareVersionLabel, versionComparisonLoading, pendingVersionLabel } =
    buildVersionLabels({
      base: baseVersion,
      compare: compareVersion,
      baseDetail: baseVersionDetail,
      compareDetail: compareVersionDetail,
    });
  const {
    editingSegments,
    editingFallbackStemImageUrls,
    unresolvedEditingTableCount,
    emptyEditingCodeCount,
  } = useQuestionEditingProjection(editForm, selectedQuestion, { setEditForm });

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

  const { updateFilter, applyFilterPreset: applyNextFilters, updatePageSize } =
    useQuestionListInteractions(
      { setFilters, setPage, setPageSize },
      {
        clearSelection,
        closeDetailDrawer: () => setIsDetailDrawerOpen(false),
        closeCommonFilterMenu,
      },
    );
  const {
    keywordInput,
    importBatchInput,
    searchDebouncing,
    handleKeywordChange,
    handleImportBatchChange,
    handleResetFilters,
    handlePageSizeChange,
    handleSaveCurrentFilters,
    handleApplySavedFilters,
    applyFilterPreset,
  } = useQuestionFilterInteractions({
    initialFilters: filters,
    onFilterChanged: updateFilter,
    onFilterPresetApplied: applyNextFilters,
    onPageSizeChanged: updatePageSize,
    onMessage: (nextMessage) => {
      setMessage(nextMessage);
      closeCommonFilterMenu();
    },
    getStorage: () => window.localStorage,
  });

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

          <QuestionFilterToolbar
            filters={filters}
            subjectOptions={subjectOptions}
            keywordInput={keywordInput}
            importBatchInput={importBatchInput}
            searchDebouncing={searchDebouncing}
            listFetching={questions.isFetching}
            hasActiveFilters={hasActiveFilters}
            commonFilterOpen={menus.isCommonFilterOpen}
            moreFilterOpen={menus.isMoreFilterOpen}
            commonFilterRef={commonFilterMenuRef}
            moreFilterRef={moreFilterRef}
            onKeywordChange={handleKeywordChange}
            onResetFilters={handleResetFilters}
            onToggleMenu={toggleMenu}
            onApplyFilterPreset={applyFilterPreset}
            onApplySavedFilters={handleApplySavedFilters}
            onSaveCurrentFilters={handleSaveCurrentFilters}
            onFilterChange={updateFilter}
            onImportBatchChange={handleImportBatchChange}
          />
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <section className="min-w-0 space-y-3">
              <QuestionListToolbar
                itemCount={items.length}
                total={questions.data?.total}
                isFetching={questions.isFetching}
                isLoading={questions.isLoading}
                hasActiveFilters={hasActiveFilters}
                selectedCount={selectedIds.size}
                allChecked={allChecked}
                exportOpen={menus.isExportOpen}
                exportingFormat={exportingFormat}
                exportMenuRef={exportMenuRef}
                onToggleAll={toggleAll}
                onToggleExportMenu={() => toggleMenu("isExportOpen")}
                onExport={(format) => void handleExport(format)}
              />

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

              <QuestionListFeedback
                emptyVisible={!questions.isLoading && !questions.isError && items.length === 0}
                isError={questions.isError}
                hasActiveFilters={hasActiveFilters}
                onResetFilters={handleResetFilters}
                onRetry={() => questions.refetch()}
              />
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
                {buildQuestionPaginationViewport({
                  page,
                  totalPages: questions.data.total_pages,
                }).map((p) => {
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
                })}
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
                <QuestionSideDetailPanel
                  questionId={selectedQuestionId}
                  question={selectedQuestion}
                  isError={detail.isError}
                  scrollRef={detailScrollRef}
                  copyButton={copyQuestionButton}
                  canWrite={canWrite}
                  canDelete={canDelete}
                  onOpenFullDetail={() => setIsDetailDrawerOpen(true)}
                  onEdit={() => {
                    startEditing();
                    setIsDetailDrawerOpen(true);
                  }}
                  onDelete={() => {
                    if (selectedQuestion) requestDelete(selectedQuestion.id);
                  }}
                  onRetry={() => detail.refetch()}
                />
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
              onClick={clearMessage}
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
                onClick={requestBatchDelete}
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
            <QuestionDrawerHeader
              editing={editing}
              dirty={dirty}
              questionId={selectedQuestionId}
              canWrite={canWrite}
              canDelete={canDelete}
              copyButton={copyQuestionButton}
              onBackToDetail={cancelEditing}
              onEdit={startEditing}
              onDelete={() => requestDelete(selectedQuestionId)}
              onClose={closeDetailDrawer}
            />

            <QuestionDrawerBody
              editing={editing}
              question={selectedQuestion}
              detailError={detail.isError}
              editForm={editForm}
              setEditForm={setEditForm}
              setStemText={setEditStemText}
              stemText={editStemText}
              subjectOptions={subjectOptions}
              segments={editingSegments}
              fallbackImageUrls={editingFallbackStemImageUrls}
              dirty={dirty}
              unresolvedTableCount={unresolvedEditingTableCount}
              emptyCodeCount={emptyEditingCodeCount}
              saving={updateMutation.isPending}
              beforeDirtyMutation={prepareImmediateQuestionMutation}
              onMutated={handleQuestionMutated}
              cancelEditing={cancelEditing}
              saveEditing={() => updateMutation.mutate()}
              versions={versions}
              history={{
                open: versionHistoryOpen,
                toggle: toggleVersionHistory,
                base: baseVersion,
                compare: compareVersion,
                setBase: setBaseVersion,
                setCompare: setCompareVersion,
                swap: swapVersions,
              }}
              details={{
                base: baseVersionDetail.data,
                compare: compareVersionDetail.data,
              }}
              labels={{
                baseVersionLabel,
                compareVersionLabel,
                versionComparisonLoading,
                pendingVersionLabel,
              }}
              onRetry={() => detail.refetch()}
            />
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
        description={deleteDescription}
        confirmText="删除"
        danger
        loading={deleteMutation.isPending}
        onCancel={cancelDelete}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
