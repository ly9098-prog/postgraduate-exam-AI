import { describe, it, expect } from "vitest";
import {
  shortName,
  clamp,
  edgeStrength,
  collapseEdgesByPair,
  nodeRadius,
  estimatedLabelWidth,
  relationLabel,
  relationColor,
  difficultyText,
} from "./knowledge-graph-utils";
import type { KnowledgeGraphEdge, KnowledgeGraphNode } from "./api/types";

function makeEdge(overrides: Partial<KnowledgeGraphEdge>): KnowledgeGraphEdge {
  return { id: 1, source: 1, target: 2, type: "prerequisite", weight: 5, confidence: 0.8, ...overrides } as KnowledgeGraphEdge;
}
function makeNode(overrides: Partial<KnowledgeGraphNode>): KnowledgeGraphNode {
  return { id: 1, name: "Test", degree: 3, level: 1, subject_id: 1, ...overrides } as KnowledgeGraphNode;
}

describe("shortName", () => {
  it("returns name when within length", () => { expect(shortName("abc", 9)).toBe("abc"); });
  it("truncates with ellipsis", () => { expect(shortName("abcdefghijk", 5)).toBe("abcde…"); });
  it("uses default length 9", () => { expect(shortName("abcdefghijk")).toBe("abcdefghi…"); });
});

describe("clamp", () => {
  it("clamps to min", () => { expect(clamp(-5, 0, 10)).toBe(0); });
  it("clamps to max", () => { expect(clamp(15, 0, 10)).toBe(10); });
  it("returns value when in range", () => { expect(clamp(5, 0, 10)).toBe(5); });
});

describe("edgeStrength", () => {
  it("computes weighted blend", () => {
    const e = makeEdge({ weight: 10, confidence: 1.0 });
    expect(edgeStrength(e)).toBeCloseTo(1.0);
  });
  it("handles zero weight", () => {
    const e = makeEdge({ weight: 0, confidence: 0.5 });
    expect(edgeStrength(e)).toBeCloseTo(0.38);
  });
});

describe("collapseEdgesByPair", () => {
  it("keeps strongest edge per pair", () => {
    const edges = [
      makeEdge({ id: 1, source: 1, target: 2, confidence: 0.5, weight: 3 }),
      makeEdge({ id: 2, source: 2, target: 1, confidence: 0.9, weight: 8 }),
    ];
    const result = collapseEdgesByPair(edges);
    expect(result.length).toBe(1);
    expect(result[0].id).toBe(2);
  });
  it("preserves different pairs", () => {
    const edges = [
      makeEdge({ id: 1, source: 1, target: 2 }),
      makeEdge({ id: 2, source: 1, target: 3 }),
    ];
    expect(collapseEdgesByPair(edges).length).toBe(2);
  });
  it("handles empty array", () => { expect(collapseEdgesByPair([])).toEqual([]); });
});

describe("nodeRadius", () => {
  it("clamps to minimum 18", () => {
    expect(nodeRadius(makeNode({ degree: 0 }))).toBeGreaterThanOrEqual(18);
  });
  it("clamps to maximum 28", () => {
    expect(nodeRadius(makeNode({ degree: 1000 }))).toBeLessThanOrEqual(28);
  });
  it("scales with degree", () => {
    const r1 = nodeRadius(makeNode({ degree: 1 }));
    const r2 = nodeRadius(makeNode({ degree: 16 }));
    expect(r2).toBeGreaterThan(r1);
  });
});

describe("estimatedLabelWidth", () => {
  it("clamps to minimum 54", () => {
    expect(estimatedLabelWidth(makeNode({ name: "A" }))).toBeGreaterThanOrEqual(54);
  });
  it("clamps to maximum 154", () => {
    expect(estimatedLabelWidth(makeNode({ name: "非常长的知识点名称超过限制" }))).toBeLessThanOrEqual(154);
  });
});

describe("relationLabel", () => {
  it("returns label for known type", () => { expect(relationLabel("prerequisite")).toBe("前置"); });
  it("returns type for unknown type", () => { expect(relationLabel("unknown")).toBe("unknown"); });
});

describe("relationColor", () => {
  it("returns color for known type", () => { expect(relationColor("parent")).toBe("#5b8c5b"); });
  it("returns default for unknown type", () => { expect(relationColor("unknown")).toBe("#8a9ba9"); });
});

describe("difficultyText", () => {
  it("returns 基础 for level <= 1", () => { expect(difficultyText(0)).toBe("基础"); expect(difficultyText(1)).toBe("基础"); });
  it("returns 较易 for level 2", () => { expect(difficultyText(2)).toBe("较易"); });
  it("returns 中等 for level 3", () => { expect(difficultyText(3)).toBe("中等"); });
  it("returns 较难 for level 4", () => { expect(difficultyText(4)).toBe("较难"); });
  it("returns 进阶 for level > 4", () => { expect(difficultyText(5)).toBe("进阶"); });
});

import { selectDefaultSubject, buildDonutStops, computeDonutTotal } from "./knowledge-graph-utils";
import type { KnowledgeGraphSubject } from "./api/types";

const subjects: KnowledgeGraphSubject[] = [
  { id: 1, code: "computer_network", name: "计算机网络", level: 1, path: "/cn", knowledge_point_count: 50, edge_count: 80 },
  { id: 2, code: "data_structure", name: "数据结构", level: 1, path: "/ds", knowledge_point_count: 60, edge_count: 100 },
  { id: 3, code: "operating_system", name: "操作系统", level: 1, path: "/os", knowledge_point_count: 40, edge_count: 70 },
];

describe("selectDefaultSubject", () => {
  it("prefers data_structure by code", () => {
    expect(selectDefaultSubject(subjects)?.id).toBe(2);
  });
  it("prefers 数据结构 by name when no code match", () => {
    const s = [{ ...subjects[0], code: "ds", name: "数据结构" }];
    expect(selectDefaultSubject(s)?.name).toBe("数据结构");
  });
  it("falls back to highest edge_count", () => {
    const s = [
      { ...subjects[0], code: "x", name: "Other", edge_count: 50 },
      { ...subjects[2], code: "y", name: "Another", edge_count: 200 },
    ];
    expect(selectDefaultSubject(s)?.id).toBe(subjects[2].id);
  });
  it("falls back to highest knowledge_point_count when edges equal", () => {
    const s = [
      { id: 1, code: "a", name: "A", level: 1, path: "", knowledge_point_count: 10, edge_count: 50 },
      { id: 2, code: "b", name: "B", level: 1, path: "", knowledge_point_count: 20, edge_count: 50 },
    ];
    expect(selectDefaultSubject(s)?.id).toBe(2);
  });
  it("returns undefined for empty list", () => {
    expect(selectDefaultSubject([])).toBeUndefined();
  });
});

describe("buildDonutStops", () => {
  it("returns empty for all-zero counts", () => {
    expect(buildDonutStops({})).toEqual([]);
  });
  it("builds single stop when one relation", () => {
    const stops = buildDonutStops({ prerequisite: 5 });
    expect(stops).toHaveLength(1);
    expect(stops[0]).toContain("0%");
    expect(stops[0]).toContain("100%");
  });
  it("builds multiple stops proportionally", () => {
    const stops = buildDonutStops({ prerequisite: 3, related: 1 });
    expect(stops).toHaveLength(2);
    expect(stops[0]).toContain("0%");
    expect(stops[0]).toContain("75%");
    expect(stops[1]).toContain("75%");
    expect(stops[1]).toContain("100%");
  });
  it("handles NaN values as 0", () => {
    expect(buildDonutStops({ prerequisite: NaN })).toEqual([]);
  });
});

describe("computeDonutTotal", () => {
  it("sums all relation counts", () => {
    expect(computeDonutTotal({ prerequisite: 3, related: 2, next: 1 })).toBe(6);
  });
  it("returns 0 for empty", () => {
    expect(computeDonutTotal({})).toBe(0);
  });
  it("treats NaN as 0", () => {
    expect(computeDonutTotal({ prerequisite: NaN, related: 3 })).toBe(3);
  });
});
