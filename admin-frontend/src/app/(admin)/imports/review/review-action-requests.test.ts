import { describe, expect, it, vi } from "vitest";
import {
  executeReviewActionRequest,
  type ReviewActionApiRequest,
  type ReviewActionRequestOptions,
  type ReviewActionState,
} from "./review-action-requests";

const keyFor = vi.fn((operation: string) => `key:${operation}`);

type RequestSpy = ReturnType<typeof vi.fn> & ReviewActionApiRequest;

function createRequestSpy(
  implementation: (path: string, options?: RequestInit) => unknown = () => ({ affected_count: 1 }),
): RequestSpy {
  return vi.fn(async (path: string, requestOptions?: RequestInit) => (
    implementation(path, requestOptions)
  )) as unknown as RequestSpy;
}

function options(
  action: ReviewActionState,
  overrides: Partial<Omit<ReviewActionRequestOptions, "action">> = {},
): ReviewActionRequestOptions {
  return {
    action,
    batchId: "selected-batch",
    batchIdParam: "url-batch",
    selectedIds: [],
    rejectReason: "wrong answer",
    batchIdempotencyKeyFor: keyFor,
    request: createRequestSpy(),
    ...overrides,
  };
}

describe("review action request execution", () => {
  it("preserves single approve/reject routes and wrapped error messages", async () => {
    const request = createRequestSpy();
    await executeReviewActionRequest(options({ action: "approve", id: 8 }, { request }));
    await executeReviewActionRequest(options({ action: "reject", id: 9 }, { request }));
    expect(request.mock.calls).toEqual([
      ["/imports/questions/8/approve", { method: "POST" }],
      ["/imports/questions/9/reject", { method: "POST", body: '{"reason":"wrong answer"}' }],
    ]);

    const failingRequest = createRequestSpy(() => {
      throw new Error("permission denied");
    });
    await expect(
      executeReviewActionRequest(options({ action: "approve", id: 8 }, { request: failingRequest })),
    ).rejects.toThrow("题目 #8 审核通过失败：permission denied");
  });

  it("executes selected ids in six-item chunks and keeps partial failures in input order", async () => {
    let activeRequests = 0;
    let maxConcurrentRequests = 0;
    const request = createRequestSpy(async (path: string) => {
      activeRequests += 1;
      maxConcurrentRequests = Math.max(maxConcurrentRequests, activeRequests);
      try {
        await Promise.resolve();
        if (path.endsWith("/3/approve")) throw "conflict";
        return { affected_count: 1 };
      } finally {
        activeRequests -= 1;
      }
    });
    const result = await executeReviewActionRequest(options(
      { action: "batch-approve" },
      { selectedIds: [1, 2, 3, 4, 5, 6, 7], request },
    ));
    expect(request).toHaveBeenCalledTimes(7);
    expect(maxConcurrentRequests).toBe(6);
    expect(request.mock.calls[0]?.[0]).toBe("/imports/questions/1/approve");
    expect(request.mock.calls[6]?.[0]).toBe("/imports/questions/7/approve");
    expect(result).toEqual({
      affected_count: 6,
      errors: [{ id: 3, message: "conflict" }],
    });
  });

  it("uses batch idempotency keys and includes the reject reason in its operation key", async () => {
    const request = createRequestSpy(() => ({ affected_count: 2 }));
    await executeReviewActionRequest(options({ action: "batch-approve" }, { request }));
    await executeReviewActionRequest(options({ action: "batch-reject" }, { request }));
    expect(request.mock.calls).toEqual([
      ["/imports/selected-batch/approve", { method: "POST", headers: { "Idempotency-Key": "key:approve:selected-batch" } }],
      ["/imports/selected-batch/reject", {
        method: "POST",
        headers: { "Idempotency-Key": "key:reject:selected-batch:wrong answer" },
        body: '{"reason":"wrong answer"}',
      }],
    ]);
  });

  it("falls back to the URL batch id only for low-risk approval", async () => {
    const request = createRequestSpy(() => (
      { affected_count: 1, skipped_count: 2, skipped_reasons: ["visual"] }
    ));
    await executeReviewActionRequest(options(
      { action: "low-risk-batch-approve" },
      { batchId: "", request },
    ));
    expect(request).toHaveBeenCalledWith("/imports/url-batch/approve-low-risk", { method: "POST" });

    await expect(executeReviewActionRequest(options(
      { action: "low-risk-batch-approve" },
      { batchId: "", batchIdParam: "" },
    ))).rejects.toThrow("请先选择导入批次");
  });
});
