import { describe, expect, it } from "vitest";
import type { ImportQuestionItem } from "@/lib/api/types";
import { getSourceLocator, getSourceQuestionNo } from "./review-source-location";

function item(value: Partial<ImportQuestionItem>): ImportQuestionItem {
  return value as ImportQuestionItem;
}

describe("review source location", () => {
  it("prefers explicit question number, then label, then supported raw text formats", () => {
    expect(getSourceQuestionNo(item({
      source_question_no: "8",
      source_question_label: "第 9 题",
      raw_text_preview: "10. raw",
    }))).toBe("8");
    expect(getSourceQuestionNo(item({
      source_question_label: "来源题目 12",
      raw_text_preview: "13、raw",
    }))).toBe("12");
    expect(getSourceQuestionNo(item({ raw_text_preview: "  14．raw" }))).toBe("14");
    expect(getSourceQuestionNo(item({ raw_text_preview: "第 15 题 raw" }))).toBe("15");
    expect(getSourceQuestionNo(item({ raw_text_preview: "（16）raw" }))).toBe("16");
  });

  it("falls through raw text fields in their established priority", () => {
    expect(getSourceQuestionNo(item({
      raw_text_preview: "",
      raw_data: { raw_text: "", raw_question_text: "第17题", text: "18. ignored" },
    }))).toBe("17");
    expect(getSourceQuestionNo(item({
      raw_data: { raw_text: "not numbered", raw_question_text: "", text: "(19) raw" },
    }))).toBe("");
    expect(getSourceQuestionNo(item({ raw_text_preview: "unrecognized" }))).toBe("");
  });

  it("prefers explicit locator and combines image and page metadata", () => {
    expect(getSourceLocator(item({
      source_locator: "explicit",
      source_image_seq: 3,
      source_file: "scan.pdf",
      source_page_start: 2,
    }))).toBe("explicit");
    expect(getSourceLocator(item({
      source_image_seq: 3,
      source_file: "scan.pdf",
      source_page_start: 2,
      source_page_end: 4,
    }))).toBe("图3 · scan.pdf · 第2-4页");
  });

  it("uses raw metadata fallbacks and source type only when no locator parts exist", () => {
    expect(getSourceLocator(item({
      raw_data: { source_image_name: "page.png", source_page: 6, page_end: 7 },
    }))).toBe("page.png · 第6-7页");
    expect(getSourceLocator(item({ source_type: "pdf" }))).toBe("pdf");
    expect(getSourceLocator(item({ source_type: "  " }))).toBe("");
    expect(getSourceLocator(item({ source_type: "unknown" }))).toBe("");
    expect(getSourceLocator(item({ source_type: "uNkNoWn" }))).toBe("uNkNoWn");
    expect(getSourceLocator(item({}))).toBe("");
  });
});
