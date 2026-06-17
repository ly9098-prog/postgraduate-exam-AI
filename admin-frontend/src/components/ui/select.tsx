"use client";

import { createPortal } from "react-dom";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
  suffix?: string;
  disabled?: boolean;
}

export function Select({
  value,
  onChange,
  options,
  placeholder = "选择...",
  disabled,
  className,
  optionClassName,
  color,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  optionClassName?: string;
  color?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const activeIndexRef = useRef(-1);

  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (!open) {
      activeIndexRef.current = -1;
    }
  }, [open]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!disabled) setOpen((v) => !v);
    }
    if (e.key === "Escape") {
      setOpen(false);
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const dir = e.key === "ArrowDown" ? 1 : -1;
      let next = activeIndexRef.current + dir;
      if (next < 0) next = options.length - 1;
      if (next >= options.length) next = 0;
      activeIndexRef.current = next;
      const el = listRef.current?.children[next] as HTMLElement | undefined;
      el?.focus();
    }
  };

  return (
    <div ref={ref} className="relative" onKeyDown={handleKeyDown}>
      <button
        type="button"
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-white pl-3 pr-2 text-xs font-medium outline-none transition-all duration-150",
          "cursor-pointer disabled:cursor-default disabled:opacity-50",
          open && "ring-2",
          className,
        )}
        style={{
          borderColor: open && color ? color : undefined,
          ...(open && color ? { boxShadow: `0 0 0 3px ${color}15` } : {}),
        }}
      >
        <span className="flex-1 truncate text-left text-[var(--ink)]">
          {selected ? selected.label : placeholder}
        </span>
        {selected?.suffix && (
          <span className="shrink-0 text-[10px] text-[var(--color-text-hint)]">{selected.suffix}</span>
        )}
        <svg
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-[var(--color-text-hint)] transition-transform duration-200",
            open && "rotate-180",
          )}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <PortalDropdown
          triggerRef={ref}
          color={color}
          optionClassName={optionClassName}
          value={value}
          onChange={(v) => { onChange(v); setOpen(false); }}
          options={options}
        />
      )}
    </div>
  );
}

function PortalDropdown({
  triggerRef,
  color,
  optionClassName,
  value,
  onChange,
  options,
}: {
  triggerRef: React.RefObject<HTMLDivElement | null>;
  color?: string;
  optionClassName?: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
}) {
  const [style, setStyle] = useState<React.CSSProperties>({});
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const btn = triggerRef.current?.querySelector("button");
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const estH = 44;
    const spaceBelow = window.innerHeight - rect.bottom - 8;
    const spaceAbove = rect.top - 8;
    const dir = spaceBelow >= estH || spaceBelow > spaceAbove ? "down" : "up";

    setStyle({
      position: "fixed",
      zIndex: 9999,
      minWidth: Math.max(rect.width, 200),
      ...(dir === "down"
        ? { top: rect.bottom + 6, left: rect.left }
        : { bottom: window.innerHeight - rect.top + 6, left: rect.left }),
    });
  }, [triggerRef]);

  return createPortal(
    <div
      ref={listRef}
      role="listbox"
      className={cn(
        "overflow-hidden rounded-xl border border-[var(--color-border)]/80 bg-white py-1 shadow-lg",
        optionClassName,
      )}
      style={style}
    >
      {options.length === 0 ? (
        <div className="px-4 py-3 text-xs text-[var(--color-text-hint)]">无可用选项</div>
      ) : (
        options.map((opt) => {
          const isSelected = opt.value === value;
          return (
            <button
              key={opt.value}
              type="button"
              role="option"
              aria-selected={isSelected}
              disabled={opt.disabled}
              onClick={() => onChange(opt.value)}
              className={cn(
                "flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs transition-colors",
                isSelected
                  ? "font-semibold text-[var(--ink)]"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-primary-light)]",
                opt.disabled && "cursor-not-allowed opacity-40",
              )}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 shrink-0 rounded-full transition-opacity",
                  isSelected ? "opacity-100" : "opacity-0",
                )}
                style={{ backgroundColor: color }}
              />
              <span className="flex-1">{opt.label}</span>
              {opt.suffix && (
                <span className="shrink-0 text-[10px] text-[var(--color-text-hint)]">{opt.suffix}</span>
              )}
            </button>
          );
        })
      )}
    </div>,
    document.body,
  );
}
