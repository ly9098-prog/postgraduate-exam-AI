"use client";

import type { KeyboardEvent, ReactNode } from "react";
import {
  AlertTriangle,
  BookOpen,
  RefreshCw,
  RotateCcw,
  Search,
  X,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { CustomSelect, type SelectOption } from "@/components/ui/custom-select";
import { REVIEW_TABS, type ReviewTab } from "../review-queue-state";

type ReviewToolbarProps = {
  tab: ReviewTab;
  onTabChange: (tab: ReviewTab) => void;
  keyword: string;
  onKeywordChange: (value: string) => void;
  subjectId: string;
  subjectOptions: SelectOption[];
  onSubjectChange: (value: string) => void;
  total?: number;
  isFetching: boolean;
  hasActiveFilters: boolean;
  onResetFilters: () => void;
  onRefresh: () => void;
};

const tabIcons: Record<ReviewTab, ReactNode> = {
  re_pending: <AlertTriangle className="h-4 w-4" aria-hidden="true" />,
  rejected: <XCircle className="h-4 w-4" aria-hidden="true" />,
};

export function ReviewToolbar({
  tab,
  onTabChange,
  keyword,
  onKeywordChange,
  subjectId,
  subjectOptions,
  onSubjectChange,
  total,
  isFetching,
  hasActiveFilters,
  onResetFilters,
  onRefresh,
}: ReviewToolbarProps) {
  const handleTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const currentIndex = REVIEW_TABS.findIndex((item) => item.value === tab);
    const step = event.key === "ArrowRight" ? 1 : -1;
    const nextIndex = (currentIndex + step + REVIEW_TABS.length) % REVIEW_TABS.length;
    const next = REVIEW_TABS[nextIndex];
    if (!next) return;
    const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    buttons[nextIndex]?.focus();
    onTabChange(next.value);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="tablist"
          aria-label="审核队列"
          onKeyDown={handleTabKeyDown}
          className="inline-flex rounded-2xl border border-[var(--color-border)] bg-white p-1 shadow-sm"
        >
          {REVIEW_TABS.map((item) => {
            const active = tab === item.value;
            return (
              <button
                key={item.value}
                type="button"
                role="tab"
                aria-selected={active}
                tabIndex={active ? 0 : -1}
                onClick={() => onTabChange(item.value)}
                className={
                  active
                    ? "inline-flex h-10 items-center gap-2 rounded-xl bg-[var(--color-primary-light)] px-4 text-sm font-semibold text-[var(--color-primary-dark)] shadow-sm"
                    : "inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm font-medium text-[var(--color-text-secondary)] transition hover:bg-[var(--porcelain)] hover:text-[var(--ink)]"
                }
              >
                {tabIcons[item.value]}
                {item.label}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--color-text-secondary)]">
          <span className="inline-flex h-9 min-w-[104px] items-center justify-center rounded-full border border-[var(--color-border)] bg-white px-4 tabular-nums">
            共 <strong className="mx-1 text-[var(--ink)]">{total ?? 0}</strong> 条
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={onRefresh}
            disabled={isFetching}
            className="h-9 rounded-full px-3"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            刷新
          </Button>
        </div>
      </div>

      <div className="rounded-[1.35rem] border border-[var(--color-border)] bg-white/90 px-4 py-3 shadow-[0_8px_24px_rgba(40,60,90,0.055)]">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <label className="flex h-11 w-full min-w-0 items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-white px-4 shadow-sm transition focus-within:border-[var(--color-primary)] focus-within:shadow-[0_0_0_3px_var(--color-primary-light)] xl:max-w-md">
            <Search className="h-4 w-4 shrink-0 text-[var(--color-text-hint)]" aria-hidden="true" />
            <input
              type="text"
              className="h-9 min-w-0 flex-1 border-0 bg-transparent px-0 text-sm text-[var(--color-text-primary)] outline-none placeholder:text-[var(--color-text-hint)]"
              placeholder="搜索题干 / 科目 / 题目编号"
              aria-label="搜索审核队列"
              value={keyword}
              onChange={(event) => onKeywordChange(event.target.value)}
            />
            {keyword ? (
              <button
                type="button"
                onClick={() => onKeywordChange("")}
                className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[var(--color-text-hint)] transition hover:bg-[var(--color-primary-light)] hover:text-[var(--ink)]"
                aria-label="清空搜索"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </label>

          <div className="flex h-11 shrink-0 items-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
            <BookOpen className="h-4 w-4 shrink-0 text-[var(--color-primary)]" aria-hidden="true" />
            <span className="shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
              科目
            </span>
            <CustomSelect
              className="h-9 min-w-[160px] !border-0 !bg-transparent !shadow-none"
              value={subjectId}
              onChange={onSubjectChange}
              options={subjectOptions}
              placeholder="全部科目"
              searchable
              searchPlaceholder="搜索科目"
            />
          </div>

          <Button
            variant="ghost"
            onClick={onResetFilters}
            disabled={!hasActiveFilters}
            className="h-11 shrink-0 self-start rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm text-[var(--color-text-secondary)] shadow-sm hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)] disabled:opacity-45 xl:self-auto"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            重置
          </Button>

          <p className="text-xs leading-5 text-[var(--color-text-hint)] xl:ml-auto xl:max-w-[240px] xl:shrink-0 xl:text-right">
            通过会重新启用题目；拒绝与回滚需填写原因。
          </p>
        </div>
      </div>
    </div>
  );
}
