import { describe, it, expect } from "vitest";
import {
  filterCatalogItems,
  groupCatalogBySubject,
  extractIncludedIds,
  isMembershipDirty,
  SUBJECT_PREFERRED_ORDER,
  STATUS_LABEL,
  RELATION_LABEL,
  statusTone,
} from "./syllabus-utils";
import type { SyllabusCatalogItem } from "./api/types";

const items: SyllabusCatalogItem[] = [
  { knowledge_point_id: 1, subject_id: 1, subject_code: "data_structure", subject_name: "数据结构", name: "树", difficulty_level: 2, included: true },
  { knowledge_point_id: 2, subject_id: 4, subject_code: "computer_network", subject_name: "计算机网络", name: "TCP", difficulty_level: 3, included: false },
  { knowledge_point_id: 3, subject_id: 1, subject_code: "data_structure", subject_name: "数据结构", name: "图", difficulty_level: 3, included: true },
  { knowledge_point_id: 4, subject_id: 3, subject_code: "operating_system", subject_name: "操作系统", name: "进程", difficulty_level: 2, included: false },
];

describe("filterCatalogItems", () => {
  it("returns all when keyword empty", () => {
    expect(filterCatalogItems(items, "")).toHaveLength(4);
  });
  it("filters by name", () => {
    expect(filterCatalogItems(items, "树")).toHaveLength(1);
  });
  it("filters by subject_name", () => {
    expect(filterCatalogItems(items, "网络")).toHaveLength(1);
  });
  it("filters by knowledge_point_id", () => {
    expect(filterCatalogItems(items, "3")).toHaveLength(1);
  });
  it("case-insensitive", () => {
    expect(filterCatalogItems(items, "TCP")).toHaveLength(1);
  });
  it("returns empty for no match", () => {
    expect(filterCatalogItems(items, "不存在")).toHaveLength(0);
  });
});

describe("groupCatalogBySubject", () => {
  it("groups by subject", () => {
    const groups = groupCatalogBySubject(items);
    expect(groups).toHaveLength(3);
  });
  it("sorts by preferred order", () => {
    const groups = groupCatalogBySubject(items);
    expect(groups[0][1][0]?.subject_code).toBe("data_structure");
    expect(groups[1][1][0]?.subject_code).toBe("operating_system");
    expect(groups[2][1][0]?.subject_code).toBe("computer_network");
  });
  it("combines items from same subject", () => {
    const groups = groupCatalogBySubject(items);
    const ds = groups.find(([key]) => key.includes("data_structure"));
    expect(ds?.[1]).toHaveLength(2);
  });
  it("handles empty items", () => {
    expect(groupCatalogBySubject([])).toEqual([]);
  });
});

describe("extractIncludedIds", () => {
  it("extracts included ids", () => {
    expect([...extractIncludedIds(items)].sort()).toEqual([1, 3]);
  });
  it("returns empty set when none included", () => {
    expect(extractIncludedIds(items.map((i) => ({ ...i, included: false }))).size).toBe(0);
  });
  it("handles empty items", () => {
    expect(extractIncludedIds([]).size).toBe(0);
  });
});

describe("isMembershipDirty", () => {
  it("false when sets are equal", () => {
    const s = new Set([1, 2]);
    expect(isMembershipDirty(s, s)).toBe(false);
  });
  it("true when sizes differ", () => {
    expect(isMembershipDirty(new Set([1, 2]), new Set([1]))).toBe(true);
  });
  it("true when same size but different ids", () => {
    expect(isMembershipDirty(new Set([1, 2]), new Set([1, 3]))).toBe(true);
  });
  it("false when both empty", () => {
    expect(isMembershipDirty(new Set(), new Set())).toBe(false);
  });
  it("true when selected has extra", () => {
    expect(isMembershipDirty(new Set([1, 2, 3]), new Set([1, 2]))).toBe(true);
  });
});

describe("statusTone", () => {
  it("returns success for active", () => {
    expect(statusTone("active")).toBe("success");
  });
  it("returns warning for draft", () => {
    expect(statusTone("draft")).toBe("warning");
  });
  it("returns neutral for archived", () => {
    expect(statusTone("archived")).toBe("neutral");
  });
  it("returns neutral for unknown status", () => {
    expect(statusTone("unknown")).toBe("neutral");
  });
});

describe("STATUS_LABEL", () => {
  it("has all status labels", () => {
    expect(STATUS_LABEL.draft).toBe("草稿");
    expect(STATUS_LABEL.active).toBe("当前生效");
    expect(STATUS_LABEL.archived).toBe("已归档");
  });
});

describe("RELATION_LABEL", () => {
  it("has all relation labels", () => {
    expect(RELATION_LABEL.unchanged).toBe("保持");
    expect(RELATION_LABEL.renamed).toBe("重命名");
    expect(RELATION_LABEL.added).toBe("新增");
    expect(RELATION_LABEL.removed).toBe("移除");
    expect(RELATION_LABEL.merged).toBe("合并");
    expect(RELATION_LABEL.split).toBe("拆分");
    expect(RELATION_LABEL.replaced).toBe("替换");
  });
});
