import { describe, expect, it } from "vitest";
import {
  batchAnswerLoadingLabel,
  buildBatchAnswerViewState,
  type BatchAnswerFillTab,
} from "./review-batch-answer-view-state";
import type {
  BatchAnswerApplyResponse,
  BatchAnswerImageApplyResponse,
  BatchAnswerImagePreviewResponse,
  BatchAnswerPreviewResponse,
} from "@/lib/api/types";

const textPreview = {
  summary: { writable_count: 7 },
} as BatchAnswerPreviewResponse;
const imagePreview = {
  summary: { matched_count: 9 },
} as BatchAnswerImagePreviewResponse;
const textResult = {
  updated_count: 3,
} as BatchAnswerApplyResponse;
const imageResult = {
  updated_answer_count: 4,
  updated_analysis_count: 5,
} as BatchAnswerImageApplyResponse;

describe("review batch answer view state", () => {
  it.each<[
    BatchAnswerFillTab,
    typeof textPreview | null,
    typeof textResult | null,
    typeof imagePreview | null,
    typeof imageResult | null,
  ]>([
    ["text", null, null, null, null],
    ["text", textPreview, null, null, null],
    ["text", null, textResult, null, null],
    ["text", textPreview, textResult, imagePreview, imageResult],
    ["image", null, null, null, null],
    ["image", null, null, imagePreview, null],
    ["image", null, null, null, imageResult],
    ["image", textPreview, textResult, imagePreview, imageResult],
  ])("preserves result priority and tab visibility for %j", (tab, text, applied, image, imageApplied) => {
    const state = buildBatchAnswerViewState({
      tab,
      textPreview: text,
      textResult: applied,
      imagePreview: image,
      imageResult: imageApplied,
    });
    const expectedSummary = applied
      ? `· 已更新 ${applied.updated_count} 题`
      : text
        ? `· 预览 ${text.summary.writable_count} 题可写入`
        : imageApplied
          ? `· 已更新答案 ${imageApplied.updated_answer_count} 解析 ${imageApplied.updated_analysis_count}`
          : image
            ? `· 匹配 ${image.summary.matched_count} 题`
            : null;
    expect(state.summary).toBe(expectedSummary);
    expect(state.showTabs).toBe(!applied && !imageApplied);
    expect(state.showTextInput).toBe(tab === "text" && !text && !applied);
    expect(state.showTextPreview).toBe(tab === "text" && Boolean(text) && !applied);
    expect(state.showTextResult).toBe(tab === "text" && Boolean(applied));
    expect(state.showImageContent).toBe(tab === "image");
    expect(state.showImageInput).toBe(tab === "image" && !image && !imageApplied);
    expect(state.showImagePreview).toBe(tab === "image" && Boolean(image) && !imageApplied);
    expect(state.showImageResult).toBe(tab === "image" && Boolean(imageApplied));
  });

  it.each([
    ["text", true, "正在写入答案…"],
    ["text", false, "正在解析答案…"],
    ["image", true, "正在写入答案…"],
    ["image", false, "正在识别图片…"],
  ] as const)("keeps the %s loading label for preview=%s", (mode, hasPreview, expected) => {
    expect(batchAnswerLoadingLabel({ mode, hasPreview })).toBe(expected);
  });
});
