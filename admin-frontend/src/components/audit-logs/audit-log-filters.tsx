"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Search, X, RefreshCw, RotateCcw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import {
  ACTION_LABELS,
  SEVERITY_LABELS,
  STATUS_LABELS,
  RESOURCE_TYPE_LABELS,
  actionLabel,
} from "./action-labels";
import type { SelectOption } from "@/components/ui/custom-select";

const DEBOUNCE_MS = 300;
const KEYWORD_MAX_LENGTH = 200;

// Build select options
const SEVERITY_OPTIONS: SelectOption[] = [
  { value: "", label: "全部级别" },
  ...Object.entries(SEVERITY_LABELS).map(([value, label]) => ({ value, label })),
];

const STATUS_OPTIONS: SelectOption[] = [
  { value: "", label: "全部状态" },
  ...Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label })),
];

const ACTION_OPTIONS: SelectOption[] = [
  { value: "", label: "全部操作" },
  ...Object.entries(ACTION_LABELS).map(([value, label]) => ({ value, label, suffix: value })),
];

const RESOURCE_TYPE_OPTIONS: SelectOption[] = [
  { value: "", label: "全部资源" },
  ...Object.entries(RESOURCE_TYPE_LABELS).map(([value, label]) => ({ value, label, suffix: value })),
];

export type AuditLogFiltersState = {
  keyword: string;
  debouncedKeyword: string;
  severity: string;
  status: string;
  action: string;
  resourceType: string;
  dateFrom: string;
  dateTo: string;
};

export type AuditLogFiltersProps = {
  filters: AuditLogFiltersState;
  onFilterChange: (patch: Partial<AuditLogFiltersState>) => void;
  onReset: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
};

export function AuditLogFilters({
  filters,
  onFilterChange,
  onReset,
  onRefresh,
  isRefreshing,
}: AuditLogFiltersProps) {
  const { keyword, severity, status, action, resourceType, dateFrom, dateTo } = filters;

  // Keyword debounce
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [localKeyword, setLocalKeyword] = useState(keyword);

  useEffect(() => {
    setLocalKeyword(keyword);
  }, [keyword]);

  const handleKeywordChange = useCallback(
    (value: string) => {
      setLocalKeyword(value);
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      if (value === "") {
        onFilterChange({ keyword: "", debouncedKeyword: "" });
        return;
      }
      debounceTimer.current = setTimeout(() => {
        onFilterChange({ keyword: value, debouncedKeyword: value });
      }, DEBOUNCE_MS);
    },
    [onFilterChange],
  );

  const clearKeyword = useCallback(() => {
    setLocalKeyword("");
    onFilterChange({ keyword: "", debouncedKeyword: "" });
  }, [onFilterChange]);

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, []);

  // Count active filters
  const activeFilterCount = [severity, status, action, resourceType, dateFrom, dateTo].filter(Boolean).length;

  return (
    <div className="space-y-3">
      {/* Row 1: keyword + action + resource type + severity + status */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        {/* Search */}
        <div className="relative xl:col-span-2">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
          <Input
            className="pl-9 pr-8"
            placeholder="搜索操作、资源、操作人或资源 ID"
            value={localKeyword}
            maxLength={KEYWORD_MAX_LENGTH}
            onChange={(e) => handleKeywordChange(e.target.value)}
          />
          {localKeyword && (
            <button
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-hint)] transition-colors hover:text-[var(--ink)]"
              onClick={clearKeyword}
              aria-label="清除搜索"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Action type (searchable) */}
        <CustomSelect
          value={action}
          onChange={(v) => onFilterChange({ action: v })}
          options={ACTION_OPTIONS}
          placeholder="全部操作"
          searchable
          searchPlaceholder="搜索操作名称..."
        />

        {/* Resource type (searchable) */}
        <CustomSelect
          value={resourceType}
          onChange={(v) => onFilterChange({ resourceType: v })}
          options={RESOURCE_TYPE_OPTIONS}
          placeholder="全部资源"
          searchable
          searchPlaceholder="搜索资源类型..."
        />

        {/* Severity */}
        <CustomSelect
          value={severity}
          onChange={(v) => onFilterChange({ severity: v })}
          options={SEVERITY_OPTIONS}
          placeholder="全部级别"
        />

        {/* Status */}
        <CustomSelect
          value={status}
          onChange={(v) => onFilterChange({ status: v })}
          options={STATUS_OPTIONS}
          placeholder="全部状态"
        />
      </div>

      {/* Row 2: date range + actions */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-medium text-[var(--color-text-secondary)]">日期范围</span>
        <Input
          className="h-11 w-auto min-w-[140px] flex-1 sm:flex-none sm:w-40"
          type="date"
          value={dateFrom}
          onChange={(e) => onFilterChange({ dateFrom: e.target.value })}
          aria-label="开始日期"
        />
        <span className="text-[var(--color-text-hint)]">—</span>
        <Input
          className="h-11 w-auto min-w-[140px] flex-1 sm:flex-none sm:w-40"
          type="date"
          value={dateTo}
          onChange={(e) => onFilterChange({ dateTo: e.target.value })}
          aria-label="结束日期"
        />
        {(dateFrom || dateTo) && (
          <span className="text-xs text-[var(--color-text-hint)]">默认查询近 183 天</span>
        )}

        <div className="ml-auto flex gap-2">
          <Button variant="secondary" onClick={onReset} size="sm">
            <RotateCcw className="h-4 w-4" />
            重置
          </Button>
          <Button variant="secondary" onClick={onRefresh} disabled={isRefreshing} size="sm">
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
            刷新
          </Button>
        </div>
      </div>

      {/* Active filter indicator */}
      {activeFilterCount > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-[var(--color-text-hint)]">
            已启用 {activeFilterCount} 个筛选条件
          </span>
          <button
            onClick={onReset}
            className="text-xs text-[var(--color-primary)] underline-offset-2 hover:underline"
          >
            清除全部
          </button>
        </div>
      )}
    </div>
  );
}
