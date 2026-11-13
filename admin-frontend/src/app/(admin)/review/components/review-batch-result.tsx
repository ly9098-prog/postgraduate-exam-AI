"use client";

import { CheckCircle2, X } from "lucide-react";
import type { NormalizedBatchResult } from "../review-queue-state";

type ReviewBatchResultProps = {
  decision: "approved" | "rejected";
  result: NormalizedBatchResult;
  onDismiss: () => void;
};

/**
 * Per-id batch feedback required by the admin UI rules: both successful ids
 * and failed items stay visible until the operator dismisses the panel.
 */
export function ReviewBatchResult({
  decision,
  result,
  onDismiss,
}: ReviewBatchResultProps) {
  const label = decision === "approved" ? "批量通过" : "批量拒绝";

  return (
    <section
      aria-live="polite"
      className="animate-fade-in rounded-2xl border border-[var(--color-border)] bg-white/90 p-4 shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[var(--ink)]">{label}结果</p>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
            成功 {result.successIds.length} 项，失败 {result.failedItems.length} 项。
          </p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-[var(--color-text-hint)] transition hover:bg-[var(--color-primary-light)] hover:text-[var(--ink)]"
          aria-label="关闭批量结果"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-xl border border-[var(--color-success)]/30 bg-[var(--color-success-light)]/55 p-3">
          <p className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--color-success)]">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            成功 {result.successIds.length} 项
          </p>
          <p className="mt-1.5 break-words font-mono text-[11px] leading-5 text-[var(--color-text-secondary)]">
            {result.successIds.length > 0
              ? result.successIds.map((id) => `#${id}`).join("、")
              : "—"}
          </p>
        </div>
        <div className="rounded-xl border border-[var(--color-danger)]/25 bg-[var(--color-danger-light)]/55 p-3">
          <p className="text-xs font-semibold text-[var(--color-danger)]">
            失败 {result.failedItems.length} 项
          </p>
          {result.failedItems.length > 0 ? (
            <ul className="mt-1.5 space-y-1 text-[11px] leading-5 text-[var(--color-text-secondary)]">
              {result.failedItems.map((item) => (
                <li key={`${item.id}-${item.error}`} className="break-words">
                  <span className="font-mono text-[var(--color-danger)]">#{item.id}</span>{" "}
                  {item.error}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 text-[11px] text-[var(--color-text-secondary)]">无失败项</p>
          )}
        </div>
      </div>
    </section>
  );
}
