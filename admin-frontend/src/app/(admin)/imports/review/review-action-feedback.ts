import type { ImportActionResponse } from "@/lib/api/types";
import type {
  ReviewActionState,
  ReviewBatchActionResult,
} from "./review-action-requests";

type LowRiskBatchResult = {
  affected_count: number;
  skipped_count: number;
  skipped_reasons: string[];
};

type ReviewActionResult =
  | ImportActionResponse
  | ReviewBatchActionResult
  | LowRiskBatchResult;

export type ReviewActionFeedback = {
  message: string;
  closeDrawer: boolean;
};

export function buildReviewActionFeedback(
  result: ReviewActionResult,
  action: ReviewActionState,
): ReviewActionFeedback | null {
  if (action.action === "approve" || action.action === "reject") {
    return {
      message: `导入题目 #${action.id} ${action.action === "approve" ? "已通过审核" : "已驳回"}。`,
      closeDrawer: true,
    };
  }
  if (action.action === "batch-approve" || action.action === "batch-reject") {
    const affected = "affected_count" in result ? result.affected_count : 0;
    const errors = "errors" in result ? result.errors : undefined;
    const label = action.action === "batch-approve" ? "审核通过" : "驳回";
    if (errors && errors.length > 0) {
      const failedIds = errors.map((error) => `#${error.id}`).join("、");
      return {
        message: `批量${label}部分完成：成功 ${affected}，失败 ${errors.length}（${failedIds}）。`,
        closeDrawer: false,
      };
    }
    return {
      message: `批量${label}完成，影响 ${affected} 条导入题目。`,
      closeDrawer: false,
    };
  }
  if (action.action !== "low-risk-batch-approve") return null;
  const lowRisk = result as LowRiskBatchResult;
  const message = `低风险批量通过完成：通过 ${lowRisk.affected_count} 题，跳过 ${lowRisk.skipped_count} 题`;
  return {
    message: lowRisk.skipped_count > 0
      ? `${message}（部分高风险/需检查题已跳过）`
      : message,
    closeDrawer: false,
  };
}
