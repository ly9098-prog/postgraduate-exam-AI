"use client";

import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  Clock,
  Eye,
  Hash,
  Inbox,
  Layers,
  Loader2,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { CustomCheckbox } from "@/components/ui/custom-checkbox";
import { MathFormula } from "@/components/ui/math-formula";
import { StatusBadge } from "@/components/status-badge";
import type { AdminQuestion } from "@/lib/api/types";
import { ApiError } from "@/lib/api/errors";
import { looksLikeProgrammingCode } from "@/lib/math-text";
import { getQuestionTypeLabel } from "@/lib/question-types";
import { statusTone, textFromContent, unresolvedTableCount } from "@/lib/review-page-utils";
import { formatChinaDateTime } from "@/lib/time";
import {
  reviewDifficultyLabel,
  reviewStatusLabel,
  REVIEW_DIFFICULTY_LABELS,
  type ReviewTab,
} from "../review-queue-state";

type ReviewQuestionListProps = {
  items: AdminQuestion[];
  tab: ReviewTab;
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  error?: unknown;
  hasActiveFilters: boolean;
  selectedIds: Set<number>;
  allChecked: boolean;
  canBatchReview: boolean;
  canReview: boolean;
  onToggleAll: () => void;
  onToggleOne: (id: number) => void;
  onOpenPreview: (id: number) => void;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  onResetFilters: () => void;
  onRetry: () => void;
};

const difficultyTones = [
  "border-emerald-200 bg-emerald-50 text-emerald-700",
  "border-green-200 bg-green-50 text-green-700",
  "border-amber-200 bg-amber-50 text-amber-700",
  "border-orange-200 bg-orange-50 text-orange-700",
  "border-red-200 bg-red-50 text-red-700",
];

function DifficultyPill({ value }: { value: number | string | null | undefined }) {
  const difficulty = Number(value) || 0;
  const index = Math.min(
    Math.max(Math.round(difficulty) - 1, 0),
    REVIEW_DIFFICULTY_LABELS.length - 1,
  );
  return (
    <span
      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${difficultyTones[index]}`}
    >
      {reviewDifficultyLabel(value)}
    </span>
  );
}

function TypePill({ type }: { type: string | null | undefined }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-white/80 px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-text-secondary)]">
      <Layers className="h-3 w-3" aria-hidden="true" />
      {getQuestionTypeLabel(type)}
    </span>
  );
}

function ReviewRow({
  question,
  tab,
  checked,
  canSelect,
  canReview,
  onToggle,
  onOpenPreview,
  onApprove,
  onReject,
}: {
  question: AdminQuestion;
  tab: ReviewTab;
  checked: boolean;
  canSelect: boolean;
  canReview: boolean;
  onToggle: () => void;
  onOpenPreview: () => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const stem = textFromContent(question.content) || `题目 #${question.id}`;
  const tableCount = unresolvedTableCount(question.content);
  const approvable = tableCount === 0;

  return (
    <article
      className={
        checked
          ? "group rounded-[1.2rem] border border-[var(--color-primary)] bg-[var(--color-primary-light)]/25 shadow-sm transition-all duration-200"
          : "group rounded-[1.2rem] border border-[var(--color-border)] bg-white/85 shadow-sm transition-all duration-200 hover:border-[var(--color-primary)]/45 hover:bg-white hover:shadow-[var(--shadow-card)]"
      }
    >
      <div className="flex items-start gap-3 px-4 py-3">
        {canSelect ? (
          <CustomCheckbox
            checked={checked}
            onCheckedChange={onToggle}
            aria-label={`选择题目 #${question.id}`}
            className="mt-1"
          />
        ) : null}

        <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row sm:items-start">
          <button
            type="button"
            onClick={onOpenPreview}
            className="min-w-0 flex-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]/40 focus-visible:ring-offset-2"
          >
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded-full bg-[var(--color-primary-light)] px-2.5 py-1 text-[11px] font-semibold text-[var(--color-primary-dark)]">
              #{String(question.id).padStart(4, "0")}
            </span>
            <StatusBadge tone={statusTone(question.review_status)}>
              {reviewStatusLabel(question.review_status)}
            </StatusBadge>
            <TypePill type={question.question_type} />
            <DifficultyPill value={question.difficulty} />
            {tableCount > 0 ? (
              <StatusBadge tone="warning">表格待核验</StatusBadge>
            ) : null}
          </div>

          <div className="mt-2 line-clamp-2 text-sm font-medium leading-6 text-[var(--ink)]">
            {looksLikeProgrammingCode(stem) ? stem : <MathFormula text={stem} />}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-text-hint)]">
            <span className="inline-flex items-center gap-1">
              <BookOpen className="h-3 w-3" aria-hidden="true" />
              {question.subject_name || question.subject_code || "未分类"}
            </span>
            {question.year ? (
              <span className="inline-flex items-center gap-1">
                <Layers className="h-3 w-3" aria-hidden="true" />
                {question.year} 年
              </span>
            ) : null}
            {question.import_batch_id ? (
              <span className="inline-flex max-w-[220px] items-center gap-1 truncate">
                <Hash className="h-3 w-3 shrink-0" aria-hidden="true" />
                {question.import_batch_id}
              </span>
            ) : null}
            {question.updated_at ? (
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" aria-hidden="true" />
                更新于 {formatChinaDateTime(question.updated_at)}
              </span>
            ) : null}
          </div>
        </button>

          <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
            <Button variant="ghost" size="sm" onClick={onOpenPreview}>
              <Eye className="h-3.5 w-3.5" aria-hidden="true" />
              预览
            </Button>
            {canReview ? (
              <Button
                variant="success"
                size="sm"
                disabled={!approvable}
                title={
                  approvable
                    ? undefined
                    : `仍有 ${tableCount} 个结构化表格待核验，请先在题库编辑页完成核验`
                }
                onClick={onApprove}
              >
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                {tab === "rejected" ? "恢复通过" : "通过"}
              </Button>
            ) : null}
            {canReview && tab === "re_pending" ? (
              <Button variant="dangerOutline" size="sm" onClick={onReject}>
                <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
                拒绝
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </article>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-2.5" aria-hidden="true">
      {Array.from({ length: 5 }, (_, index) => (
        <div
          key={index}
          className="h-[104px] animate-pulse rounded-[1.2rem] border border-[var(--color-border)] bg-white/60"
        />
      ))}
    </div>
  );
}

export function ReviewQuestionList({
  items,
  tab,
  isLoading,
  isFetching,
  isError,
  error,
  hasActiveFilters,
  selectedIds,
  allChecked,
  canBatchReview,
  canReview,
  onToggleAll,
  onToggleOne,
  onOpenPreview,
  onApprove,
  onReject,
  onResetFilters,
  onRetry,
}: ReviewQuestionListProps) {
  const emptyVisible = !isLoading && !isError && items.length === 0;
  const EmptyIcon = tab === "re_pending" ? CheckCircle2 : Inbox;
  const forbidden = error instanceof ApiError && error.status === 403;
  const errorTitle = forbidden ? "没有审核队列读取权限" : "审核队列加载失败";
  const errorHint = forbidden
    ? "当前角色缺少 question:read 权限，请联系管理员调整角色权限。"
    : error instanceof ApiError && error.status === 0
      ? "网络连接失败，请检查网络后重试。"
      : "请检查网络或后端服务后重试。";

  return (
    <section className="space-y-3" aria-busy={isFetching}>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1.25rem] border border-[var(--color-border)] bg-white px-3 py-2.5 shadow-sm">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {canBatchReview ? (
            <CustomCheckbox
              checked={allChecked}
              onCheckedChange={onToggleAll}
              aria-label="选择当前页全部题目"
              disabled={items.length === 0}
            />
          ) : null}
          <span className="text-xs font-medium text-[var(--color-text-secondary)]">
            当前页 {items.length} 题
          </span>
          {selectedIds.size > 0 ? (
            <span className="inline-flex h-7 items-center rounded-full bg-[var(--color-primary-light)] px-2.5 text-xs font-semibold text-[var(--color-primary-dark)]">
              已选 {selectedIds.size} 项
            </span>
          ) : null}
          {isFetching && !isLoading ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-[var(--color-text-hint)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              更新中
            </span>
          ) : null}
        </div>
        {canBatchReview ? (
          <p className="text-[11px] text-[var(--color-text-hint)]">
            批量操作上限 50 项
          </p>
        ) : null}
      </div>

      {isLoading ? <LoadingRows /> : null}

      <div
        key={`${tab}-${items.map((item) => item.id).join(",")}`}
        className="stagger-enter space-y-2.5"
      >
        {items.map((question) => (
          <ReviewRow
            key={question.id}
            question={question}
            tab={tab}
            checked={selectedIds.has(question.id)}
            canSelect={canBatchReview}
            canReview={canReview}
            onToggle={() => onToggleOne(question.id)}
            onOpenPreview={() => onOpenPreview(question.id)}
            onApprove={() => onApprove(question.id)}
            onReject={() => onReject(question.id)}
          />
        ))}
      </div>

      {emptyVisible ? (
        <div className="flex flex-col items-center gap-3 rounded-[1.6rem] border border-dashed border-[var(--color-border)] bg-white/60 py-16 text-center animate-fade-in">
          <EmptyIcon className="h-12 w-12 text-[var(--color-text-hint)]" aria-hidden="true" />
          <p className="text-sm font-semibold text-[var(--color-text-secondary)]">
            {hasActiveFilters
              ? "没有匹配的题目"
              : tab === "re_pending"
                ? "当前没有待重审题目"
                : "没有已驳回题目"}
          </p>
          <p className="max-w-sm text-xs leading-5 text-[var(--color-text-hint)]">
            {hasActiveFilters
              ? "尝试调整搜索关键词或科目筛选。"
              : tab === "re_pending"
                ? "已入库题目被编辑后会进入待重审队列，届时在这里处理。"
                : "被拒绝的题目会显示在这里，可恢复通过或回滚到历史版本。"}
          </p>
          {hasActiveFilters ? (
            <Button variant="secondary" size="sm" onClick={onResetFilters}>
              清除筛选
            </Button>
          ) : null}
        </div>
      ) : null}

      {isError ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-red-200 bg-red-50/45 py-12 text-center animate-fade-in">
          <AlertCircle className="h-9 w-9 text-red-400" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold text-red-700">{errorTitle}</p>
            <p className="mt-1 text-xs text-red-500">{errorHint}</p>
          </div>
          <Button variant="secondary" size="sm" onClick={onRetry}>
            {forbidden ? "重新检查" : "重新加载"}
          </Button>
        </div>
      ) : null}

      {!isLoading && !isError && items.length === 0 ? (
        <p className="sr-only" role="status">
          审核队列为空
        </p>
      ) : null}
    </section>
  );
}
