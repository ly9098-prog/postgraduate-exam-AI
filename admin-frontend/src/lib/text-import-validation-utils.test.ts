import { describe, it, expect } from "vitest";
import { validateEditStructure, buildEditFormLatexText, type EditFormLike } from "./text-import-validation-utils";

const base: EditFormLike = {
  stem: "What is 2+2?",
  options: [
    { key: "A", text: "3" },
    { key: "B", text: "4" },
    { key: "C", text: "5" },
    { key: "D", text: "6" },
  ],
  answer: "4",
  question_type: "single_choice",
  analysis: "Basic arithmetic",
};

describe("validateEditStructure", () => {
  it("returns empty for valid form", () => {
    expect(validateEditStructure(base)).toEqual([]);
  });
  it("flags empty stem", () => {
    expect(validateEditStructure({ ...base, stem: "  " })).toContain("题干不能为空");
  });
  it("flags null answer", () => {
    expect(validateEditStructure({ ...base, answer: null })).toContain("答案不能为空");
  });
  it("flags empty string answer", () => {
    expect(validateEditStructure({ ...base, answer: "" })).toContain("答案不能为空");
  });
  it("flags empty array answer", () => {
    expect(validateEditStructure({ ...base, answer: [] })).toContain("答案不能为空");
  });
  it("does not flag non-choice with missing options", () => {
    expect(validateEditStructure({ ...base, question_type: "short_answer", options: [] })).not.toContain(expect.stringContaining("选择题"));
  });
  it("flags missing option A for single_choice", () => {
    const f = { ...base, options: base.options.filter((o) => o.key !== "A") };
    const issues = validateEditStructure(f);
    expect(issues.some((i) => i.includes("A"))).toBe(true);
  });
  it("flags missing options B and D", () => {
    const f = { ...base, options: [base.options[0], base.options[2]] };
    const issues = validateEditStructure(f);
    expect(issues.some((i) => i.includes("B"))).toBe(true);
    expect(issues.some((i) => i.includes("D"))).toBe(true);
  });
  it("works for multiple_choice", () => {
    expect(validateEditStructure({ ...base, question_type: "multiple_choice" })).toEqual([]);
  });
  it("accepts boolean true answer", () => {
    expect(validateEditStructure({ ...base, question_type: "true_false", answer: true })).toEqual([]);
  });
  it("flags boolean false as valid (not empty)", () => {
    expect(validateEditStructure({ ...base, question_type: "true_false", answer: false })).toEqual([]);
  });
  it("accepts array answer for multiple_choice", () => {
    expect(validateEditStructure({ ...base, question_type: "multiple_choice", answer: ["A", "B"] })).toEqual([]);
  });
  it("returns empty for null form type but no missing options", () => {
    expect(validateEditStructure({ ...base, question_type: null })).toEqual([]);
  });
});

describe("buildEditFormLatexText", () => {
  it("joins stem, options, answer, analysis", () => {
    const text = buildEditFormLatexText(base);
    expect(text).toContain("What is 2+2?");
    expect(text).toContain("3");
    expect(text).toContain("4");
    expect(text).toContain("Basic arithmetic");
  });
  it("filters out empty strings", () => {
    const text = buildEditFormLatexText({ ...base, analysis: null });
    expect(text).not.toContain("null");
  });
  it("excludes non-string answer types", () => {
    const text = buildEditFormLatexText({ ...base, answer: true });
    expect(text).toContain("What is 2+2?");
    expect(text).not.toContain("true");
  });
  it("includes string answer", () => {
    const text = buildEditFormLatexText({ ...base, answer: "AB" });
    expect(text).toContain("AB");
  });
  it("handles empty options", () => {
    const text = buildEditFormLatexText({ ...base, options: [] });
    expect(text).toContain("What is 2+2?");
  });
});
