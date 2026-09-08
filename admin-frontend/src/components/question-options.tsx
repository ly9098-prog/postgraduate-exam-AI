"use client";

import { MathFormula } from "@/components/ui/math-formula";
import {
  haveIdenticalBlankOptionSets,
  type NormalizedBlankOptionGroup,
  type NormalizedQuestionOption,
} from "@/lib/question-options";

interface QuestionOptionsProps {
  options: NormalizedQuestionOption[];
  className?: string;
}

/**
 * Structured display of question options.
 *
 * Each option is rendered as a labeled row:
 *   A. {text}   — text content via MathFormula
 *   B. <img />  — image content
 *
 * Adapted for both narrow (drawer) and wide (desktop sidebar) layouts.
 */
export function QuestionOptions({ options, className = "" }: QuestionOptionsProps) {
  if (options.length === 0) {
    return (
      <p className="text-sm text-[var(--color-text-hint)]">—</p>
    );
  }

  return (
    <div className={`space-y-3 ${className}`}>
      {options.map((opt, i) => (
        <div key={opt.key || i} className="flex items-start gap-3">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--color-primary-light)] text-[10px] font-bold text-[var(--color-primary-dark)]">
            {opt.key}
          </span>
          <div className="min-w-0 flex-1 leading-7">
            {opt.text ? (
              <span className="whitespace-pre-wrap text-sm text-[var(--color-text-secondary)]">
                <MathFormula text={opt.text} />
              </span>
            ) : opt.imageUrl ? (
              <img
                src={opt.imageUrl}
                alt={`选项 ${opt.key}`}
                className="max-h-32 max-w-full rounded-lg border border-[var(--color-border)]/50 object-contain"
                onError={(e) => {
                  const target = e.currentTarget;
                  target.style.display = "none";
                  if (target.parentElement) {
                    target.parentElement.innerHTML =
                      `<span class="text-xs text-[var(--color-text-hint)]">（图片选项 ${opt.key} 加载失败）</span>`;
                  }
                }}
              />
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}


interface MultiBlankQuestionOptionsProps {
  groups: NormalizedBlankOptionGroup[];
  className?: string;
}

/**
 * Group-aware option preview for multi_blank_choice questions.
 * Identical groups are collapsed into one shared option list; otherwise each
 * blank keeps its own option block so differences remain visible.
 */
export function MultiBlankQuestionOptions({
  groups,
  className = "",
}: MultiBlankQuestionOptionsProps) {
  if (groups.length === 0) {
    return <p className="text-sm text-[var(--color-text-hint)]">—</p>;
  }

  if (haveIdenticalBlankOptionSets(groups)) {
    return (
      <div className={className}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-[var(--color-text-hint)]">
            {groups.map((group) => group.id).join("、")} 共用选项
          </span>
        </div>
        <QuestionOptions options={groups[0].options} />
      </div>
    );
  }

  return (
    <div className={`space-y-4 ${className}`}>
      {groups.map((group) => (
        <div
          key={group.id}
          className="rounded-lg border border-[var(--color-border)]/70 bg-[var(--color-bg-input)]/20 p-3"
        >
          <div className="mb-3 flex items-center gap-2">
            <span className="flex h-6 min-w-6 items-center justify-center rounded-md bg-[var(--color-primary-light)] px-1.5 text-[11px] font-bold text-[var(--color-primary-dark)]">
              {group.id}
            </span>
            <span className="text-xs font-medium text-[var(--color-text-hint)]">
              该空选项
            </span>
          </div>
          <QuestionOptions options={group.options} />
        </div>
      ))}
    </div>
  );
}
