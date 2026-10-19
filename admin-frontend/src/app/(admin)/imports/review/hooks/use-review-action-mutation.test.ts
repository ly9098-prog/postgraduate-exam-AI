import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  executeReviewActionRequest,
  type ReviewActionApiRequest,
} from "../review-action-requests";
import { useReviewActionMutation } from "./use-review-action-mutation";

vi.mock("../review-action-requests", async () => {
  const actual = await vi.importActual<typeof import("../review-action-requests")>("../review-action-requests");
  return { ...actual, executeReviewActionRequest: vi.fn() };
});

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

const request: ReviewActionApiRequest = vi.fn();
const action = { action: "batch-approve" as const };
const result = { affected_count: 2 };

afterEach(() => {
  clients.splice(0).forEach((value) => value.clear());
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

describe("useReviewActionMutation", () => {
  it("runs page feedback and cache invalidation in the established order", async () => {
    const cache = client();
    const events: unknown[] = [];
    vi.mocked(executeReviewActionRequest).mockResolvedValue(result);
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(filters?.queryKey);
    });
    const hook = renderHook(cache, () => useReviewActionMutation({
      batchId: "batch-1",
      batchIdParam: "",
      selectedIds: new Set([2, 1]),
      rejectReason: "",
      request,
    }, {
      onSuccess: (value, intent) => { events.push(["success", value, intent]); },
      onReset: () => { events.push("reset"); },
      onError: vi.fn(),
    }));

    await expect(hook.mutateAsync(action)).resolves.toBe(result);
    expect(executeReviewActionRequest).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      action,
      batchId: "batch-1",
      selectedIds: [2, 1],
      request,
    }));
    expect(events).toEqual([
      ["success", result, action],
      "reset",
      ["import-review-queue"],
      ["import-batches"],
      ["questions"],
    ]);
  });

  it("does not reset or invalidate when the request rejects", async () => {
    const cache = client();
    const error = new Error("transport");
    const onSuccess = vi.fn();
    const onReset = vi.fn();
    const onError = vi.fn();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    vi.mocked(executeReviewActionRequest).mockRejectedValue(error);
    const hook = renderHook(cache, () => useReviewActionMutation({
      batchId: "",
      batchIdParam: "batch-2",
      selectedIds: new Set(),
      rejectReason: "bad",
      request,
    }, { onSuccess, onReset, onError }));

    await expect(hook.mutateAsync({ action: "reject", id: 4 })).rejects.toBe(error);
    expect(onError).toHaveBeenCalledOnce();
    expect(onError.mock.calls[0][0]).toBe(error);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onReset).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("keeps each page instance's mutation hook isolated", async () => {
    vi.mocked(executeReviewActionRequest).mockResolvedValue(result);
    const first = renderHook(client(), () => useReviewActionMutation({
      batchId: "first",
      batchIdParam: "",
      selectedIds: new Set(),
      rejectReason: "",
      request,
    }, { onSuccess: vi.fn(), onReset: vi.fn(), onError: vi.fn() }));
    const second = renderHook(client(), () => useReviewActionMutation({
      batchId: "second",
      batchIdParam: "",
      selectedIds: new Set(),
      rejectReason: "",
      request,
    }, { onSuccess: vi.fn(), onReset: vi.fn(), onError: vi.fn() }));

    await first.mutateAsync({ action: "batch-approve" });
    await second.mutateAsync({ action: "batch-approve" });
    expect(vi.mocked(executeReviewActionRequest).mock.calls.map(([input]) => input.batchId))
      .toEqual(["first", "second"]);
  });
});
