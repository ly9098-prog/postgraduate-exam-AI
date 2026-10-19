"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AdminQuestion, QuestionEditRequest } from "@/lib/api/types";
import { updateQuestion } from "../question-api";
import { buildQuestionEditPatch } from "../question-edit-patch";
import { questionKeys } from "../question-queries";

type QuestionUpdateInput = {
  questionId: number | null;
  baseline: AdminQuestion | undefined;
  form: QuestionEditRequest;
  stemText: string;
};

type UpdateFeedback = {
  onSaved: () => void;
  onError: (error: unknown) => void;
};

export function useQuestionUpdate(input: QuestionUpdateInput, feedback: UpdateFeedback) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      if (!input.questionId) throw new Error("未选中题目");
      if (!input.baseline) throw new Error("题目详情尚未加载完成");
      const patch = buildQuestionEditPatch(input.form, input.baseline, input.stemText);
      if (Object.keys(patch).length === 0) throw new Error("没有需要保存的修改");
      return updateQuestion(input.questionId, patch);
    },
    onSuccess: () => {
      feedback.onSaved();
      queryClient.invalidateQueries({ queryKey: questionKeys.all });
      queryClient.invalidateQueries({ queryKey: questionKeys.scope(input.questionId) });
    },
    onError: feedback.onError,
  });
}
