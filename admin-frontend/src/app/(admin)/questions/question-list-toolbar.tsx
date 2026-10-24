"use client";

import type { RefObject } from "react";
import { Check, ChevronDown, Download, Layers, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

type QuestionListToolbarProps = {
  itemCount: number;
  total?: number;
  isFetching: boolean;
  isLoading: boolean;
  hasActiveFilters: boolean;
  selectedCount: number;
  allChecked: boolean;
  exportOpen: boolean;
  exportingFormat: "csv" | "docx" | null;
  exportMenuRef: RefObject<HTMLDivElement | null>;
  onToggleAll: () => void;
  onToggleExportMenu: () => void;
  onExport: (format: "csv" | "docx") => void;
};

export function QuestionListToolbar({
  itemCount,
  total,
  isFetching,
  isLoading,
  hasActiveFilters,
  selectedCount,
  allChecked,
  exportOpen,
  exportingFormat,
  exportMenuRef,
  onToggleAll,
  onToggleExportMenu,
  onExport,
}: QuestionListToolbarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1.25rem] border border-[var(--color-border)] bg-white px-3 py-2.5 shadow-sm">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="inline-flex h-9 items-center gap-1.5 rounded-full bg-[var(--color-primary-light)] px-3 text-xs font-semibold text-[var(--color-primary-dark)]">
          <Layers className="h-3.5 w-3.5" />
          题目总览
        </span>
        <span className="inline-flex h-9 items-center rounded-full bg-[var(--porcelain)] px-3 text-xs font-semibold text-[var(--ink)]">
          当前页 {itemCount} 题
        </span>
        {isFetching && !isLoading ? (
          <span className="inline-flex h-9 items-center gap-1.5 rounded-full px-2 text-xs font-medium text-[var(--color-text-hint)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            更新中
          </span>
        ) : null}
        {typeof total === "number" ? (
          <span className="inline-flex h-9 items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--color-text-secondary)]">
            共 {total} 题
          </span>
        ) : null}
        {hasActiveFilters ? (
          <span className="inline-flex h-9 items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--color-text-secondary)]">
            已启用筛选
          </span>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {selectedCount > 0 ? (
          <span className="inline-flex h-9 items-center rounded-full bg-[var(--color-primary-light)] px-4 text-sm font-semibold text-[var(--color-primary-dark)]">
            已选 {selectedCount} 项
          </span>
        ) : null}
        <button
          type="button"
          role="checkbox"
          aria-checked={allChecked}
          onClick={onToggleAll}
          className="inline-flex h-9 items-center gap-2 rounded-full border border-[var(--color-border)] bg-white px-4 text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
        >
          <span
            aria-hidden="true"
            className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[4px] border transition-colors ${
              allChecked
                ? "border-[var(--color-primary)] bg-[var(--color-primary)]"
                : "border-[var(--color-border)] bg-white"
            }`}
          >
            {allChecked ? (
              <Check className="h-3 w-3 text-white" strokeWidth={3} />
            ) : null}
          </span>
          <span className="font-medium">选择当前页</span>
        </button>
        <div ref={exportMenuRef} className="relative">
          <Button
            variant="secondary"
            onClick={onToggleExportMenu}
            aria-expanded={exportOpen}
            aria-haspopup="menu"
            disabled={!!exportingFormat}
            className="h-9 rounded-full px-3"
          >
            <Download className="h-4 w-4" />
            {exportingFormat
              ? exportingFormat === "csv"
                ? "导出 CSV 中..."
                : "导出 Word 中..."
              : "导出"}
            <ChevronDown
              className={`h-4 w-4 transition ${exportOpen ? "rotate-180" : ""}`}
            />
          </Button>
          {exportOpen ? (
            <div className="absolute right-0 top-full z-20 mt-2 min-w-[160px] animate-drop-in overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white p-1.5 shadow-[var(--shadow-floating)]">
              <button
                type="button"
                onClick={() => onExport("csv")}
                className="flex w-full items-center rounded-xl px-3 py-2 text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
              >
                导出 CSV
              </button>
              <button
                type="button"
                onClick={() => onExport("docx")}
                className="flex w-full items-center rounded-xl px-3 py-2 text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
              >
                导出 Word
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
