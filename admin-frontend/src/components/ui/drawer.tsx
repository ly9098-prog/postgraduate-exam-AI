"use client";

import { createPortal } from "react-dom";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";

type DrawerProps = {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Accessibility label */
  ariaLabel?: string;
};

/**
 * True when this drawer is the top-most modal surface. A confirm dialog opened
 * from inside the drawer must own Escape/focus until it closes.
 */
function isTopModalSurface(drawer: HTMLElement | null): boolean {
  if (!drawer) return true;
  const modals = Array.from(
    document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]'),
  );
  const topModal = modals.at(-1);
  return !topModal || topModal.contains(drawer);
}

/**
 * Slide-in drawer from the right edge via portal.
 *
 * - Animates in/out with CSS transitions (opacity + translateX).
 * - Locks background scroll while open.
 * - Closes on Escape and overlay click.
 * - Respects prefers-reduced-motion.
 */
export function Drawer({
  open,
  onClose,
  title,
  children,
  className,
  ariaLabel = "抽屉",
}: DrawerProps) {
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Mount/unmount with delay for exit animation. The mount flag cannot be
  // derived from `open` because the DOM must stay mounted while sliding out.
  useEffect(() => {
    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMounted(true);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setVisible(true));
      });
    } else {
      setVisible(false);
      const timer = setTimeout(() => {
        setMounted(false);
        previousFocusRef.current?.focus();
      }, 250);
      return () => clearTimeout(timer);
    }
  }, [open]);

  // Body scroll lock
  useEffect(() => {
    if (visible) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [visible]);

  // Escape key
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === "Escape" && isTopModalSurface(drawerRef.current)) onClose();
  }, [onClose]);

  useEffect(() => {
    if (visible) {
      document.addEventListener("keydown", handleKeyDown);
      drawerRef.current?.focus();
    }
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [visible, handleKeyDown]);

  // Focus trap: keep tab within drawer
  useEffect(() => {
    if (!visible || !drawerRef.current) return;
    const drawer = drawerRef.current;
    const handleFocusTrap = (e: FocusEvent) => {
      if (drawer.contains(e.target as Node)) return;
      if (!isTopModalSurface(drawer)) return;
      drawer.focus();
    };
    document.addEventListener("focusin", handleFocusTrap);
    return () => document.removeEventListener("focusin", handleFocusTrap);
  }, [visible]);

  if (!mounted) return null;

  return createPortal(
    <div
      className={cn(
        "fixed inset-0 z-50 flex justify-end transition-all duration-250 ease-out",
        visible ? "bg-[rgba(16,24,40,0.32)]" : "bg-transparent",
      )}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel}
    >
      <aside
        ref={drawerRef}
        tabIndex={-1}
        className={cn(
          "flex h-full flex-col bg-white shadow-xl outline-none transition-all duration-250 ease-out",
          "motion-reduce:transition-none",
          visible ? "translate-x-0" : "translate-x-full",
          className || "w-full max-w-2xl",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        {title && (
          <div className="flex shrink-0 items-center justify-between border-b border-[var(--color-border)] px-6 py-4">
            <div className="min-w-0 flex-1">{title}</div>
            <button
              onClick={onClose}
              className="ml-4 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--color-text-hint)] transition-colors hover:bg-[var(--color-primary-light)] hover:text-[var(--ink)]"
              aria-label="关闭"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {children}
        </div>
      </aside>
    </div>,
    document.body,
  );
}
