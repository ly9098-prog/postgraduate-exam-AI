import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BatchAnswerApplyResponse, BatchAnswerPreviewResponse } from "@/lib/api/types";
import {
  useReviewBatchAnswerMutations,
  type ReviewBatchAnswerApiRequest,
} from "./use-review-batch-answer-mutations";

const clients: QueryClient[] = [];
function client() {
  const value = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  clients.push(value);
  return value;
}

function renderHook<T>(cache: QueryClient, useFeature: () => T): T {
  let result!: T;
  function Probe() {
    result = useFeature();
    return null;
  }
  renderToStaticMarkup(createElement(QueryClientProvider, { client: cache }, createElement(Probe)));
  return result;
}

afterEach(() => {
  clients.splice(0).forEach((value) => value.clear());
  vi.restoreAllMocks();
});

describe("useReviewBatchAnswerMutations", () => {
  it("preserves text preview request and lifecycle feedback", async () => {
    const cache = client();
    const preview = { preview_token: "token", operation_id: "operation" } as BatchAnswerPreviewResponse;
    const request: ReviewBatchAnswerApiRequest = vi.fn().mockResolvedValue(preview);
    const events: unknown[] = [];
    const hook = renderHook(cache, () => useReviewBatchAnswerMutations(request, {
      onPreviewStarted: () => events.push("started"),
      onPreviewed: (result) => events.push(["previewed", result]),
      onPreviewError: (error) => events.push(["preview-error", error]),
      onApplyStarted: vi.fn(),
      onApplied: vi.fn(),
      onApplyError: vi.fn(),
    }));

    await expect(hook.preview.mutateAsync({ batchId: "batch/1", rawText: "  1. A  " })).resolves.toBe(preview);
    expect(request).toHaveBeenCalledExactlyOnceWith("/imports/batch/1/answers/preview", {
      method: "POST",
      body: JSON.stringify({ raw_text: "1. A", allow_partial_prefix: true }),
    });
    expect(events).toEqual(["started", ["previewed", preview]]);
  });

  it("reports preview failures without applying or invalidating queries", async () => {
    const cache = client();
    const error = new Error("invalid input");
    const request: ReviewBatchAnswerApiRequest = vi.fn().mockRejectedValue(error);
    const onPreviewError = vi.fn();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const hook = renderHook(cache, () => useReviewBatchAnswerMutations(request, {
      onPreviewStarted: vi.fn(),
      onPreviewed: vi.fn(),
      onPreviewError,
      onApplyStarted: vi.fn(),
      onApplied: vi.fn(),
      onApplyError: vi.fn(),
    }));

    await expect(hook.preview.mutateAsync({ batchId: "b", rawText: "A" })).rejects.toBe(error);
    expect(onPreviewError).toHaveBeenCalledOnce();
    expect(onPreviewError.mock.calls[0][0]).toBe(error);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("applies the confirmed preview token before queue invalidation", async () => {
    const cache = client();
    const result = { updated_count: 2 } as BatchAnswerApplyResponse;
    const request: ReviewBatchAnswerApiRequest = vi.fn().mockResolvedValue(result);
    const events: unknown[] = [];
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(["invalidate", filters?.queryKey]);
    });
    const hook = renderHook(cache, () => useReviewBatchAnswerMutations(request, {
      onPreviewStarted: vi.fn(),
      onPreviewed: vi.fn(),
      onPreviewError: vi.fn(),
      onApplyStarted: vi.fn(),
      onApplied: (value) => events.push(["applied", value]),
      onApplyError: vi.fn(),
    }));

    await expect(hook.apply.mutateAsync({
      batchId: "b",
      previewToken: "token",
      operationId: "operation",
    })).resolves.toBe(result);
    expect(request).toHaveBeenCalledExactlyOnceWith("/imports/b/answers/apply", {
      method: "POST",
      body: JSON.stringify({ preview_token: "token", operation_id: "operation" }),
    });
    expect(events).toEqual([
      ["applied", result],
      ["invalidate", ["import-review-queue"]],
    ]);
  });

  it("does not invalidate the queue when apply fails", async () => {
    const cache = client();
    const error = new Error("expired preview");
    const request: ReviewBatchAnswerApiRequest = vi.fn().mockRejectedValue(error);
    const onApplyError = vi.fn();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const hook = renderHook(cache, () => useReviewBatchAnswerMutations(request, {
      onPreviewStarted: vi.fn(),
      onPreviewed: vi.fn(),
      onPreviewError: vi.fn(),
      onApplyStarted: vi.fn(),
      onApplied: vi.fn(),
      onApplyError,
    }));

    await expect(hook.apply.mutateAsync({
      batchId: "b",
      previewToken: "expired",
      operationId: "",
    })).rejects.toBe(error);
    expect(onApplyError).toHaveBeenCalledOnce();
    expect(onApplyError.mock.calls[0][0]).toBe(error);
    expect(invalidate).not.toHaveBeenCalled();
  });
});
