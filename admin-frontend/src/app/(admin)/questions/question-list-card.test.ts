import { createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AdminQuestion } from "@/lib/api/types";
import { CustomCheckbox } from "./components/question-custom-checkbox";
import { MathFormula } from "@/components/ui/math-formula";
import { QuestionListCard } from "./question-list-card";
import { QuestionListFeedback } from "./question-list-feedback";
import { QuestionListPagination } from "./question-list-pagination";
import { QuestionListToolbar } from "./question-list-toolbar";
import { DEFAULT_QUESTION_FILTERS, type QuestionListFilters } from "./question-list-state";

type Element = ReactElement<Record<string, unknown>>;
type PureComponent = (props: Record<string, unknown>) => ReactNode;
const hookComponents = new Set<unknown>([CustomCheckbox, MathFormula, QuestionListToolbar, QuestionListFeedback, QuestionListPagination]);

function elements(node: ReactNode): Element[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement<Record<string, unknown>>(node)) return [];
  if (typeof node.type === "function" && !hookComponents.has(node.type)) {
    return elements((node.type as PureComponent)(node.props));
  }
  return [node, ...elements(node.props.children as ReactNode)];
}

const question: AdminQuestion = {
  id: 7,
  question_type: "single_choice",
  content: { stem: "question stem" },
  options: { A: "yes" },
  answer: "A",
  difficulty: 4,
  review_status: "approved",
  is_active: true,
  subject_name: "操作系统",
  year: 2026,
  updated_at: "2026-10-24T08:00:00",
};

function renderCard(overrides: Partial<Parameters<typeof QuestionListCard>[0]> = {}) {
  const callbacks = {
    onToggleAll: vi.fn(),
    onToggleOne: vi.fn(),
    onSelectQuestion: vi.fn(),
    onOpenDetail: vi.fn(),
    onPrefetchDetail: vi.fn(),
    onToggleExportMenu: vi.fn(),
    onExport: vi.fn(),
    onResetFilters: vi.fn(),
    onRetry: vi.fn(),
    onPageSizeChange: vi.fn(),
    onSetPage: vi.fn(),
  };
  const props = {
    items: [question],
    total: 1,
    page: 1,
    totalPages: 1,
    pageSize: 20,
    isLoading: false,
    isFetching: false,
    isError: false,
    hasActiveFilters: false,
    selectedQuestionId: 7,
    selectedIds: new Set([7]),
    allChecked: true,
    filters: { ...DEFAULT_QUESTION_FILTERS } as QuestionListFilters,
    exportOpen: false,
    exportingFormat: null,
    exportMenuRef: { current: null },
    ...callbacks,
    ...overrides,
  };
  const element = createElement(QuestionListCard, props);
  return { html: renderToStaticMarkup(element), nodes: elements(element), callbacks, props };
}

describe("QuestionListCard", () => {
  it("renders the existing list item metadata and selected state", () => {
    const card = renderCard();

    expect(card.html).toContain("#0007");
    expect(card.html).toContain("question stem");
    expect(card.html).toContain("已启用");
    expect(card.html).toContain("操作系统");
    expect(card.html).toContain("2026 年");
    expect(card.html).toContain("更新于 2026-10-24 08:00");
    expect(card.html).toContain("详情");
  });

  it("composes the existing toolbar, feedback, and pagination sections", () => {
    const card = renderCard({ totalPages: 2, total: 2 });
    const types = card.nodes.map((node) => node.type);

    expect(types).toContain(QuestionListToolbar);
    expect(types).toContain(QuestionListFeedback);
    expect(types).toContain(QuestionListPagination);
  });

  it("renders the existing loading skeleton instead of items during initial load", () => {
    const card = renderCard({ isLoading: true, items: [] });

    expect(card.html).toContain("animate-pulse");
    expect(card.html).not.toContain("#0007");
  });
});
