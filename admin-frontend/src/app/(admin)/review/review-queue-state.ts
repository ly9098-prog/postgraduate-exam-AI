/**
 * Pure state and request helpers for the re-review workbench (`/review`).
 *
 * The page talks to the already implemented question review API:
 * - `GET /questions` with `review_status`
 * - `POST /questions/{id}/approve|reject|rollback`
 * - `POST /questions/batch-approve|batch-reject`
 *
 * Keeping request shaping, reason validation and batch feedback here makes the
 * contracts testable without mounting the React tree.
 */

import type {
  AdminQuestionDetail,
  BatchResult,
  QuestionVersionDetail,
} from "@/lib/api/types";
import { renderJson, textFromContent } from "@/lib/review-page-utils";

export type ReviewTab = "re_pending" | "rejected";

export type ReviewConfirmAction =
  | "approve"
  | "reject"
  | "rollback"
  | "batch-approve"
  | "batch-reject";

export const REVIEW_REASON_MAX_LENGTH = 256;
export const REVIEW_SELECTION_LIMIT = 50;

export const REVIEW_PAGE_SIZE_OPTIONS = [
  { label: "20 条/页", value: "20" },
  { label: "50 条/页", value: "50" },
] as const;

export const REVIEW_TABS: ReadonlyArray<{ value: ReviewTab; label: string }> = [
  { value: "re_pending", label: "待重审" },
  { value: "rejected", label: "已驳回" },
];

export const REVIEW_DIFFICULTY_LABELS = [
  "简单",
  "较易",
  "中等",
  "较难",
  "困难",
] as const;

/** Map the numeric 1–5 difficulty to its Chinese label. */
export function reviewDifficultyLabel(
  value: number | string | null | undefined,
): string {
  if (value === null || value === undefined || value === "") return "—";
  const difficulty = Number(value);
  if (!Number.isFinite(difficulty)) return String(value);
  const index = Math.min(
    Math.max(Math.round(difficulty) - 1, 0),
    REVIEW_DIFFICULTY_LABELS.length - 1,
  );
  return REVIEW_DIFFICULTY_LABELS[index];
}

export function reviewStatusLabel(status: string | null | undefined): string {
  if (status === "re_pending") return "待重审";
  if (status === "rejected") return "已驳回";
  if (status === "approved") return "已通过";
  return status || "未知状态";
}

export type ReviewQueryInput = {
  tab: ReviewTab;
  keyword: string;
  subjectId: string;
  page: number;
  pageSize: number;
};

/**
 * Build the `/questions` list query. Empty keyword/subject filters are
 * omitted so the URL stays stable across the two queue tabs.
 */
export function buildReviewQuery({
  tab,
  keyword,
  subjectId,
  page,
  pageSize,
}: ReviewQueryInput): Record<string, string | number> {
  const trimmedKeyword = keyword.trim();
  const numericSubjectId = Number(subjectId);
  return {
    page,
    page_size: pageSize,
    review_status: tab,
    ...(trimmedKeyword ? { keyword: trimmedKeyword } : {}),
    ...(Number.isInteger(numericSubjectId) && numericSubjectId > 0
      ? { subject_id: numericSubjectId }
      : {}),
  };
}

/** Rejections and rollbacks are audited, so the backend requires a reason. */
export function reviewRequiresReason(action: ReviewConfirmAction): boolean {
  return action === "reject" || action === "batch-reject" || action === "rollback";
}

export function reviewReasonError(
  action: ReviewConfirmAction,
  reason: string,
): string | null {
  if (!reviewRequiresReason(action)) return null;
  const trimmed = reason.trim();
  if (!trimmed) {
    return action === "rollback" ? "请填写回滚原因" : "请填写拒绝原因";
  }
  if (trimmed.length > REVIEW_REASON_MAX_LENGTH) {
    return `原因不能超过 ${REVIEW_REASON_MAX_LENGTH} 个字符`;
  }
  return null;
}

export type ReviewDiffRow = {
  key: string;
  label: string;
  current: string;
  previous: string;
  changed: boolean;
};

/**
 * Compare the current question projection with a historical revision.
 * Fields mirror what `AdminQuestionDetail` and `QuestionVersionDetail` expose.
 */
export function buildReviewDiff(
  current: AdminQuestionDetail | null | undefined,
  previous: QuestionVersionDetail | null | undefined,
): ReviewDiffRow[] {
  if (!current || !previous) return [];

  return [
    {
      key: "stem",
      label: "题干",
      current: textFromContent(current.content),
      previous: textFromContent(previous.content),
    },
    {
      key: "options",
      label: "选项",
      current: renderJson(current.options ?? null),
      previous: renderJson(previous.options ?? null),
    },
    {
      key: "answer",
      label: "答案",
      current: renderJson(current.answer),
      previous: renderJson(previous.answer),
    },
    {
      key: "analysis",
      label: "解析",
      current: renderJson(current.analysis ?? null),
      previous: renderJson(previous.analysis ?? null),
    },
    {
      key: "difficulty",
      label: "难度",
      current: String(current.difficulty),
      previous: String(previous.difficulty),
    },
    {
      key: "knowledge_points",
      label: "知识点",
      current: renderJson(current.knowledge_points ?? null),
      previous: renderJson(previous.knowledge_points ?? null),
    },
  ].map((row) => ({ ...row, changed: row.current !== row.previous }));
}

export type NormalizedBatchResult = {
  successIds: number[];
  failedItems: Array<{ id: number; error: string }>;
};

export function normalizeBatchResult(result: unknown): NormalizedBatchResult {
  const value = result as Partial<BatchResult> | null | undefined;
  return {
    successIds: value?.success_ids ?? value?.successIds ?? [],
    failedItems: value?.failed_items ?? value?.failedItems ?? [],
  };
}

/**
 * Human-readable batch summary. The UI rules require surfacing both
 * `success_ids` and `failed_items`, never a bare "全部成功" claim.
 */
export function formatBatchReviewMessage(
  decision: "approved" | "rejected",
  result: unknown,
): string {
  const { successIds, failedItems } = normalizeBatchResult(result);
  const label = decision === "approved" ? "批量通过" : "批量拒绝";
  if (failedItems.length === 0) {
    return `${label}完成：成功 ${successIds.length} 项，无失败项。`;
  }
  const preview = failedItems
    .slice(0, 5)
    .map((item) => `#${item.id} ${item.error}`)
    .join("；");
  return `${label}完成：成功 ${successIds.length} 项，失败 ${failedItems.length} 项（${preview}${failedItems.length > 5 ? "；…" : ""}）。`;
}

/** Toggle one row, enforcing the backend batch limit of 50 ids. */
export function toggleReviewSelection(
  current: Set<number>,
  id: number,
  limit = REVIEW_SELECTION_LIMIT,
): Set<number> {
  const next = new Set(current);
  if (next.has(id)) {
    next.delete(id);
    return next;
  }
  if (next.size >= limit) return current;
  next.add(id);
  return next;
}

/** Toggle every row on the current page, capped at the batch limit. */
export function toggleAllReviewSelection(
  current: Set<number>,
  visibleIds: number[],
  limit = REVIEW_SELECTION_LIMIT,
): Set<number> {
  if (visibleIds.length === 0) return current;
  const next = new Set(current);
  if (visibleIds.every((id) => next.has(id))) {
    visibleIds.forEach((id) => next.delete(id));
    return next;
  }
  for (const id of visibleIds) {
    if (next.size >= limit) break;
    next.add(id);
  }
  return next;
}

/**
 * Drop selected ids that are no longer visible after a status change or
 * filter update. Returns the same set reference when nothing changed.
 */
export function pruneReviewSelection(
  current: Set<number>,
  visibleItems: ReadonlyArray<{ id: number }>,
): Set<number> {
  if (visibleItems.length === 0) return current;
  const visibleIds = new Set(visibleItems.map((item) => item.id));
  const next = new Set<number>();
  let changed = false;
  current.forEach((id) => {
    if (visibleIds.has(id)) next.add(id);
    else changed = true;
  });
  return changed ? next : current;
}

/** Sliding five-page window used by the pagination footer. */
export function buildReviewPaginationViewport(
  page: number,
  totalPages: number,
): number[] {
  if (totalPages <= 0) return [];
  const windowSize = 5;
  const startPage = Math.max(
    1,
    Math.min(page - 2, totalPages - (windowSize - 1)),
  );
  return Array.from(
    { length: Math.min(totalPages, windowSize) },
    (_, index) => startPage + index,
  ).filter((candidate) => candidate >= 1 && candidate <= totalPages);
}

/**
 * Batch review endpoints require an `Idempotency-Key` header (the backend
 * rejects requests without one). The key must be <=128 characters and contain
 * no whitespace.
 */
export function createReviewIdempotencyKey(
  randomUUID: () => string = () =>
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`,
): string {
  return `review-batch-${randomUUID()}`;
}
