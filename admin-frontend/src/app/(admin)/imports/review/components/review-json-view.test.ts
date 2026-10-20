import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ImportQuestionItem } from "@/lib/api/types";
import { ReviewJsonView } from "./review-json-view";

function item(): ImportQuestionItem {
  return {
    id: 1, batch_id: "batch", source_type: "ocr", subject_id: 2, subject_code: "408", subject_name: "计算机",
    question_type: "single_choice", status: "pending", ai_generated: true, ai_answer_flag: false,
    created_at: "created", updated_at: "updated", parsed_content: { stem: "stem" }, parsed_options: { A: "a" },
    parsed_answer: "A", parsed_analysis: "analysis", duplicate_status: "none",
    duplicate_of_question_id: null, duplicate_of_import_id: null, question_hash: "hash",
    raw_data: { raw_text: "raw" }, ai_metadata: { model: "model" },
    risk_flags: [], risk_level: "low", risk_reasons: [],
  };
}

describe("review JSON view", () => {
  it("preserves four groups, open details and JSON data values", () => {
    const html = renderToStaticMarkup(createElement(ReviewJsonView, { item: item() }));
    expect((html.match(/<section/g) ?? [])).toHaveLength(4);
    expect((html.match(/<details[^>]* open/g) ?? [])).toHaveLength(4);
    expect(html).toContain("基础信息");
    expect(html).toContain("解析数据");
    expect(html).toContain("重复检测");
    expect(html).toContain("OCR / AI 原始数据");
    expect(html).toContain("&quot;parsed_answer&quot;: &quot;A&quot;");
    expect(html).toContain("&quot;raw_text&quot;: &quot;raw&quot;");
    expect(html).toContain("#5b7b9a18");
  });

  it("preserves null and empty nested values in the existing JSON serialization", () => {
    const data = item();
    data.parsed_answer = "";
    data.parsed_analysis = null;
    const html = renderToStaticMarkup(createElement(ReviewJsonView, { item: data }));
    expect(html).toContain("&quot;parsed_answer&quot;: &quot;&quot;");
    expect(html).toContain("&quot;parsed_analysis&quot;: null");
  });

  it("keeps section field boundaries, omission and escaped raw data", () => {
    const data = item();
    data.raw_data = { text: "</pre><script>alert(1)</script>", values: [null, false, 0, ""] };
    data.ai_metadata = undefined;
    const html = renderToStaticMarkup(createElement(ReviewJsonView, { item: data }));
    const groups = Array.from(html.matchAll(/<pre[^>]*>([\s\S]*?)<\/pre>/g), (match) =>
      JSON.parse(match[1].replaceAll("&quot;", '"').replaceAll("&#x27;", "'")
        .replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&amp;", "&")),
    );
    expect(groups).toEqual([
      {
        id: data.id, batch_id: data.batch_id, source_type: data.source_type,
        subject_id: data.subject_id, subject_code: data.subject_code, subject_name: data.subject_name,
        question_type: data.question_type, status: data.status, ai_generated: true,
        ai_answer_flag: false, created_at: "created", updated_at: "updated",
      },
      { parsed_content: data.parsed_content, parsed_options: data.parsed_options,
        parsed_answer: "A", parsed_analysis: "analysis" },
      { duplicate_status: "none", duplicate_of_question_id: null,
        duplicate_of_import_id: null, question_hash: "hash" },
      { raw_data: data.raw_data },
    ]);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;/pre&gt;&lt;script&gt;");
  });
});
