/**
 * Graph layout algorithm for knowledge-graph page, extracted from
 * knowledge-graph/page.tsx buildLayout. Computes radial-tree positions
 * with iterative collision relaxation.
 */

import type { KnowledgeGraphEdge, KnowledgeGraphNode } from "@/lib/api/types";
import {
  clamp,
  edgeStrength,
  nodeRadius,
  estimatedLabelWidth,
} from "@/lib/knowledge-graph-utils";

export type PositionedNode = KnowledgeGraphNode & { x: number; y: number; level: number };

/**
 * Compute radial-tree layout positions for knowledge-graph nodes.
 * Uses BFS to assign levels, then places nodes in concentric rings
 * around the root, and performs iterative rectangle+label collision
 * relaxation to prevent overlapping.
 */
export function buildLayout(
  nodes: KnowledgeGraphNode[],
  edges: KnowledgeGraphEdge[],
  focusId: number | null,
  activeId: number | null,
  variant: number,
): PositionedNode[] {
  if (nodes.length === 0) return [];

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const adjacency = new Map<number, Array<{ id: number; strength: number }>>();
  for (const node of nodes) adjacency.set(node.id, []);
  for (const edge of edges) {
    if (!nodeMap.has(edge.source) || !nodeMap.has(edge.target)) continue;
    const strength = edgeStrength(edge);
    adjacency.get(edge.source)?.push({ id: edge.target, strength });
    adjacency.get(edge.target)?.push({ id: edge.source, strength });
  }
  for (const entries of adjacency.values()) {
    entries.sort((a, b) => b.strength - a.strength || (nodeMap.get(b.id)?.degree ?? 0) - (nodeMap.get(a.id)?.degree ?? 0));
  }

  const rootId = focusId && nodeMap.has(focusId)
    ? focusId
    : [...nodes].sort((a, b) => b.degree - a.degree || b.question_count - a.question_count)[0].id;
  const collisionFocusId = activeId != null && nodeMap.has(activeId) ? activeId : rootId;
  const collisionFocusNeighbors = new Set((adjacency.get(collisionFocusId) ?? []).slice(0, 16).map((item) => item.id));

  const levels = new Map<number, number>([[rootId, 0]]);
  const parents = new Map<number, number>();
  const queue = [rootId];
  while (queue.length) {
    const current = queue.shift()!;
    const level = levels.get(current) ?? 0;
    for (const neighbor of adjacency.get(current) ?? []) {
      if (levels.has(neighbor.id)) continue;
      levels.set(neighbor.id, level + 1);
      parents.set(neighbor.id, current);
      queue.push(neighbor.id);
    }
  }

  const reachableLevels = [...levels.values()];
  const fallbackLevel = (reachableLevels.length ? Math.max(...reachableLevels) : 0) + 1;
  const disconnected = nodes.filter((node) => !levels.has(node.id));
  for (const node of disconnected) levels.set(node.id, fallbackLevel);

  const centerX = 500;
  const centerY = 355;
  const targetPositions = new Map<number, { x: number; y: number; level: number }>();
  targetPositions.set(rootId, { x: centerX, y: centerY, level: 0 });

  const levelOne = nodes
    .filter((node) => levels.get(node.id) === 1)
    .sort((a, b) => b.degree - a.degree || b.question_count - a.question_count || a.id - b.id);
  const levelOneAngles = new Map<number, number>();
  const levelOneCount = Math.max(levelOne.length, 1);
  const startAngle = -Math.PI / 2 + (variant % 12) * 0.055;
  const levelOneRx = Math.min(372, 252 + levelOneCount * 5.2);
  const levelOneRy = Math.min(272, 190 + levelOneCount * 3.8);
  levelOne.forEach((node, index) => {
    const angle = startAngle + (Math.PI * 2 * index) / levelOneCount;
    levelOneAngles.set(node.id, angle);
    targetPositions.set(node.id, {
      x: centerX + Math.cos(angle) * levelOneRx,
      y: centerY + Math.sin(angle) * levelOneRy,
      level: 1,
    });
  });

  function firstBranch(nodeId: number) {
    let current = nodeId;
    let safety = 0;
    while ((levels.get(current) ?? fallbackLevel) > 1 && safety < 12) {
      current = parents.get(current) ?? current;
      safety += 1;
    }
    return current;
  }

  const maxReachableLevel = Math.max(1, ...reachableLevels);
  for (let level = 2; level <= maxReachableLevel; level += 1) {
    const bucket = nodes.filter((node) => levels.get(node.id) === level);
    const byBranch = new Map<number, KnowledgeGraphNode[]>();
    for (const node of bucket) {
      const branch = firstBranch(node.id);
      const group = byBranch.get(branch) ?? [];
      group.push(node);
      byBranch.set(branch, group);
    }

    const radiusX = Math.min(442, levelOneRx + (level - 1) * 118);
    const radiusY = Math.min(306, levelOneRy + (level - 1) * 86);
    for (const [branch, group] of byBranch.entries()) {
      const branchAngle = levelOneAngles.get(branch) ?? startAngle;
      group.sort((a, b) => b.degree - a.degree || a.id - b.id);
      const spread = Math.min(0.82, Math.max(0.18, (group.length - 1) * 0.13));
      group.forEach((node, index) => {
        const offset = group.length <= 1 ? 0 : -spread / 2 + (spread * index) / (group.length - 1);
        const angle = branchAngle + offset;
        targetPositions.set(node.id, {
          x: centerX + Math.cos(angle) * radiusX,
          y: centerY + Math.sin(angle) * radiusY,
          level,
        });
      });
    }
  }

  if (disconnected.length) {
    const radiusX = 440;
    const radiusY = 305;
    disconnected
      .sort((a, b) => b.degree - a.degree || a.id - b.id)
      .forEach((node, index) => {
        const angle = startAngle + (Math.PI * 2 * index) / Math.max(1, disconnected.length);
        targetPositions.set(node.id, {
          x: centerX + Math.cos(angle) * radiusX,
          y: centerY + Math.sin(angle) * radiusY,
          level: fallbackLevel,
        });
      });
  }

  const positioned = nodes.map((node) => {
    const target = targetPositions.get(node.id) ?? { x: centerX, y: centerY, level: fallbackLevel };
    return { ...node, ...target };
  });
  const targetMap = new Map(positioned.map((node) => [node.id, { x: node.x, y: node.y }]));

  function collisionBox(node: PositionedNode) {
    const radius = nodeRadius(node);
    const hasVisibleLabel = node.id === rootId
      || node.level <= 1
      || node.degree >= 7
      || node.id === collisionFocusId
      || collisionFocusNeighbors.has(node.id);
    const labelWidth = hasVisibleLabel ? estimatedLabelWidth(node) : 0;
    const labelHeight = hasVisibleLabel ? (node.id === rootId ? 34 : 20) : 0;
    return {
      halfWidth: Math.max(radius + 12, labelWidth / 2 + 10),
      halfHeight: radius + 12 + labelHeight * 0.58,
    };
  }

  for (let pass = 0; pass < 92; pass += 1) {
    for (let i = 0; i < positioned.length; i += 1) {
      for (let j = i + 1; j < positioned.length; j += 1) {
        const a = positioned[i];
        const b = positioned[j];
        const aBox = collisionBox(a);
        const bBox = collisionBox(b);
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) {
          dx = ((a.id * 17 + b.id * 29 + variant) % 9) - 4;
          dy = ((a.id * 31 + b.id * 11 + variant) % 9) - 4;
        }

        const directRingPair = a.level <= 1 && b.level <= 1;
        const activeNeighborhoodPair = (a.id === collisionFocusId || collisionFocusNeighbors.has(a.id))
          && (b.id === collisionFocusId || collisionFocusNeighbors.has(b.id));
        const touchesActive = a.id === collisionFocusId || b.id === collisionFocusId;
        const extraGap = touchesActive ? 58 : activeNeighborhoodPair ? 44 : directRingPair ? 26 : a.level === b.level ? 16 : 10;
        const overlapX = aBox.halfWidth + bBox.halfWidth + extraGap - Math.abs(dx);
        const overlapY = aBox.halfHeight + bBox.halfHeight + extraGap - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;

        if (overlapX < overlapY) {
          const direction = dx >= 0 ? 1 : -1;
          const push = overlapX * 0.53;
          if (a.id !== rootId) a.x -= direction * push;
          if (b.id !== rootId) b.x += direction * push;
        } else {
          const direction = dy >= 0 ? 1 : -1;
          const push = overlapY * 0.53;
          if (a.id !== rootId) a.y -= direction * push;
          if (b.id !== rootId) b.y += direction * push;
        }
      }
    }

    for (const node of positioned) {
      if (node.id === rootId) {
        node.x = centerX;
        node.y = centerY;
        continue;
      }
      const target = targetMap.get(node.id)!;
      node.x += (target.x - node.x) * 0.026;
      node.y += (target.y - node.y) * 0.026;
      node.x = clamp(node.x, 66, 934);
      node.y = clamp(node.y, 58, 646);
    }
  }

  const activeNode = positioned.find((node) => node.id === collisionFocusId);
  if (activeNode) {
    const directIds = new Set((adjacency.get(collisionFocusId) ?? []).slice(0, 14).map((item) => item.id));
    const activeRadius = nodeRadius(activeNode);
    for (let pass = 0; pass < 26; pass += 1) {
      for (const node of positioned) {
        if (!directIds.has(node.id) || node.id === rootId) continue;
        let dx = node.x - activeNode.x;
        let dy = node.y - activeNode.y;
        let distance = Math.hypot(dx, dy);
        if (distance < 0.001) {
          dx = ((node.id * 19 + variant) % 7) - 3;
          dy = ((node.id * 23 + variant) % 7) - 3;
          distance = Math.max(1, Math.hypot(dx, dy));
        }
        const labelAllowance = Math.min(44, estimatedLabelWidth(node) * 0.16);
        const desiredDistance = activeRadius + nodeRadius(node) + 62 + labelAllowance;
        if (distance >= desiredDistance) continue;
        const push = (desiredDistance - distance) * 0.44;
        node.x += (dx / distance) * push;
        node.y += (dy / distance) * push;
        node.x = clamp(node.x, 74, 926);
        node.y = clamp(node.y, 66, 638);
      }
    }
  }

  return positioned;
}
