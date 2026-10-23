"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ImportQuestionItem } from "@/lib/api/types";
import {
  executeReviewSaveRequest,
  type ReviewSaveApiRequest,
  type ReviewSaveRequestInput,
} from "../review-save-request";

type ReviewUpdateInput = Omit<ReviewSaveRequestInput, "request"> & {
  request: ReviewSaveApiRequest;
};

type ReviewUpdateFeedback = {
  onSaved: (result: ImportQuestionItem) => void;
  onAfterInvalidation: () => void;
  onError: (error: unknown) => void;
};

export function useReviewUpdateMutation(
  input: ReviewUpdateInput,
  feedback: ReviewUpdateFeedback,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => executeReviewSaveRequest(input),
    onSuccess: (result) => {
      queryClient.setQueryData(
        ["import-question-detail", input.previewId],
        result,
      );
      feedback.onSaved(result);
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["import-question-detail", input.previewId] });
      feedback.onAfterInvalidation();
    },
    onError: feedback.onError,
  });
}
