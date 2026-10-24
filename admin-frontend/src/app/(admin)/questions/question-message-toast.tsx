"use client";

import { X } from "lucide-react";

type QuestionMessageToastProps = {
  message: string | null;
  onClose: () => void;
};

export function QuestionMessageToast({ message, onClose }: QuestionMessageToastProps) {
  if (!message) return null;

  return (
    <div className="fixed right-6 top-24 z-[60] max-w-[calc(100vw-3rem)] animate-fade-in">
      <div
        role="status"
        aria-live="polite"
        className="flex max-w-sm items-center gap-3 rounded-full border border-[var(--color-success)]/30 bg-white/92 py-2 pl-5 pr-2 text-sm font-medium text-[var(--ink)] shadow-[var(--shadow-floating)] backdrop-blur-xl"
      >
        <span>{message}</span>
        <button
          type="button"
          onClick={onClose}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-[var(--color-text-hint)] transition hover:bg-[var(--color-success-light)] hover:text-[var(--color-success)]"
          aria-label="关闭提示"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
