"use client";

import type { RefObject } from "react";
import { ChevronDown, Filter, Loader2, RotateCcw, Search, SlidersHorizontal, Star, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { QUESTION_TYPE_OPTIONS } from "@/lib/question-types";
import type { QuestionSubjectOption } from "./hooks/use-question-subject-options";
import type { QuestionMenuKind } from "./hooks/use-question-menus";
import type { QuestionListFilters } from "./question-list-state";

const activeOptions = [
  { label: "全部状态", value: "" },
  { label: "启用", value: "true" },
  { label: "停用", value: "false" },
];

const difficultyOptions = [
  { label: "全部难度", value: "" },
  { label: "简单", value: "1" },
  { label: "较易", value: "2" },
  { label: "中等", value: "3" },
  { label: "较难", value: "4" },
  { label: "困难", value: "5" },
];

type QuestionFilterToolbarProps = {
  filters: QuestionListFilters;
  subjectOptions: QuestionSubjectOption[];
  keywordInput: string;
  importBatchInput: string;
  searchDebouncing: boolean;
  listFetching: boolean;
  hasActiveFilters: boolean;
  commonFilterOpen: boolean;
  moreFilterOpen: boolean;
  commonFilterRef: RefObject<HTMLDivElement | null>;
  moreFilterRef: RefObject<HTMLDivElement | null>;
  onKeywordChange: (value: string) => void;
  onResetFilters: () => void;
  onToggleMenu: (key: QuestionMenuKind) => void;
  onApplyFilterPreset: (preset: Partial<QuestionListFilters>) => void;
  onApplySavedFilters: () => void;
  onSaveCurrentFilters: (filters: QuestionListFilters) => void;
  onFilterChange: <K extends keyof QuestionListFilters>(key: K, value: QuestionListFilters[K]) => void;
  onImportBatchChange: (value: string) => void;
};

export function QuestionFilterToolbar({
  filters,
  subjectOptions,
  keywordInput,
  importBatchInput,
  searchDebouncing,
  listFetching,
  hasActiveFilters,
  commonFilterOpen,
  moreFilterOpen,
  commonFilterRef,
  moreFilterRef,
  onKeywordChange,
  onResetFilters,
  onToggleMenu,
  onApplyFilterPreset,
  onApplySavedFilters,
  onSaveCurrentFilters,
  onFilterChange,
  onImportBatchChange,
}: QuestionFilterToolbarProps) {
  return (
    <div className="space-y-3">
      <div className="rounded-[1.35rem] border border-[var(--color-border)] bg-white/90 px-5 py-3 shadow-[0_8px_24px_rgba(40,60,90,0.055)]">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <label className="flex h-11 w-full min-w-0 items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-white px-4 shadow-sm transition-all duration-200 hover:border-[var(--color-primary-light)] focus-within:border-[var(--color-primary)] focus-within:shadow-[0_0_0_3px_var(--color-primary-light)] xl:w-[38%] xl:min-w-[440px] xl:max-w-[600px]">
            <Search className="h-4 w-4 shrink-0 text-[var(--color-text-hint)]" />
            <input
              type="text"
              className="h-9 min-w-0 flex-1 border-0 bg-transparent px-0 text-sm text-[var(--color-text-primary)] outline-none placeholder:text-[var(--color-text-hint)] focus:outline-none"
              placeholder="搜索题干 / 科目 / 题目编号"
              value={keywordInput}
              onChange={(event) => onKeywordChange(event.target.value)}
            />
            <div className="flex shrink-0 items-center gap-1">
              {searchDebouncing || (listFetching && Boolean(filters.keyword)) ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-text-hint)]" />
              ) : null}
              {keywordInput ? (
                <button
                  type="button"
                  onClick={() => onKeywordChange("")}
                  className="grid h-7 w-7 place-items-center rounded-lg text-[var(--color-text-hint)] transition hover:bg-[var(--color-primary-light)] hover:text-[var(--ink)]"
                  aria-label="清空搜索"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
          </label>

          <span
            className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-semibold text-[var(--ink)] shadow-sm"
            aria-label="筛选条件"
          >
            <Filter className="h-4 w-4 text-[var(--color-primary)]" />
            筛选
          </span>

          <Button
            variant="ghost"
            onClick={onResetFilters}
            disabled={!hasActiveFilters}
            className="h-11 shrink-0 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm text-[var(--color-text-secondary)] shadow-sm hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)] disabled:opacity-45"
          >
            <RotateCcw className="h-4 w-4" />
            重置
          </Button>

          <div className="hidden h-7 w-px shrink-0 bg-[var(--color-border)] xl:block" />

          <div ref={commonFilterRef} className="relative shrink-0">
            <button
              type="button"
              onClick={() => onToggleMenu("isCommonFilterOpen")}
              aria-expanded={commonFilterOpen}
              aria-haspopup="menu"
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
            >
              常用筛选
              <ChevronDown
                className={`h-4 w-4 text-[var(--color-text-hint)] transition ${commonFilterOpen ? "rotate-180" : ""}`}
              />
            </button>
            {commonFilterOpen ? (
              <div className="absolute left-0 top-full z-30 mt-2 min-w-[176px] animate-drop-in overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white p-1.5 shadow-[var(--shadow-floating)]">
                <button
                  type="button"
                  onClick={() => onApplyFilterPreset({})}
                  className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                >
                  全部有效题目
                </button>
                <button
                  type="button"
                  onClick={() => onApplyFilterPreset({ is_active: "true" })}
                  className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                >
                  仅看已启用
                </button>
                <button
                  type="button"
                  onClick={() => onApplyFilterPreset({ difficulty: "5" })}
                  className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                >
                  困难题目
                </button>
                <div className="my-1 border-t border-[var(--color-border)]" />
                <button
                  type="button"
                  onClick={onApplySavedFilters}
                  className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                >
                  已保存筛选
                </button>
              </div>
            ) : null}
          </div>

          <button
            type="button"
            onClick={() => onSaveCurrentFilters(filters)}
            className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
          >
            <Star className="h-4 w-4 text-[var(--color-text-secondary)]" />
            保存筛选
          </button>
        </div>
      </div>

      {filters.knowledge_point_id ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-2 text-sm text-blue-800">
          <span className="font-semibold">覆盖率跳转筛选</span>
          <span>知识点 #{filters.knowledge_point_id}</span>
          <button
            type="button"
            className="rounded-lg px-2 py-1 text-xs font-semibold hover:bg-blue-100"
            onClick={() => onFilterChange("knowledge_point_id", "")}
          >
            清除
          </button>
        </div>
      ) : null}

      <div className="rounded-[1.35rem] border border-[var(--color-border)] bg-white/90 px-5 py-3 shadow-[0_8px_24px_rgba(40,60,90,0.05)]">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1.16fr_1fr_1fr_0.92fr_1fr_auto] xl:items-center">
          <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
            <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">科目</span>
            <div className="min-w-0 flex-1">
              <CustomSelect
                className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
                value={filters.subject_id}
                onChange={(v) => onFilterChange("subject_id", v)}
                options={[
                  { label: "全部科目", value: "" },
                  ...subjectOptions.map((subject) => ({
                    label: subject.name,
                    value: String(subject.id),
                  })),
                ]}
              />
            </div>
          </div>

          <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
            <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">题型</span>
            <div className="min-w-0 flex-1">
              <CustomSelect
                className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
                placeholder="全部题型"
                value={filters.question_type}
                onChange={(v) => onFilterChange("question_type", v)}
                options={QUESTION_TYPE_OPTIONS}
              />
            </div>
          </div>

          <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
            <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">状态</span>
            <div className="min-w-0 flex-1">
              <CustomSelect
                className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
                value={filters.is_active}
                onChange={(v) => onFilterChange("is_active", v)}
                options={activeOptions}
              />
            </div>
          </div>

          <label className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
            <span className="mr-3 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">年份</span>
            <input
              inputMode="numeric"
              className="h-9 min-w-0 flex-1 border-0 bg-transparent px-0 text-sm text-[var(--color-text-primary)] outline-none shadow-none placeholder:text-[var(--color-text-hint)] focus:border-0 focus:outline-none focus:ring-0"
              placeholder="选择年份"
              value={filters.year}
              maxLength={4}
              onChange={(event) =>
                onFilterChange("year", event.target.value.replace(/\D/g, "").slice(0, 4))
              }
            />
          </label>

          <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
            <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">难度</span>
            <div className="min-w-0 flex-1">
              <CustomSelect
                className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
                value={filters.difficulty}
                onChange={(v) => onFilterChange("difficulty", v)}
                options={difficultyOptions}
              />
            </div>
          </div>

          <div ref={moreFilterRef} className="relative justify-self-start xl:justify-self-end">
            <button
              type="button"
              onClick={() => onToggleMenu("isMoreFilterOpen")}
              aria-expanded={moreFilterOpen}
              aria-haspopup="dialog"
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
            >
              <SlidersHorizontal className="h-4 w-4 text-[var(--color-text-secondary)]" />
              更多条件
            </button>
            {moreFilterOpen ? (
              <div className="absolute right-0 top-full z-30 mt-2 w-[320px] animate-drop-in rounded-2xl border border-[var(--color-border)] bg-white p-4 shadow-[var(--shadow-floating)]">
                <p className="text-xs font-semibold text-[var(--color-text-secondary)]">导入批次 ID</p>
                <Input
                  className="mt-2 h-10 rounded-xl border-[var(--color-border)] bg-white px-3"
                  placeholder="输入批次 ID 片段"
                  value={importBatchInput}
                  onChange={(event) => onImportBatchChange(event.target.value)}
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
