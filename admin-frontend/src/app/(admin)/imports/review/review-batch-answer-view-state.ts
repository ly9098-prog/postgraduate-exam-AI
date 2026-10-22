import type {
  BatchAnswerApplyResponse,
  BatchAnswerImageApplyResponse,
  BatchAnswerImagePreviewResponse,
  BatchAnswerPreviewResponse,
} from "@/lib/api/types";

export type BatchAnswerFillTab = "text" | "image";

export type BatchAnswerViewState = {
  summary: string | null;
  showTabs: boolean;
  showTextInput: boolean;
  showTextPreview: boolean;
  showTextResult: boolean;
  showImageContent: boolean;
  showImageInput: boolean;
  showImagePreview: boolean;
  showImageResult: boolean;
};

export function buildBatchAnswerViewState({
  tab,
  textPreview,
  textResult,
  imagePreview,
  imageResult,
}: {
  tab: BatchAnswerFillTab;
  textPreview: BatchAnswerPreviewResponse | null;
  textResult: BatchAnswerApplyResponse | null;
  imagePreview: BatchAnswerImagePreviewResponse | null;
  imageResult: BatchAnswerImageApplyResponse | null;
}): BatchAnswerViewState {
  const textActive = tab === "text";
  return {
    summary: textResult
      ? `· 已更新 ${textResult.updated_count} 题`
      : textPreview
        ? `· 预览 ${textPreview.summary.writable_count} 题可写入`
        : imageResult
          ? `· 已更新答案 ${imageResult.updated_answer_count} 解析 ${imageResult.updated_analysis_count}`
          : imagePreview
            ? `· 匹配 ${imagePreview.summary.matched_count} 题`
            : null,
    showTabs: !textResult && !imageResult,
    showTextInput: textActive && !textPreview && !textResult,
    showTextPreview: textActive && Boolean(textPreview) && !textResult,
    showTextResult: textActive && Boolean(textResult),
    showImageContent: !textActive,
    showImageInput: !textActive && !imagePreview && !imageResult,
    showImagePreview: !textActive && Boolean(imagePreview) && !imageResult,
    showImageResult: !textActive && Boolean(imageResult),
  };
}

export function batchAnswerLoadingLabel({
  mode,
  hasPreview,
}: {
  mode: BatchAnswerFillTab;
  hasPreview: boolean;
}): string {
  if (mode === "text") return hasPreview ? "正在写入答案…" : "正在解析答案…";
  return hasPreview ? "正在写入答案…" : "正在识别图片…";
}
