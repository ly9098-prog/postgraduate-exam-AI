import { canonicalizeQuestionType } from "@/lib/question-types";

export function isReviewAnswerSelected(questionType: string, answer: string, key: string): boolean {
  return canonicalizeQuestionType(questionType) === "multiple_choice"
    ? answer.split(/[,，\s]+/).includes(key)
    : answer === key;
}

export function toggleReviewAnswer(questionType: string, answer: string, key: string): string {
  if (canonicalizeQuestionType(questionType) !== "multiple_choice") {
    return answer === key ? "" : key;
  }
  const keys = answer.split(/[,，\s]+/).filter(Boolean);
  const next = keys.includes(key) ? keys.filter((value) => value !== key) : [...keys, key];
  return next.join(",");
}
