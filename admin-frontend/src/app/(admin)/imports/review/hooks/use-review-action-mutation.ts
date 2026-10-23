"use client";

import { useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  executeReviewActionRequest,
  type ReviewActionApiRequest,
  type ReviewActionState,
} from "../review-action-requests";
import {
  buildReviewActionFeedback,
  type ReviewActionFeedback,
} from "../review-action-feedback";

type ReviewActionMutationInput = {
  batchId: string;
  batchIdParam: string;
  selectedIds: Set<number>;
  rejectReason: string;
  request: ReviewActionApiRequest;
};

type ReviewActionMutationFeedback = {
  onSuccess: (feedback: ReviewActionFeedback) => void;
  onReset: () => void;
  onError: (error: unknown) => void;
};

export function useReviewActionMutation(
  input: ReviewActionMutationInput,
  feedback: ReviewActionMutationFeedback,
) {
  const queryClient = useQueryClient();
  const idempotencyKeysRef = useRef(new Map<string, string>());

  const batchIdempotencyKeyFor = (operation: string) => {
    const keys = idempotencyKeysRef.current;
    let key = keys.get(operation);
    if (!key) {
      key = crypto.randomUUID();
      keys.set(operation, key);
    }
    return key;
  };

  return useMutation({
    mutationFn: (action: ReviewActionState) => executeReviewActionRequest({
      action,
      batchId: input.batchId,
      batchIdParam: input.batchIdParam,
      selectedIds: Array.from(input.selectedIds),
      rejectReason: input.rejectReason,
      batchIdempotencyKeyFor,
      request: input.request,
    }),
    onSuccess: (result, action) => {
      idempotencyKeysRef.current.clear();
      const actionFeedback = buildReviewActionFeedback(result, action);
      feedback.onSuccess(actionFeedback);
      if (actionFeedback.resetSelection) feedback.onReset();
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["import-batches"] });
      if (action.action !== "reject" && action.action !== "batch-reject") {
        queryClient.invalidateQueries({ queryKey: ["questions"] });
      }
    },
    onError: feedback.onError,
  });
}
