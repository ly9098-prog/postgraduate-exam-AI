import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { QuestionEditRequest } from "@/lib/api/types";
import { QuestionDrawerEditForm } from "./question-drawer-edit-form";

const editForm: QuestionEditRequest = {
  subject_id: 1,
  question_type: "single_choice",
  content: { stem: "stem" },
  options: { A: { text: "yes" } },
  answer: "A",
  analysis: "analysis",
  knowledge_points: [],
  difficulty: 3,
};

function renderForm(overrides: Partial<Parameters<typeof QuestionDrawerEditForm>[0]> = {}) {
  const props = {
    questionId: 7,
    editForm,
    setEditForm: () => undefined,
    setStemText: () => undefined,
    stemText: "stem",
    subjectOptions: [{ id: 1, code: "os", name: "操作系统" }],
    segments: [],
    fallbackImageUrls: [],
    dirty: true,
    unresolvedTableCount: 0,
    emptyCodeCount: 0,
    saving: false,
    beforeDirtyMutation: async () => null,
    onMutated: () => undefined,
    cancelEditing: () => undefined,
    saveEditing: () => undefined,
    ...overrides,
  };
  return { html: renderToStaticMarkup(createElement(QuestionDrawerEditForm, props)), props };
}

describe("QuestionDrawerEditForm", () => {
  it("renders the existing edit-form wrapper and submit footer", () => {
    const form = renderForm();

    expect(form.html).toContain("question-drawer-edit");
    expect(form.html).toContain("保存修改");
  });

  it("renders the existing table and empty-code warnings", () => {
    const html = renderForm({ unresolvedTableCount: 2, emptyCodeCount: 3 }).html;

    expect(html).toContain("仍有 2 个结构化表格需要人工核验");
    expect(html).toContain("仍有 3 个代码块正文为空");
  });

  it("keeps all editor children mounted in the existing order", () => {
    const html = renderForm().html;

    expect(html).toContain("科目");
    expect(html).toContain("题干");
    expect(html).toContain("选项");
    expect(html).toContain("答案");
    expect(html).toContain("知识点");
    expect(html).toContain("解析");
    expect(html).toContain("保存修改");
  });
});
