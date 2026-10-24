import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { QuestionListToolbar } from "./question-list-toolbar";

function renderToolbar(overrides: Partial<Parameters<typeof QuestionListToolbar>[0]> = {}) {
  const onToggleAll = vi.fn();
  const onToggleExportMenu = vi.fn();
  const onExport = vi.fn();
  const html = renderToStaticMarkup(createElement(QuestionListToolbar, {
    itemCount: 3,
    total: 12,
    isFetching: false,
    isLoading: false,
    hasActiveFilters: false,
    selectedCount: 0,
    allChecked: false,
    exportOpen: false,
    exportingFormat: null,
    exportMenuRef: { current: null },
    onToggleAll,
    onToggleExportMenu,
    onExport,
    ...overrides,
  }));
  return { html, onToggleAll, onToggleExportMenu, onExport };
}

describe("QuestionListToolbar", () => {
  it("renders the current-page, total, and selection summary", () => {
    const toolbar = renderToolbar({ selectedCount: 2 });

    expect(toolbar.html).toContain("当前页 3 题");
    expect(toolbar.html).toContain("共 12 题");
    expect(toolbar.html).toContain("已选 2 项");
    expect(toolbar.html).toContain("选择当前页");
  });

  it("renders updating and active-filter badges only in their existing states", () => {
    const idle = renderToolbar();
    const updating = renderToolbar({ isFetching: true, isLoading: false, hasActiveFilters: true });

    expect(idle.html).not.toContain("更新中");
    expect(idle.html).not.toContain("已启用筛选");
    expect(updating.html).toContain("更新中");
    expect(updating.html).toContain("已启用筛选");
  });

  it("renders export menu and pending labels only in their existing states", () => {
    const closed = renderToolbar();
    const open = renderToolbar({ exportOpen: true });
    const exportingCsv = renderToolbar({ exportingFormat: "csv" });
    const exportingWord = renderToolbar({ exportingFormat: "docx" });

    expect(closed.html).not.toContain("导出 CSV");
    expect(open.html).toContain("导出 CSV");
    expect(open.html).toContain("导出 Word");
    expect(exportingCsv.html).toContain("导出 CSV 中...");
    expect(exportingWord.html).toContain("导出 Word 中...");
  });
});
