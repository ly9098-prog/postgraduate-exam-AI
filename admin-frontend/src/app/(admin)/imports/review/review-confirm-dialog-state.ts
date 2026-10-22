import type { ReviewActionState } from "./review-action-requests";

export type ReviewConfirmDialogState = {
  title: string;
  description: string;
  confirmText: string;
  danger: boolean;
  showRejectReason: boolean;
};

export function buildReviewConfirmDialogState(
  action: ReviewActionState | null,
  selectedCount: number,
): ReviewConfirmDialogState {
  return {
    title: action?.action === "low-risk-batch-approve"
      ? "批量通过低风险题"
      : action?.action?.includes("reject") ? "驳回导入题目" : "通过导入题目",
    description: action?.action === "low-risk-batch-approve"
      ? "将自动通过当前批次中所有低风险题（risk_level=low）并跳过高风险和需检查题。高风险和需检查题不会被通过。"
      : action?.action === "batch-approve" && selectedCount > 0
        ? `将对已选的 ${selectedCount} 条导入题目执行批量通过操作。`
        : action?.action === "batch-reject" && selectedCount > 0
          ? `将对已选的 ${selectedCount} 条导入题目执行批量驳回操作。`
          : "操作会更新 question_imports 暂存审核状态。",
    confirmText: action?.action === "low-risk-batch-approve"
      ? "批量通过低风险"
      : action?.action?.includes("reject") ? "驳回" : "通过",
    danger: Boolean(action?.action.includes("reject")),
    showRejectReason: action?.action === "reject" || action?.action === "batch-reject",
  };
}
