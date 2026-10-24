"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  Download,
  Focus,
  GitBranch,
  LayoutGrid,
  Maximize2,
  Minimize2,
  Minus,
  Network,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { apiRequest, toQuery } from "@/lib/api/client";
import type {
  KnowledgeGraphEdge,
  KnowledgeGraphNode,
  KnowledgeGraphResponse,
  KnowledgeGraphSubject,
} from "@/lib/api/types";
import {
  RELATIONS,
  shortName,
  clamp,
  edgeStrength,
  collapseEdgesByPair,
  nodeRadius,
  estimatedLabelWidth,
  relationLabel,
  relationColor,
  difficultyText,
  type RelationKey,
  selectDefaultSubject,
  buildDonutStops,
  computeDonutTotal,
} from "@/lib/knowledge-graph-utils";
import {
  cubicPoint,
  cubicUnitNormal,
  segmentsProperlyIntersect,
  polylineIntersectionCount,
  getNodeLabelPlacement,
  type NodeLabelPlacement,
} from "@/lib/knowledge-graph-geometry";
import { cn } from "@/lib/utils";

import {
  buildLayout,
  type PositionedNode,
} from "@/lib/knowledge-graph-layout";


function GraphCanvas({
  data,
  selectedId,
  onSelect,
  onFocus,
  layoutVariant,
  zoom,
  pan,
  onZoomChange,
  onPanChange,
}: {
  data: KnowledgeGraphResponse;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onFocus: (id: number) => void;
  layoutVariant: number;
  zoom: number;
  pan: { x: number; y: number };
  onZoomChange: (value: number) => void;
  onPanChange: (value: { x: number; y: number }) => void;
}) {
  const dragRef = useRef<{ pointerId: number; x: number; y: number; panX: number; panY: number } | null>(null);
  // Keep the physical layout stable while users inspect different nodes. Selection now
  // only changes emphasis/relations; a new layout is produced only when data, focus or
  // the explicit layout variant changes.
  const nodes = useMemo(
    () => buildLayout(data.nodes, data.edges, data.focus_id, data.focus_id, layoutVariant),
    [data.nodes, data.edges, data.focus_id, layoutVariant],
  );
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  const primaryEdges = useMemo(() => {
    const activeId = selectedId ?? data.focus_id;
    const candidates = activeId == null
      ? data.edges
      : data.edges.filter((edge) => edge.source === activeId || edge.target === activeId);
    return collapseEdgesByPair(candidates)
      .sort((a, b) => edgeStrength(b) - edgeStrength(a))
      .slice(0, activeId == null ? 22 : 14);
  }, [data.edges, data.focus_id, selectedId]);

  const displayEdges = useMemo(() => {
    const activeId = selectedId ?? data.focus_id;
    // 选中节点后主画布只展示一跳关系。邻居之间的二级关系仍保留在详情数据中，
    // 但不同时绘制到画布，避免局部探索时出现“线网叠线”。
    if (activeId != null) return primaryEdges;

    return collapseEdgesByPair(data.edges)
      .sort((a, b) => edgeStrength(b) - edgeStrength(a))
      .slice(0, 18);
  }, [data.edges, data.focus_id, primaryEdges, selectedId]);

  const primaryEdgeIds = useMemo(() => new Set(primaryEdges.map((edge) => edge.id)), [primaryEdges]);
  const directNeighborIds = useMemo(() => {
    const activeId = selectedId ?? data.focus_id;
    const ids = new Set<number>();
    if (activeId == null) return ids;
    for (const edge of primaryEdges) ids.add(edge.source === activeId ? edge.target : edge.source);
    return ids;
  }, [data.focus_id, primaryEdges, selectedId]);
  const directRelationByNodeId = useMemo(() => {
    const activeId = selectedId ?? data.focus_id;
    const relations = new Map<number, KnowledgeGraphEdge>();
    if (activeId == null) return relations;
    for (const edge of primaryEdges) {
      const otherId = edge.source === activeId ? edge.target : edge.source;
      const current = relations.get(otherId);
      if (!current || edgeStrength(edge) > edgeStrength(current)) relations.set(otherId, edge);
    }
    return relations;
  }, [data.focus_id, primaryEdges, selectedId]);
  const showEdgeLabels = primaryEdges.length > 0 && primaryEdges.length <= 6;
  const activeNode = nodeMap.get(selectedId ?? data.focus_id ?? -1) ?? nodeMap.get(data.focus_id ?? -1) ?? null;
  const activeId = selectedId ?? data.focus_id;
  const activePortAngles = useMemo(() => {
    const angles = new Map<number, number>();
    if (activeId == null) return angles;
    const active = nodeMap.get(activeId);
    if (!active) return angles;

    type Side = "right" | "left" | "top" | "bottom";
    const groups: Record<Side, Array<{ edge: KnowledgeGraphEdge; other: PositionedNode }>> = {
      right: [], left: [], top: [], bottom: [],
    };

    for (const edge of primaryEdges) {
      const other = nodeMap.get(edge.source === activeId ? edge.target : edge.source);
      if (!other) continue;
      const dx = other.x - active.x;
      const dy = other.y - active.y;
      const side: Side = Math.abs(dx) >= Math.abs(dy)
        ? (dx >= 0 ? "right" : "left")
        : (dy >= 0 ? "bottom" : "top");
      groups[side].push({ edge, other });
    }

    const centers: Record<Side, number> = {
      right: 0,
      bottom: Math.PI / 2,
      left: Math.PI,
      top: -Math.PI / 2,
    };

    (Object.keys(groups) as Side[]).forEach((side) => {
      const entries = groups[side];
      entries.sort((a, b) => {
        if (side === "left" || side === "right") return a.other.y - b.other.y || a.other.id - b.other.id;
        return a.other.x - b.other.x || a.other.id - b.other.id;
      });
      const span = Math.min(0.82, Math.max(0, (entries.length - 1) * 0.17));
      entries.forEach((entry, index) => {
        const offset = entries.length <= 1 ? 0 : -span / 2 + (span * index) / (entries.length - 1);
        // SVG 圆周参数在 left / bottom 两侧的屏幕坐标顺序与 offset 方向相反：
        // - left: angle 增大时 y 反而减小
        // - bottom: angle 增大时 x 反而减小
        // 如果仍直接使用 +offset，同一侧邻居会被分配到“镜像端口”，两条曲线会在节点附近必然交叉。
        // 对这两侧翻转 offset，确保端口顺序与邻居在屏幕上的顺序一致。
        const orderedOffset = side === "left" || side === "bottom" ? -offset : offset;
        angles.set(entry.edge.id, centers[side] + orderedOffset);
      });
    });
    return angles;
  }, [activeId, nodeMap, primaryEdges]);

  const nodeVisuals = useMemo(() => new Map(nodes.map((node) => {
    const selected = node.id === selectedId;
    const focused = node.id === data.focus_id;
    const direct = directNeighborIds.has(node.id);
    const radius = nodeRadius(node) + (selected ? 4 : focused ? 2 : 0);
    const showLabel = selected || focused || direct || (selectedId == null && node.degree >= 7);
    const withMeta = selected || focused;
    return [node.id, {
      selected,
      focused,
      direct,
      radius,
      showLabel,
      withMeta,
      placement: getNodeLabelPlacement(node, activeNode, radius, withMeta, estimatedLabelWidth(node)),
    }];
  })), [activeNode, data.focus_id, directNeighborIds, nodes, selectedId]);

  const edgeGeometries = useMemo(() => {
    const occupiedLabels: Array<{ x: number; y: number; width: number; height: number }> = [];
    const labeledRelationTypes = new Set<string>();
    const routedPrimarySamples: Array<Array<{ x: number; y: number }>> = [];
    const routedPrimaryPolylines: Array<Array<{ x: number; y: number }>> = [];
    let visibleRelationLabelCount = 0;
    const geometries: Array<{
      edge: KnowledgeGraphEdge;
      source: PositionedNode;
      target: PositionedNode;
      primary: boolean;
      start: { x: number; y: number };
      end: { x: number; y: number };
      control1: { x: number; y: number };
      control2: { x: number; y: number };
      labelPoint: { x: number; y: number } | null;
    }> = [];

    for (const edge of displayEdges) {
      const source = nodeMap.get(edge.source);
      const target = nodeMap.get(edge.target);
      if (!source || !target) continue;
      const primary = primaryEdgeIds.has(edge.id);
      const sourceRadius = nodeVisuals.get(source.id)?.radius ?? nodeRadius(source);
      const targetRadius = nodeVisuals.get(target.id)?.radius ?? nodeRadius(target);
      const activeDirect = primary && activeId != null && (source.id === activeId || target.id === activeId);

      const baseDx = target.x - source.x;
      const baseDy = target.y - source.y;
      const baseLen = Math.max(1, Math.hypot(baseDx, baseDy));
      let sx = source.x + (baseDx / baseLen) * (sourceRadius + 5);
      let sy = source.y + (baseDy / baseLen) * (sourceRadius + 5);
      // 箭头尖端只与目标节点保留很小的视觉间隙。旧版预留 11~12px，
      // 会让箭头看起来悬空，尤其在曲线或关系标签附近容易失去“指向谁”的语义。
      let tx = target.x - (baseDx / baseLen) * (targetRadius + 3.5);
      let ty = target.y - (baseDy / baseLen) * (targetRadius + 3.5);

      // 直接关系采用“扇区端口”：同侧的多条边会沿圆周错开，避免中心节点旁形成线束。
      const activePortAngle = activeDirect ? activePortAngles.get(edge.id) : undefined;
      if (activePortAngle != null && activeId != null) {
        if (source.id === activeId) {
          sx = source.x + Math.cos(activePortAngle) * (sourceRadius + 7);
          sy = source.y + Math.sin(activePortAngle) * (sourceRadius + 7);
        }
        if (target.id === activeId) {
          tx = target.x + Math.cos(activePortAngle) * (targetRadius + 3.5);
          ty = target.y + Math.sin(activePortAngle) * (targetRadius + 3.5);
        }
      }

      const start = { x: sx, y: sy };
      const end = { x: tx, y: ty };
      const chordDx = end.x - start.x;
      const chordDy = end.y - start.y;
      const chordLen = Math.max(1, Math.hypot(chordDx, chordDy));
      const normal = { x: -chordDy / chordLen, y: chordDx / chordLen };
      const tangent = { x: chordDx / chordLen, y: chordDy / chordLen };

      let baseControl1: { x: number; y: number };
      let baseControl2: { x: number; y: number };

      if (activeDirect && activePortAngle != null && activeId != null) {
        const stub = clamp(chordLen * 0.23, 42, 78);
        if (source.id === activeId) {
          // 从中心节点先沿分配好的端口方向离开，再平滑接近目标节点。
          baseControl1 = {
            x: start.x + Math.cos(activePortAngle) * stub,
            y: start.y + Math.sin(activePortAngle) * stub,
          };
          baseControl2 = {
            x: end.x - tangent.x * stub * 0.9,
            y: end.y - tangent.y * stub * 0.9,
          };
        } else {
          // 指向中心节点时，末端沿中心端口方向进入，避免多条箭头挤在同一点。
          baseControl1 = {
            x: start.x + tangent.x * stub * 0.9,
            y: start.y + tangent.y * stub * 0.9,
          };
          baseControl2 = {
            x: end.x + Math.cos(activePortAngle) * stub,
            y: end.y + Math.sin(activePortAngle) * stub,
          };
        }
      } else {
        // 非核心边保持近似直线，仅保留很轻的弧度。
        const bend = (((edge.id * 17) % 7) - 3) * 8;
        baseControl1 = {
          x: start.x + chordDx * 0.34 + normal.x * bend,
          y: start.y + chordDy * 0.34 + normal.y * bend,
        };
        baseControl2 = {
          x: start.x + chordDx * 0.66 + normal.x * bend,
          y: start.y + chordDy * 0.66 + normal.y * bend,
        };
      }

      // 在基础路由附近只做小范围“车道偏移”。成本函数同时考虑节点/文字遮挡
      // 和已绘制主边，优先选择不与其他主边贴在一起或交叉的路线。
      const laneCandidates = activeDirect
        ? [0, 18, -18, 36, -36, 56, -56]
        : [0, 24, -24, 48, -48];
      let control1 = baseControl1;
      let control2 = baseControl2;
      let bestSamples: Array<{ x: number; y: number }> = [];
      let bestCost = Number.POSITIVE_INFINITY;

      for (const laneOffset of laneCandidates) {
        const c1 = {
          x: baseControl1.x + normal.x * laneOffset,
          y: baseControl1.y + normal.y * laneOffset,
        };
        const c2 = {
          x: baseControl2.x + normal.x * laneOffset,
          y: baseControl2.y + normal.y * laneOffset,
        };
        const samples: Array<{ x: number; y: number }> = [];
        let obstacleHits = 0;
        let nearNodeHits = 0;
        let edgeOverlapHits = 0;

        for (let step = 1; step < 36; step += 1) {
          const point = cubicPoint(start, c1, c2, end, step / 36);
          samples.push(point);
          for (const node of nodes) {
            if (node.id === source.id || node.id === target.id) continue;
            const visual = nodeVisuals.get(node.id);
            const radius = visual?.radius ?? nodeRadius(node);
            const distance = Math.hypot(point.x - node.x, point.y - node.y);
            if (distance < radius + 12) obstacleHits += 1;
            else if (distance < radius + 25) nearNodeHits += 1;
            if (visual?.showLabel) {
              const box = visual.placement.box;
              const padding = 7;
              if (
                point.x >= box.x - padding && point.x <= box.x + box.width + padding
                && point.y >= box.y - padding && point.y <= box.y + box.height + padding
              ) obstacleHits += 1;
            }
          }

          if (primary) {
            for (const otherSamples of routedPrimarySamples) {
              for (let idx = 0; idx < otherSamples.length; idx += 3) {
                const other = otherSamples[idx];
                const distance = Math.hypot(point.x - other.x, point.y - other.y);
                if (distance < 7) edgeOverlapHits += 4;
                else if (distance < 15) edgeOverlapHits += 1;
              }
            }
          }
        }

        const candidatePolyline = [start, ...samples, end];
        const crossingHits = primary
          ? routedPrimaryPolylines.reduce((sum, other) => sum + polylineIntersectionCount(candidatePolyline, other), 0)
          : 0;

        const cost = obstacleHits * 1200
          + crossingHits * 6000
          + nearNodeHits * 16
          + edgeOverlapHits * 34
          + Math.abs(laneOffset) * 0.08;
        if (cost < bestCost) {
          bestCost = cost;
          control1 = c1;
          control2 = c2;
          bestSamples = samples;
          if (obstacleHits === 0 && crossingHits === 0 && nearNodeHits === 0 && edgeOverlapHits === 0) break;
        }
      }

      if (primary && bestSamples.length) {
        routedPrimarySamples.push(bestSamples);
        routedPrimaryPolylines.push([start, ...bestSamples, end]);
      }

      let labelPoint: { x: number; y: number } | null = null;
      const relationAlreadyLabeled = primaryEdges.length > 4 && labeledRelationTypes.has(edge.relation_type);
      const canShowRelationLabel = showEdgeLabels && primary && !relationAlreadyLabeled && visibleRelationLabelCount < 3;
      if (canShowRelationLabel) {
        const labelCandidates = activeId != null && edge.target === activeId
          ? [0.28, 0.36, 0.44, 0.2]
          : activeId != null && edge.source === activeId
            ? [0.72, 0.64, 0.56, 0.8]
            : [0.5, 0.38, 0.62];
        labelSearch:
        for (const t of labelCandidates) {
          const pathPoint = cubicPoint(start, control1, control2, end, t);
          const labelNormal = cubicUnitNormal(start, control1, control2, end, t);
          // 关系标签不再直接盖在线上。优先放到曲线一侧，必要时尝试另一侧/更远位置，
          // 这样既保留连续的方向线索，也避免白色标签底遮住箭头前后的短线段。
          for (const normalOffset of [15, -15, 22, -22]) {
            const point = {
              x: pathPoint.x + labelNormal.x * normalOffset,
              y: pathPoint.y + labelNormal.y * normalOffset,
            };
            const clearOfNodes = nodes.every((node) => {
              const visual = nodeVisuals.get(node.id);
              const radius = visual?.radius ?? nodeRadius(node);
              const isActive = node.id === activeId;
              if (Math.hypot(point.x - node.x, point.y - node.y) < radius + (isActive ? 48 : 22)) return false;
              if (!visual?.showLabel) return true;
              const box = visual.placement.box;
              const padding = isActive ? 24 : 9;
              return !(
                point.x >= box.x - padding && point.x <= box.x + box.width + padding
                && point.y >= box.y - padding && point.y <= box.y + box.height + padding
              );
            });
            if (!clearOfNodes) continue;

            const candidateBox = { x: point.x - 23, y: point.y - 11, width: 46, height: 22 };
            const clearOfLabels = occupiedLabels.every((box) => (
              candidateBox.x + candidateBox.width + 6 < box.x
              || box.x + box.width + 6 < candidateBox.x
              || candidateBox.y + candidateBox.height + 6 < box.y
              || box.y + box.height + 6 < candidateBox.y
            ));
            if (!clearOfLabels) continue;

            labelPoint = point;
            occupiedLabels.push(candidateBox);
            labeledRelationTypes.add(edge.relation_type);
            visibleRelationLabelCount += 1;
            break labelSearch;
          }
        }
      }

      geometries.push({ edge, source, target, primary, start, end, control1, control2, labelPoint });
    }
    return geometries;
  }, [activeId, activePortAngles, displayEdges, nodeMap, nodeVisuals, nodes, primaryEdgeIds, primaryEdges.length, showEdgeLabels]);

  function handlePointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    const target = event.target as Element;
    if (target.closest("[data-kg-node]")) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y };
  }

  function handlePointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const viewScale = rect.width > 0 ? 1000 / rect.width : 1;
    onPanChange({
      x: drag.panX + (event.clientX - drag.x) * viewScale,
      y: drag.panY + (event.clientY - drag.y) * viewScale,
    });
  }

  function handlePointerUp(event: ReactPointerEvent<SVGSVGElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    event.preventDefault();
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  return (
    <svg
      id="knowledge-graph-svg"
      viewBox="0 0 1000 710"
      className="h-full min-h-[620px] w-full select-none cursor-grab active:cursor-grabbing"
      role="img"
      aria-label="知识图谱可视化"
      style={{ touchAction: "none" }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onLostPointerCapture={() => { dragRef.current = null; }}
      onWheel={(event) => {
        // 普通滚轮只滚动页面；Ctrl/⌘ + 滚轮才缩放图谱，避免页面滚动与画布缩放同时发生。
        if (!event.ctrlKey && !event.metaKey) return;
        event.preventDefault();
        const delta = event.deltaY > 0 ? -0.08 : 0.08;
        onZoomChange(clamp(zoom + delta, 0.68, 1.55));
      }}
    >
      <defs>
        {(Object.keys(RELATIONS) as RelationKey[]).map((type) => (
          <marker
            key={type}
            id={`kg-arrow-${type}`}
            markerWidth="9"
            markerHeight="9"
            refX="8.2"
            refY="4.5"
            orient="auto"
            markerUnits="userSpaceOnUse"
            overflow="visible"
          >
            <path d="M0.7,0.6 L8.8,4.5 L0.7,8.4 z" fill={RELATIONS[type].color} />
          </marker>
        ))}
        <filter id="kg-node-shadow" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="2" stdDeviation="2.4" floodColor="#27485d" floodOpacity="0.12" />
        </filter>
      </defs>

      <rect x="0" y="0" width="1000" height="710" fill="transparent" pointerEvents="all" aria-hidden="true" />

      <g transform={`translate(${500 + pan.x} ${355 + pan.y}) scale(${zoom}) translate(-500 -355)`}>
        <g>
        {/* 1. 关系线路层：连续几何路径，永远位于主要节点与文字下方，不再通过 mask 截断。 */}
        <g pointerEvents="none">
          {edgeGeometries.map(({ edge, primary, start, end, control1, control2 }) => {
            const color = relationColor(edge.relation_type);
            return (
              <path
                key={`edge-${edge.id}`}
                d={`M ${start.x} ${start.y} C ${control1.x} ${control1.y} ${control2.x} ${control2.y} ${end.x} ${end.y}`}
                fill="none"
                stroke={primary ? color : "#b7c4cc"}
                strokeWidth={primary ? 1.15 + edge.confidence * 0.5 : 0.7}
                strokeOpacity={primary ? 0.58 : 0.06}
                strokeDasharray={edge.source_type === "inferred" ? "7 6" : undefined}
                strokeLinecap="round"
                markerEnd={primary ? `url(#kg-arrow-${edge.relation_type})` : undefined}
              />
            );
          })}
        </g>

        {/* 2. 关系标签层：仅在能找到不与节点/节点标签冲突的位置时显示。 */}
        <g pointerEvents="none">
          {edgeGeometries.map(({ edge, primary, labelPoint }) => {
            if (!primary || !labelPoint) return null;
            const color = relationColor(edge.relation_type);
            return (
              <g key={`edge-label-${edge.id}`} transform={`translate(${labelPoint.x} ${labelPoint.y})`}>
                <rect x="-20" y="-8.5" width="40" height="17" rx="7.5" fill="#ffffff" fillOpacity="0.98" stroke="#eef2f4" strokeWidth="0.7" />
                <text textAnchor="middle" dominantBaseline="middle" y="-0.5" fontSize="8" fontWeight="650" fill={color}>
                  {relationLabel(edge.relation_type)}
                </text>
              </g>
            );
          })}
        </g>

        {[...nodes]
          .sort((a, b) => {
            const aPriority = Number(directNeighborIds.has(a.id)) + Number(a.id === data.focus_id) * 2 + Number(a.id === selectedId) * 3;
            const bPriority = Number(directNeighborIds.has(b.id)) + Number(b.id === data.focus_id) * 2 + Number(b.id === selectedId) * 3;
            return aPriority - bPriority;
          })
          .map((node) => {
            const visual = nodeVisuals.get(node.id);
            if (!visual) return null;
            const { selected, focused, direct, radius, showLabel, withMeta, placement } = visual;
            const dimmed = selectedId != null && !selected && !direct && !focused;
            const relationEdge = directRelationByNodeId.get(node.id);
            const semanticColor = relationEdge ? relationColor(relationEdge.relation_type) : "#5b83a0";
            return (
              <g
                key={node.id}
                data-kg-node="true"
                transform={`translate(${node.x} ${node.y})`}
                className="cursor-pointer"
                style={{ opacity: dimmed ? 0.16 : 1, transition: "opacity 140ms ease" }}
                onClick={(event) => { event.stopPropagation(); onSelect(node.id); }}
                onDoubleClick={(event) => { event.stopPropagation(); onFocus(node.id); }}
              >
                <title>{`${node.name}\n${node.degree} 条关系 · ${node.question_count} 题${node.aliases?.length ? `\n别名：${node.aliases.join("、")}` : ""}`}</title>
                {selected && <circle r={radius + 7} fill="#4a6f8a" fillOpacity="0.055" stroke="#4a6f8a" strokeOpacity="0.14" strokeWidth="1.6" />}
                <circle
                  r={radius}
                  fill={selected ? "#4a6f8a" : focused ? "#e7f1f7" : direct ? `${semanticColor}18` : "#ffffff"}
                  stroke={selected ? "#365f79" : focused ? "#5b83a0" : direct ? semanticColor : "#b5c3cc"}
                  strokeWidth={selected ? 2 : focused ? 1.65 : direct ? 1.45 : 1.05}
                  filter={selected ? "url(#kg-node-shadow)" : undefined}
                />
                <circle r={selected ? 6 : 5} fill={selected ? "#ffffff" : semanticColor} fillOpacity={selected ? 0.96 : direct ? 0.88 : 0.58} />
                {showLabel && (
                  <>
                    <text
                      textAnchor={placement.textAnchor}
                      x={placement.x}
                      y={placement.y}
                      fontSize={selected || focused ? "11" : "9.5"}
                      fontWeight={selected || focused ? "700" : "600"}
                      fill="#1e2b38"
                      stroke="#ffffff"
                      strokeWidth="4.5"
                      paintOrder="stroke fill"
                      strokeLinejoin="round"
                    >
                      {shortName(node.name, 11)}
                    </text>
                    {withMeta && (
                      <text
                        textAnchor={placement.textAnchor}
                        x={placement.x}
                        y={placement.metaY}
                        fontSize="7.8"
                        fill="#8295a2"
                        stroke="#ffffff"
                        strokeWidth="3.2"
                        paintOrder="stroke fill"
                      >
                        {node.degree} 关系 · {node.question_count} 题
                      </text>
                    )}
                  </>
                )}
              </g>
            );
          })}
        </g>
      </g>
    </svg>
  );
}

function RelationDonut({ counts }: { counts: Record<string, number> }) {
  const stops = buildDonutStops(counts);
  const total = computeDonutTotal(counts);

  return (
    <div className="grid grid-cols-[88px_1fr] items-center gap-4">
      <div
        className="relative h-[88px] w-[88px] rounded-full"
        style={{ background: total ? `conic-gradient(${stops.join(",")})` : "#e8e4dd" }}
      >
        <div className="absolute inset-[13px] grid place-items-center rounded-full bg-[var(--porcelain)] text-center">
          <div>
            <div className="text-lg font-bold text-[var(--ink)]">{total}</div>
            <div className="text-[9px] text-[var(--color-text-hint)]">关系</div>
          </div>
        </div>
      </div>
      <div className="space-y-1.5">
        {(Object.keys(RELATIONS) as RelationKey[]).map((key) => {
          const value = Number(counts[key] ?? 0);
          return (
            <div key={key} className="flex items-center justify-between gap-3 text-[11px]">
              <span className="flex items-center gap-1.5 text-[var(--color-text-secondary)]">
                <span className="h-2 w-2 rounded-full" style={{ background: RELATIONS[key].color }} />
                {RELATIONS[key].label}
              </span>
              <span className="font-mono text-[var(--color-text-hint)]">
                {value} {total ? `· ${((value / total) * 100).toFixed(0)}%` : ""}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}


function SubjectOverview({
  subjectName,
  totalNodes,
  topics,
  onFocus,
}: {
  subjectName: string;
  totalNodes: number;
  topics: KnowledgeGraphResponse["overview_topics"];
  onFocus: (id: number) => void;
}) {
  const center = { x: 500, y: 355 };
  const positions = [
    { x: 220, y: 165 },
    { x: 500, y: 112 },
    { x: 780, y: 165 },
    { x: 845, y: 355 },
    { x: 780, y: 545 },
    { x: 500, y: 598 },
    { x: 220, y: 545 },
    { x: 155, y: 355 },
  ];

  function labelPlacement(position: { x: number; y: number }) {
    if (position.x < 360) return { x: position.x - 42, y: position.y - 2, anchor: "end" as const, metaY: position.y + 15 };
    if (position.x > 640) return { x: position.x + 42, y: position.y - 2, anchor: "start" as const, metaY: position.y + 15 };
    if (position.y < center.y) return { x: position.x, y: position.y - 44, anchor: "middle" as const, metaY: position.y - 29 };
    return { x: position.x, y: position.y + 50, anchor: "middle" as const, metaY: position.y + 65 };
  }

  return (
    <svg
      id="knowledge-graph-svg"
      viewBox="0 0 1000 710"
      className="h-full min-h-[620px] w-full select-none"
      role="img"
      aria-label={`${subjectName} 一级主题知识图谱`}
    >
      <defs>
        <marker id="kg-overview-arrow" markerWidth="9" markerHeight="9" refX="8.2" refY="4.5" orient="auto" markerUnits="userSpaceOnUse" overflow="visible">
          <path d="M0.7,0.6 L8.8,4.5 L0.7,8.4 z" fill={RELATIONS.parent.color} />
        </marker>
        <filter id="kg-overview-shadow" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="2" stdDeviation="2.4" floodColor="#27485d" floodOpacity="0.12" />
        </filter>
      </defs>

      <g pointerEvents="none">
        {topics.slice(0, 8).map((topic, index) => {
          const position = positions[index] ?? positions[0];
          const dx = position.x - center.x;
          const dy = position.y - center.y;
          const length = Math.max(1, Math.hypot(dx, dy));
          const startRadius = 56;
          const endRadius = 31;
          const start = { x: center.x + (dx / length) * startRadius, y: center.y + (dy / length) * startRadius };
          const end = { x: position.x - (dx / length) * endRadius, y: position.y - (dy / length) * endRadius };
          return (
            <path
              key={`overview-edge-${topic.id}`}
              d={`M ${start.x} ${start.y} L ${end.x} ${end.y}`}
              fill="none"
              stroke={RELATIONS.parent.color}
              strokeWidth="1.35"
              strokeOpacity="0.52"
              strokeLinecap="round"
              markerEnd="url(#kg-overview-arrow)"
            />
          );
        })}
      </g>

      <g
        transform={`translate(${center.x} ${center.y})`}
        className="cursor-default"
      >
        <circle r="64" fill="#4a6f8a" fillOpacity="0.05" stroke="#4a6f8a" strokeOpacity="0.12" strokeWidth="1.6" />
        <circle r="52" fill="#e7f1f7" stroke="#5b83a0" strokeWidth="1.7" filter="url(#kg-overview-shadow)" />
        <circle r="6" cy="-16" fill="#5b83a0" />
        <text textAnchor="middle" y="7" fontSize="14" fontWeight="700" fill="#1e2b38">{shortName(subjectName, 8)}</text>
        <text textAnchor="middle" y="25" fontSize="8.5" fill="#8295a2">{totalNodes} 个知识点</text>
      </g>

      {topics.slice(0, 8).map((topic, index) => {
        const position = positions[index] ?? positions[0];
        const label = labelPlacement(position);
        return (
          <g
            key={topic.id}
            data-kg-node="true"
            transform={`translate(${position.x} ${position.y})`}
            className="cursor-pointer"
            onClick={(event) => { event.stopPropagation(); onFocus(topic.id); }}
          >
            <title>{`${topic.name}\n${topic.direct_child_count} 个直接子节点${topic.question_count ? ` · ${topic.question_count} 道题` : ""}`}</title>
            <circle r="31" fill="#ffffff" stroke={RELATIONS.parent.color} strokeWidth="1.45" />
            <circle r="5" fill={RELATIONS.parent.color} fillOpacity="0.88" />
            <text
              x={label.x - position.x}
              y={label.y - position.y}
              textAnchor={label.anchor}
              fontSize="10.5"
              fontWeight="650"
              fill="#1e2b38"
              stroke="#ffffff"
              strokeWidth="4.5"
              paintOrder="stroke fill"
              strokeLinejoin="round"
            >
              {shortName(topic.name, 11)}
            </text>
            <text
              x={label.x - position.x}
              y={label.metaY - position.y}
              textAnchor={label.anchor}
              fontSize="8"
              fill="#8295a2"
              stroke="#ffffff"
              strokeWidth="3.2"
              paintOrder="stroke fill"
            >
              {topic.direct_child_count} 个直接子节点{topic.question_count ? ` · ${topic.question_count} 题` : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function KnowledgeGraphPage() {
  const [subjectId, setSubjectId] = useState("");
  const [relationType, setRelationType] = useState("");
  const [depth, setDepth] = useState("2");
  const [searchDraft, setSearchDraft] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [searchDebouncing, setSearchDebouncing] = useState(false);
  const [centerId, setCenterId] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [layoutVariant, setLayoutVariant] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [fullscreenMode, setFullscreenMode] = useState<"none" | "native" | "overlay">("none");
  const graphPanelRef = useRef<HTMLElement | null>(null);
  const preservedScrollRef = useRef<{ x: number; y: number } | null>(null);
  const pendingResetRef = useRef(false);
  const viewportAnimationRef = useRef<number | null>(null);

  const subjects = useQuery({
    queryKey: ["knowledge-graph", "subjects"],
    queryFn: () => apiRequest<KnowledgeGraphSubject[]>("/knowledge/subjects"),
  });

  useEffect(() => {
    if (subjectId || !subjects.data?.length) return;
    const selected = selectDefaultSubject(subjects.data);
    if (selected) setSubjectId(String(selected.id));
  }, [subjectId, subjects.data]);

  useEffect(() => {
    const next = searchDraft.trim();
    if (next === searchTerm) {
      setSearchDebouncing(false);
      return;
    }
    setSearchDebouncing(true);
    const timer = window.setTimeout(() => {
      preservedScrollRef.current = { x: window.scrollX, y: window.scrollY };
      setCenterId(null);
      setSearchTerm(next);
      setSearchDebouncing(false);
      setZoom(1);
      setPan({ x: 0, y: 0 });
    }, next ? 320 : 160);
    return () => window.clearTimeout(timer);
  }, [searchDraft, searchTerm]);

  const graph = useQuery({
    queryKey: ["knowledge-graph", subjectId, relationType, depth, searchTerm, centerId],
    enabled: Boolean(subjectId),
    placeholderData: (previousData) => previousData,
    queryFn: () => apiRequest<KnowledgeGraphResponse>(`/knowledge/graph${toQuery({
      subject_id: Number(subjectId),
      relation_type: relationType || undefined,
      knowledge_point_id: centerId ?? undefined,
      search: searchTerm || undefined,
      depth: Number(depth),
      // Overview stays intentionally compact; focused/search views may reveal more local context.
      max_nodes: centerId != null || searchTerm ? 36 : 24,
    })}`),
  });

  // Keep explicit selection state separate from the fallback selection. This avoids the
  // mount -> effect -> select cycle that used to repaint/highlight the graph right after entry.
  useEffect(() => {
    const data = graph.data;
    if (!data || graph.isFetching) return;
    if (pendingResetRef.current) {
      pendingResetRef.current = false;
      setSelectedId(null);
      return;
    }
    if (selectedId != null && !data.nodes.some((node) => node.id === selectedId)) setSelectedId(null);
  }, [graph.data, graph.isFetching, selectedId]);

  const resolvedSelectedId = useMemo(() => {
    const data = graph.data;
    if (!data) return null;
    if (selectedId != null && data.nodes.some((node) => node.id === selectedId)) return selectedId;
    return data.focus_id ?? data.nodes[0]?.id ?? null;
  }, [graph.data, selectedId]);

  const selectedNode = useMemo(
    () => graph.data?.nodes.find((node) => node.id === resolvedSelectedId) ?? null,
    [graph.data, resolvedSelectedId],
  );

  const selectedNeighbors = useMemo(() => {
    if (!graph.data || resolvedSelectedId == null) return [];
    const nodeMap = new Map(graph.data.nodes.map((node) => [node.id, node]));
    const grouped = new Map<number, {
      node: KnowledgeGraphNode;
      relations: Array<{ edge: KnowledgeGraphEdge; outgoing: boolean }>;
      maxConfidence: number;
    }>();
    for (const edge of graph.data.edges) {
      if (edge.source !== resolvedSelectedId && edge.target !== resolvedSelectedId) continue;
      const outgoing = edge.source === resolvedSelectedId;
      const otherId = outgoing ? edge.target : edge.source;
      const node = nodeMap.get(otherId);
      if (!node) continue;
      const current = grouped.get(otherId) ?? { node, relations: [], maxConfidence: 0 };
      current.relations.push({ edge, outgoing });
      current.maxConfidence = Math.max(current.maxConfidence, edge.confidence);
      grouped.set(otherId, current);
    }
    return [...grouped.values()]
      .map((item) => ({ ...item, relations: item.relations.sort((a, b) => edgeStrength(b.edge) - edgeStrength(a.edge)) }))
      .sort((a, b) => b.maxConfidence - a.maxConfidence || b.node.degree - a.node.degree);
  }, [graph.data, resolvedSelectedId]);

  const visibleSelectedNeighbors = selectedNeighbors.slice(0, 8);

  function preserveScroll(action: () => void) {
    preservedScrollRef.current = { x: window.scrollX, y: window.scrollY };
    action();
    window.requestAnimationFrame(() => {
      const position = preservedScrollRef.current;
      if (position) window.scrollTo(position.x, position.y);
    });
  }

  useEffect(() => {
    if (graph.isFetching || !preservedScrollRef.current) return;
    const position = preservedScrollRef.current;
    window.requestAnimationFrame(() => {
      window.scrollTo(position.x, position.y);
      preservedScrollRef.current = null;
    });
  }, [graph.dataUpdatedAt, graph.isFetching]);

  function animateViewportReset(duration = 320) {
    if (viewportAnimationRef.current != null) window.cancelAnimationFrame(viewportAnimationRef.current);
    const startZoom = zoom;
    const startPan = { ...pan };
    const startedAt = performance.now();
    const tick = (now: number) => {
      const progress = clamp((now - startedAt) / duration, 0, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setZoom(startZoom + (1 - startZoom) * eased);
      setPan({ x: startPan.x * (1 - eased), y: startPan.y * (1 - eased) });
      if (progress < 1) viewportAnimationRef.current = window.requestAnimationFrame(tick);
      else viewportAnimationRef.current = null;
    };
    viewportAnimationRef.current = window.requestAnimationFrame(tick);
  }

  useEffect(() => () => {
    if (viewportAnimationRef.current != null) window.cancelAnimationFrame(viewportAnimationRef.current);
  }, []);

  function resetView() {
    const needsDataReset = Boolean(searchDraft || searchTerm || relationType || depth !== "2" || centerId != null);
    pendingResetRef.current = needsDataReset;
    preserveScroll(() => {
      setSearchDraft("");
      setSearchTerm("");
      setRelationType("");
      setDepth("2");
      setCenterId(null);
      if (!needsDataReset) setSelectedId(null);
    });
    animateViewportReset();
  }

  useEffect(() => {
    function syncFullscreenState() {
      if (document.fullscreenElement === graphPanelRef.current) setFullscreenMode("native");
      else if (fullscreenMode === "native") setFullscreenMode("none");
    }
    document.addEventListener("fullscreenchange", syncFullscreenState);
    return () => document.removeEventListener("fullscreenchange", syncFullscreenState);
  }, [fullscreenMode]);

  useEffect(() => {
    if (fullscreenMode !== "overlay") return;
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setFullscreenMode("none");
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [fullscreenMode]);

  async function toggleFullscreen() {
    const panel = graphPanelRef.current;
    if (!panel) return;
    if (fullscreenMode === "overlay") {
      setFullscreenMode("none");
      return;
    }
    if (document.fullscreenElement === panel) {
      await document.exitFullscreen().catch(() => undefined);
      setFullscreenMode("none");
      return;
    }
    try {
      if (!panel.requestFullscreen) throw new Error("Fullscreen API unavailable");
      await panel.requestFullscreen();
      setFullscreenMode("native");
    } catch {
      // Safari/WebView or permission-restricted environments still get a usable overlay fallback.
      setFullscreenMode("overlay");
    }
  }

  function exportGraph() {
    if (!graph.data) return;
    const svg = document.querySelector<SVGSVGElement>("#knowledge-graph-svg");
    if (!svg) return;

    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", "1000");
    clone.setAttribute("height", "710");
    clone.removeAttribute("class");
    const background = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    background.setAttribute("x", "0");
    background.setAttribute("y", "0");
    background.setAttribute("width", "1000");
    background.setAttribute("height", "710");
    background.setAttribute("fill", "#fefcf9");
    clone.insertBefore(background, clone.firstChild);

    const source = new XMLSerializer().serializeToString(clone);
    const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `knowledge-graph-${graph.data.subject.code || graph.data.subject.id}.svg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // 某些浏览器在 click() 返回后仍异步读取 Blob，立即 revoke 可能导致空文件。
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const summary = graph.data?.summary;
  const relationCounts = summary?.relation_counts ?? {};
  const isDefaultOverview = Boolean(
    graph.data
    && !searchTerm
    && centerId == null
    && !relationType
    && depth === "2"
    && graph.data.overview_topics.length,
  );

  return (
    <div className="mx-auto flex max-w-[1580px] flex-col gap-3.5 [overflow-anchor:none]">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-[28px] font-bold tracking-tight text-[var(--ink)]">知识图谱</h1>
            <span className="rounded-full bg-[var(--color-primary-light)] px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-[var(--color-primary-dark)]">Graph</span>
          </div>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">探索知识点关系、定位学习路径，并检查图谱连接质量。</p>
        </div>
        {summary && (
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-lg border border-[var(--color-border-light)] bg-white/68 px-2.5 py-1.5 text-[var(--color-text-secondary)]">
              <b className="mr-1 text-[var(--ink)]">{summary.total_nodes}</b>知识点
            </span>
            <span className="rounded-lg border border-[var(--color-border-light)] bg-white/68 px-2.5 py-1.5 text-[var(--color-text-secondary)]">
              <b className="mr-1 text-[var(--ink)]">{summary.total_edges}</b>关系边
            </span>
            <span className="rounded-lg border border-[var(--color-border-light)] bg-white/68 px-2.5 py-1.5 text-[var(--color-text-secondary)]">
              平均置信度 <b className="ml-1 text-[var(--ink)]">{(summary.avg_confidence * 100).toFixed(0)}%</b>
            </span>
          </div>
        )}
      </div>

      <section className="surface-card rounded-2xl p-3.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="relative min-w-[300px] flex-1 lg:max-w-[560px]">
            <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
            <Input
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              className="h-10 bg-white/80 pl-10 pr-20"
              placeholder="搜索名称、别名或 ID，输入后自动定位"
              aria-label="搜索知识点名称、别名或 ID"
            />
            <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1">
              {(searchDebouncing || (graph.isFetching && !!searchTerm)) && <RefreshCw className="h-3.5 w-3.5 animate-spin text-[var(--color-text-hint)]" />}
              {searchDraft && (
                <button
                  type="button"
                  onClick={() => setSearchDraft("")}
                  className="grid h-7 w-7 place-items-center rounded-lg text-[var(--color-text-hint)] transition hover:bg-[var(--color-primary-light)] hover:text-[var(--ink)]"
                  title="清空搜索"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>

          <Select
            value={subjectId}
            onChange={(value) => preserveScroll(() => {
              setSubjectId(value);
              setCenterId(null);
              setSearchDraft("");
              setSearchTerm("");
              setZoom(1);
              setPan({ x: 0, y: 0 });
            })}
            className="h-10 min-w-[150px] border-[var(--color-border)]"
            options={(subjects.data ?? []).map((subject) => ({
              value: String(subject.id),
              label: subject.name,
              suffix: `${subject.knowledge_point_count}点`,
            }))}
            placeholder="选择科目"
          />
          <Select
            value={relationType}
            onChange={(value) => preserveScroll(() => setRelationType(value))}
            className="h-10 min-w-[128px] border-[var(--color-border)]"
            options={[
              { value: "", label: "全部关系" },
              ...Object.entries(RELATIONS).map(([value, config]) => ({ value, label: config.label })),
            ]}
          />
          <Select
            value={depth}
            onChange={(value) => preserveScroll(() => setDepth(value))}
            className="h-10 min-w-[92px] border-[var(--color-border)]"
            options={[1, 2, 3].map((value) => ({ value: String(value), label: `深度 ${value}` }))}
          />

          <div className="ml-auto flex items-center gap-2">
            <Button variant="secondary" onClick={() => setLayoutVariant((value) => value + 1)} disabled={isDefaultOverview}>
              <LayoutGrid className="h-4 w-4" />布局
            </Button>
            <Button variant="secondary" onClick={resetView} title="重置搜索、关系、深度与当前中心节点">
              <RefreshCw className="h-4 w-4" />重置筛选
            </Button>
            <Button variant="primary" onClick={exportGraph} disabled={!graph.data?.nodes.length || isDefaultOverview}>
              <Download className="h-4 w-4" />导出图谱
            </Button>
          </div>
        </div>

      </section>

      <div className={cn(
        "grid min-h-[680px] grid-cols-1 items-start gap-4 [overflow-anchor:none]",
        !isDefaultOverview && "xl:grid-cols-[minmax(0,1fr)_350px]",
      )}>
        <section
          ref={graphPanelRef}
          className={cn(
            "surface-card relative min-h-0 overflow-hidden rounded-2xl [overflow-anchor:none]",
            fullscreenMode === "none" && "h-[680px]",
            fullscreenMode === "overlay" && "fixed inset-3 z-[100] h-[calc(100vh-1.5rem)] bg-[var(--porcelain)] shadow-2xl",
            fullscreenMode === "native" && "h-screen w-screen rounded-none bg-[var(--porcelain)]",
          )}
        >
          <div
            className="absolute inset-0"
            style={{
              backgroundColor: "#fbfcfd",
              backgroundImage: "linear-gradient(rgba(74,111,138,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(74,111,138,0.045) 1px, transparent 1px), radial-gradient(circle at 50% 44%, rgba(74,111,138,0.05), transparent 46%)",
              backgroundSize: "28px 28px, 28px 28px, auto",
            }}
          />

          {!isDefaultOverview ? (
            <div className="absolute left-4 top-4 z-10 w-[148px] rounded-xl border border-[var(--color-border-light)] bg-white/94 p-3 shadow-[0_6px_18px_rgba(27,39,51,0.06)] backdrop-blur-md">
              <div className="mb-2 text-[11px] font-semibold text-[var(--ink)]">关系类型</div>
              <div className="mb-2 flex items-center gap-2 text-[10px] text-[var(--color-text-secondary)]">
                <span className="grid h-5 w-5 place-items-center rounded-full border border-[var(--color-primary)] bg-[var(--color-primary-light)]"><Network className="h-3 w-3" /></span>
                知识点节点
              </div>
              <div className="space-y-1.5 border-t border-[var(--color-border-light)] pt-2">
                {(Object.keys(RELATIONS) as RelationKey[]).map((key) => (
                  <div key={key} className="flex items-center gap-2 text-[10px] text-[var(--color-text-secondary)]">
                    <span className="h-[2px] w-6 rounded-full" style={{ background: RELATIONS[key].color }} />
                    {RELATIONS[key].label}
                    <ArrowRight className="ml-auto h-3 w-3" style={{ color: RELATIONS[key].color }} />
                  </div>
                ))}
                <div className="pt-1 text-[9px] leading-4 text-[var(--color-text-hint)]">虚线表示 inferred 自动推断边</div>
              </div>
            </div>
          ) : null}

          <div className="absolute right-4 top-4 z-10 flex gap-2">
            {graph.isFetching && (
              <span className="flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-white/85 px-3 py-2 text-[10px] text-[var(--color-text-hint)]">
                <RefreshCw className="h-3 w-3 animate-spin" />刷新中
              </span>
            )}
            <button
              type="button"
              onClick={toggleFullscreen}
              className="grid h-9 w-9 place-items-center rounded-xl border border-[var(--color-border-light)] bg-white/94 text-[var(--color-text-secondary)] shadow-sm transition hover:border-[#cbd8e0] hover:bg-white hover:text-[var(--color-primary-dark)]"
              title={fullscreenMode !== "none" ? "退出全屏" : "全屏查看"}
              aria-label={fullscreenMode !== "none" ? "退出全屏" : "全屏查看"}
            >
              {fullscreenMode !== "none" ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
          </div>

          {!isDefaultOverview ? (
            <div className="absolute bottom-5 right-5 z-10 overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-white/95 shadow-[0_6px_18px_rgba(27,39,51,0.06)]">
              <button type="button" onClick={() => setZoom((value) => clamp(value + 0.12, 0.68, 1.5))} className="grid h-9 w-10 place-items-center text-[var(--color-text-secondary)] transition hover:bg-[var(--color-primary-light)] disabled:cursor-default disabled:opacity-35" disabled={zoom >= 1.5} title="放大" aria-label="放大图谱"><Plus className="h-4 w-4" /></button>
              <button type="button" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }} className="grid h-9 w-10 place-items-center border-y border-[var(--color-border-light)] text-[10px] font-semibold tabular-nums text-[var(--color-text-secondary)] transition hover:bg-[var(--color-primary-light)]" title="重置缩放与位置" aria-label="重置缩放与位置">{Math.round(zoom * 100)}%</button>
              <button type="button" onClick={() => setZoom((value) => clamp(value - 0.12, 0.68, 1.5))} className="grid h-9 w-10 place-items-center text-[var(--color-text-secondary)] transition hover:bg-[var(--color-primary-light)] disabled:cursor-default disabled:opacity-35" disabled={zoom <= 0.68} title="缩小" aria-label="缩小图谱"><Minus className="h-4 w-4" /></button>
            </div>
          ) : null}

          <div className="relative h-full min-h-0">
            {graph.isLoading ? (
              <div className="absolute inset-0 grid place-items-center">
                <div className="text-center text-sm text-[var(--color-text-hint)]">
                  <RefreshCw className="mx-auto mb-3 h-6 w-6 animate-spin" />正在加载知识图谱…
                </div>
              </div>
            ) : graph.isError ? (
              <div className="absolute inset-0 grid place-items-center p-8 text-center">
                <div>
                  <ShieldCheck className="mx-auto mb-3 h-8 w-8 text-[var(--color-danger)]" />
                  <div className="font-semibold text-[var(--ink)]">知识图谱加载失败</div>
                  <p className="mt-1 text-sm text-[var(--color-text-hint)]">请确认后端已部署管理端 /knowledge/graph 接口并检查当前账号权限。</p>
                </div>
              </div>
            ) : graph.data && isDefaultOverview ? (
              <SubjectOverview
                subjectName={graph.data.subject.name}
                totalNodes={graph.data.summary.total_nodes}
                topics={graph.data.overview_topics}
                onFocus={(id) => preserveScroll(() => {
                  setCenterId(id);
                  setSelectedId(id);
                  setZoom(1);
                  setPan({ x: 0, y: 0 });
                })}
              />
            ) : graph.data && graph.data.nodes.length > 0 ? (
              <GraphCanvas
                data={graph.data}
                selectedId={resolvedSelectedId}
                onSelect={setSelectedId}
                onFocus={(id) => preserveScroll(() => {
                  setCenterId(id);
                  setSearchTerm("");
                  setSearchDraft("");
                  setSelectedId(id);
                  setZoom(1);
                  setPan({ x: 0, y: 0 });
                })}
                layoutVariant={layoutVariant}
                zoom={zoom}
                pan={pan}
                onZoomChange={setZoom}
                onPanChange={setPan}
              />
            ) : (
              <div className="absolute inset-0 grid place-items-center px-8 text-center text-sm text-[var(--color-text-hint)]">
                {searchTerm ? `未找到与「${searchTerm}」匹配的知识点（已检索名称、aliases 别名与 ID）` : "当前筛选条件下没有可展示的知识点关系"}
              </div>
            )}
          </div>

          {summary && !isDefaultOverview && (
            <div className="absolute bottom-5 left-5 z-10 flex flex-wrap gap-1.5 text-[10px] text-[var(--color-text-hint)]">
              <span className="rounded-lg border border-[var(--color-border-light)] bg-white/92 px-2 py-1.5 shadow-[0_2px_8px_rgba(27,39,51,0.035)]">{summary.visible_nodes} 节点 · {summary.visible_edges} 边</span>
              <span className="rounded-lg border border-[var(--color-border-light)] bg-white/92 px-2 py-1.5 shadow-[0_2px_8px_rgba(27,39,51,0.035)]">单击查看 · 双击聚焦 · Ctrl/⌘ + 滚轮缩放</span>
              {summary.isolated_nodes > 0 && <span className="rounded-lg border border-[var(--color-warning)]/30 bg-[var(--color-warning-light)] px-2.5 py-1.5 text-[#8a6846]">孤立节点 {summary.isolated_nodes}</span>}
            </div>
          )}
        </section>

        {!isDefaultOverview ? (
        <aside className="surface-card min-h-[680px] rounded-2xl p-[18px] [overflow-anchor:none] [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden xl:h-[680px] xl:overflow-y-auto">
          {selectedNode ? (
            <div className="space-y-[18px]">
              <section>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="font-display text-xl font-bold text-[var(--ink)]">{selectedNode.name}</h2>
                      <span className="rounded-full bg-[var(--color-primary-light)] px-2 py-0.5 text-[9px] font-bold text-[var(--color-primary-dark)]">知识点</span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-[var(--color-text-secondary)]">
                      {selectedNode.description || "暂无知识点描述，可通过关系结构与关联题量判断其在学习路径中的位置。"}
                    </p>
                    {!!selectedNode.aliases?.length && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {selectedNode.aliases.slice(0, 6).map((alias) => (
                          <span key={alias} className="rounded-full border border-[var(--color-border-light)] bg-white/70 px-2 py-0.5 text-[9px] text-[var(--color-text-secondary)]">
                            {alias}
                          </span>
                        ))}
                        {selectedNode.aliases.length > 6 && <span className="px-1 py-0.5 text-[9px] text-[var(--color-text-hint)]">+{selectedNode.aliases.length - 6}</span>}
                      </div>
                    )}
                  </div>
                </div>

                <div className="mt-3.5 grid grid-cols-2 gap-x-3 gap-y-2 rounded-xl border border-[var(--color-border-light)] bg-white/52 p-3 text-[11px]">
                  <div><span className="text-[var(--color-text-hint)]">知识点 ID</span><div className="mt-0.5 font-mono font-semibold text-[var(--ink)]">#{selectedNode.id}</div></div>
                  <div><span className="text-[var(--color-text-hint)]">难度</span><div className="mt-0.5 font-semibold text-[var(--ink)]">{difficultyText(selectedNode.difficulty_level)} · L{selectedNode.difficulty_level}</div></div>
                  <div><span className="text-[var(--color-text-hint)]">关联题目</span><div className="mt-0.5 font-semibold text-[var(--ink)]">{selectedNode.question_count} 题</div></div>
                  <div><span className="text-[var(--color-text-hint)]">连接度</span><div className="mt-0.5 font-semibold text-[var(--ink)]">{selectedNode.degree} 条</div></div>
                  <div><span className="text-[var(--color-text-hint)]">入边</span><div className="mt-0.5 font-semibold text-[var(--ink)]">{selectedNode.in_degree}</div></div>
                  <div><span className="text-[var(--color-text-hint)]">出边</span><div className="mt-0.5 font-semibold text-[var(--ink)]">{selectedNode.out_degree}</div></div>
                </div>

                {centerId !== selectedNode.id && (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-3 w-full"
                    onClick={() => preserveScroll(() => {
                      setCenterId(selectedNode.id);
                      setSearchTerm("");
                      setSearchDraft("");
                      setZoom(1);
                      setPan({ x: 0, y: 0 });
                    })}
                  >
                    <Focus className="h-3.5 w-3.5" />以此知识点为中心展开
                  </Button>
                )}
              </section>

              <section className="border-t border-[var(--color-border-light)] pt-4">
                <div className="mb-2.5 flex items-center justify-between">
                  <h3 className="text-xs font-bold text-[var(--ink)]">相邻知识点 <span className="font-normal text-[var(--color-text-hint)]">({selectedNeighbors.length})</span></h3>
                  {selectedNeighbors.length > 0 && <span className="text-[9px] text-[var(--color-text-hint)]">按最高置信度排序</span>}
                </div>
                <div className="space-y-1.5">
                  {selectedNeighbors.length ? visibleSelectedNeighbors.map(({ node, relations, maxConfidence }) => {
                    const leadRelation = relations[0];
                    return (
                      <button
                        type="button"
                        key={node.id}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => preserveScroll(() => setSelectedId(node.id))}
                        className="flex w-full items-center gap-2 rounded-xl border border-transparent px-2.5 py-2 text-left transition hover:border-[var(--color-border-light)] hover:bg-white/70"
                      >
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: relationColor(leadRelation.edge.relation_type) }} />
                        <span className="min-w-0 flex-1 truncate text-xs font-medium text-[var(--ink)]">{node.name}</span>
                        <span className="flex shrink-0 items-center gap-1">
                          {relations.slice(0, 2).map(({ edge, outgoing }) => (
                            <span
                              key={edge.id}
                              className="rounded-md px-1.5 py-0.5 text-[9px]"
                              style={{ color: relationColor(edge.relation_type), background: `${relationColor(edge.relation_type)}12` }}
                            >
                              {outgoing ? "→" : "←"}{relationLabel(edge.relation_type)}
                            </span>
                          ))}
                          {relations.length > 2 && <span className="text-[9px] text-[var(--color-text-hint)]">+{relations.length - 2}</span>}
                        </span>
                        <span className="w-8 shrink-0 text-right font-mono text-[9px] text-[var(--color-text-hint)]">{Math.round(maxConfidence * 100)}%</span>
                      </button>
                    );
                  }) : (
                    <div className="rounded-xl border border-dashed border-[var(--color-border)] p-4 text-center text-[11px] text-[var(--color-text-hint)]">当前视图中没有相邻关系</div>
                  )}
                  {selectedNeighbors.length > visibleSelectedNeighbors.length && (
                    <div className="px-2 pt-1 text-[10px] text-[var(--color-text-hint)]">
                      仅展示置信度最高的 {visibleSelectedNeighbors.length} 个，当前视图共 {selectedNeighbors.length} 个相邻知识点
                    </div>
                  )}
                </div>
              </section>

              <section className="border-t border-[var(--color-border-light)] pt-4">
                <h3 className="mb-3 text-xs font-bold text-[var(--ink)]">关系类型分布</h3>
                <RelationDonut counts={selectedNode.relation_counts} />
              </section>

              <section className="border-t border-[var(--color-border-light)] pt-4">
                <h3 className="mb-3 flex items-center gap-1.5 text-xs font-bold text-[var(--ink)]"><GitBranch className="h-3.5 w-3.5" />图谱质量</h3>
                <div className="space-y-2.5 text-[11px]">
                  {(Object.keys(RELATIONS) as RelationKey[]).map((key) => {
                    const count = Number(relationCounts[key] ?? 0);
                    const confidence = Number(summary?.relation_confidence?.[key] ?? 0);
                    if (!count) return null;
                    return (
                      <div key={key}>
                        <div className="mb-1 flex justify-between text-[var(--color-text-secondary)]"><span>{RELATIONS[key].label} · {count}</span><span>{Math.round(confidence * 100)}% 置信度</span></div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-border-light)]"><div className="h-full rounded-full" style={{ width: `${clamp(confidence * 100, 3, 100)}%`, background: RELATIONS[key].color }} /></div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>
          ) : (
            <div className="grid min-h-[620px] place-items-center text-center">
              <div>
                <BookOpen className="mx-auto mb-3 h-7 w-7 text-[var(--color-text-hint)]" />
                <p className="text-sm font-semibold text-[var(--ink)]">选择一个知识点</p>
                <p className="mt-1 text-xs text-[var(--color-text-hint)]">点击图中节点查看关系与题量详情</p>
              </div>
            </div>
          )}
        </aside>
        ) : null}
      </div>
    </div>
  );
}
