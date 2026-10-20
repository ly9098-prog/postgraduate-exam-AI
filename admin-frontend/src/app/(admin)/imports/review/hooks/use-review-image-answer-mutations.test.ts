import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BatchAnswerImageApplyResponse, BatchAnswerImagePreviewResponse } from "@/lib/api/types";
import {
  useReviewImageAnswerMutations,
  type ReviewImageAnswerApiRequest,
} from "./use-review-image-answer-mutations";

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

describe("useReviewImageAnswerMutations", () => {
  it("preserves multipart preview payload and lifecycle feedback", async () => {
    const cache = client();
    const preview = { preview_token: "token" } as BatchAnswerImagePreviewResponse;
    const request: ReviewImageAnswerApiRequest = vi.fn().mockResolvedValue(preview);
    const events: unknown[] = [];
    const hook = renderHook(cache, () => useReviewImageAnswerMutations(request, {
      onPreviewStarted: () => events.push("started"),
      onPreviewed: (result) => events.push(["previewed", result]),
      onPreviewError: vi.fn(),
      onApplyStarted: vi.fn(),
      onApplied: vi.fn(),
      onApplyError: vi.fn(),
    }));
    const image = new Blob(["image"], { type: "image/png" }) as File;

    await expect(hook.preview.mutateAsync({
      batchId: "batch/1",
      files: [image, image],
      mode: "answer_analysis",
    })).resolves.toBe(preview);
    const [path, options] = (request as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/imports/batch/1/answers/image/preview");
    expect(options.method).toBe("POST");
    expect(options.body).toBeInstanceOf(FormData);
    const files = (options.body as FormData).getAll("files");
    expect(files).toHaveLength(2);
    expect(files.every((file) => file instanceof Blob && file.type === "image/png")).toBe(true);
    expect((options.body as FormData).get("mode")).toBe("answer_analysis");
    expect(events).toEqual(["started", ["previewed", preview]]);
  });

  it("reports preview failures without invalidating the review queue", async () => {
    const cache = client();
    const error = new Error("invalid image");
    const request: ReviewImageAnswerApiRequest = vi.fn().mockRejectedValue(error);
    const onPreviewError = vi.fn();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const hook = renderHook(cache, () => useReviewImageAnswerMutations(request, {
      onPreviewStarted: vi.fn(),
      onPreviewed: vi.fn(),
      onPreviewError,
      onApplyStarted: vi.fn(),
      onApplied: vi.fn(),
      onApplyError: vi.fn(),
    }));

    await expect(hook.preview.mutateAsync({ batchId: "b", files: [], mode: "answer_only" })).rejects.toBe(error);
    expect(onPreviewError).toHaveBeenCalledOnce();
    expect(onPreviewError.mock.calls[0][0]).toBe(error);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("applies the preview token before invalidating the review queue", async () => {
    const cache = client();
    const result = { updated_answer_count: 1 } as BatchAnswerImageApplyResponse;
    const request: ReviewImageAnswerApiRequest = vi.fn().mockResolvedValue(result);
    const events: unknown[] = [];
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(["invalidate", filters?.queryKey]);
    });
    const hook = renderHook(cache, () => useReviewImageAnswerMutations(request, {
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
    expect(request).toHaveBeenCalledExactlyOnceWith("/imports/b/answers/image/apply", {
      method: "POST",
      body: JSON.stringify({ preview_token: "token", operation_id: "operation" }),
    });
    expect(events).toEqual([
      ["applied", result],
      ["invalidate", ["import-review-queue"]],
    ]);
  });

  it("reports apply failures without invalidating the review queue", async () => {
    const cache = client();
    const error = new Error("expired preview");
    const request: ReviewImageAnswerApiRequest = vi.fn().mockRejectedValue(error);
    const onApplyError = vi.fn();
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    const hook = renderHook(cache, () => useReviewImageAnswerMutations(request, {
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
