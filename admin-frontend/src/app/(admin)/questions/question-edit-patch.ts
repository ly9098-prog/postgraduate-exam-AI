import type { AdminQuestion, QuestionEditRequest, QuestionOptionsValue } from "@/lib/api/types";
import {
  normalizeQuestionOptions, resolveBlankOptionGroupsValue, resolveQuestionOptions,
} from "@/lib/question-options";
import {
  contentRecord, nonStemContentSegments, normalizeStemForEditing,
  textForStemEditor, updateStemInContent,
} from "./question-content-editing";

function comparableOptionState(options: QuestionOptionsValue | undefined): string {
  return JSON.stringify(
    normalizeQuestionOptions(options).map((option) => ({
      key: option.key,
      text: option.text ?? "",
      imageUrl: option.imageUrl ?? "",
    })),
  );
}

function contentPatch(
  form: QuestionEditRequest,
  question: AdminQuestion,
  currentStemText?: string,
): QuestionEditRequest {
  const baselineStem = normalizeStemForEditing(textForStemEditor(question.content));
  const editorStem = currentStemText ?? textForStemEditor(form.content);
  const stemChanged = editorStem !== baselineStem;
  const structuredContentChanged =
    JSON.stringify(nonStemContentSegments(form.content)) !==
    JSON.stringify(nonStemContentSegments(question.content));
  const blankOptionGroupsChanged =
    JSON.stringify(resolveBlankOptionGroupsValue(form.content) ?? null) !==
    JSON.stringify(resolveBlankOptionGroupsValue(question.content) ?? null);
  if (!stemChanged && !structuredContentChanged && !blankOptionGroupsChanged) return {};
  return {
    content: stemChanged
      ? updateStemInContent(form.content, editorStem)
      : contentRecord(form.content),
  };
}

// Compare visible edits without persisting incidental legacy normalization.
export function buildQuestionEditPatch(
  form: QuestionEditRequest,
  question: AdminQuestion,
  currentStemText?: string,
): QuestionEditRequest {
  const patch: QuestionEditRequest = {};
  if ((form.answer ?? "") !== (question.answer ?? "")) patch.answer = form.answer ?? "";
  if ((form.analysis ?? "") !== (question.analysis ?? "")) patch.analysis = form.analysis ?? "";
  if ((form.difficulty ?? null) !== (question.difficulty ?? null) && form.difficulty !== undefined) {
    patch.difficulty = form.difficulty;
  }
  if ((form.question_type ?? "") !== (question.question_type ?? "")) {
    patch.question_type = form.question_type ?? "";
  }
  if ((form.subject_id ?? null) !== (question.subject_id ?? null)) {
    patch.subject_id = form.subject_id ?? null;
  }
  Object.assign(patch, contentPatch(form, question, currentStemText));
  if (
    comparableOptionState(form.options) !==
    comparableOptionState(resolveQuestionOptions(question) ?? undefined)
  ) {
    patch.options = form.options ?? null;
  }
  if (
    JSON.stringify(form.knowledge_points ?? null) !==
    JSON.stringify(question.knowledge_points ?? null)
  ) {
    patch.knowledge_points = form.knowledge_points ?? [];
  }
  return patch;
}
