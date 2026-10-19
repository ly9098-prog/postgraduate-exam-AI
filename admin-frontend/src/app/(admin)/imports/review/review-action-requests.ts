import type { ImportActionResponse } from "@/lib/api/types";

export type ReviewActionState =
  | { action: "approve"; id: number }
  | { action: "reject"; id: number }
  | { action: "batch-approve" }
  | { action: "batch-reject" }
  | { action: "low-risk-batch-approve" };

export type ReviewBatchActionResult = {
  affected_count: number;
  errors?: Array<{ id: number; message: string }>;
};

type LowRiskBatchResult = {
  affected_count: number;
  skipped_count: number;
  skipped_reasons: string[];
};

export type ReviewActionApiRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

export type ReviewActionRequestOptions = {
  action: ReviewActionState;
  batchId: string;
  batchIdParam: string;
  selectedIds: number[];
  rejectReason: string;
  batchIdempotencyKeyFor: (operation: string) => string;
  request: ReviewActionApiRequest;
};

async function executeInChunks<T>(
  ids: number[],
  concurrency: number,
  execute: (id: number) => Promise<T>,
): Promise<PromiseSettledResult<T>[]> {
  const results: PromiseSettledResult<T>[] = [];
  for (let index = 0; index < ids.length; index += concurrency) {
    const settled = await Promise.allSettled(ids.slice(index, index + concurrency).map(execute));
    results.push(...settled);
  }
  return results;
}

function summarizeBatchResults(
  ids: number[],
  results: PromiseSettledResult<ImportActionResponse>[],
): ReviewBatchActionResult {
  const errors: Array<{ id: number; message: string }> = [];
  let affected = 0;
  results.forEach((result, index) => {
    if (result.status === "fulfilled") {
      affected += 1;
    } else {
      errors.push({
        id: ids[index],
        message: result.reason instanceof Error ? result.reason.message : String(result.reason),
      });
    }
  });
  return { affected_count: affected, errors };
}

export async function executeReviewActionRequest({
  action,
  batchId,
  batchIdParam,
  selectedIds,
  rejectReason,
  batchIdempotencyKeyFor,
  request,
}: ReviewActionRequestOptions): Promise<ImportActionResponse | ReviewBatchActionResult | LowRiskBatchResult> {
  if (action.action === "approve") {
    try {
      return await request<ImportActionResponse>(`/imports/questions/${action.id}/approve`, { method: "POST" });
    } catch (error) {
      throw new Error(`题目 #${action.id} 审核通过失败：${error instanceof Error ? error.message : "未知错误"}`);
    }
  }

  if (action.action === "reject") {
    try {
      return await request<ImportActionResponse>(`/imports/questions/${action.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: rejectReason }),
      });
    } catch (error) {
      throw new Error(`题目 #${action.id} 驳回失败：${error instanceof Error ? error.message : "未知错误"}`);
    }
  }

  if (action.action === "batch-approve" && selectedIds.length > 0) {
    const results = await executeInChunks(selectedIds, 6, (id) =>
      request<ImportActionResponse>(`/imports/questions/${id}/approve`, { method: "POST" }),
    );
    return summarizeBatchResults(selectedIds, results);
  }

  if (action.action === "batch-reject" && selectedIds.length > 0) {
    const results = await executeInChunks(selectedIds, 6, (id) =>
      request<ImportActionResponse>(`/imports/questions/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: rejectReason }),
      }),
    );
    return summarizeBatchResults(selectedIds, results);
  }

  if (action.action === "batch-approve") {
    return request<ImportActionResponse>(`/imports/${batchId}/approve`, {
      method: "POST",
      headers: { "Idempotency-Key": batchIdempotencyKeyFor(`approve:${batchId}`) },
    });
  }

  if (action.action === "batch-reject") {
    return request<ImportActionResponse>(`/imports/${batchId}/reject`, {
      method: "POST",
      headers: { "Idempotency-Key": batchIdempotencyKeyFor(`reject:${batchId}:${rejectReason}`) },
      body: JSON.stringify({ reason: rejectReason }),
    });
  }

  if (action.action === "low-risk-batch-approve") {
    const targetBatchId = batchId || batchIdParam;
    if (!targetBatchId) throw new Error("请先选择导入批次");
    return request<LowRiskBatchResult>(`/imports/${targetBatchId}/approve-low-risk`, { method: "POST" });
  }

  throw new Error("未知操作");
}
