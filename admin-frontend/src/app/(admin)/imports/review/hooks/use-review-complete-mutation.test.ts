import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminImportCompleteResponse } from "@/lib/api/types";
import { useReviewCompleteMutation, type ReviewCompleteApiRequest } from "./use-review-complete-mutation";

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

describe("useReviewCompleteMutation", () => {
  it("preserves request, callback, queue invalidation, detail write and UI sync order", async () => {
    const cache = client();
    const item = { id: 12 };
    const result = { item, missing: ["answer"] } as AdminImportCompleteResponse;
    const request: ReviewCompleteApiRequest = vi.fn().mockResolvedValue(result);
    const events: unknown[] = [];
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(["invalidate", filters?.queryKey]);
    });
    vi.spyOn(cache, "setQueryData").mockImplementation(((key: unknown, data: unknown) => {
      events.push(["set", key, data]);
      return data;
    }) as typeof cache.setQueryData);
    const hook = renderHook(cache, () => useReviewCompleteMutation(request, {
      onCompleted: (value) => events.push(["completed", value]),
      onDetailSynced: (value) => events.push(["detail-synced", value]),
      onError: vi.fn(),
    }));

    await expect(hook.mutateAsync(12)).resolves.toBe(result);
    expect(request).toHaveBeenCalledExactlyOnceWith("/imports/questions/12/complete", { method: "POST" });
    expect(events).toEqual([
      ["completed", result],
      ["invalidate", ["import-review-queue"]],
      ["set", ["import-question-detail", 12], item],
      ["detail-synced", result],
    ]);
  });

  it("wraps request errors and does not update caches on failure", async () => {
    const cache = client();
    const request: ReviewCompleteApiRequest = vi.fn().mockRejectedValue("offline");
    const onError = vi.fn();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const hook = renderHook(cache, () => useReviewCompleteMutation(request, {
      onCompleted: vi.fn(),
      onDetailSynced: vi.fn(),
      onError,
    }));

    await expect(hook.mutateAsync(5)).rejects.toThrow("题目 #5 补全失败：未知错误");
    expect(onError).toHaveBeenCalledOnce();
    expect(invalidate).not.toHaveBeenCalled();
  });
});
