import { createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AdminQuestion, QuestionVersion } from "@/lib/api/types";
import { QuestionVersionPicker } from "@/components/questions/question-version-picker";
import { QuestionVersionComparison } from "./components/question-version-comparison";
import { QuestionVersionHistorySection } from "./question-version-history-section";

type Element = ReactElement<Record<string, unknown>>;
type PureComponent = (props: Record<string, unknown>) => ReactNode;

// Version pickers and comparison renderers own React hooks; expand only section wrappers.
const hookComponents: Set<unknown> = new Set([QuestionVersionPicker, QuestionVersionComparison]);
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
  content: { stem: "current" },
  answer: "A",
  difficulty: 3,
  review_status: "approved",
  is_active: true,
};

const versions: QuestionVersion[] = [{
  id: 1,
  question_id: 7,
  version: 1,
  edited_by: 1,
}];

function render({
  open = true,
  total = 1,
  compare = 1 as number | null,
  fetching = false,
  detail = {
    id: 1,
    question_id: 7,
    version: 1,
    edited_by: 1,
    content: { stem: "history" },
    answer: "B",
    difficulty: 2,
    knowledge_points: [],
  },
} = {}) {
  const toggle = vi.fn();
  const setBase = vi.fn();
  const setCompare = vi.fn();
  const swap = vi.fn();
  const element = createElement(QuestionVersionHistorySection, {
    question,
    versions: { data: { total, items: total ? versions : [] }, isFetching: fetching },
    history: {
      open,
      toggle,
      base: "current" as const,
      compare,
      setBase,
      setCompare,
      swap,
    },
    details: { base: undefined, compare: detail },
    labels: {
      baseVersionLabel: "当前版本",
      compareVersionLabel: "v1",
      versionComparisonLoading: fetching,
      pendingVersionLabel: fetching ? "v1" : null,
    },
  });
  const nodes = elements(element)
    .filter((node) => node.type === QuestionVersionPicker)
    .map((node) => node);
  return { element, nodes, html: renderToStaticMarkup(element), toggle, setBase, setCompare, swap };
}

describe("QuestionVersionHistorySection", () => {
  it("shows the collapsed version count and expansion state", () => {
    const section = render({ open: false });

    expect(section.html).toContain("1 个版本");
    expect(section.html).not.toContain("基准版本");
    const root = elements(section.element).find((node) => node.type === "section") as Element;
    const button = elements(root.props.children as ReactNode)
      .find((node) => node.type === "button") as Element;
    (button.props.onClick as () => void)();
    expect(section.toggle).toHaveBeenCalledOnce();
  });

  it("renders empty state only after fetching completes with no versions", () => {
    const fetching = render({ total: 0, compare: null, fetching: true });
    const empty = render({ total: 0, compare: null });

    expect(fetching.html).toContain("基准版本");
    expect(empty.html).toContain("暂无历史版本");
  });

  it("passes current and selected historical snapshots to the comparison", () => {
    const section = render();
    const root = elements(section.element)
      .find((node) => node.type === QuestionVersionComparison) as Element;
    const props = root.props as Record<string, unknown>;

    expect(props.left).toBe(question);
    expect(props.right).toMatchObject({ content: { stem: "history" }, answer: "B" });
    expect(props.leftTitle).toBe("当前版本");
    expect(props.rightTitle).toBe("v1");
  });
});
