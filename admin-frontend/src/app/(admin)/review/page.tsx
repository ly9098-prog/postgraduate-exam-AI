"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { MessageToast } from "@/components/ui/message-toast";
import { useAuthStore } from "@/lib/auth/auth-store";
import { apiRequest, toQuery } from "@/lib/api/client";
import { hasPermission } from "@/lib/permissions/permissions";
import { unresolvedTableCount } from "@/lib/review-page-utils";
import { flattenSubjects } from "@/lib/subject-tree-utils";
import type {
  AdminQuestion,
  AdminQuestionDetail,
  AdminSubjectNode,
  BatchResult,
  PaginatedResponse,
  QuestionVersion,
  QuestionVersionDetail,
} from "@/lib/api/types";
import { ReviewBatchResult } from "./components/review-batch-result";
import { ReviewBatchSelectionBar } from "./components/review-batch-selection-bar";
import { ReviewDetailDrawer } from "./components/review-detail-drawer";
import { ReviewPagination } from "./components/review-pagination";
import { ReviewQuestionList } from "./components/review-question-list";
import { ReviewToolbar } from "./components/review-toolbar";
import {
  REVIEW_REASON_MAX_LENGTH,
  buildReviewQuery,
  createReviewIdempotencyKey,
  formatBatchReviewMessage,
  normalizeBatchResult,
  pruneReviewSelection,
  reviewReasonError,
  reviewRequiresReason,
  toggleAllReviewSelection,
  toggleReviewSelection,
  type NormalizedBatchResult,
  type ReviewTab,
} from "./review-queue-state";
import { useDebouncedValue } from "./use-debounced-value";

type ConfirmState =
  | { action: "approve"; id: number }
  | { action: "reject"; id: number }
  | { action: "rollback"; id: number; version: number }
  | { action: "batch-approve" }
  | { action: "batch-reject" };

type MessageState = { text: string; tone: "success" | "danger" };

function confirmDialogCopy(state: ConfirmState | null, selectedCount: number) {
  if (!state) return { title: "", description: "", confirmText: "确认", danger: false };
  switch (state.action) {
    case "approve":
      return {
        title: `通过题目 #${state.id}？`,
        description:
          "通过后题目会重新启用并进入正式题库，该操作会写入审计日志。",
        confirmText: "通过",
        danger: false,
      };
    case "reject":
      return {
        title: `拒绝题目 #${state.id}？`,
        description:
          "拒绝后题目会停用。请填写原因，原因会写入审计日志，便于后续追溯。",
        confirmText: "拒绝",
        danger: true,
      };
    case "rollback":
      return {
        title: `回滚到 v${state.version}？`,
        description: `将用 v${state.version} 的内容覆盖当前题目，并恢复为审核通过；回滚本身会生成新版本。`,
        confirmText: "回滚",
        danger: true,
      };
    case "batch-approve":
      return {
        title: `批量通过 ${selectedCount} 道题？`,
        description:
          "通过后这些题目会重新启用。操作会逐题记录审计日志，并返回成功与失败明细。",
        confirmText: "批量通过",
        danger: false,
      };
    case "batch-reject":
      return {
        title: `批量拒绝 ${selectedCount} 道题？`,
        description:
          "拒绝后这些题目会停用。请填写统一原因，原因会写入审计日志。",
        confirmText: "批量拒绝",
        danger: true,
      };
  }
}

export default function ReviewPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const canReview = hasPermission(permissions, "question:review");
  const canRollback = canReview && hasPermission(permissions, "question:write");
  const canBatchReview = hasPermission(permissions, "question:batch_review");

  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [keywordInput, setKeywordInput] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [tab, setTab] = useState<ReviewTab>("re_pending");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [baselineVersion, setBaselineVersion] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [message, setMessage] = useState<MessageState | null>(null);
  const [batchResult, setBatchResult] = useState<{
    decision: "approved" | "rejected";
    result: NormalizedBatchResult;
  } | null>(null);
  const batchIdempotencyKeysRef = useRef(new Map<string, string>());
  const debouncedKeyword = useDebouncedValue(keywordInput, 300, () =>
    setPage(1),
  );
  // Clearing the box should take effect immediately; otherwise the old
  // keyword would still drive one intermediate request while the reset
  // subject/page filters are already applied.
  const keyword = keywordInput.trim() === "" ? "" : debouncedKeyword;

  const queryParams = useMemo(
    () => buildReviewQuery({ tab, keyword, subjectId, page, pageSize }),
    [tab, keyword, subjectId, page, pageSize],
  );

  const questions = useQuery({
    queryKey: ["review-questions", queryParams],
    queryFn: () =>
      apiRequest<PaginatedResponse<AdminQuestion>>(`/questions${toQuery(queryParams)}`),
    placeholderData: (previousData) => previousData,
    retry: false,
  });

  const subjects = useQuery({
    queryKey: ["review-subject-options"],
    queryFn: () => apiRequest<AdminSubjectNode[]>("/questions/subject-options"),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const preview = useQuery({
    queryKey: ["review-preview", previewId],
    queryFn: () => apiRequest<AdminQuestionDetail>(`/questions/${previewId}`),
    enabled: previewId !== null,
    retry: false,
  });

  const versions = useQuery({
    queryKey: ["review-preview", previewId, "versions"],
    queryFn: () =>
      apiRequest<PaginatedResponse<QuestionVersion>>(
        `/questions/${previewId}/versions${toQuery({ page: 1, page_size: 20 })}`,
      ),
    enabled: previewId !== null,
    retry: false,
  });

  const versionItems = versions.data?.items ?? [];
  const effectiveBaseline = baselineVersion ?? versionItems[1]?.version;

  const baselineDetail = useQuery({
    queryKey: ["review-preview", previewId, "version-detail", effectiveBaseline],
    queryFn: () =>
      apiRequest<QuestionVersionDetail>(
        `/questions/${previewId}/versions/${effectiveBaseline}`,
      ),
    enabled: previewId !== null && typeof effectiveBaseline === "number",
    retry: false,
  });

  const items = useMemo(() => questions.data?.items ?? [], [questions.data?.items]);
  const totalPages = Math.max(1, questions.data?.total_pages ?? 1);

  useEffect(() => {
    // A filter change can shrink total_pages below the current page. Clamp it
    // so the pagination footer never advertises a page that no longer exists.
    if (page > totalPages) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const validSelectedIds = useMemo(
    () => pruneReviewSelection(selectedIds, items),
    [selectedIds, items],
  );
  const allChecked =
    items.length > 0 && items.every((item) => validSelectedIds.has(item.id));

  const subjectOptions = useMemo(
    () =>
      flattenSubjects(subjects.data ?? [])
        .filter((subject) => subject.is_active && subject.level > 1)
        .map((subject) => ({
          value: String(subject.id),
          label: subject.name,
          suffix: subject.code,
        })),
    [subjects.data],
  );

  const hasActiveFilters = Boolean(keywordInput.trim() || subjectId);

  const closePreview = useCallback(() => {
    setPreviewId(null);
    setBaselineVersion(null);
  }, []);

  const openPreview = useCallback((id: number) => {
    setPreviewId(id);
    setBaselineVersion(null);
  }, []);

  const clearMessage = useCallback(() => setMessage(null), []);

  /**
   * Batch review requires an idempotency key. Reuse the key for an identical
   * retry (same decision, ids and reason) so a lost response cannot double
   * apply the batch; rotate it when the request fingerprint changes.
   */
  const batchIdempotencyKeyFor = (operation: string): string => {
    const keys = batchIdempotencyKeysRef.current;
    const existing = keys.get(operation);
    if (existing) return existing;
    const key = createReviewIdempotencyKey();
    keys.set(operation, key);
    return key;
  };

  const openConfirm = (state: ConfirmState) => {
    setReason(state.action === "rollback" ? "恢复历史版本" : "");
    setConfirmState(state);
  };

  const closeConfirm = () => {
    setConfirmState(null);
    setReason("");
  };

  const handleTabChange = (next: ReviewTab) => {
    if (next === tab) return;
    setTab(next);
    setPage(1);
    setSelectedIds(new Set());
    setBatchResult(null);
    closePreview();
  };

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
    if (value.trim() === "") setPage(1);
  };

  const handleSubjectChange = (value: string) => {
    setSubjectId(value);
    setSelectedIds(new Set());
    setPage(1);
  };

  const handleResetFilters = () => {
    setKeywordInput("");
    setSubjectId("");
    setSelectedIds(new Set());
    setPage(1);
  };

  const handlePageSizeChange = (value: string) => {
    const next = Number(value);
    if (!Number.isFinite(next) || next <= 0) return;
    setPageSize(next);
    setSelectedIds(new Set());
    setPage(1);
  };

  const reviewMutation = useMutation({
    mutationFn: async (
      state: Extract<ConfirmState, { action: "approve" | "reject" }>,
    ) => {
      if (state.action === "approve") {
        const target =
          preview.data?.id === state.id
            ? preview.data
            : await apiRequest<AdminQuestionDetail>(`/questions/${state.id}`);
        const tableCount = unresolvedTableCount(target.content);
        if (tableCount > 0) {
          throw new Error(
            `无法通过：仍有 ${tableCount} 个结构化表格需要在题库编辑页完成核验。`,
          );
        }
        return apiRequest<AdminQuestion>(`/questions/${state.id}/approve`, {
          method: "POST",
          exposeErrorDetail: true,
        });
      }
      return apiRequest<AdminQuestion>(`/questions/${state.id}/reject`, {
        method: "POST",
        exposeErrorDetail: true,
        body: JSON.stringify({ reason: reason.trim() }),
      });
    },
    onSuccess: (result, variables) => {
      const label = variables.action === "approve" ? "已通过" : "已拒绝";
      setMessage({ text: `题目 #${result.id} ${label}。`, tone: "success" });
      closeConfirm();
      setSelectedIds((current) => {
        const next = new Set(current);
        next.delete(result.id);
        return next;
      });
      if (previewId === result.id) closePreview();
      queryClient.invalidateQueries({ queryKey: ["review-questions"] });
      queryClient.removeQueries({ queryKey: ["review-preview", result.id] });
    },
    onError: (error) => {
      setMessage({
        text: error instanceof Error ? error.message : "操作失败，请稍后重试。",
        tone: "danger",
      });
    },
  });

  const batchMutation = useMutation({
    mutationFn: async (decision: "approved" | "rejected") => {
      if (validSelectedIds.size === 0) throw new Error("请先选择题目。");
      const ids = Array.from(validSelectedIds).sort((a, b) => a - b);
      const trimmedReason = reason.trim();
      const idempotencyKey = batchIdempotencyKeyFor(
        `${decision}:${ids.join(",")}:${trimmedReason}`,
      );
      return apiRequest<BatchResult>(
        `/questions/batch-${decision === "approved" ? "approve" : "reject"}`,
        {
          method: "POST",
          exposeErrorDetail: true,
          headers: { "Idempotency-Key": idempotencyKey },
          body: JSON.stringify({
            ids,
            ...(decision === "rejected" && trimmedReason
              ? { reason: trimmedReason }
              : {}),
          }),
        },
      );
    },
    onSuccess: (result, decision) => {
      batchIdempotencyKeysRef.current.clear();
      const normalized = normalizeBatchResult(result);
      setBatchResult({ decision, result: normalized });
      setMessage({
        text: formatBatchReviewMessage(decision, normalized),
        tone: normalized.failedItems.length > 0 ? "danger" : "success",
      });
      closeConfirm();
      setSelectedIds(new Set());
      if (previewId !== null && normalized.successIds.includes(previewId)) {
        closePreview();
      }
      queryClient.invalidateQueries({ queryKey: ["review-questions"] });
    },
    onError: (error) => {
      setMessage({
        text:
          error instanceof Error ? error.message : "批量审核失败，请稍后重试。",
        tone: "danger",
      });
    },
  });

  const rollbackMutation = useMutation({
    mutationFn: async (
      state: Extract<ConfirmState, { action: "rollback" }>,
    ) =>
      apiRequest<AdminQuestion>(`/questions/${state.id}/rollback`, {
        method: "POST",
        exposeErrorDetail: true,
        body: JSON.stringify({
          version: state.version,
          reason: reason.trim() || "恢复历史版本",
        }),
      }),
    onSuccess: (result, variables) => {
      setMessage({
        text: `题目 #${result.id} 已回滚到 v${variables.version} 并恢复审核通过。`,
        tone: "success",
      });
      closeConfirm();
      if (previewId === result.id) closePreview();
      queryClient.invalidateQueries({ queryKey: ["review-questions"] });
      queryClient.removeQueries({ queryKey: ["review-preview", result.id] });
    },
    onError: (error) => {
      setMessage({
        text: error instanceof Error ? error.message : "回滚失败，请稍后重试。",
        tone: "danger",
      });
    },
  });

  const reasonError = confirmState
    ? reviewReasonError(confirmState.action, reason)
    : null;
  const confirmPending =
    reviewMutation.isPending ||
    batchMutation.isPending ||
    rollbackMutation.isPending;
  const dialogCopy = confirmDialogCopy(confirmState, validSelectedIds.size);
  const reasonAction = confirmState?.action;
  const showReasonInput = reasonAction ? reviewRequiresReason(reasonAction) : false;
  const reasonLabel =
    reasonAction === "rollback" ? "回滚原因" : "拒绝原因";

  return (
    <div
      className={`space-y-4 ${
        canBatchReview && validSelectedIds.size > 0 ? "pb-28" : "pb-10"
      }`}
    >
      <Card className="overflow-visible border border-[var(--color-border)] bg-white/90 shadow-[var(--shadow-card)]">
        <CardHeader className="space-y-4 pb-4">
          <div>
            <h2 className="font-display text-2xl font-bold text-[var(--ink)]">
              审核工作台
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-[var(--color-text-secondary)]">
              处理已入库题目的重审、驳回恢复与版本回滚。首次导入审核请前往{" "}
              <Link
                href="/imports/review"
                className="font-semibold text-[var(--color-primary-dark)] underline decoration-[var(--color-primary)]/35 underline-offset-2 transition hover:decoration-[var(--color-primary)]"
              >
                待审核题目
              </Link>
              。
            </p>
          </div>

          <ReviewToolbar
            tab={tab}
            onTabChange={handleTabChange}
            keyword={keywordInput}
            onKeywordChange={handleKeywordChange}
            subjectId={subjectId}
            subjectOptions={subjectOptions}
            onSubjectChange={handleSubjectChange}
            total={questions.data?.total}
            isFetching={questions.isFetching}
            hasActiveFilters={hasActiveFilters}
            onResetFilters={handleResetFilters}
            onRefresh={() => {
              void questions.refetch();
            }}
          />
        </CardHeader>

        <CardContent className="space-y-4">
          {batchResult ? (
            <ReviewBatchResult
              decision={batchResult.decision}
              result={batchResult.result}
              onDismiss={() => setBatchResult(null)}
            />
          ) : null}

          <ReviewQuestionList
            items={items}
            tab={tab}
            isLoading={questions.isLoading}
            isFetching={questions.isFetching}
            isError={questions.isError}
            error={questions.error}
            hasActiveFilters={hasActiveFilters}
            selectedIds={validSelectedIds}
            allChecked={allChecked}
            canBatchReview={canBatchReview}
            canReview={canReview}
            onToggleAll={() =>
              setSelectedIds((current) =>
                toggleAllReviewSelection(
                  current,
                  items.map((item) => item.id),
                ),
              )
            }
            onToggleOne={(id) =>
              setSelectedIds((current) => toggleReviewSelection(current, id))
            }
            onOpenPreview={openPreview}
            onApprove={(id) => openConfirm({ action: "approve", id })}
            onReject={(id) => openConfirm({ action: "reject", id })}
            onResetFilters={handleResetFilters}
            onRetry={() => {
              void questions.refetch();
            }}
          />

          <ReviewPagination
            total={questions.data?.total ?? 0}
            page={page}
            totalPages={totalPages}
            pageSize={pageSize}
            isFetching={questions.isFetching}
            onPageChange={(nextPage) => {
              setSelectedIds(new Set());
              setPage(nextPage);
            }}
            onPageSizeChange={handlePageSizeChange}
          />
        </CardContent>
      </Card>

      {canBatchReview ? (
        <ReviewBatchSelectionBar
          selectedCount={validSelectedIds.size}
          canBatchReject={tab === "re_pending"}
          pending={batchMutation.isPending}
          onBatchApprove={() => openConfirm({ action: "batch-approve" })}
          onBatchReject={() => openConfirm({ action: "batch-reject" })}
          onClear={() => setSelectedIds(new Set())}
        />
      ) : null}

      <ReviewDetailDrawer
        open={previewId !== null}
        questionId={previewId}
        question={preview.data}
        isLoading={preview.isLoading}
        isError={preview.isError}
        onRetry={() => {
          void preview.refetch();
        }}
        onClose={closePreview}
        canReview={canReview}
        canRollback={canRollback}
        versions={versionItems}
        versionsLoading={versions.isLoading}
        versionsError={versions.isError}
        baselineVersion={effectiveBaseline}
        onSelectBaseline={setBaselineVersion}
        baselineDetail={baselineDetail.data}
        baselineLoading={baselineDetail.isLoading}
        baselineError={baselineDetail.isError}
        onApprove={(id) => openConfirm({ action: "approve", id })}
        onReject={(id) => openConfirm({ action: "reject", id })}
        onRollback={(id, version) =>
          openConfirm({ action: "rollback", id, version })
        }
      />

      <ConfirmDialog
        open={confirmState !== null}
        title={dialogCopy.title}
        description={dialogCopy.description}
        confirmText={dialogCopy.confirmText}
        danger={dialogCopy.danger}
        loading={confirmPending}
        confirmDisabled={Boolean(reasonError)}
        onCancel={closeConfirm}
        onConfirm={() => {
          if (!confirmState || reasonError) return;
          if (
            confirmState.action === "approve" ||
            confirmState.action === "reject"
          ) {
            reviewMutation.mutate(confirmState);
            return;
          }
          if (confirmState.action === "rollback") {
            rollbackMutation.mutate(confirmState);
            return;
          }
          batchMutation.mutate(
            confirmState.action === "batch-approve" ? "approved" : "rejected",
          );
        }}
      >
        {showReasonInput ? (
          <label className="block">
            <span className="text-xs font-semibold text-[var(--color-text-secondary)]">
              {reasonLabel}（必填）
            </span>
            <textarea
              autoFocus
              maxLength={REVIEW_REASON_MAX_LENGTH}
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={
                reasonAction === "rollback"
                  ? "说明本次回滚的原因"
                  : "说明拒绝原因，便于后续追溯"
              }
              aria-invalid={Boolean(reasonError)}
              className="mt-2 w-full resize-y rounded-xl border border-[var(--color-border)] bg-white p-3 text-sm text-[var(--color-text-primary)] outline-none transition focus:border-[var(--color-primary)] focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
            />
            <span className="mt-1 flex items-center justify-between gap-3 text-[11px]">
              <span
                className={
                  reasonError
                    ? "font-medium text-[var(--color-danger)]"
                    : "text-[var(--color-text-hint)]"
                }
              >
                {reasonError || "将记录到审核日志，便于后续追溯。"}
              </span>
              <span className="shrink-0 text-[var(--color-text-hint)]">
                {reason.length}/{REVIEW_REASON_MAX_LENGTH}
              </span>
            </span>
          </label>
        ) : null}
      </ConfirmDialog>

      <MessageToast
        message={message?.text ?? null}
        tone={message?.tone}
        onClose={clearMessage}
      />
    </div>
  );
}
