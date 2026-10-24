import { describe, it, expect } from "vitest";
import {
  statusMeta,
  paperKindLabel,
  computePaperSummary,
  filterPapers,
  buildStatusSegments,
  stableDesktopListHeight,
  stableMobileListHeight,
} from "./exam-paper-utils";
import type { AdminExamPaperListItem } from "./api/types";

function makePaper(overrides: Partial<AdminExamPaperListItem>): AdminExamPaperListItem {
  return {
    id: 1,
    title: "Test Paper",
    paper_type: "mock_choice",
    status: "draft",
    year: 2024,
    version: "v1",
    source: null,
    attempt_count: 0,
    question_count: 0,
    created_at: "",
    updated_at: "",
    ...overrides,
  } as AdminExamPaperListItem;
}

describe("statusMeta", () => {
  it("returns success for published", () => {
    expect(statusMeta("published")).toEqual({ label: "已发布", tone: "success" });
  });
  it("returns neutral for archived", () => {
    expect(statusMeta("archived")).toEqual({ label: "已归档", tone: "neutral" });
  });
  it("returns warning for draft", () => {
    expect(statusMeta("draft")).toEqual({ label: "草稿", tone: "warning" });
  });
});

describe("paperKindLabel", () => {
  it("labels past exam choice", () => {
    expect(paperKindLabel(makePaper({ paper_type: "past_exam_choice", year: 2025 }))).toBe("2025 真题");
  });
  it("labels past exam without year", () => {
    expect(paperKindLabel(makePaper({ paper_type: "past_exam_choice", year: null }))).toBe("年份未设置 真题");
  });
  it("labels mock exam with year", () => {
    expect(paperKindLabel(makePaper({ paper_type: "mock_choice", year: 2024 }))).toBe("2024 模拟卷");
  });
  it("labels mock exam without year", () => {
    expect(paperKindLabel(makePaper({ paper_type: "mock_choice", year: null }))).toBe("模拟卷");
  });
});

describe("computePaperSummary", () => {
  it("computes summary from paper list", () => {
    const papers = [
      makePaper({ status: "draft", attempt_count: 5 }),
      makePaper({ status: "published", attempt_count: 10 }),
      makePaper({ status: "published", attempt_count: 3 }),
    ];
    expect(computePaperSummary(papers)).toEqual({
      total: 3,
      draft: 1,
      published: 2,
      attempts: 18,
    });
  });
  it("handles empty list", () => {
    expect(computePaperSummary([])).toEqual({
      total: 0,
      draft: 0,
      published: 0,
      attempts: 0,
    });
  });
});

describe("filterPapers", () => {
  const papers = [
    makePaper({ id: 1, title: "数据结构", status: "draft", year: 2024 }),
    makePaper({ id: 2, title: "操作系统", status: "published", year: 2025 }),
  ];
  it("filters by status", () => {
    expect(filterPapers(papers, "published", "").length).toBe(1);
  });
  it("filters by keyword", () => {
    expect(filterPapers(papers, "", "数据").length).toBe(1);
  });
  it("returns all when no filter", () => {
    expect(filterPapers(papers, "", "").length).toBe(2);
  });
  it("combines status and keyword", () => {
    expect(filterPapers(papers, "draft", "操作").length).toBe(0);
  });
});

describe("buildStatusSegments", () => {
  it("builds segments with counts", () => {
    const papers = [
      makePaper({ status: "draft" }),
      makePaper({ status: "published" }),
      makePaper({ status: "archived" }),
    ];
    const summary = computePaperSummary(papers);
    const segments = buildStatusSegments(papers, summary);
    expect(segments[0]).toEqual({ value: "", label: "全部", count: 3 });
    expect(segments[1]).toEqual({ value: "draft", label: "草稿", count: 1 });
    expect(segments[2]).toEqual({ value: "published", label: "已发布", count: 1 });
    expect(segments[3]).toEqual({ value: "archived", label: "已归档", count: 1 });
  });
});

describe("stableDesktopListHeight", () => {
  it("returns 260 for zero papers", () => {
    expect(stableDesktopListHeight(0)).toBe(260);
  });
  it("returns 260 for negative", () => {
    expect(stableDesktopListHeight(-1)).toBe(260);
  });
  it("returns header+offset for single paper", () => {
    expect(stableDesktopListHeight(1)).toBe(260);
  });
  it("clamps to max 720 for many papers", () => {
    expect(stableDesktopListHeight(20)).toBe(720);
  });
  it("grows linearly in the middle range", () => {
    expect(stableDesktopListHeight(5)).toBe(436);  // 46 + 5*78 = 436, within [260, 720]
  });
  it("clamps to 720 when formula exceeds max", () => {
    expect(stableDesktopListHeight(9)).toBe(720);  // 46 + 9*78 = 748, clamped
  });
});

describe("stableMobileListHeight", () => {
  it("returns 240 for zero papers", () => {
    expect(stableMobileListHeight(0)).toBe(240);
  });
  it("returns 240 for negative", () => {
    expect(stableMobileListHeight(-1)).toBe(240);
  });
  it("returns row*count for single paper", () => {
    expect(stableMobileListHeight(1)).toBe(240);  // 96 < 240, clamped to min
  });
  it("clamps to max 560 for many papers", () => {
    expect(stableMobileListHeight(10)).toBe(560);
  });
  it("grows linearly in the middle range", () => {
    expect(stableMobileListHeight(4)).toBe(384);  // 4*96=384, within [240, 560]
  });
});
