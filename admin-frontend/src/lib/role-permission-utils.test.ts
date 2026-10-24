import { describe, it, expect } from "vitest";
import {
  computePermissionChanges,
  sortCategoryEntries,
  computeTotalPermissionCount,
  categoryLabel,
  categoryDescription,
  resourceLabel,
  actionLabel,
  actionIndex,
  samePermissionSet,
  buildMatrixRows,
  permissionMatches,
} from "./role-permission-utils";
import type { Permission } from "@/lib/api/types";

describe("computePermissionChanges", () => {
  it("returns zero for identical sets", () => {
    const s = new Set([1, 2, 3]);
    expect(computePermissionChanges(s, s)).toEqual({ added: 0, removed: 0 });
  });
  it("counts added permissions", () => {
    expect(computePermissionChanges(new Set([1]), new Set([1, 2, 3]))).toEqual({ added: 2, removed: 0 });
  });
  it("counts removed permissions", () => {
    expect(computePermissionChanges(new Set([1, 2, 3]), new Set([1]))).toEqual({ added: 0, removed: 2 });
  });
  it("counts mixed changes", () => {
    expect(computePermissionChanges(new Set([1, 2, 3]), new Set([2, 4, 5]))).toEqual({ added: 2, removed: 2 });
  });
  it("handles empty original", () => {
    expect(computePermissionChanges(new Set(), new Set([1, 2]))).toEqual({ added: 2, removed: 0 });
  });
  it("handles empty active", () => {
    expect(computePermissionChanges(new Set([1, 2]), new Set())).toEqual({ added: 0, removed: 2 });
  });
  it("handles both empty", () => {
    expect(computePermissionChanges(new Set(), new Set())).toEqual({ added: 0, removed: 0 });
  });
});

describe("sortCategoryEntries", () => {
  const order = ["users", "questions", "formulas"];
  it("sorts by predefined order", () => {
    const entries: Array<[string, string[]]> = [
      ["formulas", []],
      ["users", []],
      ["questions", []],
    ];
    const out = sortCategoryEntries(entries, order);
    expect(out.map(([k]) => k)).toEqual(["users", "questions", "formulas"]);
  });
  it("places unknown categories after known ones", () => {
    const entries: Array<[string, string[]]> = [
      ["custom", []],
      ["users", []],
      ["formulas", []],
    ];
    const out = sortCategoryEntries(entries, order);
    expect(out[0][0]).toBe("users");
    expect(out[1][0]).toBe("formulas");
    expect(out[2][0]).toBe("custom");
  });
  it("sorts unknown categories alphabetically", () => {
    const entries: Array<[string, string[]]> = [
      ["zebra", []],
      ["alpha", []],
    ];
    const out = sortCategoryEntries(entries, order);
    expect(out[0][0]).toBe("alpha");
    expect(out[1][0]).toBe("zebra");
  });
  it("handles empty entries", () => {
    expect(sortCategoryEntries<string>([] as Array<[string, string[]]>, order)).toEqual([] as Array<[string, string[]]>);
  });
});

describe("computeTotalPermissionCount", () => {
  it("sums items across categories", () => {
    expect(computeTotalPermissionCount<number>([
      ["a", [1, 2, 3]],
      ["b", [1, 2]],
    ])).toBe(5);
  });
  it("handles empty entries", () => {
    expect(computeTotalPermissionCount<number>([])).toBe(0);
  });
  it("handles empty categories", () => {
    expect(computeTotalPermissionCount<number>([["a", []], ["b", []]])).toBe(0);
  });
});

describe("categoryLabel", () => {
  it("returns known label", () => {
    expect(categoryLabel("dashboard")).toBe("仪表盘");
  });
  it("falls back to replacing underscores", () => {
    expect(categoryLabel("unknown_category")).toBe("unknown category");
  });
});

describe("categoryDescription", () => {
  it("returns known description", () => {
    expect(categoryDescription("dashboard")).toBe("统计概览与运营数据");
  });
  it("falls back to default text", () => {
    expect(categoryDescription("unknown")).toBe("该模块下的功能访问与操作权限");
  });
});

describe("resourceLabel", () => {
  it("returns known label", () => {
    expect(resourceLabel("question")).toBe("题目");
  });
  it("falls back to replacing hyphens and underscores", () => {
    expect(resourceLabel("unknown-resource")).toBe("unknown resource");
  });
});

describe("actionLabel", () => {
  it("returns known label", () => {
    expect(actionLabel("read")).toBe("查看");
  });
  it("falls back to replacing hyphens", () => {
    expect(actionLabel("unknown-action")).toBe("unknown action");
  });
});

describe("actionIndex", () => {
  it("returns index for known action", () => {
    expect(actionIndex("read")).toBe(0);
    expect(actionIndex("delete")).toBe(4);
  });
  it("returns MAX_SAFE_INTEGER for unknown action", () => {
    expect(actionIndex("unknown")).toBe(Number.MAX_SAFE_INTEGER);
  });
});

describe("samePermissionSet", () => {
  it("true for same sets", () => {
    expect(samePermissionSet([1, 2, 3], [3, 2, 1])).toBe(true);
  });
  it("false for different sizes", () => {
    expect(samePermissionSet([1, 2], [1, 2, 3])).toBe(false);
  });
  it("false for same size different elements", () => {
    expect(samePermissionSet([1, 2, 3], [1, 2, 4])).toBe(false);
  });
  it("true for both empty", () => {
    expect(samePermissionSet([], [])).toBe(true);
  });
  it("accepts Set arguments", () => {
    expect(samePermissionSet(new Set([1, 2]), new Set([2, 1]))).toBe(true);
  });
});

describe("buildMatrixRows", () => {
  const permissions: Permission[] = [
    { id: 1, name: "question:read", resource: "question", action: "read", description: null, category: "question" },
    { id: 2, name: "question:delete", resource: "question", action: "delete", description: null, category: "question" },
    { id: 3, name: "subject:read", resource: "subject", action: "read", description: null, category: "subject" },
  ];
  it("groups permissions by resource", () => {
    const rows = buildMatrixRows(permissions);
    expect(rows).toHaveLength(2);
    expect(rows[0].resource).toBe("question");
    expect(rows[0].permissions).toHaveLength(2);
  });
  it("builds byAction map", () => {
    const rows = buildMatrixRows(permissions);
    expect(rows[0].byAction.get("read")?.id).toBe(1);
    expect(rows[0].byAction.get("delete")?.id).toBe(2);
  });
  it("returns empty for empty input", () => {
    expect(buildMatrixRows([])).toEqual([]);
  });
});

describe("permissionMatches", () => {
  const perm: Permission = {
    id: 1, name: "question:read", resource: "question", action: "read", description: "查看题目", category: "question",
  };
  it("matches by name", () => {
    expect(permissionMatches(perm, "question", "question:read")).toBe(true);
  });
  it("matches by action label", () => {
    expect(permissionMatches(perm, "question", "查看")).toBe(true);
  });
  it("matches by description", () => {
    expect(permissionMatches(perm, "question", "查看题目")).toBe(true);
  });
  it("matches by category label", () => {
    expect(permissionMatches(perm, "question", "题库管理")).toBe(true);
  });
  it("does not match unrelated keyword", () => {
    expect(permissionMatches(perm, "question", "nonexistent")).toBe(false);
  });
  it("matches empty keyword (substring of all)", () => {
    expect(permissionMatches(perm, "question", "")).toBe(true);
  });
});
