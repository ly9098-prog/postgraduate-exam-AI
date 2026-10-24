"use client";

import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import {
  Copy,
  Trash2,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { buildVersionLabels } from "./question-version-labels";
import { QuestionSideDetailPanel } from "./question-side-detail-panel";
import { QuestionDrawerHeader } from "./question-drawer-header";
import { QuestionDrawerBody } from "./question-drawer-body";
import { QuestionFilterToolbar } from "./question-filter-toolbar";
import { QuestionListCard } from "./question-list-card";
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
import { questionDetailOptions } from "./question-queries";
import { useQuestionDetail, useQuestionList } from "./hooks/use-question-queries";

import { positiveInt } from "./question-list-state";
import { buildExportPayload } from "./question-export-payload";

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
            <QuestionListCard
              items={items}
              total={questions.data?.total}
              page={page}
              totalPages={questions.data?.total_pages ?? 1}
              pageSize={pageSize}
              isLoading={questions.isLoading}
              isFetching={questions.isFetching}
              isError={questions.isError}
              hasActiveFilters={hasActiveFilters}
              selectedQuestionId={selectedQuestionId}
              selectedIds={selectedIds}
              allChecked={allChecked}
              filters={filters}
              exportOpen={menus.isExportOpen}
              exportingFormat={exportingFormat}
              exportMenuRef={exportMenuRef}
              onToggleAll={toggleAll}
              onToggleOne={toggleOne}
              onSelectQuestion={selectQuestion}
              onOpenDetail={openDetail}
              onPrefetchDetail={prefetchDetail}
              onToggleExportMenu={() => toggleMenu("isExportOpen")}
              onExport={(format) => void handleExport(format)}
              onResetFilters={handleResetFilters}
              onRetry={() => questions.refetch()}
              onPageSizeChange={handlePageSizeChange}
              onSetPage={setPage}
            />

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
