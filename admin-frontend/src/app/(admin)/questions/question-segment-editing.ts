import type { QuestionEditRequest } from "@/lib/api/types";
import {
  canonicalStemAfterSegmentUpdate, contentRecord, contentSegments,
  isCodeSegment, isStemTextSegment, type ContentSegment,
} from "./question-content-editing";

export function replaceQuestionSegments(
  form: QuestionEditRequest,
  segments: ContentSegment[],
): QuestionEditRequest {
  const content = contentRecord(form.content);
  const stem = canonicalStemAfterSegmentUpdate(content, segments);
  return {
    ...form,
    content: { ...content, stem, text: stem, render_mode: "segments", segments },
  };
}

export function addQuestionCodeSegment(form: QuestionEditRequest): QuestionEditRequest {
  const segments = contentSegments(form.content);
  // Append after the last code block, or before non-stem material when no code exists.
  let insertAt = segments.reduce(
    (lastCodeIndex, segment, index) => isCodeSegment(segment) ? index + 1 : lastCodeIndex,
    -1,
  );
  if (insertAt < 0) {
    insertAt = segments.findIndex((segment) => !isStemTextSegment(segment));
    if (insertAt < 0) insertAt = segments.length;
  }
  const next = [...segments];
  next.splice(insertAt, 0, { type: "code", code: "", language: "" });
  return replaceQuestionSegments(form, next);
}

export function updateCodeSegmentField(
  segment: ContentSegment,
  field: "caption" | "language" | "code",
  value: string,
): ContentSegment {
  const next = { ...segment };
  if (field === "code") {
    next.code = value;
    // Keep code authoritative when old content also has a duplicate text field.
    if (Object.prototype.hasOwnProperty.call(next, "text")) delete next.text;
  } else if (value) {
    next[field] = value;
  } else {
    delete next[field];
  }
  return next;
}
