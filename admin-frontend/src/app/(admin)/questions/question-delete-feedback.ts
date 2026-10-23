import type { BatchDeleteResult } from "./question-api";
import type { QuestionDeleteIntent } from "./hooks/use-question-delete";

type DeleteFeedbackInputs = {
  result: unknown;
  intent: QuestionDeleteIntent;
  selectedQuestionId: number | null;
};

export type QuestionDeleteFeedback = {
  message: string;
  clearSelection: boolean;
  closeDetailDrawer: boolean;
};

function normalizeBatchDeleteResult(result: unknown): BatchDeleteResult {
  const value = result as Partial<BatchDeleteResult> | null | undefined;
  return {
    success_ids: value?.success_ids ?? value?.successIds ?? [],
    failed_items: value?.failed_items ?? value?.failedItems ?? [],
  };
}

function buildBatchDeleteMessage(result: BatchDeleteResult): string {
  const successIds = result.success_ids ?? [];
  const failedItems = result.failed_items ?? [];
  const failurePreview = failedItems
    .slice(0, 5)
    .map((item) => `#${item.id} ${item.error}`)
    .join("；");
  const failures = failedItems.length
    ? `失败 ${failedItems.length} 条：${failurePreview}${failedItems.length > 5 ? "；…" : ""}`
    : "无失败项";
  return `批量删除完成，成功 ${successIds.length} 条，${failures}。`;
}

export function buildQuestionDeleteFeedback({
  result,
  intent,
  selectedQuestionId,
}: DeleteFeedbackInputs): QuestionDeleteFeedback {
  if (intent.action === "delete") {
    return {
      message: `题目 #${intent.id} 已删除。`,
      clearSelection: true,
      closeDetailDrawer: true,
    };
  }

  const batch = normalizeBatchDeleteResult(result);
  const successIds = batch.success_ids ?? [];
  return {
    message: buildBatchDeleteMessage(batch),
    clearSelection: true,
    closeDetailDrawer: selectedQuestionId !== null && successIds.includes(selectedQuestionId),
  };
}
