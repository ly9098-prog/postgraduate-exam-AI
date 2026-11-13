"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { CustomSelect } from "@/components/ui/custom-select";
import {
  REVIEW_PAGE_SIZE_OPTIONS,
  buildReviewPaginationViewport,
} from "../review-queue-state";

type ReviewPaginationProps = {
  total: number;
  page: number;
  totalPages: number;
  pageSize: number;
  isFetching: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (value: string) => void;
};

const pageSizeOptions = REVIEW_PAGE_SIZE_OPTIONS.map((option) => ({ ...option }));

export function ReviewPagination({
  total,
  page,
  totalPages,
  pageSize,
  isFetching,
  onPageChange,
  onPageSizeChange,
}: ReviewPaginationProps) {
  if (total <= 0) return null;
  const safeTotalPages = Math.max(1, totalPages);

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-[1.2rem] border border-[var(--color-border)] bg-white px-3 py-2.5 shadow-sm">
      <div className="flex flex-wrap items-center gap-3 text-sm text-[var(--color-text-secondary)]">
        <span>
          共 <span className="font-semibold text-[var(--ink)]">{total}</span> 条
        </span>
        <span>
          第 <span className="font-semibold text-[var(--ink)]">{page}</span> / {safeTotalPages} 页
        </span>
        <CustomSelect
          className="h-10 min-w-[116px] rounded-full border-[var(--color-border)] bg-white px-3"
          value={String(pageSize)}
          onChange={onPageSizeChange}
          options={pageSizeOptions}
          clearable={false}
        />
      </div>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          disabled={page <= 1 || isFetching}
          onClick={() => onPageChange(Math.max(1, page - 1))}
          className="inline-flex h-9 items-center justify-center gap-1 rounded-xl border border-[var(--color-border)] bg-white px-2.5 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
        >
          <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
          上一页
        </button>
        {buildReviewPaginationViewport(page, safeTotalPages).map((item) => {
          const active = item === page;
          return (
            <button
              key={item}
              type="button"
              aria-current={active ? "page" : undefined}
              disabled={active || isFetching}
              onClick={() => onPageChange(item)}
              className={
                active
                  ? "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-primary-dark)] bg-[var(--color-primary)] text-sm font-bold text-white shadow-sm"
                  : "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-white text-sm font-medium text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]"
              }
            >
              {item}
            </button>
          );
        })}
        <button
          type="button"
          disabled={page >= safeTotalPages || isFetching}
          onClick={() => onPageChange(page + 1)}
          className="inline-flex h-9 items-center justify-center gap-1 rounded-xl border border-[var(--color-border)] bg-white px-2.5 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
        >
          下一页
          <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
