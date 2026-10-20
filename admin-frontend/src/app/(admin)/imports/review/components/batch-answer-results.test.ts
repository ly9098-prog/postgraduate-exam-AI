import { Children, createElement, isValidElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { Button } from "@/components/ui/button";
import type { BatchAnswerApplyResponse, BatchAnswerPreviewResponse } from "@/lib/api/types";
import { BatchAnswerPreview, BatchAnswerResult } from "./batch-answer-results";

function preview(): BatchAnswerPreviewResponse {
  return {
    batch_id: "b", preview_token: "token", operation_id: "operation",
    summary: {
      batch_total: 9, parsed_answer_count: 9, target_question_count: 9,
      remaining_question_count: 0, writable_count: 1, skipped_existing_count: 2,
      skipped_existing_same_count: 1, unsupported_count: 1, invalid_count: 1,
      warning_count: 1, order_anomaly_count: 1,
    },
    items: ["skip_existing", "skip_existing_same", "invalid_answer", "unsupported_type",
      "order_anomaly", "future_status", "", "invalid_answer"].map((status, index) => ({
      import_id: index, status, status_message: "", validation_errors: [],
      source_question_no: index === 0 ? "" : null,
      source_order_index: index === 1 ? 0 : null,
      stem_excerpt: `stem <${index}>`, question_type: null,
      original_answer: index === 0 ? "A" : null,
      input_answer: "B", normalized_answer: index === 0 ? "B" : "",
      will_update: index === 7,
    })),
    warnings: ["warning <unsafe>", "warning two"],
  };
}

function button(element: ReactElement<{ children?: React.ReactNode }>) {
  const result = Children.toArray(element.props.children).find(
    (child) => isValidElement(child) && child.type === Button,
  );
  if (!isValidElement<{ onClick: () => void; disabled?: boolean }>(result)) {
    throw new Error("Expected the action button");
  }
  return result.props;
}

describe("batch answer result views", () => {
  it("preserves status precedence, row fallbacks, escaped content and warnings", () => {
    const html = renderToStaticMarkup(createElement(BatchAnswerPreview, {
      preview: preview(), executing: false, onApply: vi.fn(),
    }));
    const rows = html.match(/<tbody>(.*?)<\/tbody>/)?.[1].match(/<tr\b.*?<\/tr>/g) ?? [];
    const labels = ["跳过", "相同", "无效", "不支持", "异常", "future_status", "—", "将写入"];
    const colors = ["text-amber-600", "text-amber-600", "text-red-600", "text-gray-400",
      "text-[var(--color-text-secondary)]", "text-[var(--color-text-secondary)]",
      "text-[var(--color-text-secondary)]", "text-emerald-600"];
    expect(rows).toHaveLength(labels.length);
    rows.forEach((row, index) => {
      expect(row).toContain(` ${colors[index]}">${labels[index]}</td>`);
    });
    expect(rows[0]).toMatch(/<td[^>]*><\/td>/);
    expect(rows[1]).toMatch(/<td[^>]*>0<\/td>/);
    expect(rows[2]).toMatch(/<td[^>]*>\?<\/td>/);
    expect(rows[0]).toContain("stem &lt;0&gt;");
    expect(rows[2]).toContain('text-[var(--color-text-hint)]">—</span>');
    expect(html).toContain("warning &lt;unsafe&gt;");
    expect(html).toContain("warning two");
    expect(html).toContain("跳过已有");
  });

  it("hides zero summaries and empty warnings while keeping the empty table", () => {
    const data = preview();
    data.items = [];
    data.warnings = [];
    data.summary.skipped_existing_count = 0;
    data.summary.invalid_count = 0;
    data.summary.unsupported_count = 0;
    const html = renderToStaticMarkup(createElement(BatchAnswerPreview, {
      preview: data, executing: false, onApply: vi.fn(),
    }));
    expect(html).toContain("<tbody></tbody>");
    expect(html).not.toContain("跳过已有");
    expect(html).not.toContain("无效");
    expect(html).not.toContain("不支持");
    expect(html).not.toContain("border-amber-200");
  });

  it("keeps the apply callback and disables writes for zero capacity or pending requests", () => {
    const data = preview();
    const onApply = vi.fn();
    const action = button(BatchAnswerPreview({ preview: data, executing: false, onApply }));
    expect(action.disabled).toBe(false);
    action.onClick();
    expect(onApply).toHaveBeenCalledOnce();
    expect(button(BatchAnswerPreview({ preview: data, executing: true, onApply })).disabled).toBe(true);
    data.summary.writable_count = 0;
    expect(button(BatchAnswerPreview({ preview: data, executing: false, onApply })).disabled).toBe(true);
  });

  it("renders apply totals and routes closing through the supplied callback", () => {
    const result: BatchAnswerApplyResponse = {
      operation_id: "operation", updated_count: 3, skipped_existing_count: 2,
      remaining_count: 4, batch_stats: {},
    };
    const onClose = vi.fn();
    const view = BatchAnswerResult({ result, onClose });
    const html = renderToStaticMarkup(view);
    expect(html).toContain("批量答案写入完成");
    expect(html).toContain('text-emerald-600">3</p>');
    expect(html).toContain('text-amber-600">2</p>');
    expect(html).toContain('text-[var(--color-text-secondary)]">4</p>');
    button(view).onClick();
    expect(onClose).toHaveBeenCalledOnce();
  });
});
