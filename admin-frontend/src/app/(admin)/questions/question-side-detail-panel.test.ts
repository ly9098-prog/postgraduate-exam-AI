import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AdminQuestion } from "@/lib/api/types";
import { QuestionSideDetailPanel } from "./question-side-detail-panel";

const question: AdminQuestion = {
  id: 7,
  question_type: "single_choice",
  content: { stem: "question stem" },
  options: { A: "yes", B: "no" },
  answer: "A",
  analysis: "analysis",
  difficulty: 4,
  review_status: "approved",
  is_active: true,
};

function renderPanel(props: Partial<Parameters<typeof QuestionSideDetailPanel>[0]> = {}) {
  const onOpenFullDetail = vi.fn();
  const onEdit = vi.fn();
  const onDelete = vi.fn();
  const onRetry = vi.fn();
  const element = createElement(QuestionSideDetailPanel, {
    questionId: 7,
    question,
    isError: false,
    scrollRef: { current: null },
    copyButton: createElement("button", { type: "button", "aria-label": "复制题干和选项" }),
    canWrite: true,
    canDelete: true,
    onOpenFullDetail,
    onEdit,
    onDelete,
    onRetry,
    ...props,
  });
  return { html: renderToStaticMarkup(element), onOpenFullDetail, onEdit, onDelete, onRetry };
}

describe("QuestionSideDetailPanel", () => {
  it("renders the empty-selection, error, and loading states without a question", () => {
    const empty = renderPanel({ questionId: null, question: null });
    const error = renderPanel({ question: null, isError: true });
    const loading = renderPanel({ question: null, isError: false });

    expect(empty.html).toContain("选择一道题目");
    expect(error.html).toContain("详情加载失败");
    expect(error.html).toContain("重新加载");
    expect(loading.html).toContain("animate-pulse");
  });

  it("renders the compact side detail and conditional actions", () => {
    const full = renderPanel();
    const restricted = renderPanel({ canWrite: false, canDelete: false });

    expect(full.html).toContain("题目 #7");
    expect(full.html).toContain("question stem");
    expect(full.html).toContain("yes");
    expect(full.html).toContain("完整详情");
    expect(full.html).toContain("编辑");
    expect(full.html).toContain("删除");
    expect(restricted.html).not.toContain("编辑");
    expect(restricted.html).not.toContain("删除");
  });
});
