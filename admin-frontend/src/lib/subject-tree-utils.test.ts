import { describe, it, expect } from "vitest";
import {
  flattenSubjects,
  buildSubjectRelations,
  summarizeSubjects,
  scopeLabel,
  scopeTone,
  updateSubjectTreeStatus,
} from "./subject-tree-utils";
import type { AdminSubjectNode } from "./api/types";

const makeNode = (id: number, overrides: Partial<AdminSubjectNode> = {}): AdminSubjectNode => ({
  id, parent_id: null, code: `s${id}`, name: `科目${id}`, level: 1,
  path: `/s${id}`, sort_order: id, is_active: true,
  created_at: "", updated_at: "", children: [],
  ...overrides,
});

const tree: AdminSubjectNode[] = [
  makeNode(1, {
    name: "根科目", is_product_root: true, product_scope: "product",
    children: [
      makeNode(2, { name: "数据结构", product_scope: "exam408", parent_id: 1 }),
      makeNode(3, { name: "操作系统", product_scope: "exam408", parent_id: 1, is_active: false,
        children: [makeNode(4, { name: "进程", parent_id: 3 })],
      }),
    ],
  }),
];

describe("flattenSubjects", () => {
  it("flattens with depth", () => {
    const flat = flattenSubjects(tree);
    expect(flat).toHaveLength(4);
    expect(flat[0].depth).toBe(0);
    expect(flat[3].depth).toBe(2);
  });
  it("handles empty", () => {
    expect(flattenSubjects([])).toEqual([]);
  });
});

describe("buildSubjectRelations", () => {
  it("builds active descendants map", () => {
    const { activeDescendantsById } = buildSubjectRelations(tree);
    expect(activeDescendantsById.get(1)).toHaveLength(2); // nodes 2 and 4 are active descendants of 1
  });
  it("builds inactive ancestors map", () => {
    const { inactiveAncestorsById } = buildSubjectRelations(tree);
    // Node 4 has ancestor 3 which is inactive
    expect(inactiveAncestorsById.get(4)).toHaveLength(1);
  });
  it("node 3 has no inactive ancestors", () => {
    const { inactiveAncestorsById } = buildSubjectRelations(tree);
    expect(inactiveAncestorsById.get(3)).toHaveLength(0);
  });
  it("empty tree returns empty maps", () => {
    const { activeDescendantsById, inactiveAncestorsById } = buildSubjectRelations([]);
    expect(activeDescendantsById.size).toBe(0);
    expect(inactiveAncestorsById.size).toBe(0);
  });
});

describe("summarizeSubjects", () => {
  const subjects = [makeNode(1), makeNode(2), makeNode(3), makeNode(4), makeNode(5)];
  it("joins names when <= max", () => {
    expect(summarizeSubjects(subjects.slice(0, 3))).toBe("科目1、科目2、科目3");
  });
  it("adds count when > max", () => {
    expect(summarizeSubjects(subjects)).toBe("科目1、科目2、科目3 等 5 个科目");
  });
  it("handles empty", () => {
    expect(summarizeSubjects([])).toBe("");
  });
  it("respects custom max", () => {
    expect(summarizeSubjects(subjects, 2)).toBe("科目1、科目2 等 5 个科目");
  });
});

describe("scopeLabel", () => {
  it("returns 产品根科目 for root", () => {
    expect(scopeLabel(makeNode(1, { is_product_root: true }))).toBe("产品根科目");
  });
  it("returns 核心科目 for exam408", () => {
    expect(scopeLabel(makeNode(1, { product_scope: "exam408" }))).toBe("核心科目");
  });
  it("returns 扩展科目 for others", () => {
    expect(scopeLabel(makeNode(1, { product_scope: "custom" }))).toBe("扩展科目");
  });
});

describe("scopeTone", () => {
  it("accent for exam408", () => {
    expect(scopeTone(makeNode(1, { product_scope: "exam408" }))).toBe("accent");
  });
  it("neutral for others", () => {
    expect(scopeTone(makeNode(1, { product_scope: "custom" }))).toBe("neutral");
  });
});

describe("updateSubjectTreeStatus", () => {
  it("deactivates subject and descendants", () => {
    const updated = updateSubjectTreeStatus(tree, 1, false);
    expect(updated[0].is_active).toBe(false);
  });
  it("deactivates descendants too", () => {
    const updated = updateSubjectTreeStatus(tree, 1, false);
    expect(updated[0].children[0].is_active).toBe(true);  // node 2 not targeted, stays active
  });
  it("activates path to target", () => {
    const updated = updateSubjectTreeStatus(tree, 4, true);
    // Node 3 (parent of 4) should be activated
    const node3 = updated[0].children.find((c) => c.id === 3);
    expect(node3?.is_active).toBe(true);
    // Node 4 should be active
    const node4 = node3?.children.find((c) => c.id === 4);
    expect(node4?.is_active).toBe(true);
  });
  it("does not activate siblings when activating", () => {
    const updated = updateSubjectTreeStatus(tree, 4, true);
    const node2 = updated[0].children.find((c) => c.id === 2);
    expect(node2?.is_active).toBe(true); // already active
  });
});
