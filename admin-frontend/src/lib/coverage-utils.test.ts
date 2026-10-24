import { describe, it, expect } from "vitest";
import {
  computeStatusCounts,
  filterCoverageItems,
  computeIntegrityIssueCount,
  computeQualitySampleCount,
  hasGraphIssues,
  coverageTone,
  examStatusTone,
  questionBankHref,
  questionIdHref,
  COVERAGE_STATUS_LABEL,
  EXAM_STATUS_LABEL,
  type CoverageItemLike,
  type CoverageSummaryLike,
  type CoverageQualityLike,
  type GraphQualityLike,
} from "./coverage-utils";

const items: CoverageItemLike[] = [
  { status: "empty", subject_name: "数据结构", subject_code: "DS", name: "树" },
  { status: "healthy", subject_name: "网络", subject_code: "NET", name: "TCP" },
  { status: "empty", subject_name: "OS", subject_code: "OS", name: "进程" },
  { status: "imbalanced", subject_name: "组成原理", subject_code: "CO", name: "CPU" },
];

describe("computeStatusCounts", () => {
  it("counts by status", () => {
    const c = computeStatusCounts(items);
    expect(c.empty).toBe(2);
    expect(c.healthy).toBe(1);
    expect(c.imbalanced).toBe(1);
    expect(c.insufficient).toBe(0);
  });
  it("returns zeros for empty", () => {
    expect(computeStatusCounts([])).toEqual({ empty: 0, insufficient: 0, imbalanced: 0, healthy: 0 });
  });
});

describe("filterCoverageItems", () => {
  it("filters by keyword", () => {
    expect(filterCoverageItems(items, "数据", "")).toHaveLength(1);
  });
  it("filters by status", () => {
    expect(filterCoverageItems(items, "", "empty")).toHaveLength(2);
  });
  it("filters by keyword and status", () => {
    expect(filterCoverageItems(items, "数据", "empty")).toHaveLength(1);
  });
  it("returns all when no filters", () => {
    expect(filterCoverageItems(items, "", "")).toHaveLength(4);
  });
  it("search is case-insensitive", () => {
    expect(filterCoverageItems(items, "tcp", "")).toHaveLength(1);
  });
  it("matches subject_code", () => {
    expect(filterCoverageItems(items, "DS", "")).toHaveLength(1);
  });
  it("returns empty for no match", () => {
    expect(filterCoverageItems(items, "不存在", "")).toHaveLength(0);
  });
});

const summary: CoverageSummaryLike = {
  unversioned_questions: 5,
  syllabus_snapshot_missing_questions: 3,
  missing_analysis_questions: 2,
  image_reference_anomaly_questions: 1,
  duplicate_suspect_questions: 4,
  empty_knowledge_points: 10,
  insufficient_knowledge_points: 8,
  imbalanced_knowledge_points: 6,
};

const quality: CoverageQualityLike = {
  unmapped_question_ids: [1, 2, 3],
  missing_analysis_question_ids: [1],
  image_reference_anomaly_question_ids: [],
  unversioned_question_ids: [1, 2],
  syllabus_snapshot_missing_question_ids: [1],
  duplicate_groups: [{ id: 1 }],
};

const graph: GraphQualityLike = { warnings: ["w1"], summary: { isolated_count: 2, cycle_count: 1 } };

describe("computeIntegrityIssueCount", () => {
  it("sums integrity issues", () => {
    expect(computeIntegrityIssueCount(summary, graph)).toBe(5 + 3 + 2 + 1);
  });
  it("handles null summary", () => {
    expect(computeIntegrityIssueCount(null, graph)).toBe(0);
  });
  it("handles null graph", () => {
    expect(computeIntegrityIssueCount(summary, null)).toBe(8);
  });
  it("handles undefined graph summary", () => {
    expect(computeIntegrityIssueCount(summary, {})).toBe(8);
  });
});

describe("computeQualitySampleCount", () => {
  it("sums quality issue counts", () => {
    expect(computeQualitySampleCount(quality)).toBe(3 + 1 + 0 + 2 + 1 + 1);
  });
  it("returns 0 for null", () => {
    expect(computeQualitySampleCount(null)).toBe(0);
  });
  it("returns 0 for undefined", () => {
    expect(computeQualitySampleCount(undefined)).toBe(0);
  });
});

describe("hasGraphIssues", () => {
  it("true when warnings exist", () => {
    expect(hasGraphIssues({ warnings: ["x"] })).toBe(true);
  });
  it("true when isolated_count > 0", () => {
    expect(hasGraphIssues({ summary: { isolated_count: 1 } })).toBe(true);
  });
  it("true when cycle_count > 0", () => {
    expect(hasGraphIssues({ summary: { cycle_count: 1 } })).toBe(true);
  });
  it("false when all zero/empty", () => {
    expect(hasGraphIssues({ warnings: [], summary: { isolated_count: 0, cycle_count: 0 } })).toBe(false);
  });
  it("false for null/undefined", () => {
    expect(hasGraphIssues(null)).toBe(false);
    expect(hasGraphIssues(undefined)).toBe(false);
  });
});

describe("coverageTone", () => {
  it("returns success for healthy", () => {
    expect(coverageTone("healthy")).toBe("success");
  });
  it("returns danger for empty", () => {
    expect(coverageTone("empty")).toBe("danger");
  });
  it("returns warning for insufficient", () => {
    expect(coverageTone("insufficient")).toBe("warning");
  });
  it("returns warning for imbalanced", () => {
    expect(coverageTone("imbalanced")).toBe("warning");
  });
});

describe("examStatusTone", () => {
  it("returns success for complete", () => {
    expect(examStatusTone("complete")).toBe("success");
  });
  it("returns neutral for archived", () => {
    expect(examStatusTone("archived")).toBe("neutral");
  });
  it("returns danger for missing", () => {
    expect(examStatusTone("missing")).toBe("danger");
  });
  it("returns danger for invalid", () => {
    expect(examStatusTone("invalid")).toBe("danger");
  });
  it("returns warning for draft", () => {
    expect(examStatusTone("draft")).toBe("warning");
  });
});

describe("questionBankHref", () => {
  it("builds URL with knowledge_point_id", () => {
    const href = questionBankHref(42);
    expect(href).toContain("knowledge_point_id=42");
    expect(href).toContain("is_active=true");
    expect(href).toMatch(/^\/questions\?/);
  });
});

describe("questionIdHref", () => {
  it("builds URL with keyword hash", () => {
    const href = questionIdHref(99);
    expect(href).toContain("keyword=%2399");
    expect(href).toContain("is_active=true");
    expect(href).toMatch(/^\/questions\?/);
  });
});

describe("COVERAGE_STATUS_LABEL", () => {
  it("has all status labels", () => {
    expect(COVERAGE_STATUS_LABEL.empty).toBe("无题");
    expect(COVERAGE_STATUS_LABEL.healthy).toBe("良好");
    expect(COVERAGE_STATUS_LABEL.insufficient).toBe("题量不足");
    expect(COVERAGE_STATUS_LABEL.imbalanced).toBe("结构失衡");
  });
});

describe("EXAM_STATUS_LABEL", () => {
  it("has all status labels", () => {
    expect(EXAM_STATUS_LABEL.missing).toBe("缺失");
    expect(EXAM_STATUS_LABEL.complete).toBe("完整");
    expect(EXAM_STATUS_LABEL.archived).toBe("已归档");
  });
});
