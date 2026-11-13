"use client";

import { useEffect } from "react";
import { AlertCircle, CheckCircle2, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type MessageToastTone = "success" | "danger";

type MessageToastProps = {
  message: string | null;
  tone?: MessageToastTone;
  onClose: () => void;
  autoHideMs?: number;
};

/**
 * Floating operation feedback shared by admin workbenches.
 *
 * Success messages announce politely; failures use an alert role so screen
 * readers interrupt. Auto-hide can be disabled with `autoHideMs={0}`.
 */
export function MessageToast({
  message,
  tone = "success",
  onClose,
  autoHideMs = 5000,
}: MessageToastProps) {
  useEffect(() => {
    if (!message || autoHideMs <= 0) return;
    const timer = setTimeout(onClose, autoHideMs);
    return () => clearTimeout(timer);
  }, [message, tone, autoHideMs, onClose]);

  if (!message) return null;
  const isDanger = tone === "danger";

  return (
    <div className="fixed right-6 top-24 z-[60] max-w-[calc(100vw-3rem)] animate-fade-in">
      <div
        role={isDanger ? "alert" : "status"}
        aria-live={isDanger ? "assertive" : "polite"}
        className={cn(
          "flex max-w-md items-start gap-3 rounded-2xl border bg-white/94 py-2.5 pl-4 pr-2 text-sm font-medium shadow-[var(--shadow-floating)] backdrop-blur-xl",
          isDanger
            ? "border-[var(--color-danger)]/35 text-[var(--color-danger)]"
            : "border-[var(--color-success)]/30 text-[var(--ink)]",
        )}
      >
        {isDanger ? (
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        ) : (
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-success)]" aria-hidden="true" />
        )}
        <span className="min-w-0 flex-1 leading-5">{message}</span>
        <button
          type="button"
          onClick={onClose}
          className={cn(
            "grid h-7 w-7 shrink-0 place-items-center rounded-full text-[var(--color-text-hint)] transition",
            isDanger
              ? "hover:bg-[var(--color-danger-light)] hover:text-[var(--color-danger)]"
              : "hover:bg-[var(--color-success-light)] hover:text-[var(--color-success)]",
          )}
          aria-label="关闭提示"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
