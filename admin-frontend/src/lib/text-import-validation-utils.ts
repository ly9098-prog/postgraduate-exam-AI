/**
 * Pure helpers for text-import page edit validation, extracted from
 * text-import/page.tsx editStructureIssues. These are detached from React
 * state so they can be tested independently.
 */

export type EditFormLike = {
  stem: string;
  options: Array<{ key: string; text: string }>;
  answer: string | string[] | boolean | null | undefined;
  question_type: string | null;
  analysis?: string | null;
};

/**
 * Validate the edit form's structural requirements.
 * Returns a list of human-readable issue messages (empty when valid).
 */
export function validateEditStructure(form: EditFormLike): string[] {
  const issues: string[] = [];
  if (!form.stem.trim()) issues.push("题干不能为空");
  const answerEmpty =
    form.answer === null ||
    form.answer === undefined ||
    form.answer === "" ||
    (Array.isArray(form.answer) && form.answer.length === 0);
  if (answerEmpty) issues.push("答案不能为空");
  if (form.question_type === "single_choice" || form.question_type === "multiple_choice") {
    const optionKeys = new Set(form.options.map((option) => option.key.toUpperCase()));
    const missing = ["A", "B", "C", "D"].filter((key) => !optionKeys.has(key));
    if (missing.length > 0) issues.push(`选择题缺少 ${missing.join(" / ")} 选项`);
  }
  return issues;
}

/**
 * Build the joined text for LaTeX inspection from an edit form.
 * Combines stem, option texts, answer, and analysis.
 */
export function buildEditFormLatexText(form: EditFormLike): string {
  return [
    form.stem,
    ...form.options.map((option) => option.text),
    typeof form.answer === "string" ? form.answer : "",
    form.analysis ?? "",
  ].filter(Boolean).join("\n");
}
