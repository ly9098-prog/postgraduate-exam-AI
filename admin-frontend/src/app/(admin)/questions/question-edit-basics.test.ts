import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { QuestionEditRequest } from "@/lib/api/types";
import { QuestionEditBasics } from "./question-edit-basics";

function renderBasics(form: QuestionEditRequest) {
  return renderToStaticMarkup(createElement(QuestionEditBasics, {
    editForm: form,
    setEditForm: () => {},
    subjectOptions: [
      { id: 1, code: "math", name: "数学" },
      { id: 2, code: "os", name: "操作系统" },
    ],
  }));
}

describe("QuestionEditBasics", () => {
  it("renders the selected subject, canonical type, and difficulty", () => {
    const html = renderBasics({
      subject_id: 2,
      question_type: "multiple_choice",
      difficulty: 4,
    });

    expect(html).toContain("操作系统");
    expect(html).toContain("较难");
    expect(html).toContain("多选题");
  });

  it("renders a legacy unknown type as a disabled option", () => {
    const html = renderBasics({
      subject_id: null,
      question_type: "legacy_type",
      difficulty: 3,
    });

    expect(html).toContain("历史未知题型(legacy_type)");
    expect(html).not.toContain("历史未知题型()");
  });
});
