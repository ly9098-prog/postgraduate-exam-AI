"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { BatchAnswerApplyResponse, BatchAnswerPreviewResponse } from "@/lib/api/types";

export type ReviewBatchAnswerApiRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

type ReviewBatchAnswerFeedback = {
  onPreviewStarted: () => void;
  onPreviewed: (result: BatchAnswerPreviewResponse) => void;
  onPreviewError: (error: unknown) => void;
  onApplyStarted: () => void;
  onApplied: (result: BatchAnswerApplyResponse) => void;
  onApplyError: (error: unknown) => void;
};

export function useReviewBatchAnswerMutations(
  request: ReviewBatchAnswerApiRequest,
  feedback: ReviewBatchAnswerFeedback,
) {
  const queryClient = useQueryClient();
  const preview = useMutation({
    mutationFn: ({ batchId, rawText }: { batchId: string; rawText: string }) =>
      request<BatchAnswerPreviewResponse>(`/imports/${batchId}/answers/preview`, {
        method: "POST",
        body: JSON.stringify({ raw_text: rawText.trim(), allow_partial_prefix: true }),
      }),
    onMutate: feedback.onPreviewStarted,
    onSuccess: feedback.onPreviewed,
    onError: feedback.onPreviewError,
  });
  const apply = useMutation({
    mutationFn: ({
      batchId,
      previewToken,
      operationId,
    }: {
      batchId: string;
      previewToken: string;
      operationId: string;
    }) =>
      request<BatchAnswerApplyResponse>(`/imports/${batchId}/answers/apply`, {
        method: "POST",
        body: JSON.stringify({ preview_token: previewToken, operation_id: operationId }),
      }),
    onMutate: feedback.onApplyStarted,
    onSuccess: (result) => {
      feedback.onApplied(result);
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
    },
    onError: feedback.onApplyError,
  });

  return { preview, apply };
}
