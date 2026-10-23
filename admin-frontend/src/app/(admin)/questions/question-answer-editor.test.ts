import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { QuestionEditRequest } from "@/lib/api/types";
import { QuestionAnswerEditor } from "./question-answer-editor";

function renderEditor(form: QuestionEditRequest) {
  return renderToStaticMarkup(createElement(QuestionAnswerEditor, {
    editForm: form,
    setEditForm: () => {},
  }));
}

describe("QuestionAnswerEditor", () => {
  it("keeps the answer editor as a page feature component", () => {
    expect(typeof QuestionAnswerEditor).toBe("function");
  });

  it("renders each multi-blank slot as a grouped answer control", () => {
    const html = renderEditor({
      question_type: "multi_blank_multiple_choice",
      answer: "①:A,C;②:B",
      content: {
        blank_option_groups: [
          { id: "①", options: [{ key: "A", text: "first" }, { key: "C", text: "third" }] },
          { id: "②", options: [{ key: "B", text: "second" }] },
        ],
      },
    });

    expect(html).toContain("① 答案");
    expect(html).toContain("② 答案");
    expect((html.match(/aria-pressed="true"/g) ?? []).length).toBe(3);
    expect(html).toContain("点击选项可快速多选或取消");
  });

  it("renders regular options with multi-choice answer switching", () => {
    const html = renderEditor({
      question_type: "multiple_choice",
      answer: "A,B",
      options: { A: "first", B: "second" },
    });

    expect(html).toContain("快速选择");
    expect(html).toContain("答案内容");
    expect(html).toContain("多选：单击切换各选项，以逗号分隔");
    expect(html).toContain("border-slate-900 bg-slate-900 text-white");
  });

  it("renders a plain answer input when no options exist", () => {
    const html = renderEditor({
      question_type: "short_answer",
      answer: "bounded answer",
    });

    expect(html).toContain('value="bounded answer"');
    expect(html).not.toContain("快速选择");
  });
});
