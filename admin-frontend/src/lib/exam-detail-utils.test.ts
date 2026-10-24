import { describe, it, expect } from "vitest";
import {
  groupDraftItemsBySubject,
  filterCandidates,
  countMatchedSelected,
  computeDraftScore,
  hasStaleVersion,
  buildCandidateSearchSummary,
  SUBJECT_ORDER,
  type DraftItemLike,
} from "./exam-detail-utils";

const items: DraftItemLike[] = [
  { question_id: 1, subject_code: "data_structure", subject_name: "数据结构", score: 5, version_is_current: true },
  { question_id: 2, subject_code: "computer_network", subject_name: "计算机网络", score: 3, version_is_current: true },
  { question_id: 3, subject_code: "data_structure", subject_name: "数据结构", score: 2, version_is_current: false },
  { question_id: 4, subject_code: "operating_system", subject_name: "操作系统", score: null, version_is_current: true },
];

describe("groupDraftItemsBySubject", () => {
  it("groups by subject_code", () => {
    const groups = groupDraftItemsBySubject(items);
    expect(groups).toHaveLength(3);
  });
  it("preserves items within groups", () => {
    const groups = groupDraftItemsBySubject(items);
    const ds = groups.find((g) => g.subject_code === "data_structure");
    expect(ds?.entries).toHaveLength(2);
  });
  it("sorts by SUBJECT_ORDER", () => {
    const groups = groupDraftItemsBySubject(items);
    expect(groups[0].subject_code).toBe("data_structure");
    expect(groups[1].subject_code).toBe("operating_system");
    expect(groups[2].subject_code).toBe("computer_network");
  });
  it("places unknown subjects last", () => {
    const items2 = [
      { ...items[0], subject_code: "unknown_code", subject_name: "自定义" },
      { ...items[1] },
    ];
    const groups = groupDraftItemsBySubject(items2);
    expect(groups[1].subject_code).toBe("unknown_code");
  });
  it("uses subject_name fallback when code empty", () => {
    const item = { question_id: 1, subject_code: "", subject_name: "自定义", score: 0, version_is_current: true };
    const groups = groupDraftItemsBySubject([item]);
    expect(groups[0].subject_code).toBe("unknown");
    expect(groups[0].subject_name).toBe("自定义");
  });
  it("handles empty items", () => {
    expect(groupDraftItemsBySubject([])).toEqual([]);
  });
});

describe("filterCandidates", () => {
  const candidates = [{ id: 1 }, { id: 2 }, { id: 3 }];
  it("filters out selected ids", () => {
    expect(filterCandidates(candidates, new Set([1, 2]))).toEqual([{ id: 3 }]);
  });
  it("returns all when nothing selected", () => {
    expect(filterCandidates(candidates, new Set())).toEqual(candidates);
  });
  it("returns empty when all selected", () => {
    expect(filterCandidates(candidates, new Set([1, 2, 3]))).toEqual([]);
  });
});

describe("countMatchedSelected", () => {
  const candidates = [{ id: 1 }, { id: 2 }, { id: 3 }];
  it("counts matched", () => {
    expect(countMatchedSelected(candidates, new Set([1, 3]))).toBe(2);
  });
  it("returns 0 when nothing matched", () => {
    expect(countMatchedSelected(candidates, new Set([99]))).toBe(0);
  });
});

describe("computeDraftScore", () => {
  it("sums valid scores", () => {
    expect(computeDraftScore(items)).toBe(10);
  });
  it("treats null as 0", () => {
    expect(computeDraftScore([{ question_id: 1, subject_code: "x", subject_name: "x", score: null, version_is_current: true }])).toBe(0);
  });
  it("treats string scores as numbers", () => {
    expect(computeDraftScore([
      { question_id: 1, subject_code: "x", subject_name: "x", score: "5", version_is_current: true },
      { question_id: 2, subject_code: "x", subject_name: "x", score: "3", version_is_current: true },
    ])).toBe(8);
  });
  it("handles empty items", () => {
    expect(computeDraftScore([])).toBe(0);
  });
  it("treats invalid number string as 0", () => {
    expect(computeDraftScore([
      { question_id: 1, subject_code: "x", subject_name: "x", score: "abc", version_is_current: true },
    ])).toBe(0);
  });
});

describe("hasStaleVersion", () => {
  it("true when any version_is_current is false", () => {
    expect(hasStaleVersion(items)).toBe(true);
  });
  it("false when all current", () => {
    expect(hasStaleVersion([items[0], items[1]])).toBe(false);
  });
  it("false for empty", () => {
    expect(hasStaleVersion([])).toBe(false);
  });
});

describe("buildCandidateSearchSummary", () => {
  it("returns keyword summary when keyword provided", () => {
    const s = buildCandidateSearchSummary(100, 5, 95, "TCP");
    expect(s).toContain("匹配 100");
    expect(s).toContain("已在卷中 5");
    expect(s).toContain("可添加 95");
  });
  it("returns default summary when no keyword", () => {
    expect(buildCandidateSearchSummary(0, 0, 10, "")).toBe("当前可添加 10 道");
  });
});
