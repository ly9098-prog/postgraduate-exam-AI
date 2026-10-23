"use client";

import type { Dispatch, SetStateAction } from "react";
import { Input } from "@/components/ui/input";
import type { QuestionEditRequest } from "@/lib/api/types";
import { isMultiBlankChoice } from "./question-display-helpers";
import {
  isMultiBlankMultipleChoice,
  isMultiChoice,
  normalizedChoiceAnswerKeys,
} from "./question-display-helpers";
import {
  normalizeBlankOptionGroups,
  parseMultiBlankChoiceAnswer,
  resolveBlankOptionGroupsValue,
  updateMultiBlankChoiceAnswer,
} from "@/lib/question-options";
import { optionsToKeyValueList } from "./question-option-editing";

type AnswerEditorProps = {
  editForm: QuestionEditRequest;
  setEditForm: Dispatch<SetStateAction<QuestionEditRequest>>;
};

function setAnswer(
  setEditForm: AnswerEditorProps["setEditForm"],
  answer: string,
) {
  setEditForm((current) => ({ ...current, answer }));
}

export function QuestionAnswerEditor({ editForm, setEditForm }: AnswerEditorProps) {
  const questionType = editForm.question_type ?? "";
  if (isMultiBlankChoice(questionType)) {
    const groups = normalizeBlankOptionGroups(resolveBlankOptionGroupsValue(editForm.content));
    const multiSelect = isMultiBlankMultipleChoice(questionType);
    const parsedAnswer = parseMultiBlankChoiceAnswer(editForm.answer);
    const parsedAnswerMap = new Map(parsedAnswer.map((item) => [item.blankId, item.optionKey]));
    const blankIds = groups.length > 0
      ? groups.map((group) => group.id)
      : parsedAnswer.map((item) => item.blankId);

    return (
      <section className="border-b border-slate-200 py-5">
        <div className="mb-4">
          <p className="text-sm font-semibold text-slate-950">答案</p>
          <p className="mt-1 text-[11px] text-slate-400">
            {multiSelect
              ? "点击选项可快速多选或取消；也可手动填写多个字母（如 A,C）"
              : "点击选项可快速填入单选答案；再次点击已选项可清空"}
          </p>
        </div>
        {blankIds.length > 0 ? (
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
            {blankIds.map((blankId, index) => {
              const group = groups.find((item) => item.id === blankId);
              const currentLetters = (parsedAnswerMap.get(blankId) ?? "")
                .split(",")
                .map((letter) => letter.trim().toUpperCase())
                .filter(Boolean);
              return (
                <div
                  key={`${blankId}-${index}`}
                  className="flex items-center gap-4 border-b border-slate-100 px-4 py-3 last:border-b-0"
                >
                  <span className="w-8 shrink-0 text-sm font-medium text-slate-900">{blankId}</span>
                  <div className="min-w-0 flex-1 space-y-2">
                    {group && group.options.length > 0 ? (
                      <div className="flex flex-wrap items-center gap-1.5">
                        {group.options.map((opt) => {
                          const normalizedKey = opt.key.trim().toUpperCase();
                          const selected = currentLetters.includes(normalizedKey);
                          return (
                            <button
                              key={opt.key}
                              type="button"
                              className={`inline-flex h-8 min-w-9 items-center justify-center rounded-md border px-3 text-sm font-medium transition ${
                                selected
                                  ? "border-slate-900 bg-slate-900 text-white"
                                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-900"
                              }`}
                              title={opt.text ? `${opt.key}. ${opt.text}` : `选择 ${opt.key}`}
                              aria-pressed={selected}
                              onClick={() =>
                                setEditForm((current) => ({
                                  ...current,
                                  answer: updateMultiBlankChoiceAnswer(
                                    current.answer,
                                    blankIds,
                                    blankId,
                                    !multiSelect && selected ? "" : normalizedKey,
                                    multiSelect,
                                  ),
                                }))
                              }
                            >
                              {opt.key}
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                    <Input
                      value={parsedAnswerMap.get(blankId) ?? ""}
                      aria-label={`${blankId} 答案`}
                      placeholder={multiSelect ? "如 A,C" : "如 A"}
                      className="h-8 max-w-32 border-slate-200 bg-slate-50/60 text-center text-xs shadow-none focus:bg-white"
                      onChange={(event) =>
                        setEditForm((current) => ({
                          ...current,
                          answer: updateMultiBlankChoiceAnswer(
                            current.answer,
                            blankIds,
                            blankId,
                            event.target.value,
                          ),
                        }))
                      }
                    />
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <Input
            value={editForm.answer ?? ""}
            className="border-slate-200 bg-slate-50/60 shadow-none focus:bg-white"
            onChange={(event) => setAnswer(setEditForm, event.target.value)}
          />
        )}
      </section>
    );
  }

  const options = optionsToKeyValueList(editForm.options);
  if (options.length === 0) {
    return (
      <section className="border-b border-slate-200 py-5">
        <p className="mb-3 text-sm font-semibold text-slate-950">答案</p>
        <div>
          <Input
            value={editForm.answer ?? ""}
            className="border-slate-200 bg-slate-50/60 shadow-none focus:bg-white"
            onChange={(event) => setAnswer(setEditForm, event.target.value)}
          />
        </div>
      </section>
    );
  }

  return (
    <section className="border-b border-slate-200 py-5">
      <div className="mb-4">
        <p className="text-sm font-semibold text-slate-950">答案</p>
        <p className="mt-1 text-[11px] text-slate-400">快速选择正确选项，也可直接编辑答案内容</p>
      </div>
      <p className="mb-2 text-[11px] font-medium text-slate-500">快速选择</p>
      {editForm.question_type && isMultiChoice(editForm.question_type) ? (
        <p className="mb-2 text-[10px] text-[var(--color-text-hint)]">
          多选：单击切换各选项，以逗号分隔
        </p>
      ) : null}
      <div className="mb-3 flex flex-wrap gap-2">
        {options.map((opt) => {
          const normalizedKey = opt.key.trim().toUpperCase();
          const selected = isMultiChoice(questionType)
            ? normalizedChoiceAnswerKeys(editForm.answer).includes(normalizedKey)
            : String(editForm.answer ?? "").trim().toUpperCase() === normalizedKey;
          return (
            <button
              key={opt.key}
              type="button"
              className={`inline-flex h-8 min-w-9 items-center justify-center rounded-md border px-3 text-sm font-medium transition ${
                selected
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-900"
              }`}
              onClick={() => {
                if (isMultiChoice(questionType)) {
                  const keys = normalizedChoiceAnswerKeys(editForm.answer);
                  const next = keys.includes(normalizedKey)
                    ? keys.filter((key: string) => key !== normalizedKey)
                    : [...keys, normalizedKey];
                  setEditForm((current) => ({ ...current, answer: next.join(",") }));
                  return;
                }
                setEditForm((current) => ({
                  ...current,
                  answer: selected ? "" : normalizedKey,
                }));
              }}
            >
              {opt.key}
            </button>
          );
        })}
      </div>
      <div className="mt-4 space-y-1.5">
        <p className="text-[11px] font-medium text-slate-500">答案内容</p>
        <Input
          value={editForm.answer ?? ""}
          className="border-slate-200 bg-slate-50/60 shadow-none focus:bg-white"
          onChange={(event) => setAnswer(setEditForm, event.target.value)}
        />
      </div>
    </section>
  );
}
