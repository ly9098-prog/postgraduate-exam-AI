"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { BatchAnswerImageApplyResponse, BatchAnswerImagePreviewResponse } from "@/lib/api/types";

export type ReviewImageAnswerApiRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

type ReviewImageAnswerFeedback = {
  onPreviewStarted: () => void;
  onPreviewed: (result: BatchAnswerImagePreviewResponse) => void;
  onPreviewError: (error: unknown) => void;
  onApplyStarted: () => void;
  onApplied: (result: BatchAnswerImageApplyResponse) => void;
  onApplyError: (error: unknown) => void;
};

type ImageAnswerMode = "answer_only" | "answer_analysis";

function buildImagePreviewFormData(files: File[], mode: ImageAnswerMode) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  formData.append("mode", mode);
  return formData;
}

export function useReviewImageAnswerMutations(
  request: ReviewImageAnswerApiRequest,
  feedback: ReviewImageAnswerFeedback,
) {
  const queryClient = useQueryClient();
  const preview = useMutation({
    mutationFn: ({ batchId, files, mode }: {
      batchId: string;
      files: File[];
      mode: ImageAnswerMode;
    }) =>
      request<BatchAnswerImagePreviewResponse>(`/imports/${batchId}/answers/image/preview`, {
        method: "POST",
        body: buildImagePreviewFormData(files, mode),
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
      request<BatchAnswerImageApplyResponse>(`/imports/${batchId}/answers/image/apply`, {
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
