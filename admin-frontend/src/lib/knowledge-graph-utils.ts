/**
 * Pure helpers for knowledge graph page, extracted from knowledge-graph/page.tsx.
 */

import type { KnowledgeGraphNode, KnowledgeGraphEdge } from "@/lib/api/types";

export const RELATIONS = {
  prerequisite: { label: "前置", color: "#4a6f8a", text: "学习目标所依赖的基础知识" },
  parent: { label: "父子", color: "#5b8c5b", text: "概念与细分知识点的层级关系" },
  next: { label: "后续", color: "#c49a6b", text: "掌握当前知识后自然衔接的节点" },
  related: { label: "相关", color: "#8b7c97", text: "没有强依赖但语义关联紧密" },
} as const;

export type RelationKey = keyof typeof RELATIONS;

export function shortName(name: string, length = 9): string {
  return name.length > length ? `${name.slice(0, length)}…` : name;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function edgeStrength(edge: KnowledgeGraphEdge): number {
  const normalizedWeight = clamp(edge.weight / 10, 0, 1);
  return edge.confidence * 0.76 + normalizedWeight * 0.24;
}

export function collapseEdgesByPair(edges: KnowledgeGraphEdge[]): KnowledgeGraphEdge[] {
  const byPair = new Map<string, KnowledgeGraphEdge>();
  for (const edge of edges) {
    const key = edge.source < edge.target ? `${edge.source}:${edge.target}` : `${edge.target}:${edge.source}`;
    const current = byPair.get(key);
    if (!current || edgeStrength(edge) > edgeStrength(current)) byPair.set(key, edge);
  }
  return [...byPair.values()];
}

export function nodeRadius(node: KnowledgeGraphNode): number {
  return clamp(16 + Math.sqrt(Math.max(0, node.degree)) * 2.05, 18, 28);
}

export function estimatedLabelWidth(node: KnowledgeGraphNode): number {
  const text = shortName(node.name, 11);
  return clamp(text.length * 10.8 + 18, 54, 154);
}

export function relationLabel(type: string): string {
  return RELATIONS[type as RelationKey]?.label ?? type;
}

export function relationColor(type: string): string {
  return RELATIONS[type as RelationKey]?.color ?? "#8a9ba9";
}

export function difficultyText(level: number): string {
  if (level <= 1) return "基础";
  if (level === 2) return "较易";
  if (level === 3) return "中等";
  if (level === 4) return "较难";
  return "进阶";
}
