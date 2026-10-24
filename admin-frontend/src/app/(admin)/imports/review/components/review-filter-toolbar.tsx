"use client";

import { Check, ChevronDown, Search, X } from "lucide-react";
import type { RefObject } from "react";
import type { ImportBatchListItem } from "@/lib/api/types";
import { shouldShowReviewFilterReset, type ReviewFilters } from "../review-query-state";
import type { ReviewSubjectOption } from "../review-subject-state";

type FilterDropdownOption = {
  value: string;
  label: string;
  shortLabel?: string;
};

const STATUS_OPTIONS = [
  { value: "pending", label: "待审核" },
  { value: "approved", label: "已通过" },
  { value: "rejected", label: "已驳回" },
  { value: "published", label: "已发布" },
  { value: "", label: "全部状态" },
] as const;

const RISK_FILTER_OPTIONS = [
  { value: "", label: "全部", shortLabel: "全部" },
  { value: "high", label: "高风险", shortLabel: "高" },
  { value: "medium", label: "中风险", shortLabel: "中" },
  { value: "low", label: "低风险", shortLabel: "低" },
];

const ANSWER_STATUS_FILTER_OPTIONS = [
  { value: "", label: "全部", shortLabel: "全部" },
  { value: "missing", label: "答案缺失", shortLabel: "缺失" },
  { value: "ai_filled", label: "AI补全", shortLabel: "AI补全" },
  { value: "imported", label: "已导入", shortLabel: "已导入" },
  { value: "manual_verified", label: "已验证", shortLabel: "已验证" },
  { value: "abnormal", label: "答案异常", shortLabel: "异常" },
];

type DropdownKey = "risk" | "answerStatus" | "subject" | "batch" | "status";

type ReviewFilterToolbarProps = {
  filters: ReviewFilters;
  batchIdParam: string;
  subjectOptions: Array<ReviewSubjectOption & { code: string; name: string }>;
  leafSubjectOptions: Array<ReviewSubjectOption & { code: string; name: string }>;
  batches: ImportBatchListItem[];
  batchesLoading: boolean;
  dropdownState: Record<DropdownKey, boolean>;
  subjectButtonRef: RefObject<HTMLButtonElement | null>;
  batchDropdownRef: RefObject<HTMLDivElement | null>;
  onKeywordChange: (keyword: string) => void;
  onFilterChange: (key: "batch_id" | "status" | "subject_id" | "risk_level" | "answer_status", value: string) => void;
  onReset: () => void;
  onDropdownChange: (key: DropdownKey, open: boolean) => void;
};

function FilterDropdown({
  label,
  value,
  options,
  open,
  setOpen,
  onChange,
}: {
  label: string;
  value: string;
  options: FilterDropdownOption[];
  open: boolean;
  setOpen: (open: boolean | ((current: boolean) => boolean)) => void;
  onChange: (value: string) => void;
}) {
  const activeOption = options.find((o) => o.value === value);
  const buttonLabel = value
    ? `${label}：${activeOption?.shortLabel || activeOption?.label || value}`
    : label;

  return (
    <div className="relative">
      <button
        type="button"
        className={`flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs outline-none transition ${
          value
            ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)]"
            : "border-[var(--color-border)] bg-white text-[var(--color-text-primary)] hover:border-[var(--color-primary)]/50"
        }`}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{buttonLabel}</span>
        <ChevronDown className={`h-3 w-3 text-[var(--color-text-hint)] transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open ? (
        <div className="absolute left-0 top-full z-30 mt-1 min-w-[120px] overflow-hidden rounded-lg border border-[var(--color-border)] bg-white py-1 shadow-lg">
          {options.map((opt) => {
            const active = value === opt.value;
            return (
              <button
                key={opt.value || "all"}
                type="button"
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition hover:bg-[var(--color-primary-light)]/40 ${
                  active
                    ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold"
                    : "text-[var(--color-text-primary)]"
                }`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  onChange(opt.value);
                  setOpen(false);
                }}
              >
                {active ? (
                  <Check className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
                ) : (
                  <span className="inline-block w-3.5 shrink-0" />
                )}
                <span>{opt.label}</span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function ReviewFilterToolbar({
  filters,
  batchIdParam,
  subjectOptions,
  leafSubjectOptions,
  batches,
  batchesLoading,
  dropdownState,
  subjectButtonRef,
  batchDropdownRef,
  onKeywordChange,
  onFilterChange,
  onReset,
  onDropdownChange,
}: ReviewFilterToolbarProps) {
  const setDropdown = (key: DropdownKey, open: boolean | ((current: boolean) => boolean)) => {
    onDropdownChange(key, typeof open === "function" ? false : open);
  };
  const closeOtherDropdowns = (except: DropdownKey) => {
    (["risk", "answerStatus", "subject", "status"] as DropdownKey[]).forEach((key) => {
      if (key !== except) onDropdownChange(key, false);
    });
  };

  return (
    <>
      {/* ── Inline filter bar ── */}
          <div className="filter-bar flex flex-wrap items-center gap-2 px-3 py-2">
            {/* Search */}
            <div className="relative min-w-[180px] flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <input
                className="h-8 w-full rounded-lg border border-[var(--color-border)] bg-white pl-8 pr-3 text-xs outline-none transition-colors focus:border-[var(--color-primary)]"
                placeholder="搜索题干 / OCR 原文..."
                value={filters.keyword}
                onChange={(event) => onKeywordChange(event.target.value)}
              />
            </div>

            {/* Risk dropdown */}
            <FilterDropdown
              label="风险"
              value={filters.risk_level}
              options={RISK_FILTER_OPTIONS}
              open={dropdownState.risk}
              setOpen={(fn) => { setDropdown("risk", fn); closeOtherDropdowns("risk"); }}
              onChange={(value) => onFilterChange("risk_level", value)}
            />

            {/* Answer Status dropdown */}
            <FilterDropdown
              label="答案"
              value={filters.answer_status}
              options={ANSWER_STATUS_FILTER_OPTIONS}
              open={dropdownState.answerStatus}
              setOpen={(fn) => { setDropdown("answerStatus", fn); closeOtherDropdowns("answerStatus"); }}
              onChange={(value) => onFilterChange("answer_status", value)}
            />

            {/* Subject dropdown */}
            <div className="relative">
              <button
                ref={subjectButtonRef}
                type="button"
                className="flex h-8 items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-white px-2.5 text-xs text-[var(--color-text-primary)] outline-none transition focus:border-[var(--color-primary)]"
                onClick={() => onDropdownChange("subject", !dropdownState.subject)}
              >
                <span className="max-w-[160px] overflow-hidden text-ellipsis whitespace-nowrap" title={filters.subject_id ? (subjectOptions.find((s) => String(s.id) === filters.subject_id)?.name || filters.subject_id) : ""}>
                  {filters.subject_id ? (subjectOptions.find((s) => String(s.id) === filters.subject_id)?.name || filters.subject_id) : "全部科目"}
                </span>
                <ChevronDown className={`h-3 w-3 shrink-0 text-[var(--color-text-hint)] transition-transform ${dropdownState.subject ? "rotate-180" : ""}`} />
              </button>
              {dropdownState.subject ? (
                <div className="absolute left-0 top-full z-20 mt-1 min-w-[220px] max-w-[320px] max-h-72 overflow-y-auto scrollbar-hide rounded-lg border border-[var(--color-border)] bg-white py-1 shadow-lg">
                  <button
                    type="button"
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition hover:bg-[var(--color-primary-light)]/40 ${
                      !filters.subject_id ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold" : "text-[var(--color-text-primary)]"
                    }`}
                    onMouseDown={(e) => { e.preventDefault(); onFilterChange("subject_id", ""); onDropdownChange("subject", false); }}
                  >
                    {!filters.subject_id ? <Check className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" /> : <span className="inline-block w-3.5 shrink-0" />}
                    <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap">全部科目</span>
                  </button>
                  {leafSubjectOptions.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition hover:bg-[var(--color-primary-light)]/40 ${
                        filters.subject_id === String(s.id) ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold" : "text-[var(--color-text-primary)]"
                      }`}
                      onMouseDown={(e) => { e.preventDefault(); onFilterChange("subject_id", String(s.id)); onDropdownChange("subject", false); }}
                    >
                      {filters.subject_id === String(s.id) ? <Check className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" /> : <span className="inline-block w-3.5 shrink-0" />}
                      <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap" title={s.name}>{s.name}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            {/* Batch ID selector */}
            <div className="relative" ref={batchDropdownRef}>
              <div className="relative">
                <input
                  className="h-8 w-48 rounded-lg border border-[var(--color-border)] bg-white px-2.5 pr-14 text-xs outline-none transition-colors focus:border-[var(--color-primary)]"
                  placeholder="批次 ID"
                  value={filters.batch_id || batchIdParam}
                  onChange={(event) => onFilterChange("batch_id", event.target.value)}
                  onFocus={() => onDropdownChange("batch", true)}
                />
                {(filters.batch_id || batchIdParam) ? (
                  <button
                    type="button"
                    className="absolute right-6 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-[var(--color-text-hint)] hover:text-[var(--color-danger)] transition"
                    onClick={() => { onFilterChange("batch_id", ""); onDropdownChange("batch", false); }}
                    title="清空批次"
                  >
                    <X className="h-3 w-3" />
                  </button>
                ) : null}
                <button
                  type="button"
                  className="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-[var(--color-text-hint)] hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)] transition"
                  onClick={() => onDropdownChange("batch", !dropdownState.batch)}
                >
                  <ChevronDown className={`h-3.5 w-3.5 transition-transform ${dropdownState.batch ? "rotate-180" : ""}`} />
                </button>
              </div>
              {dropdownState.batch ? (
                <div className="scholar-dropdown absolute left-0 top-full z-20 mt-1 min-w-[300px] max-w-[360px] max-h-60">
                  {batchesLoading ? (
                    <div className="px-4 py-5 text-center text-xs text-[var(--color-text-hint)]">加载中…</div>
                  ) : batches.length ? (
                    batches
                      .filter((b) => b.batch_id && b.batch_id.trim() && b.pending_count > 0)
                      .map((b) => (
                      <button
                        key={b.batch_id}
                        type="button"
                        className={`flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-xs transition cursor-pointer hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] ${
                          (filters.batch_id || batchIdParam) === b.batch_id ? "bg-[var(--color-primary-light)]/20 font-semibold text-[var(--color-primary-dark)]" : "text-[var(--color-text-primary)]"
                        }`}
                        onMouseDown={(e) => { e.preventDefault(); onFilterChange("batch_id", b.batch_id); onDropdownChange("batch", false); }}
                      >
                        {(filters.batch_id || batchIdParam) === b.batch_id ? (
                          <Check className="h-3 w-3 shrink-0 text-[var(--color-primary)]" />
                        ) : (
                          <span className="inline-block w-3 shrink-0" />
                        )}
                        <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[11px]" title={b.batch_id}>{b.batch_id}</span>
                        <span className="tag-chip shrink-0 bg-[var(--color-success-light)] text-[var(--color-success)]">{b.pending_count}</span>
                      </button>
                    ))
                  ) : (
                    <div className="px-4 py-5 text-center text-xs text-[var(--color-text-hint)]">暂无可选批次</div>
                  )}
                </div>
              ) : null}
            </div>

            {/* Status dropdown */}
            <div className="relative">
              <button
                type="button"
                className="flex h-8 items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-white px-2.5 text-xs text-[var(--color-text-primary)] outline-none transition focus:border-[var(--color-primary)]"
                onClick={() => onDropdownChange("status", !dropdownState.status)}
                onBlur={() => setTimeout(() => onDropdownChange("status", false), 150)}
              >
                <span>{STATUS_OPTIONS.find((o) => o.value === filters.status)?.label}</span>
                <ChevronDown className={`h-3 w-3 text-[var(--color-text-hint)] transition-transform ${dropdownState.status ? "rotate-180" : ""}`} />
              </button>
              {dropdownState.status ? (
                <div className="absolute right-0 top-full z-20 mt-1 min-w-[120px] overflow-hidden rounded-lg border border-[var(--color-border)] bg-white py-1 shadow-lg">
                  {STATUS_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition hover:bg-[var(--color-primary-light)]/40 ${
                        filters.status === opt.value
                          ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold"
                          : "text-[var(--color-text-primary)]"
                      }`}
                      onMouseDown={(e) => { e.preventDefault(); onFilterChange("status", opt.value); onDropdownChange("status", false); }}
                    >
                      {filters.status === opt.value ? (
                        <Check className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
                      ) : (
                        <span className="inline-block w-3.5 shrink-0" />
                      )}
                      {opt.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            {shouldShowReviewFilterReset(filters) ? (
              <button
                type="button"
                className="flex h-7 items-center gap-1 rounded-lg px-2 text-[10px] font-medium text-[var(--color-text-hint)] hover:text-[var(--color-danger)] transition-colors"
                onClick={onReset}
              >
                重置
              </button>
            ) : null}
      </div>
    </>
  );
}
