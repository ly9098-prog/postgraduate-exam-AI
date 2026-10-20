import { Children, createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ReviewAnswerEditor } from "./review-answer-editor";

function props(questionType = "single_choice") {
  return {
    questionType, options: [{ key: "A" }, { key: "B" }], answer: "A", analysis: "old analysis",
    onAnswerChange: vi.fn(), onAnalysisChange: vi.fn(),
  };
}

// Expand these stateless components to exercise the actual native control callbacks.
function controls(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  return Children.toArray(node).flatMap((child) => {
    if (!isValidElement<Record<string, unknown>>(child)) return [];
    if (typeof child.type === "function") {
      return controls((child.type as (props: unknown) => ReactNode)(child.props));
    }
    const children = controls(child.props.children as ReactNode);
    return typeof child.type === "string" ? [child, ...children] : children;
  });
}

function clickOption(view: ReactNode, key: string) {
  const control = controls(view).find((element) => element.type === "button" && element.props.children === key);
  if (!control || typeof control.props.onClick !== "function") throw new Error("Option button missing");
  control.props.onClick();
}

describe("review answer editor", () => {
  it("renders selected buttons and routes single-choice toggles through the field callback", () => {
    const data = props();
    const view = createElement(ReviewAnswerEditor, data);
    const html = renderToStaticMarkup(view);
    expect(html).toContain("答案与解析");
    expect(html).toMatch(/bg-\[var\(--color-success\)\] text-white shadow-sm">A<\/button>/);
    clickOption(view, "A");
    clickOption(view, "B");
    expect(data.onAnswerChange.mock.calls).toEqual([[""], ["B"]]);
    expect(data.onAnalysisChange).not.toHaveBeenCalled();
    expect(data.answer).toBe("A");
  });

  it("uses the current multi-choice snapshot for adding and removing options", () => {
    const data = { ...props(" MULTIPLE-CHOICE "), answer: "A，C C" };
    const view = createElement(ReviewAnswerEditor, data);
    clickOption(view, "B");
    clickOption(view, "A");
    expect(data.onAnswerChange.mock.calls).toEqual([["A,C,C,B"], ["C,C"]]);
  });

  it("keeps answer and analysis input callbacks independent and allows raw slot answers", () => {
    const data = props("multi_blank_choice");
    const fields = controls(createElement(ReviewAnswerEditor, data));
    const answer = fields.find((element) => element.type === "input");
    const analysis = fields.find((element) => element.type === "textarea");
    if (typeof answer?.props.onChange !== "function" || typeof analysis?.props.onChange !== "function") {
      throw new Error("Text fields missing");
    }
    answer.props.onChange({ target: { value: "1:A;2:B" } });
    analysis.props.onChange({ target: { value: "new analysis" } });
    expect(data.onAnswerChange.mock.calls).toEqual([["1:A;2:B"]]);
    expect(data.onAnalysisChange.mock.calls).toEqual([["new analysis"]]);
    expect(answer.props.value).toBe("A");
    expect(analysis.props.value).toBe("old analysis");
  });

  it("retains the empty-option message and hides quick choices for both multi-blank types", () => {
    const data = { ...props(), options: [] };
    expect(renderToStaticMarkup(createElement(ReviewAnswerEditor, data))).toContain("请先编辑选项");
    for (const type of ["multi_blank_choice", "multi_blank_multiple_choice"]) {
      const view = createElement(ReviewAnswerEditor, { ...props(type), answer: "1:A;2:B" });
      const html = renderToStaticMarkup(view);
      expect(html).not.toContain("<button");
      expect(html).not.toContain("请先编辑选项");
      expect(html).toContain("多空选择题的答案由上方各空位的答案选择器生成");
      expect(html).toContain('value="1:A;2:B"');
    }
  });
});
