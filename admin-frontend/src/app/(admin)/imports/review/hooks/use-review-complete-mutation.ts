"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AdminImportCompleteResponse } from "@/lib/api/types";

export type ReviewCompleteApiRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

type ReviewCompleteFeedback = {
  onCompleted: (result: AdminImportCompleteResponse) => void;
  onDetailSynced: (result: AdminImportCompleteResponse) => void;
  onError: (error: unknown) => void;
};

export function useReviewCompleteMutation(
  request: ReviewCompleteApiRequest,
  feedback: ReviewCompleteFeedback,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      try {
        return await request<AdminImportCompleteResponse>(`/imports/questions/${id}/complete`, {
          method: "POST",
        });
      } catch (error) {
        throw new Error(`题目 #${id} 补全失败：${error instanceof Error ? error.message : "未知错误"}`);
      }
    },
    onSuccess: (result) => {
      feedback.onCompleted(result);
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      queryClient.setQueryData(["import-question-detail", result.item.id], result.item);
      feedback.onDetailSynced(result);
    },
    onError: feedback.onError,
  });
}
