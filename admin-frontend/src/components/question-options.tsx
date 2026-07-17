"use client";

import { MathFormula } from "@/components/ui/math-formula";
import type { NormalizedQuestionOption } from "@/lib/question-options";

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
