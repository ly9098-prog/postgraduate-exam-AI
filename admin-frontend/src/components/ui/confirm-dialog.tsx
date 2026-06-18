"use client";

import { createPortal } from "react-dom";
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
  onConfirm,
  onCancel,
  children,
}: ConfirmDialogProps) {
  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(16,24,40,0.42)] px-4">
      <div className="w-full max-w-md rounded-3xl border border-[var(--color-border)] bg-white p-6 shadow-[var(--shadow-floating)]">
        <h3 className="font-display text-2xl font-bold text-[var(--ink)]">{title}</h3>
        {description ? <p className="mt-3 text-sm leading-6 text-[var(--color-text-secondary)]">{description}</p> : null}
        {children ? <div className="mt-4">{children}</div> : null}
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="secondary" onClick={onCancel} disabled={loading}>
            {cancelText}
          </Button>
          <Button className={cn(loading && "cursor-wait")} variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={loading}>
            {loading ? "处理中..." : confirmText}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
