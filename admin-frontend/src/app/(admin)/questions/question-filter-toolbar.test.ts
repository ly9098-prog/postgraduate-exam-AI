import { createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { CustomSelect } from "@/components/ui/custom-select";
import { QuestionFilterToolbar } from "./question-filter-toolbar";
import { DEFAULT_QUESTION_FILTERS, type QuestionListFilters } from "./question-list-state";

type Element = ReactElement<Record<string, unknown>>;
type PureComponent = (props: Record<string, unknown>) => ReactNode;

const hookComponents = new Set<unknown>([CustomSelect]);

function elements(node: ReactNode): Element[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement<Record<string, unknown>>(node)) return [];
  if (typeof node.type === "function" && !hookComponents.has(node.type)) {
    return elements((node.type as PureComponent)(node.props));
  }
  return [node, ...elements(node.props.children as ReactNode)];
}

function renderToolbar(overrides: Partial<Parameters<typeof QuestionFilterToolbar>[0]> = {}) {
  const props = {
    filters: { ...DEFAULT_QUESTION_FILTERS } as QuestionListFilters,
    subjectOptions: [{ id: 1, code: "os", name: "操作系统" }],
    keywordInput: "",
    importBatchInput: "",
    searchDebouncing: false,
    listFetching: false,
    hasActiveFilters: false,
    commonFilterOpen: false,
    moreFilterOpen: false,
    commonFilterRef: { current: null },
    moreFilterRef: { current: null },
    onKeywordChange: vi.fn(),
    onResetFilters: vi.fn(),
    onToggleMenu: vi.fn(),
    onApplyFilterPreset: vi.fn(),
    onApplySavedFilters: vi.fn(),
    onSaveCurrentFilters: vi.fn(),
    onFilterChange: vi.fn(),
    onImportBatchChange: vi.fn(),
    ...overrides,
  };
  const element = createElement(QuestionFilterToolbar, props);
  return { html: renderToStaticMarkup(element), nodes: elements(element), props };
}

describe("QuestionFilterToolbar", () => {
  it("renders the existing primary and detailed filter controls", () => {
    const toolbar = renderToolbar();

    expect(toolbar.html).toContain("搜索题干 / 科目 / 题目编号");
    expect(toolbar.html).toContain("常用筛选");
    expect(toolbar.html).toContain("保存筛选");
    expect(toolbar.html).toContain("科目");
    expect(toolbar.html).toContain("题型");
    expect(toolbar.html).toContain("状态");
    expect(toolbar.html).toContain("年份");
    expect(toolbar.html).toContain("难度");
    expect(toolbar.html).toContain("更多条件");
  });

  it("renders common and more-filter menus only while open", () => {
    const closed = renderToolbar();
    const open = renderToolbar({ commonFilterOpen: true, moreFilterOpen: true });

    expect(closed.html).not.toContain("全部有效题目");
    expect(closed.html).not.toContain("导入批次 ID");
    expect(open.html).toContain("全部有效题目");
    expect(open.html).toContain("导入批次 ID");
  });

  it("renders the coverage jump filter and clear action only when present", () => {
    const withoutJump = renderToolbar();
    const withJump = renderToolbar({
      filters: { ...DEFAULT_QUESTION_FILTERS, knowledge_point_id: "42" },
    });

    expect(withoutJump.html).not.toContain("覆盖率跳转筛选");
    expect(withJump.html).toContain("覆盖率跳转筛选");
    expect(withJump.html).toContain("知识点 #42");
  });
});
