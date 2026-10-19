import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ImportQuestionItem } from "@/lib/api/types";
import { useReviewAnswerMutations, type ReviewAnswerApiRequest } from "./use-review-answer-mutations";

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

describe("useReviewAnswerMutations", () => {
  it("preserves the quick-answer request and feedback/invalidation order", async () => {
    const cache = client();
    const request: ReviewAnswerApiRequest = vi.fn().mockResolvedValue({ id: 7 } as ImportQuestionItem);
    const events: unknown[] = [];
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(filters?.queryKey);
    });
    const hook = renderHook(cache, () => useReviewAnswerMutations(request, {
      onQuickAnswerSaved: (item) => events.push(["saved", item]),
      onAnswerVerified: vi.fn(),
      onError: vi.fn(),
    }));

    await expect(hook.quickAnswer.mutateAsync({ id: 7, answer: "B" })).resolves.toEqual({ id: 7 });
    expect(request).toHaveBeenCalledExactlyOnceWith("/imports/questions/7", {
      method: "PUT",
      body: JSON.stringify({ answer: "B" }),
    });
    expect(events).toEqual([
      ["saved", { id: 7 }],
      ["import-review-queue"],
      ["import-question-detail", 7],
    ]);
  });

  it("uses the manual verification payload and does not invalidate on failure", async () => {
    const cache = client();
    const error = new Error("network");
    const request: ReviewAnswerApiRequest = vi.fn().mockRejectedValue(error);
    const onError = vi.fn();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const hook = renderHook(cache, () => useReviewAnswerMutations(request, {
      onQuickAnswerSaved: vi.fn(),
      onAnswerVerified: vi.fn(),
      onError,
    }));

    await expect(hook.verifyAnswer.mutateAsync(9)).rejects.toBe(error);
    expect(request).toHaveBeenCalledExactlyOnceWith("/imports/questions/9", {
      method: "PUT",
      body: JSON.stringify({ answer_status: "manual_verified" }),
    });
    expect(onError).toHaveBeenCalledExactlyOnceWith(error, "verify");
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("keeps hook instances isolated", async () => {
    const firstRequest: ReviewAnswerApiRequest = vi.fn().mockResolvedValue({ id: 1 } as ImportQuestionItem);
    const secondRequest: ReviewAnswerApiRequest = vi.fn().mockResolvedValue({ id: 2 } as ImportQuestionItem);
    const feedback = { onQuickAnswerSaved: vi.fn(), onAnswerVerified: vi.fn(), onError: vi.fn() };
    const first = renderHook(client(), () => useReviewAnswerMutations(firstRequest, feedback));
    const second = renderHook(client(), () => useReviewAnswerMutations(secondRequest, feedback));

    await first.verifyAnswer.mutateAsync(1);
    await second.verifyAnswer.mutateAsync(2);
    expect(firstRequest).toHaveBeenCalledOnce();
    expect(secondRequest).toHaveBeenCalledOnce();
  });
});
