import { describe, it, expect } from "vitest";
import {
  computeStatusCounts,
  filterCoverageItems,
  computeIntegrityIssueCount,
  computeQualitySampleCount,
  hasGraphIssues,
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
