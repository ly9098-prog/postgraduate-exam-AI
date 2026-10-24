import { createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AdminQuestion, QuestionEditRequest } from "@/lib/api/types";
import { QuestionDrawerBody } from "./question-drawer-body";
import { QuestionDrawerEditForm } from "./question-drawer-edit-form";
import { QuestionDetailView } from "./question-detail-view";
import { QuestionSecondaryInfo } from "./components/question-secondary-info";
import { QuestionVersionHistorySection } from "./question-version-history-section";

type Element = ReactElement<Record<string, unknown>>;
type PureComponent = (props: Record<string, unknown>) => ReactNode;
const hookComponents = new Set<unknown>([
  QuestionDrawerEditForm,
  QuestionDetailView,
  QuestionVersionHistorySection,
  QuestionSecondaryInfo,
]);

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
  analysis: "analysis",
  difficulty: 4,
  review_status: "approved",
  is_active: true,
};

const editForm: QuestionEditRequest = {
  question_type: "single_choice",
  content: { stem: "question stem" },
  answer: "A",
};

function baseProps() {
  return {
    editing: false,
    question: question as AdminQuestion | null,
    detailError: false,
    editForm,
    setEditForm: () => undefined,
    setStemText: () => undefined,
    stemText: "question stem",
    subjectOptions: [],
    segments: [],
    fallbackImageUrls: [],
    dirty: false,
    unresolvedTableCount: 0,
    emptyCodeCount: 0,
    saving: false,
    beforeDirtyMutation: async () => null,
    onMutated: () => undefined,
    cancelEditing: () => undefined,
    saveEditing: () => undefined,
    versions: { data: { total: 0, items: [] }, isFetching: false },
    history: {
      open: false,
      toggle: () => undefined,
      base: "current" as const,
      compare: null,
      setBase: () => undefined,
      setCompare: () => undefined,
      swap: () => undefined,
    },
    details: { base: undefined, compare: undefined },
    labels: {
      baseVersionLabel: "当前版本",
      compareVersionLabel: "未选择",
      versionComparisonLoading: false,
      pendingVersionLabel: null,
    },
    onRetry: vi.fn(),
  };
}

function renderBody(overrides: Partial<ReturnType<typeof baseProps>> = {}) {
  const props = { ...baseProps(), ...overrides };
  const element = createElement(QuestionDrawerBody, props);
  return { html: renderToStaticMarkup(element), nodes: elements(element), props };
}

describe("QuestionDrawerBody", () => {
  it("renders detail, version history, and secondary info in view mode", () => {
    const body = renderBody();
    const types = body.nodes.map((node) => node.type);

    expect(types).toContain(QuestionDetailView);
    expect(types).toContain(QuestionVersionHistorySection);
    expect(types).toContain(QuestionSecondaryInfo);
  });

  it("renders the edit form in edit mode", () => {
    const body = renderBody({ editing: true, dirty: true });

    expect(body.nodes.map((node) => node.type)).toContain(QuestionDrawerEditForm);
  });

  it("renders detail error and loading states when the question is unavailable", () => {
    const error = renderBody({ question: null, detailError: true });
    const loading = renderBody({ question: null, detailError: false });

    expect(error.html).toContain("题目详情加载失败");
    expect(error.html).toContain("重新加载");
    expect(loading.html).toContain("animate-pulse");
  });
});
