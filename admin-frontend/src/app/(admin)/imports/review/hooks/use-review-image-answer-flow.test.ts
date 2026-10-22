import { createElement, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type {
  BatchAnswerImageApplyResponse,
  BatchAnswerImagePreviewResponse,
} from "@/lib/api/types";
import {
  buildImageAnswerApplyInput,
  buildImageAnswerMutationFeedback,
  buildImageAnswerPreviewInput,
  createReviewImageAnswerState,
  useReviewImageAnswerFlow,
  reduceReviewImageAnswerState,
} from "./use-review-image-answer-flow";
import type { ReviewImageAnswerApiRequest } from "./use-review-image-answer-mutations";

function image(name: string) {
  return new File([name], name, { type: "image/png" });
}

const preview = {
  preview_token: "preview-token",
  operation_id: "preview-operation",
} as BatchAnswerImagePreviewResponse;

const result = {
  updated_answer_count: 2,
} as BatchAnswerImageApplyResponse;

describe("review image answer state", () => {
  it("adds files in selection order without changing the current mode", () => {
    const first = image("first.png");
    const second = image("second.png");
    const state = createReviewImageAnswerState();
    const withMode = reduceReviewImageAnswerState(state, {
      type: "mode-changed",
      mode: "answer_analysis",
    });
    const stale = {
      ...withMode,
      preview,
      result,
      error: "old error",
    };

    const next = reduceReviewImageAnswerState(stale, {
      type: "files-added",
      files: [first, second],
    });

    expect(next).toEqual({
      files: [first, second],
      mode: "answer_analysis",
      preview: null,
      result: null,
      error: null,
    });
    expect(stale.files).toEqual([]);
    expect(stale.preview).toBe(preview);

    const appended = reduceReviewImageAnswerState(next, {
      type: "files-added",
      files: [image("third.png")],
    });
    expect(appended.files.map((file) => file.name)).toEqual([
      "first.png",
      "second.png",
      "third.png",
    ]);
  });

  it("removes exactly the requested file and clears stale outputs", () => {
    const first = image("first.png");
    const second = image("second.png");
    const third = image("third.png");
    const state = {
      ...createReviewImageAnswerState(),
      files: [first, second, third],
      preview,
      result,
      error: "old error",
    };

    expect(reduceReviewImageAnswerState(state, {
      type: "file-removed",
      index: 1,
    })).toEqual({
      files: [first, third],
      mode: "answer_only",
      preview: null,
      result: null,
      error: null,
    });
    expect(reduceReviewImageAnswerState(state, {
      type: "file-removed",
      index: 99,
    }).files).toEqual([first, second, third]);
    expect(state.files).toEqual([first, second, third]);
  });

  it("clears files and outputs on reset but preserves the selected mode", () => {
    const state = {
      files: [image("first.png")],
      mode: "answer_analysis" as const,
      preview,
      result,
      error: "old error",
    };

    expect(reduceReviewImageAnswerState(state, { type: "reset" })).toEqual({
      files: [],
      mode: "answer_analysis",
      preview: null,
      result: null,
      error: null,
    });
  });

  it("clears preview and apply output when a preview starts and stores the response", () => {
    const file = image("first.png");
    const state = {
      ...createReviewImageAnswerState(),
      files: [file],
      preview,
      result,
      error: "old error",
    };

    const started = reduceReviewImageAnswerState(state, {
      type: "preview-started",
    });
    expect(started).toEqual({
      files: [file],
      mode: "answer_only",
      preview: null,
      result: null,
      error: null,
    });
    expect(reduceReviewImageAnswerState(started, {
      type: "previewed",
      preview,
    })).toEqual({
      files: [file],
      mode: "answer_only",
      preview,
      result: null,
      error: null,
    });
  });

  it("preserves Error messages and falls back for unknown preview failures", () => {
    const state = {
      ...createReviewImageAnswerState(),
      files: [image("first.png")],
    };

    const failed = reduceReviewImageAnswerState(state, {
      type: "preview-failed",
      error: new Error("invalid image"),
    });
    expect(failed.files).toEqual(state.files);
    expect(failed.mode).toBe(state.mode);
    expect(failed.preview).toBeNull();
    expect(failed.result).toBeNull();
    expect(failed.error).toBe("invalid image");
    expect(reduceReviewImageAnswerState(state, {
      type: "preview-failed",
      error: "request failed",
    }).error).toBe("预览生成失败");
  });

  it("clears only the error when apply starts and stores the final result", () => {
    const state = {
      ...createReviewImageAnswerState(),
      preview,
      error: "old error",
    };

    const started = reduceReviewImageAnswerState(state, {
      type: "apply-started",
    });
    expect(started).toEqual({
      files: [],
      mode: "answer_only",
      preview,
      result: null,
      error: null,
    });
    expect(reduceReviewImageAnswerState(started, {
      type: "applied",
      result,
    })).toEqual({
      files: [],
      mode: "answer_only",
      preview,
      result,
      error: null,
    });
  });

  it("preserves Error messages and falls back for unknown apply failures", () => {
    const state = {
      ...createReviewImageAnswerState(),
      preview,
    };

    const failed = reduceReviewImageAnswerState(state, {
      type: "apply-failed",
      error: new Error("expired preview"),
    });
    expect(failed.files).toEqual(state.files);
    expect(failed.mode).toBe(state.mode);
    expect(failed.preview).toBe(preview);
    expect(failed.result).toBeNull();
    expect(failed.error).toBe("expired preview");
    expect(reduceReviewImageAnswerState(state, {
      type: "apply-failed",
      error: null,
    }).error).toBe("写入失败");
  });
});

describe("review image answer request inputs", () => {
  it("requires a batch and at least one file for preview", () => {
    const files = [image("first.png")];

    expect(buildImageAnswerPreviewInput("", files, "answer_only")).toBeNull();
    expect(buildImageAnswerPreviewInput("batch/1", [], "answer_only")).toBeNull();
    expect(buildImageAnswerPreviewInput("batch/1", files, "answer_analysis")).toEqual({
      batchId: "batch/1",
      files,
      mode: "answer_analysis",
    });
  });

  it("requires a batch and preview token for apply", () => {
    expect(buildImageAnswerApplyInput("", preview)).toBeNull();
    expect(buildImageAnswerApplyInput("batch/1", null)).toBeNull();
    expect(buildImageAnswerApplyInput("batch/1", {
      ...preview,
      preview_token: "",
    })).toBeNull();
    const withoutOperation = {
      preview_token: "preview-token",
    } as BatchAnswerImagePreviewResponse;
    expect(buildImageAnswerApplyInput("batch/1", withoutOperation)).toEqual({
      batchId: "batch/1",
      previewToken: "preview-token",
      operationId: "",
    });
  });
});

describe("review image answer mutation feedback", () => {
  it("keeps empty-batch preview guarded and exposes the initial state", () => {
    const cache = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });
    let requestCount = 0;
    const request = vi.fn(async <T,>() => {
      requestCount += 1;
      return {} as T;
    }) as unknown as ReviewImageAnswerApiRequest;
    let flow!: ReturnType<typeof useReviewImageAnswerFlow>;
    function Probe() {
      flow = useReviewImageAnswerFlow(request);
      const [step, setStep] = useState(0);
      if (step === 0) {
        setStep(1);
        flow.handleImagePreview("");
        flow.handleImageApply("");
      }
      return null;
    }
    renderToStaticMarkup(
      createElement(QueryClientProvider, { client: cache }, createElement(Probe)),
    );
    expect(requestCount).toBe(0);
    expect(flow.imageExecuting).toBe(false);
    expect(flow.imageFiles).toEqual([]);
    expect(flow.imageImportMode).toBe("answer_only");
    expect(flow.imagePreviewResult).toBeNull();
    expect(flow.imageApplyResult).toBeNull();
    expect(flow.imageError).toBeNull();
    cache.clear();
  });

  it("maps every mutation lifecycle callback to its reducer action", () => {
    const dispatch = vi.fn();
    const feedback = buildImageAnswerMutationFeedback(dispatch);
    const previewError = new Error("preview failed");
    const applyError = new Error("apply failed");

    feedback.onPreviewStarted();
    feedback.onPreviewed(preview);
    feedback.onPreviewError(previewError);
    feedback.onApplyStarted();
    feedback.onApplied(result);
    feedback.onApplyError(applyError);

    expect(dispatch.mock.calls).toEqual([
      [{ type: "preview-started" }],
      [{ type: "previewed", preview }],
      [{ type: "preview-failed", error: previewError }],
      [{ type: "apply-started" }],
      [{ type: "applied", result }],
      [{ type: "apply-failed", error: applyError }],
    ]);
  });

  it("clears a file input after dispatching the selected files", () => {
    const cache = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });
    let flow!: ReturnType<typeof useReviewImageAnswerFlow>;
    const request = vi.fn() as unknown as ReviewImageAnswerApiRequest;
    function Probe() {
      flow = useReviewImageAnswerFlow(request);
      return null;
    }
    renderToStaticMarkup(
      createElement(QueryClientProvider, { client: cache }, createElement(Probe)),
    );
    const input = {
      target: { files: [image("first.png")], value: "selected" },
    };

    flow.handleImageFileChange(
      input as unknown as Parameters<typeof flow.handleImageFileChange>[0],
    );

    expect(input.target.value).toBe("");
    cache.clear();
  });
});
