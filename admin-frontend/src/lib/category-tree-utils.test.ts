import { describe, it, expect } from "vitest";
import {
  findNodeInTree,
  findParentNode,
  findPathToNode,
  countDescendants,
  filterCategoryTree,
  type CategoryTreeNode,
} from "./category-tree-utils";

interface Node extends CategoryTreeNode<Node> { extra?: string; }

const tree: Node[] = [
  {
    id: 1, name: "网络", code: "NET", children: [
      { id: 3, name: "传输层", code: "TCP", children: [] },
      { id: 4, name: "应用层", code: "APP", children: [
        { id: 5, name: "HTTP", code: "HTTP", children: [] },
      ] },
    ],
  },
  { id: 2, name: "数据结构", code: "DS", children: [] },
];

describe("findNodeInTree", () => {
  it("finds root node", () => {
    expect(findNodeInTree(tree, 1)?.id).toBe(1);
  });
  it("finds deeply nested node", () => {
    expect(findNodeInTree(tree, 5)?.id).toBe(5);
  });
  it("returns null for missing id", () => {
    expect(findNodeInTree(tree, 99)).toBeNull();
  });
  it("returns null for null id", () => {
    expect(findNodeInTree(tree, null)).toBeNull();
  });
  it("handles empty tree", () => {
    expect(findNodeInTree([], 1)).toBeNull();
  });
});

describe("findParentNode", () => {
  it("returns null for root node (no parent)", () => {
    expect(findParentNode(tree, 1)).toBeNull();
  });
  it("finds parent of nested node", () => {
    expect(findParentNode(tree, 5)?.id).toBe(4);
  });
  it("returns null for missing id", () => {
    expect(findParentNode(tree, 99)).toBeNull();
  });
  it("returns null for null id", () => {
    expect(findParentNode(tree, null)).toBeNull();
  });
});

describe("findPathToNode", () => {
  it("returns path to root", () => {
    expect(findPathToNode(tree, 1).map((n) => n.id)).toEqual([1]);
  });
  it("returns full path to deep node", () => {
    expect(findPathToNode(tree, 5).map((n) => n.id)).toEqual([1, 4, 5]);
  });
  it("returns empty for missing id", () => {
    expect(findPathToNode(tree, 99)).toEqual([]);
  });
  it("returns empty for null id", () => {
    expect(findPathToNode(tree, null)).toEqual([]);
  });
});

describe("countDescendants", () => {
  it("counts all descendants", () => {
    expect(countDescendants(tree[0])).toBe(3);
  });
  it("returns 0 for leaf node", () => {
    expect(countDescendants(tree[1])).toBe(0);
  });
  it("returns 0 for null", () => {
    expect(countDescendants(null)).toBe(0);
  });
});

describe("filterCategoryTree", () => {
  it("returns original tree when query empty", () => {
    expect(filterCategoryTree(tree, "")).toBe(tree);
  });
  it("filters by name", () => {
    expect(filterCategoryTree(tree, "数据")).toHaveLength(1);
    expect(filterCategoryTree(tree, "数据")[0].id).toBe(2);
  });
  it("filters by code", () => {
    expect(filterCategoryTree(tree, "NET")).toHaveLength(1);
  });
  it("keeps parent when child matches", () => {
    const out = filterCategoryTree(tree, "HTTP");
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe(1);
    expect(out[0].children).toHaveLength(1);
    expect(out[0].children![0].id).toBe(4);
  });
  it("case-insensitive", () => {
    expect(filterCategoryTree(tree, "app")).toHaveLength(1);
  });
  it("returns empty for no match", () => {
    expect(filterCategoryTree(tree, "不存在")).toEqual([]);
  });
  it("does not mutate input", () => {
    const snapshot = JSON.stringify(tree);
    filterCategoryTree(tree, "传输");
    expect(JSON.stringify(tree)).toBe(snapshot);
  });
});
