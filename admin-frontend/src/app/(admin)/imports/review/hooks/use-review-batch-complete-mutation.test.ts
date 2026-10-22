import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BatchCompleteResponse, ImportQuestionItem } from "@/lib/api/types";
import {
  useReviewBatchCompleteMutation,
  type ReviewBatchCompleteApiRequest,
} from "./use-review-batch-complete-mutation";

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

describe("useReviewBatchCompleteMutation", () => {
  it("posts batch-complete request and invalidates queue+detail on success", async () => {
    const cache = client();
    const result = { total: 2, succeeded: 2, failed: 0, skipped: 0, items: [] } as BatchCompleteResponse;
    const request: ReviewBatchCompleteApiRequest = vi.fn().mockResolvedValue(result);
    const events: unknown[] = [];
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(["invalidate", filters?.queryKey]);
    });
    const hook = renderHook(cache, () => useReviewBatchCompleteMutation(request, {
      onStarted: () => events.push("started"),
      onCompleted: (value) => events.push(["completed", value]),
      onDetailSynced: vi.fn(),
      onError: vi.fn(),
      onFinished: () => events.push("finished"),
    }));

    await expect(hook.mutateAsync({
      importIds: [1, 2], fields: ["answer"], strategy: "fill_empty", openPreviewId: null,
    })).resolves.toBe(result);
    expect(request).toHaveBeenCalledExactlyOnceWith("/imports/questions/batch-complete", {
      method: "POST",
      body: JSON.stringify({ import_ids: [1, 2], fields: ["answer"], strategy: "fill_empty" }),
    });
    expect(events).toContain("started");
    expect(events).toContainEqual(["completed", result]);
    expect(events).toContainEqual(["invalidate", ["import-review-queue"]]);
    expect(events).toContainEqual(["invalidate", ["import-question-detail"]]);
    expect(events).toContain("finished");
  });

  it("eagerly refreshes open preview detail after batch-complete succeeds", async () => {
    const cache = client();
    const result = { total: 1, succeeded: 1, failed: 0, skipped: 0, items: [] } as BatchCompleteResponse;
    const detail = { id: 7 } as ImportQuestionItem;
    const request: ReviewBatchCompleteApiRequest = vi.fn()
      .mockResolvedValueOnce(result)
      .mockResolvedValueOnce(detail);
    const onDetailSynced = vi.fn();
    const setSpy = vi.spyOn(cache, "setQueryData").mockImplementation(() => []);
    const hook = renderHook(cache, () => useReviewBatchCompleteMutation(request, {
      onStarted: vi.fn(),
      onCompleted: vi.fn(),
      onDetailSynced,
      onError: vi.fn(),
      onFinished: vi.fn(),
    }));

    await hook.mutateAsync({
      importIds: [7], fields: ["answer"], strategy: "fill_empty", openPreviewId: 7,
    });
    expect(request).toHaveBeenCalledTimes(2);
    expect(request).toHaveBeenNthCalledWith(2, "/imports/questions/7");
    expect(setSpy).toHaveBeenCalledWith(["import-question-detail", 7], detail);
    expect(onDetailSynced).toHaveBeenCalledExactlyOnceWith(detail);
  });

  it("reports errors without invalidating queries", async () => {
    const cache = client();
    const error = new Error("server error");
    const request: ReviewBatchCompleteApiRequest = vi.fn().mockRejectedValue(error);
    const onError = vi.fn();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const hook = renderHook(cache, () => useReviewBatchCompleteMutation(request, {
      onStarted: vi.fn(),
      onCompleted: vi.fn(),
      onDetailSynced: vi.fn(),
      onError,
      onFinished: vi.fn(),
    }));

    await expect(hook.mutateAsync({
      importIds: [1], fields: ["answer"], strategy: "fill_empty", openPreviewId: null,
    })).rejects.toBe(error);
    expect(onError).toHaveBeenCalledOnce();
    expect(onError.mock.calls[0][0]).toBe(error);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("swallows detail refresh failure without failing the batch", async () => {
    const cache = client();
    const result = { total: 1, succeeded: 1, failed: 0, skipped: 0, items: [] } as BatchCompleteResponse;
    const request: ReviewBatchCompleteApiRequest = vi.fn()
      .mockResolvedValueOnce(result)
      .mockRejectedValueOnce(new Error("detail fetch failed"));
    const onDetailSynced = vi.fn();
    const onError = vi.fn();
    const hook = renderHook(cache, () => useReviewBatchCompleteMutation(request, {
      onStarted: vi.fn(),
      onCompleted: vi.fn(),
      onDetailSynced,
      onError,
      onFinished: vi.fn(),
    }));

    await hook.mutateAsync({
      importIds: [3], fields: ["answer"], strategy: "fill_empty", openPreviewId: 3,
    });
    expect(onDetailSynced).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });
});
