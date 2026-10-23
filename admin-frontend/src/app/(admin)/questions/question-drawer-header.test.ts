import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { QuestionDrawerHeader } from "./question-drawer-header";

function renderHeader(overrides: Partial<Parameters<typeof QuestionDrawerHeader>[0]> = {}) {
  return renderToStaticMarkup(createElement(QuestionDrawerHeader, {
    editing: false,
    dirty: false,
    questionId: 7,
    canWrite: true,
    canDelete: true,
    copyButton: createElement("button", { type: "button", "aria-label": "复制题干和选项" }),
    onBackToDetail: () => undefined,
    onEdit: () => undefined,
    onDelete: () => undefined,
    onClose: () => undefined,
    ...overrides,
  }));
}

describe("QuestionDrawerHeader", () => {
  it("renders detail actions and the selected question id in view mode", () => {
    const html = renderHeader();

    expect(html).toContain("题目详情");
    expect(html).toContain("#7");
    expect(html).toContain("复制题干和选项");
    expect(html).toContain("编辑");
    expect(html).toContain("删除");
  });

  it("renders the dirty-editing state and hides detail-only actions while editing", () => {
    const html = renderHeader({ editing: true, dirty: true });

    expect(html).toContain("编辑题目");
    expect(html).toContain("未保存");
    expect(html).toContain("返回题目详情");
    expect(html).not.toContain("复制题干和选项");
    expect(html).not.toContain("删除");
  });

  it("keeps edit and delete behind the existing permission flags", () => {
    const html = renderHeader({ canWrite: false, canDelete: false });

    expect(html).toContain("复制题干和选项");
    expect(html).not.toContain("编辑");
    expect(html).not.toContain("删除");
  });
});
