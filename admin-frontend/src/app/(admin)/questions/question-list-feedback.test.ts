import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { QuestionListFeedback } from "./question-list-feedback";

function renderFeedback(props: Partial<Parameters<typeof QuestionListFeedback>[0]> = {}) {
  const onResetFilters = vi.fn();
  const onRetry = vi.fn();
  const html = renderToStaticMarkup(createElement(QuestionListFeedback, {
    emptyVisible: false,
    isError: false,
    hasActiveFilters: true,
    onResetFilters,
    onRetry,
    ...props,
  }));
  return { html, onResetFilters, onRetry };
}

describe("QuestionListFeedback", () => {
  it("renders empty state with the existing reset action only when filters are active", () => {
    const feedback = renderFeedback({ emptyVisible: true });

    expect(feedback.html).toContain("暂无匹配题目");
    expect(feedback.html).toContain("清除筛选");
    expect(renderFeedback({ emptyVisible: true, hasActiveFilters: false }).html).not.toContain("清除筛选");
  });

  it("renders the list error state and retry action without replacing the empty state", () => {
    const feedback = renderFeedback({ emptyVisible: true, isError: true });

    expect(feedback.html).toContain("暂无匹配题目");
    expect(feedback.html).toContain("题目加载失败");
    expect(feedback.html).toContain("请检查查询条件或后端服务后重试");
    expect(feedback.html).toContain("重新加载");
  });

  it("renders no feedback in the successful non-empty state", () => {
    expect(renderFeedback().html).toBe("");
  });
});
