import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminQuestion } from "@/lib/api/types";
import { deleteQuestion, deleteQuestionBatch, updateQuestion } from "./question-api";
import { useQuestionDelete } from "./hooks/use-question-delete";
import { useQuestionUpdate } from "./hooks/use-question-update";
import { questionKeys } from "./question-queries";

vi.mock("./question-api", () => ({
  deleteQuestion: vi.fn(), deleteQuestionBatch: vi.fn(), updateQuestion: vi.fn(),
}));

const baseline: AdminQuestion = {
  id: 7, question_type: "judge", answer: "A", difficulty: 2,
  content: { stem: "stem" }, review_status: "approved", is_active: true,
};
const input = {
  questionId: 7, baseline, stemText: "stem",
  form: { question_type: "judge", answer: "B", difficulty: 2, content: baseline.content },
};
const clients: QueryClient[] = [];
function client() {
  const cache = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  clients.push(cache);
  return cache;
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
  clients.splice(0).forEach((cache) => cache.clear());
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

describe("question update mutation", () => {
  it("sends the minimal patch then runs feedback before both invalidations", async () => {
    const cache = client();
    const events: unknown[] = [];
    vi.mocked(updateQuestion).mockResolvedValue(baseline);
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(filters?.queryKey);
    });
    const hook = renderHook(cache, () => useQuestionUpdate(input, {
      onSaved: () => { events.push("saved"); }, onError: vi.fn(),
    }));
    expect(await hook.mutateAsync()).toBe(baseline);
    expect(updateQuestion).toHaveBeenCalledExactlyOnceWith(7, { answer: "B" });
    expect(events).toEqual(["saved", questionKeys.all, questionKeys.scope(7)]);
  });

  it.each([
    [{ ...input, questionId: null, baseline: undefined }, "未选中题目"],
    [{ ...input, baseline: undefined }, "题目详情尚未加载完成"],
    [{ ...input, form: { ...input.form, answer: "A" } }, "没有需要保存的修改"],
  ])("rejects invalid state before issuing a request: %s", async (state, message) => {
    const cache = client();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const onError = vi.fn();
    const onSaved = vi.fn();
    const hook = renderHook(cache, () => useQuestionUpdate(state, { onSaved, onError }));
    await expect(hook.mutateAsync()).rejects.toThrow(message);
    expect(onError.mock.calls[0][0].message).toBe(message);
    expect(updateQuestion).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalled();
  });

  it.each([new Error("conflict"), "network error"])(
    "preserves an API failure without closing editing or invalidating: %s", async (error) => {
      const cache = client();
      const invalidate = vi.spyOn(cache, "invalidateQueries");
      const onError = vi.fn();
      const onSaved = vi.fn();
      vi.mocked(updateQuestion).mockRejectedValue(error);
      const hook = renderHook(cache, () => useQuestionUpdate(input, { onSaved, onError }));
      await expect(hook.mutateAsync()).rejects.toBe(error);
      expect(onError.mock.calls[0][0]).toBe(error);
      expect(onSaved).not.toHaveBeenCalled();
      expect(invalidate).not.toHaveBeenCalled();
    },
  );

  it("preserves feedback failure before invalidation", async () => {
    const cache = client();
    const error = new Error("feedback failure");
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const onError = vi.fn();
    vi.mocked(updateQuestion).mockResolvedValue(baseline);
    const hook = renderHook(cache, () => useQuestionUpdate(input, {
      onSaved: () => { throw error; }, onError,
    }));
    await expect(hook.mutateAsync()).rejects.toBe(error);
    expect(onError.mock.calls[0][0]).toBe(error);
    expect(invalidate).not.toHaveBeenCalled();
  });
});

describe("question deletion mutation", () => {
  it("deletes the intent ID and invalidates after UI feedback", async () => {
    const cache = client();
    const events: unknown[] = [];
    const result = { status: "deleted" };
    vi.mocked(deleteQuestion).mockResolvedValue(result);
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(filters?.queryKey);
    });
    const hook = renderHook(cache, () => useQuestionDelete(new Set([1]), {
      onDeleted: (value, intent) => { events.push([value, intent]); }, onError: vi.fn(),
    }));
    await hook.mutateAsync({ action: "delete", id: 7 });
    expect(deleteQuestion).toHaveBeenCalledExactlyOnceWith(7);
    expect(deleteQuestionBatch).not.toHaveBeenCalled();
    expect(events).toEqual([[result, { action: "delete", id: 7 }], questionKeys.all]);
  });

  it("retains chunk keys after failure and clears all keys after partial success", async () => {
    const cache = client();
    const error = new Error("ambiguous transport failure");
    const attempts: string[][] = [];
    const generated = vi.spyOn(crypto, "randomUUID");
    const partial = { success_ids: [9], failed_items: [{ id: 3, error: "blocked" }] };
    vi.mocked(deleteQuestionBatch).mockImplementation(async (ids, keyForChunk) => {
      expect(ids).toEqual([9, 3]);
      const keys = [keyForChunk([9]), keyForChunk([3]), keyForChunk([9])];
      attempts.push(keys);
      if (attempts.length === 1) throw error;
      return partial;
    });
    const onDeleted = vi.fn();
    const onError = vi.fn();
    const hook = renderHook(cache, () => useQuestionDelete(new Set([9, 3]), { onDeleted, onError }));
    await expect(hook.mutateAsync({ action: "batch-delete" })).rejects.toBe(error);
    expect(onDeleted).not.toHaveBeenCalled();
    await expect(hook.mutateAsync({ action: "batch-delete" })).resolves.toBe(partial);
    await hook.mutateAsync({ action: "batch-delete" });
    expect(attempts[0][0]).toBe(attempts[0][2]);
    expect(attempts[1]).toEqual(attempts[0]);
    expect(attempts[2][0]).not.toBe(attempts[0][0]);
    expect(attempts[2][1]).not.toBe(attempts[0][1]);
    expect(generated).toHaveBeenCalledTimes(4);
    expect(onDeleted).toHaveBeenCalledTimes(2);
    expect(onError.mock.calls[0][0]).toBe(error);
  });

  it("keeps separate key maps for two page instances", async () => {
    const keys: string[] = [];
    vi.mocked(deleteQuestionBatch).mockImplementation(async (ids, keyForChunk) => {
      keys.push(keyForChunk(ids));
      throw new Error("retry");
    });
    const feedback = { onDeleted: vi.fn(), onError: vi.fn() };
    const first = renderHook(client(), () => useQuestionDelete(new Set([7]), feedback));
    const second = renderHook(client(), () => useQuestionDelete(new Set([7]), feedback));
    await expect(first.mutateAsync({ action: "batch-delete" })).rejects.toThrow("retry");
    await expect(second.mutateAsync({ action: "batch-delete" })).rejects.toThrow("retry");
    await expect(first.mutateAsync({ action: "batch-delete" })).rejects.toThrow("retry");
    expect(keys[0]).not.toBe(keys[1]);
    expect(keys[2]).toBe(keys[0]);
  });

  it("does not invalidate or run success feedback for a single-delete failure", async () => {
    const cache = client();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const error = new Error("forbidden");
    vi.mocked(deleteQuestion).mockRejectedValue(error);
    const feedback = { onDeleted: vi.fn(), onError: vi.fn() };
    const hook = renderHook(cache, () => useQuestionDelete(new Set(), feedback));
    await expect(hook.mutateAsync({ action: "delete", id: 7 })).rejects.toBe(error);
    expect(feedback.onDeleted).not.toHaveBeenCalled();
    expect(feedback.onError.mock.calls[0][0]).toBe(error);
    expect(invalidate).not.toHaveBeenCalled();
  });
});
