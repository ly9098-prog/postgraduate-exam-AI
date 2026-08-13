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
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
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
import { cn } from "@/lib/utils";

const RELATIONS = {
  prerequisite: { label: "前置", color: "#4a6f8a", text: "学习目标所依赖的基础知识" },
  parent: { label: "父子", color: "#5b8c5b", text: "概念与细分知识点的层级关系" },
  next: { label: "后续", color: "#c49a6b", text: "掌握当前知识后自然衔接的节点" },
  related: { label: "相关", color: "#9a7bbd", text: "没有强依赖但语义关联紧密" },
} as const;

type RelationKey = keyof typeof RELATIONS;
type PositionedNode = KnowledgeGraphNode & { x: number; y: number; level: number };

function shortName(name: string, length = 9) {
  return name.length > length ? `${name.slice(0, length)}…` : name;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function buildLayout(
  nodes: KnowledgeGraphNode[],
  edges: KnowledgeGraphEdge[],
  focusId: number | null,
  variant: number,
): PositionedNode[] {
  if (nodes.length === 0) return [];

  const nodeIds = new Set(nodes.map((node) => node.id));
  const adjacency = new Map<number, number[]>();
  for (const node of nodes) adjacency.set(node.id, []);
  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
    adjacency.get(edge.source)?.push(edge.target);
    adjacency.get(edge.target)?.push(edge.source);
  }

  const rootId = focusId && nodeIds.has(focusId)
    ? focusId
    : [...nodes].sort((a, b) => b.degree - a.degree)[0].id;

  const levels = new Map<number, number>([[rootId, 0]]);
  const queue = [rootId];
  while (queue.length) {
    const current = queue.shift()!;
    const level = levels.get(current) ?? 0;
    for (const neighbor of adjacency.get(current) ?? []) {
      if (levels.has(neighbor)) continue;
      levels.set(neighbor, level + 1);
      queue.push(neighbor);
    }
  }

  const fallbackLevel = Math.max(1, ...levels.values()) + 1;
  for (const node of nodes) {
    if (!levels.has(node.id)) levels.set(node.id, fallbackLevel);
  }

  const grouped = new Map<number, KnowledgeGraphNode[]>();
  for (const node of nodes) {
    const level = levels.get(node.id) ?? fallbackLevel;
    const bucket = grouped.get(level) ?? [];
    bucket.push(node);
    grouped.set(level, bucket);
  }

  const centerX = 500;
  const centerY = 355;
  const positions: PositionedNode[] = [];
  const maxLevel = Math.max(...grouped.keys());

  for (const [level, bucket] of [...grouped.entries()].sort((a, b) => a[0] - b[0])) {
    bucket.sort((a, b) => b.degree - a.degree || a.id - b.id);
    if (level === 0) {
      positions.push({ ...bucket[0], x: centerX, y: centerY, level });
      continue;
    }

    const radiusX = Math.min(420, 125 + level * 105);
    const radiusY = Math.min(290, 92 + level * 76);
    const start = -Math.PI / 2 + (variant % 8) * 0.17 + (level % 2) * 0.24;
    bucket.forEach((node, index) => {
      const angle = start + (Math.PI * 2 * index) / Math.max(bucket.length, 1);
      const jitter = ((node.id * 37 + variant * 19) % 13) - 6;
      positions.push({
        ...node,
        x: centerX + Math.cos(angle) * (radiusX + jitter),
        y: centerY + Math.sin(angle) * (radiusY + jitter * 0.55),
        level,
      });
    });
  }

  // If many disconnected nodes were placed on a huge outer ring, keep them inside the viewport.
  return positions.map((node) => ({
    ...node,
    x: clamp(node.x, 58, 942),
    y: clamp(node.y, 55, 660),
    level: Math.min(node.level, maxLevel),
  }));
}

function relationLabel(type: string) {
  return RELATIONS[type as RelationKey]?.label ?? type;
}

function relationColor(type: string) {
  return RELATIONS[type as RelationKey]?.color ?? "#8a9ba9";
}

function difficultyText(level: number) {
  if (level <= 1) return "基础";
  if (level === 2) return "较易";
  if (level === 3) return "中等";
  if (level === 4) return "较难";
  return "进阶";
}

function GraphCanvas({
  data,
  selectedId,
  onSelect,
  onFocus,
  layoutVariant,
  zoom,
}: {
  data: KnowledgeGraphResponse;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onFocus: (id: number) => void;
  layoutVariant: number;
  zoom: number;
}) {
  const nodes = useMemo(
    () => buildLayout(data.nodes, data.edges, data.focus_id, layoutVariant),
    [data.nodes, data.edges, data.focus_id, layoutVariant],
  );
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const showEdgeLabels = data.edges.length <= 24;

  return (
    <svg id="knowledge-graph-svg" viewBox="0 0 1000 710" className="h-full min-h-[620px] w-full select-none" role="img" aria-label="知识图谱可视化">
      <defs>
        {(Object.keys(RELATIONS) as RelationKey[]).map((type) => (
          <marker key={type} id={`kg-arrow-${type}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L8,4 L0,8 z" fill={RELATIONS[type].color} />
          </marker>
        ))}
        <filter id="kg-node-shadow" x="-40%" y="-40%" width="180%" height="180%">
          <feDropShadow dx="0" dy="5" stdDeviation="5" floodColor="#1b2733" floodOpacity="0.12" />
        </filter>
      </defs>

      <g transform={`translate(500 355) scale(${zoom}) translate(-500 -355)`}>
        {data.edges.map((edge) => {
          const source = nodeMap.get(edge.source);
          const target = nodeMap.get(edge.target);
          if (!source || !target) return null;
          const dx = target.x - source.x;
          const dy = target.y - source.y;
          const len = Math.max(1, Math.sqrt(dx * dx + dy * dy));
          const sourceRadius = clamp(29 + source.degree * 0.7, 31, 45);
          const targetRadius = clamp(29 + target.degree * 0.7, 31, 45);
          const sx = source.x + (dx / len) * sourceRadius;
          const sy = source.y + (dy / len) * sourceRadius;
          const tx = target.x - (dx / len) * (targetRadius + 7);
          const ty = target.y - (dy / len) * (targetRadius + 7);
          const color = relationColor(edge.relation_type);
          const isConnected = selectedId != null && (edge.source === selectedId || edge.target === selectedId);
          return (
            <g key={edge.id}>
              <line
                x1={sx}
                y1={sy}
                x2={tx}
                y2={ty}
                stroke={color}
                strokeWidth={isConnected ? 2.7 : 1.4 + edge.confidence * 0.7}
                strokeOpacity={selectedId == null || isConnected ? 0.74 : 0.19}
                strokeDasharray={edge.source_type === "inferred" ? "7 5" : undefined}
                markerEnd={`url(#kg-arrow-${edge.relation_type})`}
              />
              {showEdgeLabels && (selectedId == null || isConnected) && (
                <g transform={`translate(${(sx + tx) / 2} ${(sy + ty) / 2})`}>
                  <rect x="-20" y="-10" width="40" height="18" rx="8" fill="#fefcf9" fillOpacity="0.94" stroke={color} strokeOpacity="0.18" />
                  <text textAnchor="middle" dominantBaseline="middle" y="-1" fontSize="9" fontWeight="600" fill={color}>
                    {relationLabel(edge.relation_type)}
                  </text>
                </g>
              )}
            </g>
          );
        })}

        {nodes.map((node) => {
          const selected = node.id === selectedId;
          const focused = node.id === data.focus_id;
          const radius = clamp(29 + node.degree * 0.7, 31, 45);
          const dimmed = selectedId != null && !selected && !data.edges.some((edge) =>
            (edge.source === selectedId && edge.target === node.id) || (edge.target === selectedId && edge.source === node.id),
          );
          return (
            <g
              key={node.id}
              transform={`translate(${node.x} ${node.y})`}
              className="cursor-pointer"
              opacity={dimmed ? 0.42 : 1}
              onClick={() => onSelect(node.id)}
              onDoubleClick={() => onFocus(node.id)}
            >
              {focused && <circle r={radius + 12} fill="none" stroke="#4a6f8a" strokeOpacity="0.16" strokeWidth="8" />}
              <circle
                r={radius}
                fill={selected ? "#e8f0f5" : "#fefcf9"}
                stroke={selected || focused ? "#4a6f8a" : "#90a8b8"}
                strokeWidth={selected ? 2.8 : 1.6}
                filter="url(#kg-node-shadow)"
              />
              <circle r={10} cy={-4} fill={selected ? "#4a6f8a" : "#dce8ef"} stroke="#4a6f8a" strokeWidth="1.6" />
              <circle r={4.1} cy={-4} fill={selected ? "#fefcf9" : "#4a6f8a"} />
              <text textAnchor="middle" y={18} fontSize="11" fontWeight="700" fill="#1e2b38">
                {shortName(node.name)}
              </text>
              <text textAnchor="middle" y={radius + 17} fontSize="9" fill="#8a9ba9">
                {node.degree} 关系 · {node.question_count} 题
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

function RelationDonut({ counts }: { counts: Record<string, number> }) {
  const entries = (Object.keys(RELATIONS) as RelationKey[])
    .map((key) => ({ key, value: Number(counts[key] ?? 0) }))
    .filter((item) => item.value > 0);
  const total = entries.reduce((sum, item) => sum + item.value, 0);
  let cursor = 0;
  const stops = entries.map((item) => {
    const start = cursor;
    cursor += total ? (item.value / total) * 100 : 0;
    return `${RELATIONS[item.key].color} ${start}% ${cursor}%`;
  });

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

export default function KnowledgeGraphPage() {
  const [subjectId, setSubjectId] = useState("");
  const [relationType, setRelationType] = useState("");
  const [depth, setDepth] = useState("2");
  const [searchDraft, setSearchDraft] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [centerId, setCenterId] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [layoutVariant, setLayoutVariant] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);

  const subjects = useQuery({
    queryKey: ["knowledge-graph", "subjects"],
    queryFn: () => apiRequest<KnowledgeGraphSubject[]>("/knowledge/subjects"),
  });

  useEffect(() => {
    if (subjectId || !subjects.data?.length) return;
    const best = [...subjects.data].sort((a, b) => b.edge_count - a.edge_count || b.knowledge_point_count - a.knowledge_point_count)[0];
    setSubjectId(String(best.id));
  }, [subjectId, subjects.data]);

  const graph = useQuery({
    queryKey: ["knowledge-graph", subjectId, relationType, depth, searchTerm, centerId],
    enabled: Boolean(subjectId),
    queryFn: () => apiRequest<KnowledgeGraphResponse>(`/knowledge/graph${toQuery({
      subject_id: Number(subjectId),
      relation_type: relationType || undefined,
      knowledge_point_id: centerId ?? undefined,
      search: searchTerm || undefined,
      depth: Number(depth),
      max_nodes: 70,
    })}`),
  });

  useEffect(() => {
    const data = graph.data;
    if (!data) return;
    if (selectedId != null && data.nodes.some((node) => node.id === selectedId)) return;
    setSelectedId(data.focus_id ?? data.nodes[0]?.id ?? null);
  }, [graph.data, selectedId]);

  const selectedNode = useMemo(
    () => graph.data?.nodes.find((node) => node.id === selectedId) ?? null,
    [graph.data, selectedId],
  );

  const selectedConnections = useMemo(() => {
    if (!graph.data || selectedId == null) return [];
    const nodeMap = new Map(graph.data.nodes.map((node) => [node.id, node]));
    return graph.data.edges
      .filter((edge) => edge.source === selectedId || edge.target === selectedId)
      .map((edge) => {
        const outgoing = edge.source === selectedId;
        const otherId = outgoing ? edge.target : edge.source;
        return { edge, node: nodeMap.get(otherId), outgoing };
      })
      .filter((item) => item.node)
      .sort((a, b) => b.edge.confidence - a.edge.confidence || b.edge.weight - a.edge.weight);
  }, [graph.data, selectedId]);

  const visibleSelectedConnections = selectedConnections.slice(0, 9);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setCenterId(null);
    setSelectedId(null);
    setSearchTerm(searchDraft.trim());
  }

  function resetView() {
    setSearchDraft("");
    setSearchTerm("");
    setCenterId(null);
    setSelectedId(null);
    setZoom(1);
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
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  const summary = graph.data?.summary;
  const relationCounts = summary?.relation_counts ?? {};

  return (
    <div className="mx-auto flex max-w-[1540px] flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-3xl font-bold tracking-tight text-[var(--ink)]">知识图谱</h1>
            <span className="rounded-full bg-[var(--color-primary-light)] px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-[var(--color-primary-dark)]">Graph</span>
          </div>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">探索知识点之间的前置、父子、后续与相关关系，校验智能推荐的学习路径基础。</p>
        </div>
        {summary && (
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-xl border border-[var(--color-border)] bg-white/70 px-3 py-2 text-[var(--color-text-secondary)]">
              <b className="mr-1 text-[var(--ink)]">{summary.total_nodes}</b>知识点
            </span>
            <span className="rounded-xl border border-[var(--color-border)] bg-white/70 px-3 py-2 text-[var(--color-text-secondary)]">
              <b className="mr-1 text-[var(--ink)]">{summary.total_edges}</b>关系边
            </span>
            <span className="rounded-xl border border-[var(--color-border)] bg-white/70 px-3 py-2 text-[var(--color-text-secondary)]">
              平均置信度 <b className="ml-1 text-[var(--ink)]">{(summary.avg_confidence * 100).toFixed(0)}%</b>
            </span>
          </div>
        )}
      </div>

      <section className="surface-card rounded-2xl p-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <form onSubmit={submitSearch} className="relative min-w-[280px] flex-1 lg:max-w-[540px]">
            <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
            <Input
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              className="h-10 bg-white/80 pl-10 pr-20"
              placeholder="搜索知识点名称或 ID"
            />
            <button type="submit" className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg px-2.5 py-1 text-xs font-semibold text-[var(--color-primary-dark)] hover:bg-[var(--color-primary-light)]">
              定位
            </button>
          </form>

          <Select
            value={subjectId}
            onChange={(value) => {
              setSubjectId(value);
              setSelectedId(null);
              setCenterId(null);
              setSearchDraft("");
              setSearchTerm("");
            }}
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
            onChange={(value) => { setRelationType(value); setSelectedId(null); }}
            className="h-10 min-w-[128px] border-[var(--color-border)]"
            options={[
              { value: "", label: "全部关系" },
              ...Object.entries(RELATIONS).map(([value, config]) => ({ value, label: config.label })),
            ]}
          />
          <Select
            value={depth}
            onChange={setDepth}
            className="h-10 min-w-[92px] border-[var(--color-border)]"
            options={[1, 2, 3].map((value) => ({ value: String(value), label: `深度 ${value}` }))}
          />

          <div className="ml-auto flex items-center gap-2">
            <Button variant="secondary" onClick={() => setLayoutVariant((value) => value + 1)}>
              <LayoutGrid className="h-4 w-4" />布局
            </Button>
            <Button variant="secondary" onClick={resetView} title="返回科目总览">
              <RefreshCw className="h-4 w-4" />总览
            </Button>
            <Button variant="primary" onClick={exportGraph} disabled={!graph.data?.nodes.length}>
              <Download className="h-4 w-4" />导出图谱
            </Button>
          </div>
        </div>

        {!!graph.data?.hot_nodes.length && (
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--color-border-light)] pt-3">
            <span className="text-[11px] font-medium text-[var(--color-text-hint)]">热门知识点：</span>
            {graph.data.hot_nodes.map((node) => (
              <button
                key={node.id}
                type="button"
                onClick={() => {
                  setSearchDraft(node.name);
                  setSearchTerm(node.name);
                  setCenterId(null);
                  setSelectedId(null);
                }}
                className="rounded-full border border-[var(--color-border-light)] bg-white/70 px-2.5 py-1 text-[11px] text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:text-[var(--color-primary-dark)]"
              >
                {node.name}<span className="ml-1 text-[9px] text-[var(--color-text-hint)]">{node.degree}</span>
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="grid min-h-[680px] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_350px]">
        <section
          className={cn(
            "surface-card relative min-h-[680px] overflow-hidden rounded-3xl",
            fullscreen && "fixed inset-4 z-[100] min-h-0 bg-[var(--porcelain)] shadow-2xl",
          )}
        >
          <div
            className="absolute inset-0"
            style={{
              backgroundColor: "rgba(254,252,249,0.94)",
              backgroundImage: "radial-gradient(circle, rgba(74,111,138,0.16) 1px, transparent 1px)",
              backgroundSize: "18px 18px",
            }}
          />

          <div className="absolute left-4 top-4 z-10 w-[150px] rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.9)] p-3 shadow-[var(--shadow-card)] backdrop-blur-md">
            <div className="mb-2 text-[11px] font-bold text-[var(--ink)]">图例</div>
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

          <div className="absolute right-4 top-4 z-10 flex gap-2">
            {graph.isFetching && (
              <span className="flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-white/85 px-3 py-2 text-[10px] text-[var(--color-text-hint)]">
                <RefreshCw className="h-3 w-3 animate-spin" />刷新中
              </span>
            )}
            <button
              type="button"
              onClick={() => setFullscreen((value) => !value)}
              className="grid h-9 w-9 place-items-center rounded-xl border border-[var(--color-border)] bg-white/90 text-[var(--color-text-secondary)] shadow-sm hover:text-[var(--color-primary-dark)]"
              title={fullscreen ? "退出全屏" : "放大画布"}
            >
              {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
          </div>

          <div className="absolute bottom-5 right-5 z-10 overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white/90 shadow-md">
            <button type="button" onClick={() => setZoom((value) => clamp(value + 0.12, 0.68, 1.5))} className="grid h-10 w-10 place-items-center text-[var(--color-text-secondary)] hover:bg-[var(--color-primary-light)]"><Plus className="h-4 w-4" /></button>
            <button type="button" onClick={() => setZoom(1)} className="grid h-10 w-10 place-items-center border-y border-[var(--color-border-light)] text-[var(--color-text-secondary)] hover:bg-[var(--color-primary-light)]"><Focus className="h-4 w-4" /></button>
            <button type="button" onClick={() => setZoom((value) => clamp(value - 0.12, 0.68, 1.5))} className="grid h-10 w-10 place-items-center text-[var(--color-text-secondary)] hover:bg-[var(--color-primary-light)]"><Minus className="h-4 w-4" /></button>
          </div>

          <div className={cn("relative h-full", fullscreen ? "min-h-0" : "min-h-[680px]")}>
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
            ) : graph.data && graph.data.nodes.length > 0 ? (
              <GraphCanvas
                data={graph.data}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onFocus={(id) => { setCenterId(id); setSearchTerm(""); setSearchDraft(""); setSelectedId(id); }}
                layoutVariant={layoutVariant}
                zoom={zoom}
              />
            ) : (
              <div className="absolute inset-0 grid place-items-center px-8 text-center text-sm text-[var(--color-text-hint)]">
                {searchTerm ? `未找到与「${searchTerm}」匹配的知识点` : "当前筛选条件下没有可展示的知识点关系"}
              </div>
            )}
          </div>

          {summary && (
            <div className="absolute bottom-5 left-5 z-10 flex flex-wrap gap-2 text-[10px] text-[var(--color-text-hint)]">
              <span className="rounded-lg border border-[var(--color-border-light)] bg-white/85 px-2.5 py-1.5">当前视图 {summary.visible_nodes} 节点 / {summary.visible_edges} 边</span>
              {summary.isolated_nodes > 0 && <span className="rounded-lg border border-[var(--color-warning)]/30 bg-[var(--color-warning-light)] px-2.5 py-1.5 text-[#8a6846]">孤立节点 {summary.isolated_nodes}</span>}
            </div>
          )}
        </section>

        <aside className="surface-card min-h-[680px] rounded-3xl p-5">
          {selectedNode ? (
            <div className="space-y-5">
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
                  </div>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2 rounded-2xl border border-[var(--color-border-light)] bg-white/55 p-3 text-[11px]">
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
                    onClick={() => { setCenterId(selectedNode.id); setSearchTerm(""); setSearchDraft(""); }}
                  >
                    <Focus className="h-3.5 w-3.5" />以此知识点为中心展开
                  </Button>
                )}
              </section>

              <section className="border-t border-[var(--color-border-light)] pt-4">
                <div className="mb-2.5 flex items-center justify-between">
                  <h3 className="text-xs font-bold text-[var(--ink)]">相邻知识点 <span className="font-normal text-[var(--color-text-hint)]">({selectedConnections.length})</span></h3>
                  {selectedConnections.length > 0 && <span className="text-[9px] text-[var(--color-text-hint)]">按置信度排序</span>}
                </div>
                <div className="space-y-1.5">
                  {selectedConnections.length ? visibleSelectedConnections.map(({ edge, node, outgoing }) => node && (
                    <button
                      type="button"
                      key={edge.id}
                      onClick={() => setSelectedId(node.id)}
                      className="flex w-full items-center gap-2 rounded-xl border border-transparent px-2.5 py-2 text-left transition hover:border-[var(--color-border-light)] hover:bg-white/70"
                    >
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: relationColor(edge.relation_type) }} />
                      <span className="min-w-0 flex-1 truncate text-xs font-medium text-[var(--ink)]">{node.name}</span>
                      <span className="shrink-0 rounded-md px-1.5 py-0.5 text-[9px]" style={{ color: relationColor(edge.relation_type), background: `${relationColor(edge.relation_type)}12` }}>
                        {outgoing ? "→" : "←"} {relationLabel(edge.relation_type)}
                      </span>
                      <span className="w-8 shrink-0 text-right font-mono text-[9px] text-[var(--color-text-hint)]">{Math.round(edge.confidence * 100)}%</span>
                    </button>
                  )) : (
                    <div className="rounded-xl border border-dashed border-[var(--color-border)] p-4 text-center text-[11px] text-[var(--color-text-hint)]">当前视图中没有相邻关系</div>
                  )}
                  {selectedConnections.length > visibleSelectedConnections.length && (
                    <div className="px-2 pt-1 text-[10px] text-[var(--color-text-hint)]">
                      仅展示置信度最高的 {visibleSelectedConnections.length} 条，当前视图共 {selectedConnections.length} 条相邻关系
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
      </div>
    </div>
  );
}
