"use client";

import { createPortal } from "react-dom";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  loading?: boolean;
  /** Prevent submission while inline validation is incomplete. */
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: React.ReactNode;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmText = "确认",
  cancelText = "取消",
  danger = false,
  loading = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
  children,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCancelRef = useRef(onCancel);
  const loadingRef = useRef(loading);

  // Keep latest props in refs so the focus/Escape effect does not re-run (and
  // steal focus) on every keystroke in dialog children.
  useEffect(() => {
    onCancelRef.current = onCancel;
    loadingRef.current = loading;
  });

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const dialog = dialogRef.current;
    if (dialog && !dialog.contains(document.activeElement)) {
      const preferred = dialog.querySelector<HTMLElement>("[autofocus]");
      (preferred ?? dialog).focus();
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !loadingRef.current) onCancelRef.current();
    };
    const handleFocusIn = (event: FocusEvent) => {
      if (dialog && !dialog.contains(event.target as Node)) dialog.focus();
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("focusin", handleFocusIn);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("focusin", handleFocusIn);
      previousFocusRef.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div className="animate-fade-in fixed inset-0 z-50 flex items-center justify-center bg-[rgba(16,24,40,0.42)] px-4">
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        data-confirm-dialog="true"
        className="animate-drop-in w-full max-w-md rounded-3xl border border-[var(--color-border)] bg-white p-6 shadow-[var(--shadow-floating)] outline-none"
      >
        <h3 className="font-display text-2xl font-bold text-[var(--ink)]">{title}</h3>
        {description ? <p className="mt-3 text-sm leading-6 text-[var(--color-text-secondary)]">{description}</p> : null}
        {children ? <div className="mt-4">{children}</div> : null}
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="secondary" onClick={onCancel} disabled={loading}>
            {cancelText}
          </Button>
          <Button className={cn(loading && "cursor-wait")} variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={loading || confirmDisabled}>
            {loading ? "处理中..." : confirmText}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
