import type { ImportQuestionItem } from "@/lib/api/types";
import { buildMultiBlankSavePayload } from "./components/multi-blank-choice-utils";
import { isMultiBlankChoice, type EditState } from "./review-edit-state";

export type ReviewSaveApiRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

export type ReviewSaveRequestInput = {
  previewId: number | null;
  editState: EditState | null;
  previewItem: ImportQuestionItem | null;
  editedSegments: Array<Record<string, unknown>> | null;
  visualBlockReasons: string[] | null;
  request: ReviewSaveApiRequest;
};

function visualBlockError(reasons: string[]): Error {
  return new Error(`无法保存：${reasons.join("；")}。请先完成视觉内容和表格结构核验。`);
}

function optionPayload(options: EditState["options"]) {
  return options.map((option) => {
    const entry: Record<string, unknown> = { key: option.key, text: option.text };
    if (option.segments && option.segments.length > 0) entry.segments = option.segments;
    return entry;
  });
}

function multiBlankPayload(
  editState: EditState,
  previewItem: ImportQuestionItem | null,
  segments: Array<Record<string, unknown>> | null,
): Record<string, unknown> {
  const multiBlank = editState.multiBlank!;
  const result = buildMultiBlankSavePayload(
    previewItem as unknown as Record<string, unknown>,
    multiBlank.groups,
    multiBlank.answerMap,
    editState.stem,
    editState.question_type,
  );
  if (result.errors.length > 0) {
    throw new Error(`保存校验失败：${result.errors.join("；")}`);
  }
  const payload = result.payload!;
  payload.subject_id = editState.subject_id;
  payload.analysis = editState.analysis || "";
  if (segments !== null && Boolean(previewItem?.parsed_content)) {
    const content = payload.parsed_content as Record<string, unknown>;
    content.segments = segments;
  }
  return payload;
}

export function buildReviewSavePayload(
  editState: EditState,
  previewItem: ImportQuestionItem | null,
  editedSegments: Array<Record<string, unknown>> | null,
): Record<string, unknown> {
  const { options, multiBlank, ...rest } = editState;
  if (isMultiBlankChoice(editState.question_type) && multiBlank) {
    return multiBlankPayload(editState, previewItem, editedSegments);
  }
  const hasSegmentEdits = editedSegments !== null && Boolean(previewItem?.parsed_content);
  const payload: Record<string, unknown> = hasSegmentEdits
    ? {
        subject_id: rest.subject_id,
        question_type: rest.question_type,
        stem: rest.stem,
        answer: rest.answer,
        analysis: rest.analysis,
        parsed_content: {
          ...previewItem!.parsed_content,
          stem: rest.stem,
          text: rest.stem,
          render_mode: "segments",
          segments: editedSegments,
        },
      }
    : { ...rest, subject_id: rest.subject_id };
  payload.options = optionPayload(options);
  return payload;
}

export async function executeReviewSaveRequest({
  previewId,
  editState,
  previewItem,
  editedSegments,
  visualBlockReasons,
  request,
}: ReviewSaveRequestInput): Promise<ImportQuestionItem> {
  if (!previewId || !editState) throw new Error("请选择要编辑的题目");
  if (visualBlockReasons) throw visualBlockError(visualBlockReasons);
  const payload = buildReviewSavePayload(editState, previewItem, editedSegments);
  return request<ImportQuestionItem>(`/imports/questions/${previewId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
