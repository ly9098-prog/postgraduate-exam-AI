import { Children, createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { Button } from "@/components/ui/button";
import type { BatchAnswerImageApplyResponse, BatchAnswerImagePreviewResponse } from "@/lib/api/types";
import { ImageAnswerPreview, ImageAnswerResult } from "./image-answer-results";

function preview(): BatchAnswerImagePreviewResponse {
  return {
    batch_id: "b", preview_token: "token", operation_id: "operation",
    summary: {
      total_images: 4, extracted_entries: 4, matched_count: 1, unmatched_count: 2,
      ambiguous_count: 1, writable_answer_count: 1, writable_analysis_count: 2,
      skipped_existing_answer_count: 0, skipped_existing_analysis_count: 0,
    },
    items: ["matched", "ambiguous", "unmatched", "future"].map((status, index) => ({
      import_id: null, status, status_message: "", validation_errors: [],
      source_question_no: index === 0 ? "" : index === 3 ? "3" : null,
      source_order_index: index === 1 ? 0 : null,
      stem_excerpt: index === 0 ? "stem <unsafe>" : "", question_type: null,
      original_answer: index === 0 ? "A" : null, original_analysis: null,
      extracted_answer: index === 0 ? "B" : "", extracted_analysis: null,
      will_update_answer: false, will_update_analysis: false,
      source_filename: index === 2 ? "" : `source <${index}>.png`, image_index: index,
      ocr_confidence: index === 0 ? 0 : index === 1 ? null : 0.946,
      extract_method: index === 0 ? "rule" : index === 1 ? null : "future",
      raw_text_excerpt: null,
    })),
    warnings: ["warning <unsafe>", "warning two"],
  };
}

function button(element: ReactElement<{ children?: ReactNode }>) {
  const result = Children.toArray(element.props.children).find(
    (child) => isValidElement(child) && child.type === Button,
  );
  if (!isValidElement<{ onClick: () => void; disabled?: boolean }>(result)) {
    throw new Error("Expected the action button");
  }
  return result.props;
}

function renderPreview(data = preview()) {
  return renderToStaticMarkup(createElement(ImageAnswerPreview, {
    preview: data, executing: false, onApply: vi.fn(),
  }));
}

describe("image answer result views", () => {
  it("preserves matching statuses, number fallbacks and blank answer placeholders", () => {
    const html = renderPreview();
    const rows = html.match(/<tbody>(.*?)<\/tbody>/)?.[1].match(/<tr\b.*?<\/tr>/g) ?? [];
    const labels = ["已匹配", "歧义", "未匹配", "未匹配"];
    const colors = ["text-emerald-600", "text-amber-600", "text-gray-400", "text-gray-400"];
    expect(rows).toHaveLength(4);
    rows.forEach((row, index) => expect(row).toContain(` ${colors[index]}">${labels[index]}</td>`));
    expect(rows[0]).toMatch(/<td[^>]*><\/td>/);
    expect(rows[1]).toMatch(/<td[^>]*>0<\/td>/);
    expect(rows[2]).toMatch(/<td[^>]*>\?<\/td>/);
    expect(rows[0]).toContain("stem &lt;unsafe&gt;");
    expect(rows[1].match(/text-\[var\(--color-text-hint\)\]">—<\/span>/g)).toHaveLength(3);
    expect(html).toContain("warning &lt;unsafe&gt;");
    expect(html).toContain("warning two");
  });

  it("filters sources and retains zero confidence, rounding and extraction labels", () => {
    const html = renderPreview();
    const sources = html.match(/<details\b.*?<\/details>/)?.[0] ?? "";
    expect(sources).toContain("图片来源信息");
    expect(sources).toContain("source &lt;0&gt;.png");
    expect(sources).toContain("置信度 0%");
    expect(sources).toContain("置信度 95%");
    expect(sources).toContain("规则提取");
    expect(sources).toContain("AI提取");
    expect(sources).toContain("题号 3");
    expect(sources.match(/<p\b/g)).toHaveLength(3);
    expect(sources.match(/置信度/g)).toHaveLength(2);
  });

  it("omits absent optional summaries, warnings and sources while retaining the table", () => {
    const data = preview();
    data.items = [];
    data.warnings = [];
    data.summary.unmatched_count = 0;
    data.summary.ambiguous_count = 0;
    data.summary.writable_answer_count = 0;
    data.summary.writable_analysis_count = 0;
    const html = renderPreview(data);
    expect(html).toContain("<tbody></tbody>");
    for (const text of ["未匹配", "歧义", "可写答案", "可写解析", "<details", "border-amber-200"]) {
      expect(html).not.toContain(text);
    }
  });

  it("enables answer-only and analysis-only writes and disables pending or unwritable requests", () => {
    const data = preview();
    const onApply = vi.fn();
    const action = () => button(ImageAnswerPreview({ preview: data, executing: false, onApply }));
    action().onClick();
    expect(onApply).toHaveBeenCalledOnce();
    data.summary.writable_analysis_count = 0;
    expect(action().disabled).toBe(false);
    expect(renderPreview(data)).toContain("1 题答案");
    data.summary.writable_answer_count = 0;
    data.summary.writable_analysis_count = 2;
    expect(action().disabled).toBe(false);
    expect(renderPreview(data)).toContain("2 题解析");
    expect(button(ImageAnswerPreview({ preview: data, executing: true, onApply })).disabled).toBe(true);
    data.summary.writable_analysis_count = 0;
    expect(action().disabled).toBe(true);
  });

  it("renders both updated and skipped totals and connects the close callback", () => {
    const result: BatchAnswerImageApplyResponse = {
      operation_id: "operation", updated_answer_count: 3, updated_analysis_count: 4,
      skipped_existing_answer_count: 5, skipped_existing_analysis_count: 6,
      remaining_count: 7, batch_stats: {},
    };
    const onClose = vi.fn();
    const view = ImageAnswerResult({ result, onClose });
    const html = renderToStaticMarkup(view);
    expect(html).toContain("图片答案导入完成");
    expect(html).toContain('text-emerald-600">3</p>');
    expect(html).toContain('text-emerald-600">4</p>');
    expect(html).toContain("跳过已有答案 5");
    expect(html).toContain("跳过已有解析 6");
    button(view).onClick();
    expect(onClose).toHaveBeenCalledOnce();
  });
});
