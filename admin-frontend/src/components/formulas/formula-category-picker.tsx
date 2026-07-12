"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronRight, Search, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/* ── Types ── */

export type FormulaCategoryNode = {
  id: number;
  parent_id: number | null;
  code: string;
  name: string;
  node_type: string;
  exam_scope?: string;
  is_active?: boolean;
  children: FormulaCategoryNode[];
};

type PickerMode = "filter" | "form";

/* ── Props ── */

export type FormulaCategoryPickerProps = {
  mode: PickerMode;
  value: number | null;
  onChange: (value: number | null) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  error?: string;
};

/* ── Helpers ── */

function findNodePath(
  tree: FormulaCategoryNode[],
  targetId: number,
): FormulaCategoryNode[] | null {
  for (const node of tree) {
    if (node.id === targetId) return [node];
    const found = findNodePath(node.children, targetId);
    if (found) return [node, ...found];
  }
  return null;
}

function flattenTree(tree: FormulaCategoryNode[]): FormulaCategoryNode[] {
  const result: FormulaCategoryNode[] = [];
  for (const node of tree) {
    result.push(node);
    result.push(...flattenTree(node.children));
  }
  return result;
}

/* ── Component ── */

export function FormulaCategoryPicker({
  mode,
  value,
  onChange,
  placeholder = "选择分类",
  disabled = false,
  className = "",
  error,
}: FormulaCategoryPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const triggerRef = useRef<HTMLDivElement>(null);
  const [dropdownEl, setDropdownEl] = useState<HTMLDivElement | null>(null);

  const categories = useQuery({
    queryKey: ["admin-formula-categories"],
    queryFn: () => apiRequest<{ items: FormulaCategoryNode[] }>("/formulas/categories"),
    staleTime: 60000,
  });

  const allNodes = useMemo(() => {
    if (!categories.data?.items) return [];
    return flattenTree(categories.data.items);
  }, [categories.data?.items]);

  const selectedNode = value ? (allNodes.find((n) => n.id === value) ?? null) : null;

  const selectedPath = value && categories.data?.items
    ? findNodePath(categories.data.items, value)
    : null;

  // Display the full path in the trigger for form mode
  const triggerLabel = selectedPath
    ? selectedPath.map((n) => n.name).join(" / ")
    : selectedNode?.name || placeholder;

  // Close handlers
  const close = useCallback(() => {
    setOpen(false);
    setSearch("");
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: PointerEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current?.contains(target) ||
        dropdownEl?.contains(target)
      ) {
        return;
      }
      close();
    };
    document.addEventListener("pointerdown", handler, { capture: true });
    return () => document.removeEventListener("pointerdown", handler, { capture: true });
  }, [open, close, dropdownEl]);

  useEffect(() => {
    if (!open) return;
    const escHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
        triggerRef.current?.querySelector("button")?.focus();
      }
    };
    document.addEventListener("keydown", escHandler);
    return () => document.removeEventListener("keydown", escHandler);
  }, [open, close]);

  // Clear search on close
  useEffect(() => {
    if (!open) {
      const id = setTimeout(() => setSearch(""), 0);
      return () => clearTimeout(id);
    }
  }, [open]);

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const canSelect = (node: FormulaCategoryNode): boolean => {
    if (mode === "form") return node.node_type === "group";
    return true; // filter mode can select any level
  };

  const handleSelect = (node: FormulaCategoryNode) => {
    if (!canSelect(node)) {
      // In form mode, toggle expand when clicking non-group nodes
      toggleExpand(node.id);
      return;
    }
    onChange(node.id);
    close();
  };

  // Auto-expand to show selected node
  useEffect(() => {
    if (open && value && categories.data?.items) {
      const path = findNodePath(categories.data.items, value);
      if (path) {
        setExpanded((prev) => {
          const next = new Set(prev);
          path!.forEach((n) => next.add(n.id));
          return next;
        });
      }
    }
  }, [open, value, categories.data]);

  const renderTree = (nodes: FormulaCategoryNode[], depth = 0) => {
    const filtered = search
      ? nodes.filter((n) => {
          const match =
            n.name.toLowerCase().includes(search.toLowerCase()) ||
            n.code.toLowerCase().includes(search.toLowerCase());
          const childMatch = n.children?.length
            ? n.children.some((c) => {
                const cm =
                  c.name.toLowerCase().includes(search.toLowerCase()) ||
                  c.code.toLowerCase().includes(search.toLowerCase());
                return cm;
              })
            : false;
          return match || childMatch;
        })
      : nodes;

    return filtered.map((node) => {
      const isExpanded = expanded.has(node.id);
      const isSelected = value === node.id;
      const selectable = canSelect(node);
      const hasChildren = node.children?.length > 0;

      // In search mode, always show children that match
      const showChildren = search ? hasChildren : hasChildren && isExpanded;
      const searchActive = search.length > 0;

      // During search, expand matching parents
      const childMatch = searchActive && hasChildren && node.children.some(
        (c) =>
          c.name.toLowerCase().includes(search.toLowerCase()) ||
          c.code.toLowerCase().includes(search.toLowerCase()),
      );
      const selfMatch = node.name.toLowerCase().includes(search.toLowerCase()) ||
        node.code.toLowerCase().includes(search.toLowerCase());

      if (searchActive && !selfMatch && !childMatch) return null;

      return (
        <div key={node.id}>
          <button
            type="button"
            onClick={() => handleSelect(node)}
            disabled={!selectable}
            className={cn(
              "flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors",
              isSelected
                ? "bg-[var(--color-primary-light)] font-medium text-[var(--ink)]"
                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-primary-light)]/40",
              !selectable && "cursor-pointer font-medium text-[var(--ink)]",
              selectable && !isSelected && "cursor-pointer",
            )}
            style={{ paddingLeft: 12 + depth * 20 }}
          >
            {hasChildren ? (
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  toggleExpand(node.id);
                }}
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-[var(--color-border)]"
              >
                {isExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
              </span>
            ) : (
              <span className="w-5 shrink-0" />
            )}
            <span
              className={cn(
                "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                node.node_type === "subject"
                  ? "bg-blue-50 text-blue-700"
                  : node.node_type === "chapter"
                    ? "bg-green-50 text-green-700"
                    : "bg-gray-100 text-gray-600",
              )}
            >
              {node.node_type === "subject"
                ? "科目"
                : node.node_type === "chapter"
                  ? "章节"
                  : "分组"}
            </span>
            <span className="min-w-0 flex-1 truncate">{node.name}</span>
            {!selectable && (
              <span className="shrink-0 text-[10px] text-[var(--color-text-hint)]">
                选择{node.node_type === "subject" ? "科目" : "章节"}
              </span>
            )}
          </button>
          {showChildren && renderTree(node.children, depth + 1)}
          {searchActive && childMatch && renderTree(node.children, depth + 1)}
        </div>
      );
    });
  };

  return (
    <div ref={triggerRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        className={cn(
          "flex h-11 w-full items-center justify-between rounded-xl border bg-[var(--color-bg-input)] px-3 text-sm transition-all",
          open
            ? "border-[var(--color-primary)] ring-4 ring-[rgba(91,123,154,0.14)]"
            : "border-[var(--color-border)] hover:border-[var(--color-primary)]",
          disabled && "cursor-default opacity-50",
          error && "border-red-400",
        )}
      >
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-left",
            selectedNode ? "text-[var(--ink)]" : "text-[var(--color-text-hint)]",
          )}
        >
          {triggerLabel}
        </span>
        {value && (
          <span
            role="button"
            tabIndex={-1}
            onClick={(e) => {
              e.stopPropagation();
              onChange(null);
            }}
            className="mr-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[var(--color-text-hint)] hover:bg-[var(--color-border)] hover:text-[var(--ink)]"
            aria-label="清除选择"
          >
            <X className="h-3 w-3" />
          </span>
        )}
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-[var(--color-text-hint)] transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {error && (
        <p className="mt-1 text-xs text-red-500">{error}</p>
      )}

      {open && createPortal(
        <CategoryPickerDropdown
          triggerRef={triggerRef}
          search={search}
          onSearchChange={setSearch}
          renderTree={() => {
            const tree = categories.data?.items;
            if (!tree) {
              return (
                <div className="flex items-center justify-center px-4 py-8 text-xs text-[var(--color-text-hint)]">
                  加载中...
                </div>
              );
            }
            const rendered = renderTree(tree);
            if (!rendered || rendered.length === 0) {
              return (
                <div className="flex items-center justify-center px-4 py-8 text-xs text-[var(--color-text-hint)]">
                  无匹配分类
                </div>
              );
            }
            return rendered;
          }}
          setDropdownEl={setDropdownEl}
        />,
        document.body,
      )}
    </div>
  );
}

/* ── Portal Dropdown ── */

function CategoryPickerDropdown({
  triggerRef,
  search,
  onSearchChange,
  renderTree,
  setDropdownEl,
}: {
  triggerRef: React.RefObject<HTMLDivElement | null>;
  search: string;
  onSearchChange: (v: string) => void;
  renderTree: () => React.ReactNode;
  setDropdownEl: (el: HTMLDivElement | null) => void;
}) {
  const [style, setStyle] = useState<React.CSSProperties>({
    position: "fixed",
    zIndex: 9999,
    visibility: "hidden",
    minWidth: 240,
  });
  const [mounted, setMounted] = useState(false);

  useLayoutEffect(() => {
    const btn = triggerRef.current?.querySelector("button");
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom - 12;
    const spaceAbove = rect.top - 12;
    const dir = spaceBelow >= spaceAbove ? "down" : "up";
    const maxH = dir === "down" ? Math.min(spaceBelow, 400) : Math.min(spaceAbove, 400);

    const dropdownWidth = Math.min(
      Math.max(rect.width, 280),
      window.innerWidth - 16,
    );

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
      minWidth: 240,
      maxHeight: Math.max(maxH, 200),
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      top,
      bottom,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - dropdownWidth - 8)),
    });
    requestAnimationFrame(() => setMounted(true));
  }, [triggerRef]);

  return (
    <div
      ref={(el) => setDropdownEl(el)}
      className={cn(
        "rounded-xl border border-[var(--color-border)]/80 bg-white shadow-lg transition-all duration-150",
        mounted ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0",
      )}
      style={style}
    >
      <div className="relative shrink-0 border-b border-[var(--color-border)]/60 p-2">
        <Search className="absolute left-4 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-hint)]" />
        <input
          className="h-8 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] pl-7 pr-2 text-xs outline-none focus:border-[var(--color-primary)]"
          placeholder="搜索分类名称或编码..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
      <div
        className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden py-1"
        style={{ maxHeight: "360px" }}
      >
        {renderTree()}
      </div>
    </div>
  );
}
