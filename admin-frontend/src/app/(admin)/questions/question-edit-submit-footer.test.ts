import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { QuestionEditSubmitFooter } from "./question-edit-submit-footer";

function renderFooter(props: Partial<Parameters<typeof QuestionEditSubmitFooter>[0]> = {}) {
  const cancelEditing = vi.fn();
  const saveEditing = vi.fn();
  const html = renderToStaticMarkup(createElement(QuestionEditSubmitFooter, {
    cancelEditing,
    saveEditing,
    saving: false,
    dirty: true,
    unresolvedTableCount: 0,
    emptyCodeCount: 0,
    ...props,
  }));
  return { html, cancelEditing, saveEditing };
}

describe("QuestionEditSubmitFooter", () => {
  it("keeps the sticky save footer and existing pending label", () => {
    const footer = renderFooter();

    expect(footer.html).toContain("sticky bottom-0");
    expect(footer.html).toContain("保存修改");
  });

  it("keeps save disabled while clean, pending, or blocked by editor warnings", () => {
    expect(renderFooter({ dirty: false }).html).toContain("disabled=\"\"");
    expect(renderFooter({ saving: true }).html).toContain("保存中...");
    expect(renderFooter({ unresolvedTableCount: 1 }).html).toContain("disabled=\"\"");
    expect(renderFooter({ emptyCodeCount: 1 }).html).toContain("disabled=\"\"");
  });
});
