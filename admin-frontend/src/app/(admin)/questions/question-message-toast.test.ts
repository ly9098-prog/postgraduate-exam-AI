import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { QuestionMessageToast } from "./question-message-toast";

function renderToast(message: string | null) {
  const onClose = vi.fn();
  const html = renderToStaticMarkup(createElement(QuestionMessageToast, { message, onClose }));
  return { html, onClose };
}

describe("QuestionMessageToast", () => {
  it("renders the existing status message and close action", () => {
    const toast = renderToast("题目已更新。");

    expect(toast.html).toContain("题目已更新。");
    expect(toast.html).toContain('aria-live="polite"');
    expect(toast.html).toContain("关闭提示");
  });

  it("renders nothing when no message is present", () => {
    expect(renderToast(null).html).toBe("");
  });
});
