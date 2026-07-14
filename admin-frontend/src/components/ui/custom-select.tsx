"use client";

import { createPortal } from "react-dom";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { Search, X } from "lucide-react";

export interface SelectOption {
  value: string;
  label: string;
  suffix?: string;
  disabled?: boolean;
}

/**
 * Find the next enabled index in the given direction, skipping disabled options.
 */
export function getNextEnabledIndex(
  current: number,
  direction: 1 | -1,
  items: SelectOption[],
): number {
  if (items.length === 0) return -1;
  const enabledIndices = items
    .map((o, i) => (o.disabled ? -1 : i))
    .filter((i) => i >= 0);
  if (enabledIndices.length === 0) return -1;

  const currentEnabledPos = enabledIndices.indexOf(current);
  let nextPos = (currentEnabledPos + direction) % enabledIndices.length;
  if (nextPos < 0) nextPos = enabledIndices.length - 1;
  return enabledIndices[nextPos];
}

/**
 * CustomSelect — dropdown with optional search, portal rendering, keyboard nav.
 *
 * - `searchable`: renders a search input inside the dropdown for filtering options.
 * - Supports ArrowUp/Down/Home/End/Enter/Escape keyboard navigation.
 * - Disabled options are skipped during keyboard navigation.
 * - Portaled to document.body so it's never clipped by overflow parents.
 */
export function CustomSelect({
  value,
  onChange,
  options,
  placeholder = "全部",
  searchable = false,
  searchPlaceholder = "搜索...",
  disabled,
  className,
  clearable = true,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  searchable?: boolean;
  searchPlaceholder?: string;
  disabled?: boolean;
  className?: string;
  clearable?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [dropdownEl, setDropdownEl] = useState<HTMLDivElement | null>(null);

  const selected = options.find((o) => o.value === value);
  const filtered = searchable && search
    ? options.filter(
        (o) =>
          o.label.toLowerCase().includes(search.toLowerCase()) ||
          o.value.toLowerCase().includes(search.toLowerCase()),
      )
    : options;

  // Correct active index after filtering changes
  useEffect(() => {
    if (activeIndex >= filtered.length) {
      setActiveIndex(filtered.length > 0 ? 0 : -1);
    }
  }, [filtered.length, activeIndex]);

  const close = useCallback(() => {
    setOpen(false);
    setActiveIndex(-1);
  }, []);

  useEffect(() => {
    const handler = (e: PointerEvent) => {
      const target = e.target as Node;
      if (ref.current?.contains(target) || dropdownEl?.contains(target)) return;
      close();
    };
    document.addEventListener("pointerdown", handler, { capture: true });
    return () => document.removeEventListener("pointerdown", handler, { capture: true });
  }, [close, dropdownEl]);

  useEffect(() => {
    if (!open) return;
    const escHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
        ref.current?.querySelector("button")?.focus();
      }
    };
    document.addEventListener("keydown", escHandler);
    return () => document.removeEventListener("keydown", escHandler);
  }, [open, close]);

  useEffect(() => {
    if (!open) {
      setSearch("");
      setActiveIndex(-1);
    } else if (searchable) {
      setTimeout(() => searchRef.current?.focus(), 50);
    }
  }, [open, searchable]);

  // Scroll active item into view
  useEffect(() => {
    if (!open || activeIndex < 0) return;
    const el = listRef.current?.children[activeIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [open, activeIndex]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!disabled) setOpen((v) => !v);
      return;
    }
    if (e.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
      ref.current?.querySelector("button")?.focus();
      return;
    }
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setOpen(true);
        return;
      }
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const dir = e.key === "ArrowDown" ? 1 : -1;
      const start = activeIndex < 0 ? -1 : activeIndex;
      setActiveIndex(getNextEnabledIndex(start, dir, filtered));
      return;
    }
    if (e.key === "Home") {
      e.preventDefault();
      const first = filtered.findIndex((o) => !o.disabled);
      setActiveIndex(first >= 0 ? first : -1);
      return;
    }
    if (e.key === "End") {
      e.preventDefault();
      const last = filtered
        .map((o, i) => (o.disabled ? -1 : i))
        .filter((i) => i >= 0)
        .pop();
      setActiveIndex(last ?? -1);
      return;
    }
    if (e.key === "Enter" && activeIndex >= 0 && activeIndex < filtered.length) {
      e.preventDefault();
      const option = filtered[activeIndex];
      if (option && !option.disabled) {
        onChange(option.value);
        setOpen(false);
        setActiveIndex(-1);
      }
      return;
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
        aria-controls={open ? "custom-select-listbox" : undefined}
        className={cn(
          "inline-flex h-11 w-full min-w-0 items-center gap-1.5 overflow-hidden rounded-xl border bg-[var(--color-bg-input)] pl-3 pr-2 text-sm outline-none transition-all duration-150",
          "cursor-pointer disabled:cursor-default disabled:opacity-50",
          open
            ? "border-[var(--color-primary)] bg-white ring-4 ring-[rgba(91,123,154,0.14)]"
            : "border-[var(--color-border)] hover:border-[var(--color-primary)]",
          className,
        )}
      >
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-left",
            selected ? "text-[var(--ink)]" : "text-[var(--color-text-hint)]",
          )}
        >
          {selected ? selected.label : placeholder}
        </span>
        {selected?.suffix && (
          <span
            className="max-w-[90px] shrink-0 truncate whitespace-nowrap text-[10px] text-[var(--color-text-hint)]"
            title={selected.suffix}
          >
            {selected.suffix}
          </span>
        )}
        {clearable && value && (
          <span
            role="button"
            tabIndex={-1}
            className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[var(--color-text-hint)] hover:bg-[var(--color-border)] hover:text-[var(--ink)]"
            onClick={(e) => {
              e.stopPropagation();
              onChange("");
            }}
            aria-label="清除选择"
          >
            <X className="h-3 w-3" />
          </span>
        )}
        <svg
          className={cn(
            "h-4 w-4 shrink-0 text-[var(--color-text-hint)] transition-transform duration-200",
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
          id="custom-select-listbox"
          triggerRef={ref}
          setDropdownEl={setDropdownEl}
          searchable={searchable}
          search={search}
          onSearchChange={setSearch}
          searchRef={searchRef}
          filtered={filtered}
          value={value}
          onChange={(v) => { onChange(v); setOpen(false); setActiveIndex(-1); }}
          listRef={listRef}
          activeIndex={activeIndex}
          onActiveIndexChange={setActiveIndex}
          searchPlaceholder={searchPlaceholder}
        />
      )}
    </div>
  );
}

function PortalDropdown({
  id,
  triggerRef,
  setDropdownEl,
  searchable,
  search,
  onSearchChange,
  searchRef,
  filtered,
  value,
  onChange,
  listRef,
  activeIndex,
  onActiveIndexChange,
  searchPlaceholder,
}: {
  id: string;
  triggerRef: React.RefObject<HTMLDivElement | null>;
  setDropdownEl: (el: HTMLDivElement | null) => void;
  searchable: boolean;
  search: string;
  onSearchChange: (v: string) => void;
  searchRef: React.RefObject<HTMLInputElement | null>;
  filtered: SelectOption[];
  value: string;
  onChange: (v: string) => void;
  listRef: React.RefObject<HTMLDivElement | null>;
  activeIndex: number;
  onActiveIndexChange: (idx: number) => void;
  searchPlaceholder: string;
}) {
  const [style, setStyle] = useState<React.CSSProperties>({
    position: "fixed",
    zIndex: 9999,
    visibility: "hidden",
    minWidth: 200,
  });
  const [mounted, setMounted] = useState(false);

  useLayoutEffect(() => {
    const btn = triggerRef.current?.querySelector("button");
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom - 12;
    const spaceAbove = rect.top - 12;
    const dir = spaceBelow >= spaceAbove ? "down" : "up";
    const maxH = dir === "down" ? Math.min(spaceBelow, 320) : Math.min(spaceAbove, 320);

    const minDropdownWidth = searchable ? 280 : Math.max(rect.width, 180);
    const dropdownWidth = Math.min(Math.max(rect.width, minDropdownWidth), window.innerWidth - 16);

    let top: number | undefined;
    let bottom: number | undefined;
    if (dir === "down") {
      top = rect.bottom + 4;
    } else {
      bottom = window.innerHeight - rect.top + 4;
    }

    setStyle({
      position: "fixed",
      zIndex: 9999,
      visibility: "visible",
      width: dropdownWidth,
      minWidth: minDropdownWidth,
      maxHeight: Math.max(maxH, 120),
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      top,
      bottom,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - dropdownWidth - 8)),
    });

    requestAnimationFrame(() => setMounted(true));
  }, [triggerRef, searchable]);

  return createPortal(
    <div
      ref={(el) => setDropdownEl(el)}
      role="listbox"
      id={id}
      className={cn(
        "rounded-xl border border-[var(--color-border)]/80 bg-white shadow-lg transition-all duration-150",
        mounted ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0",
      )}
      style={style}
    >
      {searchable && (
        <div className="relative shrink-0 border-b border-[var(--color-border)]/60 p-2">
          <Search className="absolute left-4 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-hint)]" />
          <input
            ref={searchRef}
            className="h-8 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] pl-7 pr-2 text-xs outline-none focus:border-[var(--color-primary)]"
            placeholder={searchPlaceholder}
            value={search}
            onChange={(e) => {
              onSearchChange(e.target.value);
              onActiveIndexChange(-1);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Escape") {
                e.stopPropagation();
              }
            }}
          />
        </div>
      )}
      <div
        ref={listRef}
        className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
        style={{ maxHeight: searchable ? "280px" : "320px" }}
      >
        {filtered.length === 0 ? (
          <div className="px-4 py-6 text-center text-xs text-[var(--color-text-hint)]">无匹配选项</div>
        ) : (
          filtered.map((opt, idx) => {
            const isSelected = opt.value === value;
            const isActive = activeIndex === idx;
            return (
              <button
                key={opt.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                disabled={opt.disabled}
                onClick={() => onChange(opt.value)}
                className={cn(
                  "flex w-full min-w-0 items-center gap-2.5 overflow-hidden whitespace-nowrap px-4 py-2.5 text-left text-sm transition-colors duration-100",
                  isSelected
                    ? "bg-[var(--color-primary-light)] font-medium text-[var(--ink)]"
                    : "text-[var(--color-text-secondary)]",
                  isActive && !isSelected && "bg-[var(--color-primary-light)]/60",
                  !isSelected && !isActive && "hover:bg-[var(--color-primary-light)]/40",
                  opt.disabled && "cursor-not-allowed opacity-40",
                )}
                onMouseEnter={() => { onActiveIndexChange(idx); }}
              >
                <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                  {isSelected && (
                    <svg className="h-4 w-4 text-[var(--color-primary)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                  )}
                </span>
                <span className="min-w-0 flex-1 truncate whitespace-nowrap">{opt.label}</span>
                {opt.suffix && (
                  <span
                    className="max-w-[120px] shrink-0 truncate whitespace-nowrap text-[10px] text-[var(--color-text-hint)]"
                    title={opt.suffix}
                  >
                    {opt.suffix}
                  </span>
                )}
              </button>
            );
          })
        )}
      </div>
    </div>,
    document.body,
  );
}
