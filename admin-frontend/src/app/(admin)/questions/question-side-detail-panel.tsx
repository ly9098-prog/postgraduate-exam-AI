"use client";

import type { ReactNode, RefObject } from "react";
import { AlertCircle, FileQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";
import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { MultiBlankQuestionOptions, QuestionOptions } from "@/components/question-options";
import { QuestionAnalysis } from "@/components/questions/question-analysis";
import {
  normalizeQuestionOptions,
  resolveQuestionBlankOptionGroups,
  resolveQuestionOptions,
} from "@/lib/question-options";
import type { AdminQuestion } from "@/lib/api/types";
import { QuestionAnswerDisplay } from "./components/question-answer-display";
import { QuestionSecondaryInfo } from "./components/question-secondary-info";
import { DifficultyBadge } from "./components/question-difficulty-badge";
import { TypeBadge } from "./components/question-type-badge";
import { isMultiBlankChoice } from "./question-display-helpers";
import { textFromContent } from "./question-content-editing";

type QuestionSideDetailPanelProps = {
  questionId: number | null;
  question?: AdminQuestion | null;
  isError: boolean;
  scrollRef: RefObject<HTMLDivElement | null>;
  copyButton: ReactNode;
  canWrite: boolean;
  canDelete: boolean;
  onOpenFullDetail: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onRetry: () => void;
};

function EmptySelection() {
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center text-center animate-fade-in">
      <div className="flex h-16 w-16 items-center justify-center rounded-3xl border border-[var(--color-border)] bg-[var(--porcelain)] text-[var(--color-text-hint)] shadow-sm">
        <FileQuestion className="h-8 w-8" />
      </div>
      <p className="mt-5 text-2xl font-bold text-[var(--ink)]">选择一道题目</p>
      <p className="mt-2 max-w-xs text-sm leading-6 text-[var(--color-text-secondary)]">
        在左侧列表中选择题目，查看详情、编辑内容或进行版本对比。
      </p>
    </div>
  );
}

function LoadingDetail() {
  return (
    <div className="min-h-0 flex-1 space-y-3 animate-fade-in">
      <div className="h-16 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/75" />
      <div className="h-28 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/60" />
      <div className="h-44 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/50" />
    </div>
  );
}

export function QuestionSideDetailPanel({
  questionId,
  question,
  isError,
  scrollRef,
  copyButton,
  canWrite,
  canDelete,
  onOpenFullDetail,
  onEdit,
  onDelete,
  onRetry,
}: QuestionSideDetailPanelProps) {
  if (questionId === null) return <EmptySelection />;

  if (!question) {
    return isError ? (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 text-center animate-fade-in">
        <AlertCircle className="h-9 w-9 text-red-400" />
        <p className="text-sm font-semibold text-red-700">详情加载失败</p>
        <Button variant="secondary" size="sm" onClick={onRetry}>重新加载</Button>
      </div>
    ) : (
      <LoadingDetail />
    );
  }

  return (
    <div
      ref={scrollRef}
      key={question.id}
      className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1 animate-fade-in [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      <div className="sticky top-0 z-10 -mx-1 flex items-start justify-between gap-4 border-b border-slate-200 bg-white/96 px-1 pb-4 pt-0.5 backdrop-blur supports-[backdrop-filter]:bg-white/88">
        <div className="min-w-0">
          <p className="font-mono text-xs uppercase tracking-[0.28em] text-[var(--color-text-hint)]">
            Question
          </p>
          <h3 className="mt-2 text-2xl font-bold text-[var(--ink)]">
            题目 #{question.id}
          </h3>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <TypeBadge type={question.question_type} />
            <DifficultyBadge difficulty={question.difficulty} />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {copyButton}
          <Button
            variant="secondary"
            onClick={onOpenFullDetail}
            className="shrink-0 rounded-lg border-slate-200 bg-white shadow-none transition hover:bg-slate-50"
          >
            完整详情
          </Button>
        </div>
      </div>

      <section className="rounded-lg border border-slate-200 bg-slate-50/60 p-4">
        <p className="mb-3 flex items-center justify-between gap-3 font-semibold text-[var(--ink)]">
          <span>题干</span>
          <span className="font-mono text-[11px] font-normal text-[var(--color-text-hint)]">
            #{question.id}
          </span>
        </p>
        <div className="whitespace-pre-wrap text-base leading-8 text-[var(--ink)]">
          <QuestionContentRenderer
            content={question.content}
            fallbackText={textFromContent(question.content)}
            preserveCodeText
          />
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <p className="font-semibold text-[var(--ink)]">选项</p>
        <div className="mt-3">
          {isMultiBlankChoice(question.question_type) ? (
            <MultiBlankQuestionOptions groups={resolveQuestionBlankOptionGroups(question)} />
          ) : (
            <QuestionOptions
              options={normalizeQuestionOptions(resolveQuestionOptions(question))}
            />
          )}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <p className="font-semibold text-slate-950">答案</p>
        <div className="mt-2 inline-flex min-h-9 items-center rounded-md bg-slate-50 px-2.5 py-1.5 text-sm font-semibold leading-6 text-slate-800">
          <QuestionAnswerDisplay questionType={question.question_type} answer={question.answer} />
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <p className="font-semibold text-slate-950">解析</p>
        <div className="mt-3">
          <QuestionAnalysis value={question.analysis} compact />
        </div>
      </section>

      <QuestionSecondaryInfo question={question} />

      <div className="flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-4">
        {canWrite ? (
          <Button variant="secondary" onClick={onEdit}>
            编辑
          </Button>
        ) : null}
        {canDelete ? (
          <Button variant="danger" onClick={onDelete}>
            删除
          </Button>
        ) : null}
      </div>
    </div>
  );
}
