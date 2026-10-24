import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { QuestionBatchSelectionBar } from "./question-batch-selection-bar";

function renderBar(overrides: Partial<Parameters<typeof QuestionBatchSelectionBar>[0]> = {}) {
  const onBatchDelete = vi.fn();
  const onClearSelection = vi.fn();
  const html = renderToStaticMarkup(createElement(QuestionBatchSelectionBar, {
    selectedCount: 2,
    canDelete: true,
    deleting: false,
    onBatchDelete,
    onClearSelection,
    ...overrides,
  }));
  return { html, onBatchDelete, onClearSelection };
}

describe("QuestionBatchSelectionBar", () => {
  it("renders the selected count, delete action, and clear action", () => {
    const bar = renderBar();

    expect(bar.html).toContain('已选 <strong class="text-[var(--ink)]">2</strong> 项');
    expect(bar.html).toContain("批量删除");
    expect(bar.html).toContain("清除选择");
  });

  it("keeps delete behind the existing permission and pending state", () => {
    const withoutPermission = renderBar({ canDelete: false });
    const deleting = renderBar({ deleting: true });

    expect(withoutPermission.html).not.toContain("批量删除");
    expect(deleting.html).toContain("disabled=\"\"");
  });

  it("renders nothing when no items are selected", () => {
    expect(renderBar({ selectedCount: 0 }).html).toBe("");
  });
});
