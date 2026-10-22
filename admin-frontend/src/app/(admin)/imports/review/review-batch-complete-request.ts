import type { BatchCompleteResponse } from "@/lib/api/types";
import type { BatchCompleteStrategy } from "./review-batch-complete-draft";

export type BatchCompleteRequestArgs = {
  importIds: number[];
  fields: string[];
  strategy: BatchCompleteStrategy;
};

export type BatchCompleteValidationResult =
  | { ok: true; args: BatchCompleteRequestArgs }
  | { ok: false; message: string };

/** Validate batch-complete inputs before making the API call. */
export function validateBatchCompleteRequest(
  importIds: number[],
  fields: string[],
  strategy: BatchCompleteStrategy,
): BatchCompleteValidationResult {
  if (importIds.length === 0) {
    return { ok: false, message: "请先选择需要补全的题目。" };
  }
  if (fields.length === 0) {
    return { ok: false, message: "请选择至少一个补全字段。" };
  }
  return { ok: true, args: { importIds, fields, strategy } };
}

/** Build the success message from a completed batch-complete response. */
export function buildBatchCompleteFeedback(result: BatchCompleteResponse): string {
  const failedItems = result.items.filter((item) => item.status === "failed");
  const failedIdStr = failedItems.length > 0
    ? `（${failedItems.map((item) => `#${item.import_id}`).join("、")}）`
    : "";
  return `批量补全完成：成功 ${result.succeeded}，失败 ${result.failed}，跳过 ${result.skipped}${failedIdStr}`;
}
