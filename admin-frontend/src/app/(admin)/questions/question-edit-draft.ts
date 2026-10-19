import type { AdminQuestion, QuestionEditRequest, QuestionOptionsValue } from "@/lib/api/types";
import { normalizeQuestionOptions, resolveQuestionOptions } from "@/lib/question-options";
import {
  contentRecord, normalizeStemForEditing, textForStemEditor,
} from "./question-content-editing";

function questionForm(
  question: AdminQuestion,
  content: Record<string, unknown>,
  options: QuestionOptionsValue | undefined,
): QuestionEditRequest {
  return {
    subject_id: question.subject_id ?? null,
    question_type: question.question_type || "",
    difficulty: question.difficulty,
    answer: question.answer || "",
    analysis: question.analysis || "",
    options,
    content,
    knowledge_points: question.knowledge_points ?? undefined,
  };
}

export function createQuestionEditDraft(question: AdminQuestion) {
  // Clone content before editing; legacy strings must not become numeric object keys.
  const clonedRaw = JSON.parse(JSON.stringify(question.content ?? {})) as unknown;
  const content = typeof clonedRaw === "string"
    ? { stem: clonedRaw, text: clonedRaw }
    : contentRecord(clonedRaw);
  const rawOptions = resolveQuestionOptions(question);
  let options: Record<string, unknown> | undefined;
  if (rawOptions && typeof rawOptions === "object" && !Array.isArray(rawOptions)) {
    options = rawOptions as Record<string, unknown>;
  } else if (rawOptions) {
    options = Object.fromEntries(
      normalizeQuestionOptions(rawOptions).map((option) => [
        option.key,
        option.imageUrl ? { text: option.text ?? "", url: option.imageUrl } : (option.text ?? ""),
      ]),
    );
  }
  return {
    form: questionForm(question, content, options),
    stemText: normalizeStemForEditing(textForStemEditor(content)),
  };
}

export function savedQuestionEditDraft(question: AdminQuestion) {
  // Adopt the response directly after saving, without the editor's legacy option fallback.
  return {
    form: questionForm(question, contentRecord(question.content), question.options ?? undefined),
    stemText: normalizeStemForEditing(textForStemEditor(question.content)),
  };
}
