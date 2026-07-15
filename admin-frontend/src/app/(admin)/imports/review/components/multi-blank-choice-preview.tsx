"use client";

import { MathFormula } from "@/components/ui/math-formula";
import type { BlankOptionGroup, BlankAnswerMap, BlankOption } from "./multi-blank-choice-utils";

export interface MultiBlankChoicePreviewProps {
  groups: BlankOptionGroup[];
  answerMap: BlankAnswerMap;
  usesSharedOptions: boolean;
  sharedOptions: BlankOption[];
  stem: string;
}

/**
 * Highlight circled digits (①-⑳) in stem text with a pill badge.
 */
function StemWithBlankMarkers({ text }: { text: string }) {
  if (!text) return null;

  const parts = text.split(/([①-⑳])/g);
  if (parts.length <= 1) {
    return <MathFormula text={text} />;
  }

  return (
    <span className="leading-8">
      {parts.map((part, i) => {
        if (/^[①-⑳]$/.test(part)) {
          return (
            <span
              key={i}
              className="mx-0.5 inline-flex h-5 w-5 items-center justify-center rounded-md bg-[var(--color-primary)]/10 text-[11px] font-bold text-[var(--color-primary-dark)] shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
            >
              {part}
            </span>
          );
        }
        return <MathFormula key={i} text={part} />;
      })}
    </span>
  );
}

/**
 * Per-slot answer card with left accent border and status color.
 */
function SlotCard({
  group,
  answer,
  validAnswer,
  answerOption,
}: {
  group: BlankOptionGroup;
  answer: string | undefined;
  validAnswer: boolean;
  answerOption: BlankOption | undefined;
}) {
  const hasAnswer = !!answer;
  let accentColor: string;
  let borderColor: string;
  let bgHint: string;

  if (!hasAnswer) {
    accentColor = "bg-amber-400/60";
    borderColor = "border-amber-200/70";
    bgHint = "bg-amber-50/40";
  } else if (validAnswer) {
    accentColor = "bg-emerald-400/60";
    borderColor = "border-emerald-200/70";
    bgHint = "bg-emerald-50/40";
  } else {
    accentColor = "bg-red-400/60";
    borderColor = "border-red-200/70";
    bgHint = "bg-red-50/40";
  }

  return (
    <div
      className={`relative overflow-hidden rounded-xl border ${borderColor} ${bgHint} p-3 pl-4 transition-shadow hover:shadow-[0_2px_8px_rgba(0,0,0,0.04)]`}
    >
      {/* Left accent strip */}
      <span
        className={`absolute left-0 top-0 h-full w-[3px] rounded-r-sm ${accentColor}`}
      />

      {/* Header: group ID + answer status */}
      <div className="mb-1.5 flex items-center gap-2">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-[var(--color-primary)]/8 text-[10px] font-semibold text-[var(--color-primary-dark)]">
          {group.id}
        </span>
        <span className="text-[10px] font-medium text-[var(--color-text-hint)] tracking-wide">
          空位
        </span>
      </div>

      {/* Answer region */}
      {hasAnswer && !validAnswer ? (
        <div className="mt-1 flex items-center gap-1.5">
          <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded bg-red-100 px-1 text-[11px] font-bold text-red-600">
            {answer}
          </span>
          <span className="text-[11px] text-red-500">— 非法答案</span>
        </div>
      ) : answerOption ? (
        <div className="mt-1 space-y-0.5">
          <div className="flex items-center gap-1.5">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-[var(--color-success)]/10 text-[11px] font-bold text-[var(--color-success)]">
              {answer}
            </span>
            <span className="text-sm text-[var(--color-text-secondary)]">
              <MathFormula text={answerOption.text} />
            </span>
          </div>
        </div>
      ) : (
        <div className="mt-1 flex items-center gap-1.5">
          <span className="inline-flex h-5 items-center justify-center rounded bg-amber-100 px-1.5 text-[10px] font-medium text-amber-600">
            待确认
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * Preview component for multi_blank_choice questions.
 *
 * "Exam Answer Key" aesthetic:
 *  - Shared options feel like a quick-reference lookup table
 *  - Per-slot cards use left accent strips for at-a-glance status
 *  - Colors are confident and semantic
 */
export function MultiBlankChoicePreview({
  groups,
  answerMap,
  usesSharedOptions,
  sharedOptions,
  stem,
}: MultiBlankChoicePreviewProps) {
  if (groups.length === 0) {
    return <p className="text-sm text-[var(--color-text-hint)]">（无分组选项数据）</p>;
  }

  return (
    <div className="space-y-4">
      {/* Shared options — "选项速查" reference key */}
      {usesSharedOptions && sharedOptions.length > 0 ? (
        <div className="relative overflow-hidden rounded-xl border border-[var(--color-border)]/50 bg-white/70 p-4">
          {/* Subtle header bar */}
          <div className="mb-3 flex items-center gap-2 border-b border-[var(--color-border)]/30 pb-2">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-[var(--color-primary)]/8 text-[10px] font-semibold text-[var(--color-primary-dark)]">
              ☰
            </span>
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">
              选项 · {groups.length} 个空共用
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2">
            {sharedOptions.map((opt) => (
              <div key={opt.key} className="flex items-center gap-2.5">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-primary)]/8 text-[11px] font-bold text-[var(--color-primary-dark)] shadow-[inset_0_1px_0_rgba(255,255,255,0.6)]">
                  {opt.key}
                </span>
                <span className="text-sm leading-snug text-[var(--color-text-secondary)]">
                  <MathFormula text={opt.text} />
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Per-slot answer cards */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {groups.map((group) => {
          const answer = answerMap[group.id];
          const hasAnswer = !!answer;
          const validAnswer =
            hasAnswer && group.options.some((o) => o.key === answer);
          const answerOption = group.options.find((o) => o.key === answer);

          return (
            <SlotCard
              key={group.id}
              group={group}
              answer={answer}
              validAnswer={validAnswer}
              answerOption={answerOption}
            />
          );
        })}
      </div>

      {/* Stem with highlighted blanks */}
      {stem ? (
        <div className="rounded-xl border border-[var(--color-border)]/40 bg-white/50 p-4">
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">
            题干
          </div>
          <div className="text-[15px] leading-8 text-[var(--ink)]">
            <StemWithBlankMarkers text={stem} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
