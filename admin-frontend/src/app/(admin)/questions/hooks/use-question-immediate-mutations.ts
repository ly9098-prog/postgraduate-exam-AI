"use client";

import { useCallback, useRef, type Dispatch, type SetStateAction } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import type { AdminQuestion, AdminQuestionDetail, QuestionEditRequest } from "@/lib/api/types";
import { updateQuestion } from "../question-api";
import { contentRecord } from "../question-content-editing";
import { savedQuestionEditDraft } from "../question-edit-draft";
import { buildQuestionEditPatch } from "../question-edit-patch";
import { questionKeys } from "../question-queries";

type ImmediateInput = {
  questionId: number | null;
  question: AdminQuestion | null | undefined;
  dirty: boolean;
  form: QuestionEditRequest;
  stemText: string;
  unresolvedTableCount: number;
  emptyCodeCount: number;
};
type DraftFeedback = {
  setForm: Dispatch<SetStateAction<QuestionEditRequest>>;
  setStemText: (value: string) => void;
  setMessage: (value: string) => void;
};

function mergeDetail(cache: QueryClient, id: number | null, question: AdminQuestion) {
  if (id === null) return;
  cache.setQueryData<AdminQuestionDetail>(questionKeys.detail(id), (current) =>
    current
      ? { ...current, ...question, import_record: current.import_record ?? null }
      : (question as AdminQuestionDetail),
  );
}

function preparationError(input: ImmediateInput): string | null {
  if (input.questionId === null) return "未选中题目，无法保存当前修改。";
  if (input.unresolvedTableCount > 0) return "请先完成结构化表格核验，再继续图片或选项操作。";
  if (input.emptyCodeCount > 0) return "请先填写或删除空代码块，再继续图片或选项操作。";
  return null;
}

async function saveDraft(input: ImmediateInput, cache: QueryClient, feedback: DraftFeedback) {
  try {
    if (!input.question) {
      feedback.setMessage("题目详情尚未加载完成，无法保存当前修改。");
      return false;
    }
    const patch = buildQuestionEditPatch(input.form, input.question, input.stemText);
    if (Object.keys(patch).length === 0) return true;
    const question = await updateQuestion(input.questionId!, patch);
    mergeDetail(cache, input.questionId, question);
    const draft = savedQuestionEditDraft(question);
    feedback.setForm(draft.form);
    feedback.setStemText(draft.stemText);
    cache.invalidateQueries({ queryKey: questionKeys.all });
    cache.invalidateQueries({ queryKey: questionKeys.scope(input.questionId) });
    feedback.setMessage("已先保存当前修改，将继续执行该操作。");
    return true;
  } catch (error) {
    feedback.setMessage(error instanceof Error
      ? `当前修改保存失败：${error.message}`
      : "当前修改保存失败，请稍后重试。");
    return false;
  }
}

export function useQuestionImmediateMutations(input: ImmediateInput, feedback: DraftFeedback) {
  const cache = useQueryClient();
  const pending = useRef<Promise<boolean> | null>(null);
  const { questionId, question, dirty, form, stemText, unresolvedTableCount, emptyCodeCount } = input;
  const { setForm, setStemText, setMessage } = feedback;
  const handleQuestionMutated = useCallback((question: AdminQuestion) => {
    // Keep unsaved scalar edits while adopting immediate image/option writes.
    setForm((current) => ({
      ...current,
      content: contentRecord(question.content),
      options: question.options ?? undefined,
    }));
    mergeDetail(cache, questionId, question);
    cache.invalidateQueries({ queryKey: questionKeys.scope(questionId) });
    cache.invalidateQueries({ queryKey: questionKeys.all });
  }, [cache, questionId, setForm]);

  const prepareImmediateQuestionMutation = useCallback(async (): Promise<boolean> => {
    if (!dirty) return true;
    const state = { questionId, question, dirty, form, stemText, unresolvedTableCount, emptyCodeCount };
    const error = preparationError(state);
    if (error) {
      setMessage(error);
      return false;
    }
    if (pending.current) return pending.current;
    const task = saveDraft(state, cache, { setForm, setStemText, setMessage });
    pending.current = task;
    try {
      return await task;
    } finally {
      pending.current = null;
    }
  }, [
    cache, dirty, emptyCodeCount, form, question, questionId,
    setForm, setMessage, setStemText, stemText, unresolvedTableCount,
  ]);
  return { handleQuestionMutated, prepareImmediateQuestionMutation };
}
