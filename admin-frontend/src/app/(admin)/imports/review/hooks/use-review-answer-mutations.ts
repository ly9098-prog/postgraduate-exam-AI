"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ImportQuestionItem } from "@/lib/api/types";

export type ReviewAnswerApiRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

type ReviewAnswerFeedback = {
  onQuickAnswerSaved: (result: ImportQuestionItem) => void;
  onAnswerVerified: (result: ImportQuestionItem) => void;
  onError: (error: unknown, action: "save" | "verify") => void;
};

export function useReviewAnswerMutations(
  request: ReviewAnswerApiRequest,
  feedback: ReviewAnswerFeedback,
) {
  const queryClient = useQueryClient();
  const invalidateAnswerQueries = (id: number) => {
    queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
    queryClient.invalidateQueries({ queryKey: ["import-question-detail", id] });
  };

  const quickAnswer = useMutation({
    mutationFn: ({ id, answer }: { id: number; answer: string }) =>
      request<ImportQuestionItem>(`/imports/questions/${id}`, {
        method: "PUT",
        body: JSON.stringify({ answer }),
      }),
    onSuccess: (result) => {
      feedback.onQuickAnswerSaved(result);
      invalidateAnswerQueries(result.id);
    },
    onError: (error) => feedback.onError(error, "save"),
  });

  const verifyAnswer = useMutation({
    mutationFn: (id: number) =>
      request<ImportQuestionItem>(`/imports/questions/${id}`, {
        method: "PUT",
        body: JSON.stringify({ answer_status: "manual_verified" }),
      }),
    onSuccess: (result) => {
      feedback.onAnswerVerified(result);
      invalidateAnswerQueries(result.id);
    },
    onError: (error) => feedback.onError(error, "verify"),
  });

  return { quickAnswer, verifyAnswer };
}
