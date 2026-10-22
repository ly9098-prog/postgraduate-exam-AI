"use client";

import {
  useCallback,
  useReducer,
  type ChangeEvent,
  type Dispatch,
} from "react";
import type {
  BatchAnswerImageApplyResponse,
  BatchAnswerImagePreviewResponse,
} from "@/lib/api/types";
import {
  useReviewImageAnswerMutations,
  type ReviewImageAnswerApiRequest,
} from "./use-review-image-answer-mutations";

export type ImageAnswerMode = "answer_only" | "answer_analysis";

export type ReviewImageAnswerState = {
  files: File[];
  mode: ImageAnswerMode;
  preview: BatchAnswerImagePreviewResponse | null;
  result: BatchAnswerImageApplyResponse | null;
  error: string | null;
};

export type ReviewImageAnswerAction =
  | { type: "files-added"; files: File[] }
  | { type: "file-removed"; index: number }
  | { type: "mode-changed"; mode: ImageAnswerMode }
  | { type: "reset" }
  | { type: "preview-started" }
  | { type: "previewed"; preview: BatchAnswerImagePreviewResponse }
  | { type: "preview-failed"; error: unknown }
  | { type: "apply-started" }
  | { type: "applied"; result: BatchAnswerImageApplyResponse }
  | { type: "apply-failed"; error: unknown };

export function createReviewImageAnswerState(): ReviewImageAnswerState {
  return {
    files: [],
    mode: "answer_only",
    preview: null,
    result: null,
    error: null,
  };
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function withoutOutputs(state: ReviewImageAnswerState) {
  return { ...state, preview: null, result: null, error: null };
}

function withoutError(state: ReviewImageAnswerState) {
  return { ...state, error: null };
}

export function reduceReviewImageAnswerState(
  state: ReviewImageAnswerState,
  action: ReviewImageAnswerAction,
): ReviewImageAnswerState {
  switch (action.type) {
    case "files-added":
      return { ...withoutOutputs(state), files: [...state.files, ...action.files] };
    case "file-removed":
      return {
        ...withoutOutputs(state),
        files: state.files.filter((_, index) => index !== action.index),
      };
    case "mode-changed":
      return { ...state, mode: action.mode };
    case "reset":
      return { ...withoutOutputs(state), files: [] };
    case "preview-started":
      return withoutOutputs(state);
    case "previewed":
      return { ...state, preview: action.preview };
    case "preview-failed":
      return { ...state, error: errorMessage(action.error, "预览生成失败") };
    case "apply-started":
      return withoutError(state);
    case "applied":
      return { ...state, result: action.result };
    case "apply-failed":
      return { ...state, error: errorMessage(action.error, "写入失败") };
  }
}

export function buildImageAnswerPreviewInput(
  batchId: string,
  files: File[],
  mode: ImageAnswerMode,
) {
  if (!batchId || files.length === 0) return null;
  return { batchId, files, mode };
}

export function buildImageAnswerApplyInput(
  batchId: string,
  preview: BatchAnswerImagePreviewResponse | null,
) {
  if (!batchId || !preview?.preview_token) return null;
  return {
    batchId,
    previewToken: preview.preview_token,
    operationId: preview.operation_id || "",
  };
}

export function buildImageAnswerMutationFeedback(
  dispatch: Dispatch<ReviewImageAnswerAction>,
) {
  return {
    onPreviewStarted: () => dispatch({ type: "preview-started" }),
    onPreviewed: (preview: BatchAnswerImagePreviewResponse) =>
      dispatch({ type: "previewed", preview }),
    onPreviewError: (error: unknown) =>
      dispatch({ type: "preview-failed", error }),
    onApplyStarted: () => dispatch({ type: "apply-started" }),
    onApplied: (result: BatchAnswerImageApplyResponse) =>
      dispatch({ type: "applied", result }),
    onApplyError: (error: unknown) =>
      dispatch({ type: "apply-failed", error }),
  };
}

type ImageAnswerSources = {
  state: ReviewImageAnswerState;
  dispatch: Dispatch<ReviewImageAnswerAction>;
  preview: (input: {
    batchId: string;
    files: File[];
    mode: ImageAnswerMode;
  }) => void;
  apply: (input: {
    batchId: string;
    previewToken: string;
    operationId: string;
  }) => void;
};

function useImageAnswerCommands({
  state,
  dispatch,
  preview,
  apply,
}: ImageAnswerSources) {
  const previewFiles = useCallback((batchId: string) => {
    const input = buildImageAnswerPreviewInput(
      batchId,
      state.files,
      state.mode,
    );
    if (input) preview(input);
  }, [preview, state.files, state.mode]);
  const applyPreview = useCallback((batchId: string) => {
    const input = buildImageAnswerApplyInput(
      batchId,
      state.preview,
    );
    if (input) apply(input);
  }, [apply, state.preview]);
  const removeFile = useCallback(
    (index: number) => dispatch({ type: "file-removed", index }),
    [dispatch],
  );
  const addFiles = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    dispatch({
      type: "files-added",
      files: Array.from(event.target.files || []),
    });
    event.target.value = "";
  }, [dispatch]);
  const reset = useCallback(
    () => dispatch({ type: "reset" }),
    [dispatch],
  );
  const setMode = useCallback(
    (mode: ImageAnswerMode) =>
      dispatch({ type: "mode-changed", mode }),
    [dispatch],
  );
  return {
    handleImagePreview: previewFiles,
    handleImageApply: applyPreview,
    handleImageFileChange: addFiles,
    removeImageFile: removeFile,
    handleImageReset: reset,
    setImageImportMode: setMode,
  };
}

export function useReviewImageAnswerFlow(request: ReviewImageAnswerApiRequest) {
  const [state, dispatch] = useReducer(
    reduceReviewImageAnswerState,
    undefined,
    createReviewImageAnswerState,
  );
  const { preview, apply } = useReviewImageAnswerMutations(
    request,
    buildImageAnswerMutationFeedback(dispatch),
  );
  const handlers = useImageAnswerCommands({
    state,
    dispatch,
    preview: preview.mutate,
    apply: apply.mutate,
  });

  return {
    ...state,
    imageFiles: state.files,
    imageImportMode: state.mode,
    imagePreviewResult: state.preview,
    imageApplyResult: state.result,
    imageError: state.error,
    imageExecuting: preview.isPending || apply.isPending,
    ...handlers,
  };
}
