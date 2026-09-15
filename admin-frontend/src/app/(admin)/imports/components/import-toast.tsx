"use client";

import { useEffect, useRef } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type ImportToastTone = "success" | "error" | "warning" | "info";

export function ImportToast({
  message,
  title,
  tone = "info",
  onDismiss,
  duration = 3000,
  scrollable = true,
}: {
  message: string | null;
  title?: string | null;
  tone?: ImportToastTone;
  onDismiss: () => void;
  duration?: number;
  scrollable?: boolean;
}) {
  const onDismissRef = useRef(onDismiss);

  useEffect(() => {
    onDismissRef.current = onDismiss;
  }, [onDismiss]);

  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(() => onDismissRef.current(), duration);
    return () => window.clearTimeout(timer);
  }, [duration, message, tone]);

  if (!message) return null;

  const settings = {
    success: {
      icon: CheckCircle2,
      shell: "border-emerald-200/90 bg-emerald-50/95 text-emerald-900",
      iconWrap: "border-emerald-200 bg-white/80 text-emerald-700",
    },
    error: {
      icon: AlertCircle,
      shell: "border-red-200/90 bg-red-50/95 text-red-900",
      iconWrap: "border-red-200 bg-white/80 text-red-700",
    },
    warning: {
      icon: AlertTriangle,
      shell: "border-amber-200/90 bg-amber-50/95 text-amber-950",
      iconWrap: "border-amber-200 bg-white/80 text-amber-700",
    },
    info: {
      icon: Info,
      shell: "border-[rgba(74,111,138,0.24)] bg-[rgba(239,246,249,0.96)] text-[var(--color-primary-dark)]",
      iconWrap: "border-[rgba(74,111,138,0.20)] bg-white/80 text-[var(--color-primary-dark)]",
    },
  }[tone];
  const Icon = settings.icon;

  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      aria-live={tone === "error" ? "assertive" : "polite"}
      className={cn(
        "fixed right-4 top-24 z-[80] flex w-[min(500px,calc(100vw-2rem))] items-start gap-3 rounded-2xl border px-3.5 py-3 text-[13px] shadow-[0_18px_48px_rgba(27,39,51,0.16)] backdrop-blur-xl animate-drop-in sm:right-6",
        settings.shell,
      )}
    >
      <span className={cn("mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl border", settings.iconWrap)} aria-hidden="true">
        <Icon className="h-4 w-4" strokeWidth={1.9} />
      </span>
      <div className="min-w-0 flex-1 py-0.5">
        {title ? <p className="mb-1 font-semibold leading-5">{title}</p> : null}
        <p
          className={cn(
            "whitespace-pre-line break-words leading-5",
            scrollable && "max-h-[32vh] overflow-y-auto pr-1 [scrollbar-width:thin]",
            !scrollable && "overflow-visible",
          )}
        >
          {message}
        </p>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="grid h-8 w-8 shrink-0 place-items-center rounded-xl text-current/60 transition hover:bg-white/70 hover:text-current focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current/30"
        aria-label="关闭提示"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}
