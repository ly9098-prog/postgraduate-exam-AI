"use client";

import { useState } from "react";
import { ChevronDown, CheckCircle2, AlertTriangle, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { serializeBlankAnswer } from "./multi-blank-choice-utils";
import type { BlankOptionGroup, BlankAnswerMap } from "./multi-blank-choice-utils";

export interface MultiBlankAnswerSummaryProps {
  groups: BlankOptionGroup[];
  answerMap: BlankAnswerMap;
}

type StatusTone = "success" | "warning" | "error";

function getStatus(
  groups: BlankOptionGroup[],
  answerMap: BlankAnswerMap,
): { label: string; tone: StatusTone; icon: React.ReactNode } {
  const totalSlots = groups.length;
  const answeredSlots = groups.filter((g) => answerMap[g.id]).length;
  const missingSlots = totalSlots - answeredSlots;

  const groupIds = new Set(groups.map((g) => g.id));
  const extraSlots = Object.keys(answerMap).filter((k) => !groupIds.has(k));
  if (extraSlots.length > 0) {
    return {
      label: "含未知空位",
      tone: "error",
      icon: <AlertTriangle className="h-3 w-3" />,
    };
  }

  for (const group of groups) {
    const selected = answerMap[group.id];
    if (selected) {
      const validKeys = new Set(group.options.map((o) => o.key));
      if (!validKeys.has(selected)) {
        return {
          label: "非法答案",
          tone: "error",
          icon: <AlertTriangle className="h-3 w-3" />,
        };
      }
    }
  }

  if (missingSlots === 0) {
    return {
      label: "答案完整",
      tone: "success",
      icon: <CheckCircle2 className="h-3 w-3" />,
    };
  }
  if (missingSlots > 0) {
    return {
      label: `缺少 ${missingSlots}/${totalSlots}`,
      tone: "warning",
      icon: <HelpCircle className="h-3 w-3" />,
    };
  }
  return {
    label: "未填",
    tone: "warning",
    icon: <HelpCircle className="h-3 w-3" />,
  };
}

const toneBg: Record<StatusTone, string> = {
  success: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/60",
  warning: "bg-amber-50 text-amber-700 ring-1 ring-amber-200/60",
  error: "bg-red-50 text-red-700 ring-1 ring-red-200/60",
};

export function MultiBlankAnswerSummary({
  groups,
  answerMap,
}: MultiBlankAnswerSummaryProps) {
  const [expanded, setExpanded] = useState(false);
  const status = getStatus(groups, answerMap);
  const canonical = serializeBlankAnswer(answerMap, groups.map((g) => g.id));

  return (
    <div className="rounded-xl border border-[var(--color-border)]/40 bg-white/60 p-4">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between border-b border-[var(--color-border)]/20 pb-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">
            答案
          </span>
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-medium",
            toneBg[status.tone],
          )}
        >
          {status.icon}
          {status.label}
        </span>
      </div>

      {/* Answer key table */}
      <div className="divide-y divide-[var(--color-border)]/20">
        {groups.map((group) => {
          const answer = answerMap[group.id];
          const hasAnswer = !!answer;
          const validAnswer =
            hasAnswer && group.options.some((o) => o.key === answer);
          const optionText = validAnswer
            ? group.options.find((o) => o.key === answer)!.text
            : null;

          let rowTone: "success" | "warning" | "error" | "empty" = "empty";
          if (!hasAnswer) rowTone = "warning";
          else if (validAnswer) rowTone = "success";
          else rowTone = "error";

          return (
            <div
              key={group.id}
              className="flex items-center gap-3 py-2 first:pt-0 last:pb-0"
            >
              {/* Group ID badge */}
              <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-[var(--color-primary)]/8 text-[10px] font-semibold text-[var(--color-primary-dark)]">
                {group.id}
              </span>

              {/* Answer key cell */}
              <div className="flex min-w-0 flex-1 items-center gap-2">
                {!hasAnswer ? (
                  <span className="inline-flex items-center rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-500">
                    -
                  </span>
                ) : (
                  <span
                    className={cn(
                      "inline-flex h-5 min-w-[20px] items-center justify-center rounded px-1.5 text-[11px] font-bold",
                      rowTone === "success" &&
                        "bg-emerald-50 text-emerald-600",
                      rowTone === "error" && "bg-red-50 text-red-600",
                    )}
                  >
                    {answer}
                  </span>
                )}
                {optionText ? (
                  <span className="truncate text-xs text-[var(--color-text-secondary)]">
                    {optionText}
                  </span>
                ) : null}
                {!hasAnswer ? null : !validAnswer ? (
                  <span className="text-[9px] text-red-400">非法</span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      {/* Collapsible canonical value */}
      {canonical ? (
        <div className="mt-2.5 border-t border-[var(--color-border)]/30 pt-2">
          <button
            type="button"
            className="flex items-center gap-1 text-[9px] text-[var(--color-text-hint)] transition hover:text-[var(--color-text-primary)]"
            onClick={() => setExpanded(!expanded)}
          >
            <ChevronDown
              className={cn(
                "h-3 w-3 transition-transform duration-150",
                expanded && "rotate-180",
              )}
            />
            原始值
          </button>
          {expanded ? (
            <p className="mt-1.5 rounded-lg bg-[var(--color-bg-input)]/50 px-2 py-1 font-mono text-[10px] leading-relaxed text-[var(--color-text-hint)]">
              {canonical}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
