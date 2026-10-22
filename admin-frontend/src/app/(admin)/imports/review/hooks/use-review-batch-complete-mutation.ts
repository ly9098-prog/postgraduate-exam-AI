"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { BatchCompleteResponse, ImportQuestionItem } from "@/lib/api/types";
import type { BatchCompleteStrategy } from "../review-batch-complete-draft";

export type ReviewBatchCompleteApiRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

export type ReviewBatchCompleteFeedback = {
  onStarted: () => void;
  onCompleted: (result: BatchCompleteResponse) => void;
  onDetailSynced: (item: ImportQuestionItem) => void;
  onError: (error: unknown) => void;
  onFinished: () => void;
};

export type ReviewBatchCompleteArgs = {
  importIds: number[];
  fields: string[];
  strategy: BatchCompleteStrategy;
  openPreviewId: number | null;
};

export function useReviewBatchCompleteMutation(
  request: ReviewBatchCompleteApiRequest,
  feedback: ReviewBatchCompleteFeedback,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (args: ReviewBatchCompleteArgs) => {
      feedback.onStarted();
      const result = await request<BatchCompleteResponse>(
        "/imports/questions/batch-complete",
        {
          method: "POST",
          body: JSON.stringify({
            import_ids: args.importIds,
            fields: args.fields,
            strategy: args.strategy,
          }),
        },
      );
      if (args.openPreviewId !== null && args.importIds.includes(args.openPreviewId)) {
        try {
          const refreshed = await request<ImportQuestionItem>(
            `/imports/questions/${args.openPreviewId}`,
          );
          queryClient.setQueryData(
            ["import-question-detail", args.openPreviewId],
            refreshed,
          );
          feedback.onDetailSynced(refreshed);
        } catch {
          // The completion itself has succeeded; a transient detail refresh must
          // not turn the whole batch operation into a failure message.
        }
      }
      return result;
    },
    onSuccess: (result) => {
      feedback.onCompleted(result);
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["import-question-detail"] });
    },
    onError: feedback.onError,
    onSettled: () => {
      feedback.onFinished();
    },
  });
}
