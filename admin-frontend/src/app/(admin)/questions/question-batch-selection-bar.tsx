"use client";

import { Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";

type QuestionBatchSelectionBarProps = {
  selectedCount: number;
  canDelete: boolean;
  deleting: boolean;
  onBatchDelete: () => void;
  onClearSelection: () => void;
};

export function QuestionBatchSelectionBar({
  selectedCount,
  canDelete,
  deleting,
  onBatchDelete,
  onClearSelection,
}: QuestionBatchSelectionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="fixed bottom-8 left-1/2 z-30 -translate-x-1/2 animate-drop-in">
      <div className="flex items-center gap-3 rounded-full border border-[var(--color-border)] bg-white/94 py-2 pl-4 pr-2 shadow-[var(--shadow-floating)] backdrop-blur-xl">
        <span className="text-sm text-[var(--color-text-secondary)]">
          已选 <strong className="text-[var(--ink)]">{selectedCount}</strong> 项
        </span>
        <span className="h-5 w-px bg-[var(--color-border)]" />
        {canDelete ? (
          <Button
            variant="danger"
            size="sm"
            disabled={deleting}
            onClick={onBatchDelete}
          >
            <Trash2 className="h-3.5 w-3.5" />
            批量删除
          </Button>
        ) : null}
        <button
          type="button"
          onClick={onClearSelection}
          className="grid h-8 w-8 place-items-center rounded-full text-[var(--color-text-hint)] transition-colors hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary)]"
          aria-label="清除选择"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
