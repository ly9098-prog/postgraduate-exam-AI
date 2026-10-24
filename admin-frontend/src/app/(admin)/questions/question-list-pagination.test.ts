import { createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { CustomSelect } from "@/components/ui/custom-select";
import { QuestionListPagination } from "./question-list-pagination";

type Element = ReactElement<Record<string, unknown>>;
type PureComponent = (props: Record<string, unknown>) => ReactNode;

function elements(node: ReactNode): Element[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement<Record<string, unknown>>(node)) return [];
  if (typeof node.type === "function" && node.type !== CustomSelect) {
    return elements((node.type as PureComponent)(node.props));
  }
  return [node, ...elements(node.props.children as ReactNode)];
}

function renderPagination(overrides: Partial<Parameters<typeof QuestionListPagination>[0]> = {}) {
  const onPageSizeChange = vi.fn();
  const onSetPage = vi.fn();
  const element = createElement(QuestionListPagination, {
    visible: true,
    total: 42,
    page: 3,
    totalPages: 5,
    pageSize: 20,
    isFetching: false,
    onPageSizeChange,
    onSetPage,
    ...overrides,
  });
  return { html: renderToStaticMarkup(element), nodes: elements(element), onPageSizeChange, onSetPage };
}

describe("QuestionListPagination", () => {
  it("renders the existing totals, page state, and page-size selector", () => {
    const pagination = renderPagination();

    expect(pagination.html).toContain("共 <span class=\"font-semibold text-[var(--ink)]\">42</span> 条");
    expect(pagination.html).toContain("第 <span class=\"font-semibold text-[var(--ink)]\">3</span> / 5 页");
    expect(pagination.html).toContain("20 条/页");
    expect(pagination.html).toContain("上一页");
    expect(pagination.html).toContain("下一页");
  });

  it("renders the existing pagination window", () => {
    const pagination = renderPagination();
    const pages = pagination.nodes
      .filter((node) => node.type === "button")
      .map((node) => String((node.props as { children?: ReactNode }).children));

    expect(pages).toContain("1");
    expect(pages).toContain("2");
    expect(pages).toContain("3");
    expect(pages).toContain("4");
    expect(pages).toContain("5");
  });

  it("renders nothing when the existing single-page condition is met", () => {
    expect(renderPagination({ visible: false }).html).toBe("");
  });
});
