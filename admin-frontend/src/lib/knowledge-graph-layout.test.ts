import { describe, it, expect } from "vitest";
import { buildLayout } from "./knowledge-graph-layout";
import type { KnowledgeGraphEdge, KnowledgeGraphNode } from "@/lib/api/types";

const makeNode = (id: number, degree = 1): KnowledgeGraphNode => ({
  id,
  name: `N${id}`,
  normalized_name: `n${id}`,
  aliases: [],
  description: null,
  difficulty_level: 0,
  subject_id: 1,
  question_count: 0,
  in_degree: 0,
  out_degree: 0,
  degree,
  relation_counts: {},
});

const makeEdge = (source: number, target: number): KnowledgeGraphEdge => ({
  id: source * 1000 + target,
  source,
  target,
  relation_type: "prerequisite",
  weight: 5,
  confidence: 0.8,
  source_type: "manual",
});

describe("buildLayout", () => {
  it("returns empty for empty nodes", () => {
    expect(buildLayout([], [], null, null, 0)).toEqual([]);
  });

  it("positions single node at center", () => {
    const nodes = [makeNode(1, 0)];
    const out = buildLayout(nodes, [], 1, null, 0);
    expect(out).toHaveLength(1);
    expect(out[0].x).toBe(500);
    expect(out[0].y).toBe(355);
    expect(out[0].level).toBe(0);
  });

  it("assigns level 0 to root (highest degree)", () => {
    const nodes = [makeNode(1, 5), makeNode(2, 1), makeNode(3, 1)];
    const edges = [makeEdge(1, 2), makeEdge(1, 3)];
    const out = buildLayout(nodes, edges, null, null, 0);
    const root = out.find((n) => n.id === 1);
    expect(root?.level).toBe(0);
  });

  it("assigns level 1 to direct neighbors", () => {
    const nodes = [makeNode(1, 2), makeNode(2, 1), makeNode(3, 1)];
    const edges = [makeEdge(1, 2), makeEdge(1, 3)];
    const out = buildLayout(nodes, edges, null, null, 0);
    expect(out.find((n) => n.id === 2)?.level).toBe(1);
    expect(out.find((n) => n.id === 3)?.level).toBe(1);
  });

  it("respects focusId when provided", () => {
    const nodes = [makeNode(1, 1), makeNode(2, 5), makeNode(3, 1)];
    const edges = [makeEdge(2, 1), makeEdge(2, 3)];
    // focusId=1 forces node 1 as root even though node 2 has higher degree
    const out = buildLayout(nodes, edges, 1, null, 0);
    expect(out.find((n) => n.id === 1)?.level).toBe(0);
  });

  it("positions are within canvas bounds", () => {
    const nodes = Array.from({ length: 20 }, (_, i) => makeNode(i + 1, 20 - i));
    const edges: KnowledgeGraphEdge[] = [];
    for (let i = 1; i < 20; i++) edges.push(makeEdge(1, i + 1));
    const out = buildLayout(nodes, edges, null, null, 0);
    for (const node of out) {
      expect(node.x).toBeGreaterThanOrEqual(66);
      expect(node.x).toBeLessThanOrEqual(934);
      expect(node.y).toBeGreaterThanOrEqual(58);
      expect(node.y).toBeLessThanOrEqual(646);
    }
  });

  it("handles disconnected nodes", () => {
    const nodes = [makeNode(1, 1), makeNode(2, 0), makeNode(3, 0)];
    const out = buildLayout(nodes, [], null, null, 0);
    // Disconnected nodes should still get positions
    expect(out).toHaveLength(3);
    expect(out.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
  });

  it("variant affects layout for deterministic variation", () => {
    const nodes = [makeNode(1, 3), makeNode(2, 1), makeNode(3, 1), makeNode(4, 1)];
    const edges = [makeEdge(1, 2), makeEdge(1, 3), makeEdge(1, 4)];
    const out0 = buildLayout(nodes, edges, null, null, 0);
    const out1 = buildLayout(nodes, edges, null, null, 1);
    // Root should be the same, but level-1 angles differ
    expect(out0[0].x).toBe(out1[0].x);
    // At least one non-root node should have different position
    const diff = out0.some((n, i) =>
      n.id !== 1 && (Math.abs(n.x - out1[i].x) > 0.1 || Math.abs(n.y - out1[i].y) > 0.1),
    );
    expect(diff).toBe(true);
  });

  it("returns PositionedNode type with x, y, level", () => {
    const nodes = [makeNode(1, 0)];
    const out = buildLayout(nodes, [], null, null, 0);
    expect(out[0]).toHaveProperty("x");
    expect(out[0]).toHaveProperty("y");
    expect(out[0]).toHaveProperty("level");
    expect(out[0]).toHaveProperty("name");
  });
});
