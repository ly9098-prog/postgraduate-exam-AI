"use client";

type ReviewPaginationProps = {
  page: number;
  total?: number;
  currentPage?: number;
  totalPages?: number;
  onPageChange: (page: number) => void;
};

export function ReviewPagination({
  page,
  total,
  currentPage,
  totalPages,
  onPageChange,
}: ReviewPaginationProps) {
  if (!total || !currentPage || !totalPages || totalPages <= 1) return null;

  return (
    <>
      {/* ── Pagination ── */}
            {totalPages > 1 ? (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[var(--blueprint-line)] bg-white/80 px-5 py-3 shadow-[var(--shadow-crisp)]">
                <span className="font-display text-sm tracking-wide text-[var(--color-text-secondary)]">
                  <span className="font-semibold text-[var(--ink)]">{total}</span>{" "}
                  条记录
                  <span className="mx-2 text-[var(--color-text-hint)]">/</span>
                  <span className="text-[var(--color-text-hint)]">第 </span>
                  <span className="font-semibold text-[var(--ink)]">{currentPage}</span>
                  <span className="text-[var(--color-text-hint)]"> / {totalPages} 页</span>
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    disabled={page <= 1}
                    onClick={() => onPageChange(Math.max(1, page - 1))}
                    className="inline-flex h-9 items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
                    上一页
                  </button>
                  {Array.from(
                    { length: Math.min(totalPages, 5) },
                    (_, i) => {
                      const start = Math.max(1, Math.min(page - 2, totalPages - 4));
                      const p = start + i;
                      if (p > totalPages) return null;
                      const isActive = p === page;
                      return (
                        <button
                          key={p}
                          disabled={isActive}
                          onClick={() => onPageChange(p)}
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
                    disabled={page >= totalPages}
                    onClick={() => onPageChange(page + 1)}
                    className="inline-flex h-9 items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                  >
                    下一页
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
                  </button>
                </div>
              </div>
      ) : null}
    </>
  );
}
