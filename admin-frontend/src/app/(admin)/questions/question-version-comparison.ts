import type { AdminQuestion } from "@/lib/api/types";
import { resolveBlankOptionGroupsValue } from "@/lib/question-options";
import { canonicalizeQuestionType } from "@/lib/question-types";

export type QuestionSnapshot = Pick<
  AdminQuestion, "content" | "options" | "answer" | "analysis" | "difficulty" | "knowledge_points"
>;

export function versionValueText(value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value, null, 2);
}

export function questionVersionFields(
  questionType: string,
  left: QuestionSnapshot,
  right: QuestionSnapshot,
) {
  // The current question's type selects both sides, including historical content.
  const type = canonicalizeQuestionType(questionType);
  const multiBlank = type === "multi_blank_choice" || type === "multi_blank_multiple_choice";
  const options = (snapshot: QuestionSnapshot) => multiBlank
    ? resolveBlankOptionGroupsValue(snapshot.content)
    : (snapshot.options ?? null);
  return [
    { label: "题干", leftValue: left.content, rightValue: right.content },
    { label: "选项", leftValue: options(left), rightValue: options(right) },
    { label: "答案", leftValue: left.answer, rightValue: right.answer },
    { label: "解析", leftValue: left.analysis ?? null, rightValue: right.analysis ?? null },
    { label: "难度", leftValue: left.difficulty, rightValue: right.difficulty },
    {
      label: "知识点",
      leftValue: left.knowledge_points ?? null,
      rightValue: right.knowledge_points ?? null,
    },
  ];
}
