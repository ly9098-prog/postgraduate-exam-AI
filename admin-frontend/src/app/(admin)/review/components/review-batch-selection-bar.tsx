"use client";

import { CheckCircle2, X, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

type ReviewBatchSelectionBarProps = {
  selectedCount: number;
  canBatchReject: boolean;
  pending: boolean;
  onBatchApprove: () => void;
  onBatchReject: () => void;
  onClear: () => void;
};

export function ReviewBatchSelectionBar({
  selectedCount,
  canBatchReject,
  pending,
  onBatchApprove,
  onBatchReject,
  onClear,
}: ReviewBatchSelectionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="fixed inset-x-0 bottom-6 z-30 flex justify-center px-3 animate-drop-in sm:bottom-8">
      <div className="flex max-w-full flex-wrap items-center justify-center gap-1.5 rounded-2xl border border-[var(--color-border)] bg-white/94 px-2.5 py-2 shadow-[var(--shadow-floating)] backdrop-blur-xl sm:flex-nowrap sm:gap-3 sm:rounded-full sm:pl-4 sm:pr-2">
        <span className="whitespace-nowrap text-sm text-[var(--color-text-secondary)]">
          已选 <strong className="text-[var(--ink)]">{selectedCount}</strong> 项
        </span>
        <span className="hidden h-5 w-px bg-[var(--color-border)] sm:block" />
        <Button
          variant="success"
          size="sm"
          disabled={pending}
          onClick={onBatchApprove}
          className="px-2.5 sm:px-3"
        >
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          批量通过
        </Button>
        {canBatchReject ? (
          <Button
            variant="dangerOutline"
            size="sm"
            disabled={pending}
            onClick={onBatchReject}
            className="px-2.5 sm:px-3"
          >
            <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
            批量拒绝
          </Button>
        ) : null}
        <button
          type="button"
          onClick={onClear}
          className="grid h-8 w-8 place-items-center rounded-full text-[var(--color-text-hint)] transition-colors hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary)]"
          aria-label="清除选择"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
