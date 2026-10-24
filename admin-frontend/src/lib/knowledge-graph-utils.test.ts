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
