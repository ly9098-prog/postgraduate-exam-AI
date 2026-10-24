"use client";

import { BookOpen, Clock, Tag } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MathFormula } from "@/components/ui/math-formula";
import type { AdminQuestion } from "@/lib/api/types";
import { looksLikeProgrammingCode } from "@/lib/math-text";
import { CustomCheckbox } from "./components/question-custom-checkbox";
import { DifficultyBadge } from "./components/question-difficulty-badge";
import { TypeBadge } from "./components/question-type-badge";
import { textForStemEditor } from "./question-content-editing";
import { QuestionListFeedback } from "./question-list-feedback";
import { QuestionListPagination } from "./question-list-pagination";
import { QuestionListToolbar } from "./question-list-toolbar";
import type { QuestionListFilters } from "./question-list-state";

type QuestionListCardProps = {
  items: AdminQuestion[];
  total?: number;
  page: number;
  totalPages: number;
  pageSize: number;
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  hasActiveFilters: boolean;
  selectedQuestionId: number | null;
  selectedIds: Set<number>;
  allChecked: boolean;
  filters: QuestionListFilters;
  exportOpen: boolean;
  exportingFormat: "csv" | "docx" | null;
  exportMenuRef: React.RefObject<HTMLDivElement | null>;
  onToggleAll: () => void;
  onToggleOne: (id: number) => void;
  onSelectQuestion: (id: number) => void;
  onOpenDetail: (id: number) => void;
  onPrefetchDetail: (id: number) => void;
  onToggleExportMenu: () => void;
  onExport: (format: "csv" | "docx") => void;
  onResetFilters: () => void;
  onRetry: () => void;
  onPageSizeChange: (value: string) => void;
  onSetPage: (page: number) => void;
};

function ListLoading() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }, (_, index) => (
        <div
          key={index}
          className="h-28 animate-pulse rounded-[1.2rem] border border-[var(--color-border)] bg-white/60"
        />
      ))}
    </div>
  );
}

function QuestionListItem({
  question,
  selected,
  checked,
  onPrefetch,
  onToggle,
  onSelect,
  onOpenDetail,
}: {
  question: AdminQuestion;
  selected: boolean;
  checked: boolean;
  onPrefetch: () => void;
  onToggle: () => void;
  onSelect: () => void;
  onOpenDetail: () => void;
}) {
  const stemText = textForStemEditor(question.content) || `题目 #${question.id}`;

  return (
    <article
      onMouseEnter={onPrefetch}
      className={`group rounded-[1.2rem] border transition-all duration-200 ${
        selected
          ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/30 shadow-sm ring-2 ring-[var(--color-primary-light)]"
          : "border-[var(--color-border)] bg-white/85 shadow-sm hover:border-[var(--color-primary)]/45 hover:bg-white hover:shadow-[var(--shadow-card)]"
      }`}
    >
      <div className="flex items-start gap-3 px-4 py-3">
        <CustomCheckbox checked={checked} onChange={onToggle} className="mt-1" />

        <div className="min-w-0 flex-1">
          <button type="button" onClick={onSelect} className="w-full text-left">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center rounded-full bg-[var(--color-primary-light)] px-2.5 py-1 text-[11px] font-semibold text-[var(--color-primary-dark)]">
                #{String(question.id).padStart(4, "0")}
              </span>
              <TypeBadge type={question.question_type} />
              <DifficultyBadge difficulty={question.difficulty} />
              <span
                className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                  question.is_active
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-slate-200 bg-slate-50 text-slate-500"
                }`}
              >
                {question.is_active ? "已启用" : "已停用"}
              </span>
            </div>

            <div className="mt-2 line-clamp-2 text-sm font-medium leading-6 text-[var(--ink)]">
              {looksLikeProgrammingCode(stemText) ? stemText : <MathFormula text={stemText} />}
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-text-hint)]">
              {question.subject_name || question.subject_code ? (
                <span className="inline-flex items-center gap-1">
                  <BookOpen className="h-3 w-3" />
                  {question.subject_name || question.subject_code}
                </span>
              ) : null}
              {question.year ? (
                <span className="inline-flex items-center gap-1">
                  <Tag className="h-3 w-3" />
                  {question.year} 年
                </span>
              ) : null}
              {question.updated_at ? (
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  更新于 {question.updated_at.slice(0, 16).replace("T", " ")}
                </span>
              ) : null}
            </div>
          </button>
        </div>

        <Button
          variant="ghost"
          onClick={onOpenDetail}
          className="mt-1 h-9 rounded-full px-3 text-xs text-[var(--color-text-secondary)] transition-all duration-200 group-hover:bg-[var(--porcelain)] group-hover:text-[var(--ink)]"
        >
          详情
        </Button>
      </div>
    </article>
  );
}

export function QuestionListCard({
  items,
  total,
  page,
  totalPages,
  pageSize,
  isLoading,
  isFetching,
  isError,
  hasActiveFilters,
  selectedQuestionId,
  selectedIds,
  allChecked,
  filters,
  exportOpen,
  exportingFormat,
  exportMenuRef,
  onToggleAll,
  onToggleOne,
  onSelectQuestion,
  onOpenDetail,
  onPrefetchDetail,
  onToggleExportMenu,
  onExport,
  onResetFilters,
  onRetry,
  onPageSizeChange,
  onSetPage,
}: QuestionListCardProps) {
  return (
    <section className="min-w-0 space-y-3">
      <QuestionListToolbar
        itemCount={items.length}
        total={total}
        isFetching={isFetching}
        isLoading={isLoading}
        hasActiveFilters={hasActiveFilters}
        selectedCount={selectedIds.size}
        allChecked={allChecked}
        exportOpen={exportOpen}
        exportingFormat={exportingFormat}
        exportMenuRef={exportMenuRef}
        onToggleAll={onToggleAll}
        onToggleExportMenu={onToggleExportMenu}
        onExport={onExport}
      />

      <div className={`space-y-2.5 transition-opacity duration-200 ${isFetching && !isLoading ? "opacity-70" : "opacity-100"}`}>
        {isLoading ? <ListLoading /> : null}

        <div
          key={`${filters.subject_id}-${filters.question_type}-${filters.is_active}-${filters.year}-${filters.difficulty}-${filters.keyword}-${filters.import_batch_id}-${filters.knowledge_point_id}-${page}-${pageSize}`}
          className="stagger-enter space-y-2.5"
        >
          {items.map((question) => (
            <QuestionListItem
              key={question.id}
              question={question}
              selected={selectedQuestionId === question.id}
              checked={selectedIds.has(question.id)}
              onPrefetch={() => onPrefetchDetail(question.id)}
              onToggle={() => onToggleOne(question.id)}
              onSelect={() => onSelectQuestion(question.id)}
              onOpenDetail={() => onOpenDetail(question.id)}
            />
          ))}
        </div>

        <QuestionListFeedback
          emptyVisible={!isLoading && !isError && items.length === 0}
          isError={isError}
          hasActiveFilters={hasActiveFilters}
          onResetFilters={onResetFilters}
          onRetry={onRetry}
        />
      </div>

      <QuestionListPagination
        visible={totalPages > 1}
        total={total ?? 0}
        page={page}
        totalPages={totalPages}
        pageSize={pageSize}
        isFetching={isFetching}
        onPageSizeChange={onPageSizeChange}
        onSetPage={onSetPage}
      />
    </section>
  );
}
