import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ImportQuestionItem } from "@/lib/api/types";
import { executeReviewSaveRequest } from "../review-save-request";
import { useReviewUpdateMutation } from "./use-review-update-mutation";

vi.mock("../review-save-request", async () => {
  const actual = await vi.importActual<typeof import("../review-save-request")>("../review-save-request");
  return { ...actual, executeReviewSaveRequest: vi.fn() };
});

const result = { id: 7 } as ImportQuestionItem;
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
  vi.resetAllMocks();
});

describe("useReviewUpdateMutation", () => {
  it("keeps feedback before queue/detail invalidation", async () => {
    const cache = client();
    const events: unknown[] = [];
    vi.mocked(executeReviewSaveRequest).mockResolvedValue(result);
    vi.spyOn(cache, "setQueryData").mockImplementation((queryKey) => {
      events.push(["cache", queryKey]);
      return result;
    });
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(filters?.queryKey);
    });
    const hook = renderHook(cache, () => useReviewUpdateMutation({
      previewId: 7,
      editState: null,
      previewItem: null,
      editedSegments: null,
      visualBlockReasons: null,
      request: vi.fn(),
    }, {
      onSaved: (value) => events.push(["saved", value]),
      onAfterInvalidation: () => events.push("after-invalidation"),
      onError: vi.fn(),
    }));

    await expect(hook.mutateAsync()).resolves.toBe(result);
    expect(events).toEqual([
      ["cache", ["import-question-detail", 7]],
      ["saved", result],
      ["import-review-queue"],
      ["import-question-detail", 7],
      "after-invalidation",
    ]);
  });

  it("passes rejection to feedback without invalidating", async () => {
    const cache = client();
    const error = new Error("blocked");
    const onError = vi.fn();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    vi.mocked(executeReviewSaveRequest).mockRejectedValue(error);
    const hook = renderHook(cache, () => useReviewUpdateMutation({
      previewId: null,
      editState: null,
      previewItem: null,
      editedSegments: null,
      visualBlockReasons: null,
      request: vi.fn(),
    }, {
      onSaved: vi.fn(),
      onAfterInvalidation: vi.fn(),
      onError,
    }));

    await expect(hook.mutateAsync()).rejects.toBe(error);
    expect(onError.mock.calls[0][0]).toBe(error);
    expect(invalidate).not.toHaveBeenCalled();
  });
});
