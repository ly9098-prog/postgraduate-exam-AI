"use client";

import { useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { deleteQuestion, deleteQuestionBatch } from "../question-api";
import { questionKeys } from "../question-queries";

export type QuestionDeleteIntent = { action: "batch-delete" } | { action: "delete"; id: number };
type DeleteResult = Awaited<ReturnType<typeof deleteQuestion | typeof deleteQuestionBatch>>;
type DeleteFeedback = {
  onDeleted: (result: DeleteResult, intent: QuestionDeleteIntent) => void;
  onError: (error: unknown) => void;
};

export function useQuestionDelete(selectedIds: Set<number>, feedback: DeleteFeedback) {
  const queryClient = useQueryClient();
  const keysRef = useRef(new Map<string, string>());
  const keyForChunk = (ids: number[]) => {
    const operation = ids.join(",");
    const keys = keysRef.current;
    let key = keys.get(operation);
    if (!key) {
      key = crypto.randomUUID();
      keys.set(operation, key);
    }
    return key;
  };
  return useMutation({
    mutationFn: async (intent: QuestionDeleteIntent) => {
      if (intent.action === "batch-delete") {
        return deleteQuestionBatch(Array.from(selectedIds), keyForChunk);
      }
      return deleteQuestion(intent.id);
    },
    onSuccess: (result, intent) => {
      keysRef.current.clear();
      feedback.onDeleted(result, intent);
      queryClient.invalidateQueries({ queryKey: questionKeys.all });
    },
    onError: feedback.onError,
  });
}
