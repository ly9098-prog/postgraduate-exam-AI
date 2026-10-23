"use client";

import { useCallback, useState } from "react";
import { buildQuestionDeleteFeedback } from "../question-delete-feedback";
import { useQuestionDelete, type QuestionDeleteIntent } from "./use-question-delete";

type DeleteDialogActions = {
  clearSelection: () => void;
  setSelectedQuestionId: (id: number | null) => void;
  closeDetailDrawer: () => void;
  onMessage: (message: string) => void;
};

export function useQuestionDeleteDialog(
  selectedIds: Set<number>,
  selectedQuestionId: number | null,
  actions: DeleteDialogActions,
) {
  const [confirmState, setConfirmState] = useState<QuestionDeleteIntent | null>(null);
  const deleteMutation = useQuestionDelete(selectedIds, {
    onDeleted: (result, variables) => {
      const feedback = buildQuestionDeleteFeedback({
        result,
        intent: variables,
        selectedQuestionId,
      });
      actions.onMessage(feedback.message);
      if (feedback.closeDetailDrawer) {
        actions.setSelectedQuestionId(null);
        actions.closeDetailDrawer();
      }
      if (feedback.clearSelection) {
        actions.clearSelection();
        setConfirmState(null);
      }
    },
    onError: (error) => {
      actions.onMessage(
        error instanceof Error ? error.message : "删除失败，请稍后重试。",
      );
    },
  });

  const requestBatchDelete = useCallback(() => {
    setConfirmState({ action: "batch-delete" });
  }, []);

  const requestDelete = useCallback((id: number) => {
    setConfirmState({ action: "delete", id });
  }, []);

  const cancelDelete = useCallback(() => setConfirmState(null), []);

  const confirmDelete = useCallback(() => {
    if (!confirmState) return;
    deleteMutation.mutate(confirmState);
  }, [confirmState, deleteMutation]);

  const deleteDescription = confirmState?.action === "batch-delete"
    ? "删除后这些题目将从题库永久移除，此操作不可撤销。"
    : "删除后该题目将从题库永久移除，此操作不可撤销。";

  return {
    confirmState,
    deleteMutation,
    requestBatchDelete,
    requestDelete,
    cancelDelete,
    confirmDelete,
    deleteDescription,
  };
}
