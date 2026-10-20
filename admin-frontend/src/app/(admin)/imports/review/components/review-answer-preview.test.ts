import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ImportQuestionItem } from "@/lib/api/types";
import type { EditState } from "../review-edit-state";
import { isMeaningfulText } from "../review-display-text";
import { ReviewAnswerPreview } from "./review-answer-preview";

function render(
  item: Partial<Pick<ImportQuestionItem, "answer_status" | "answer_confidence" | "answer_source" | "ai_answer_flag">> = {},
  draft: Partial<Pick<EditState, "answer" | "analysis" | "question_type" | "multiBlank">> = {},
) {
  return renderToStaticMarkup(createElement(ReviewAnswerPreview, {
    item: { ai_answer_flag: false, ...item },
    draft: { answer: "A", analysis: "", question_type: "single_choice", ...draft },
  }));
}

describe("review answer preview", () => {
  it("preserves status priority over the AI flag and missing-answer precedence", () => {
    for (const [status, label] of [
      ["missing", "需人工确认"], ["ai_filled", "AI 补全"], ["manual_filled", "人工填写"],
      ["manual_verified", "人工已核验"], ["abnormal", "答案异常"],
    ]) {
      const html = render({ answer_status: status, ai_answer_flag: true });
      expect(html).toContain(label);
      if (status !== "ai_filled") expect(html).not.toContain("AI 补全");
      expect(render({ answer_status: status }, { answer: "" })).toContain("需人工确认");
    }
    expect(render({ answer_status: "imported" }, { answer: "" })).not.toContain("需人工确认");
    expect(render({ answer_status: "other", ai_answer_flag: true })).toContain("AI 补全");
    expect(render({ answer_status: "other" })).not.toContain("AI 补全");
  });

  it("retains zero confidence and rounds percentages only in the ai-filled status", () => {
    expect(render({ answer_status: "ai_filled", answer_confidence: 0 })).toContain("(0%)");
    expect(render({ answer_status: "ai_filled", answer_confidence: 0.946 })).toContain("(95%)");
    expect(render({ answer_status: "ai_filled", answer_confidence: null })).not.toContain("%)");
    expect(render({ ai_answer_flag: true, answer_confidence: 0.946 })).not.toContain("%)");
  });

  it("preserves source filtering and labels without changing case or whitespace", () => {
    for (const source of ["unknown", " unknown ", "UNKNOWN", "uNkNoWn", "", "未知", "-", "—", "null", "undefined"]) {
      expect(render({ answer_source: source })).not.toContain("来源：");
    }
    for (const [source, label] of [
      ["ai", "AI 补全"], ["ocr", "OCR 识别"], ["parser", "解析器提取"], ["manual", "人工填写"],
      [" OCR ", " OCR "], ["custom", "custom"],
    ]) {
      expect(render({ answer_source: source })).toContain(`来源：${label}`);
    }
  });

  it("keeps grouped answers authoritative only for valid multi-blank groups", () => {
    const multiBlank: NonNullable<EditState["multiBlank"]> = {
      groups: [{ id: "1", options: [] }, { id: "2", options: [] }],
      answerMap: { "1": "B", "2": "C" }, usesSharedOptions: false, sharedOptions: [],
    };
    const grouped = render({}, { question_type: "multi_blank_choice", multiBlank });
    expect(grouped).not.toContain('class="answer-box"');
    expect(grouped).toContain("B");
    expect(grouped).toContain("C");
    expect(render({}, { question_type: "single_choice", multiBlank })).toContain('class="answer-box">A');
    expect(render({}, { question_type: "multi_blank_choice", multiBlank: { ...multiBlank, groups: [] } }))
      .toContain('class="answer-box">A');
    expect(render({}, { answer: "" })).toContain('class="answer-box">—');
  });

  it("retains empty analysis and routes nonempty formulas to the existing renderer", () => {
    expect(render()).toContain("（无解析）");
    const html = render({}, { analysis: "analysis <unsafe> $x^2$" });
    expect(html).not.toContain("（无解析）");
    expect(html).toContain("&lt;unsafe&gt;");
    expect(html).toContain("katex");
  });

  it("keeps the original meaningful-text filter shared with source locators", () => {
    for (const value of [null, undefined, "", "  ", "Unknown", "null", "—"]) {
      expect(isMeaningfulText(value)).toBe(false);
    }
    for (const value of [0, false, "CUSTOM", "NULL", "uNkNoWn"]) {
      expect(isMeaningfulText(value)).toBe(true);
    }
  });
});
