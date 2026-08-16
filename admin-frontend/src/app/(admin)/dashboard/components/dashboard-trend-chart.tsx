"use client";

import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import type { DashboardDailyPoint } from "@/lib/api/types";

type Period = "7d" | "30d";

type SeriesKey = "users" | "questions" | "imports" | "audits";

interface SeriesState {
  users: boolean;
  questions: boolean;
  imports: boolean;
  audits: boolean;
}

interface SeriesMeta {
  key: SeriesKey;
  dataKey: keyof DashboardDailyPoint;
  label: string;
  color: string;
  glow: string;
}

const SERIES: SeriesMeta[] = [
  { key: "users", dataKey: "users_new", label: "新增用户", color: "#4a6f8a", glow: "#9bb0bf" },
  { key: "questions", dataKey: "questions_new", label: "新增题目", color: "#6d906d", glow: "#a8bea8" },
  { key: "imports", dataKey: "imports_new", label: "导入批次", color: "#8b7c97", glow: "#b8afc1" },
  { key: "audits", dataKey: "audits_total", label: "审计事件", color: "#b58a62", glow: "#d7b99b" },
];

const VIEWBOX_HEIGHT = 318;
const PLOT = { left: 46, right: 14, top: 12, bottom: 34 };
const PLOT_HEIGHT = VIEWBOX_HEIGHT - PLOT.top - PLOT.bottom;

function formatDateTick(value: string) {
  const parts = value.split("-");
  if (parts.length !== 3) return value;
  return `${parts[1]}-${parts[2]}`;
}

function safeNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function niceMax(value: number) {
  if (value <= 0) return 4;
  const rawStep = value / 4;
  const exponent = Math.floor(Math.log10(rawStep));
  const magnitude = 10 ** exponent;
  const normalized = rawStep / magnitude;
  const steps = [1, 2, 2.5, 3, 4, 5, 6, 8, 10];
  const step = (steps.find((candidate) => normalized <= candidate) ?? 10) * magnitude;
  return step * 4;
}

function pointToString(point: { x: number; y: number }) {
  return `${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
}

function smoothPath(points: Array<{ x: number; y: number }>) {
  if (!points.length) return "";
  if (points.length === 1) return `M ${pointToString(points[0])}`;
  if (points.length === 2) return `M ${pointToString(points[0])} L ${pointToString(points[1])}`;

  let path = `M ${pointToString(points[0])}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const previous = points[index - 1] ?? current;
    const afterNext = points[index + 2] ?? next;
    const tension = 0.17;
    const cp1 = {
      x: current.x + (next.x - previous.x) * tension,
      y: current.y + (next.y - previous.y) * tension,
    };
    const cp2 = {
      x: next.x - (afterNext.x - current.x) * tension,
      y: next.y - (afterNext.y - current.y) * tension,
    };
    path += ` C ${pointToString(cp1)}, ${pointToString(cp2)}, ${pointToString(next)}`;
  }
  return path;
}

function areaPath(points: Array<{ x: number; y: number }>, baseline: number) {
  if (!points.length) return "";
  const line = smoothPath(points);
  return `${line} L ${points.at(-1)!.x.toFixed(2)} ${baseline.toFixed(2)} L ${points[0].x.toFixed(2)} ${baseline.toFixed(2)} Z`;
}

export function DashboardTrendChart({
  data,
  loading,
  period,
  onPeriodChange,
}: {
  data?: DashboardDailyPoint[] | null;
  loading?: boolean;
  period: Period;
  onPeriodChange: (period: Period) => void;
}) {
  const [series, setSeries] = useState<SeriesState>({
    users: true,
    questions: true,
    imports: true,
    audits: true,
  });
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(0);

  const rows = data ?? [];
  const hasData = rows.length > 0;

  useEffect(() => {
    if (loading || !hasData) return;
    const element = chartContainerRef.current;
    if (!element) return;

    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const width = element.clientWidth || element.getBoundingClientRect().width;
        if (width > 0) setChartWidth(Math.round(width));
      });
    };

    update();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(update) : null;
    observer?.observe(element);
    window.addEventListener("resize", update);
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [loading, hasData]);

  const chart = useMemo(() => {
    const width = Math.max(chartWidth, 320);
    const plotWidth = Math.max(220, width - PLOT.left - PLOT.right);
    const enabledSeries = SERIES.filter((item) => series[item.key]);
    const maxValue = Math.max(
      0,
      ...rows.flatMap((row) => enabledSeries.map((item) => safeNumber(row[item.dataKey]))),
    );
    const yMax = niceMax(maxValue * 1.08);
    const xForIndex = (index: number) =>
      rows.length <= 1 ? PLOT.left + plotWidth / 2 : PLOT.left + (index / (rows.length - 1)) * plotWidth;
    const yForValue = (value: number) => PLOT.top + PLOT_HEIGHT - (value / yMax) * PLOT_HEIGHT;

    const paths = Object.fromEntries(
      SERIES.map((meta) => {
        const points = rows.map((row, index) => ({
          x: xForIndex(index),
          y: yForValue(safeNumber(row[meta.dataKey])),
        }));
        return [meta.key, { points, line: smoothPath(points), area: areaPath(points, PLOT.top + PLOT_HEIGHT) }];
      }),
    ) as Record<SeriesKey, { points: Array<{ x: number; y: number }>; line: string; area: string }>;

    const yTicks = Array.from({ length: 5 }, (_, index) => {
      const value = (yMax / 4) * index;
      return { value, y: yForValue(value) };
    }).reverse();

    const desiredTicks = period === "30d" ? 7 : Math.min(7, rows.length);
    const xTickIndices = Array.from({ length: desiredTicks }, (_, index) => {
      if (desiredTicks <= 1) return 0;
      return Math.round((index / (desiredTicks - 1)) * Math.max(0, rows.length - 1));
    }).filter((value, index, all) => all.indexOf(value) === index);

    return { width, plotWidth, yMax, xForIndex, paths, yTicks, xTickIndices };
  }, [chartWidth, period, rows, series]);

  const hoveredRow = hoverIndex !== null ? rows[hoverIndex] : null;
  const hoveredX = hoverIndex !== null ? chart.xForIndex(hoverIndex) : null;
  const tooltipLeft = hoverIndex !== null && rows.length > 1 ? (hoverIndex / (rows.length - 1)) * 100 : 50;

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!rows.length) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const localX = event.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, (localX - PLOT.left) / chart.plotWidth));
    const index = rows.length <= 1 ? 0 : Math.round(ratio * (rows.length - 1));
    setHoverIndex(index);
  };

  return (
    <div className="h-full min-w-0 rounded-2xl border border-[var(--color-border-light)] bg-white/[0.86] p-5 shadow-[0_6px_24px_rgba(37,61,89,0.05)] backdrop-blur-sm transition-shadow duration-300 hover:shadow-[0_10px_32px_rgba(37,61,89,0.075)]">
      <style jsx global>{`
        @keyframes dashboard-shimmer {
          from { transform: translateX(-80%); }
          to { transform: translateX(440%); }
        }
      `}</style>
      <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-display text-xl font-bold text-[var(--ink)]">近日日活与内容变化</h3>
            <span className="grid h-4 w-4 place-items-center rounded-full border border-[var(--color-border)] text-[9px] font-semibold text-[var(--color-text-hint)]">
              i
            </span>
          </div>
          <p className="mt-1 text-xs text-[var(--color-text-hint)]">
            {loading ? "正在加载运营趋势" : `最近 ${period === "7d" ? "7" : "30"} 天平台新增与审计事件`}
          </p>
        </div>

        <div className="flex shrink-0 overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-[var(--color-bg-input)]/65 p-0.5 shadow-inner">
          {(["7d", "30d"] as Period[]).map((item) => (
            <button
              type="button"
              key={item}
              onClick={() => onPeriodChange(item)}
              className={`rounded-[9px] px-3 py-1.5 text-xs font-semibold transition-all duration-200 ${
                period === item
                  ? "bg-white text-[var(--color-primary-dark)] shadow-sm ring-1 ring-[var(--color-primary)]/15"
                  : "text-[var(--color-text-hint)] hover:bg-white/50 hover:text-[var(--ink)]"
              }`}
            >
              {item === "7d" ? "最近 7 天" : "最近 30 天"}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {SERIES.map((item) => {
          const enabled = series[item.key];
          return (
            <button
              type="button"
              key={item.key}
              onClick={() => setSeries((current) => ({ ...current, [item.key]: !current[item.key] }))}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-medium transition-all duration-200 ${
                enabled
                  ? "border-transparent bg-transparent text-[var(--color-text-secondary)] hover:border-[var(--color-border-light)] hover:bg-white"
                  : "border-transparent text-[var(--color-text-hint)] opacity-55 hover:opacity-80"
              }`}
            >
              <span
                className="h-2 w-2 rounded-full transition-transform duration-200"
                style={{ backgroundColor: enabled ? item.color : "var(--color-border)", transform: enabled ? "scale(1)" : "scale(.8)" }}
              />
              {item.label}
            </button>
          );
        })}
      </div>

      {loading ? (
        <div className="relative h-[318px] overflow-hidden rounded-xl bg-[var(--color-bg-input)]/55 motion-reduce:animate-none">
          <div className="absolute inset-y-0 -left-1/3 w-1/3 animate-[dashboard-shimmer_1.2s_ease-in-out_infinite] bg-gradient-to-r from-transparent via-white/80 to-transparent" />
        </div>
      ) : hasData ? (
        <div ref={chartContainerRef} className="relative h-[318px] min-h-[318px] min-w-0 w-full overflow-hidden rounded-xl bg-white/30">
          {hoveredRow && hoverIndex !== null ? (
            <div
              className="pointer-events-none absolute top-3 z-20 min-w-40 -translate-x-1/2 rounded-2xl border border-[var(--color-border-light)] bg-white/95 px-4 py-3 text-xs shadow-[0_14px_34px_rgba(37,61,89,0.14)] backdrop-blur-md transition-[left] duration-75"
              style={{ left: `${Math.min(90, Math.max(10, tooltipLeft))}%` }}
            >
              <p className="mb-2 font-bold text-[var(--ink)]">{hoveredRow.date}</p>
              <div className="space-y-1.5">
                {SERIES.filter((item) => series[item.key]).map((item) => (
                  <p key={item.key} className="flex items-center justify-between gap-5 text-[var(--color-text-secondary)]">
                    <span className="flex items-center gap-2">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
                      {item.label}
                    </span>
                    <strong className="tabular-nums text-[var(--ink)]">{safeNumber(hoveredRow[item.dataKey]).toLocaleString("zh-CN")}</strong>
                  </p>
                ))}
              </div>
            </div>
          ) : null}

          <svg
            key={period}
            viewBox={`0 0 ${chart.width} ${VIEWBOX_HEIGHT}`}
            preserveAspectRatio="none"
            className="block h-full w-full select-none outline-none"
            aria-label="近日日活与内容变化趋势图"
            focusable="false"
            onPointerMove={handlePointerMove}
            onPointerLeave={() => setHoverIndex(null)}
          >
            <defs>
              <linearGradient id="dashboardUsersArea" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#4a6f8a" stopOpacity="0.13" />
                <stop offset="48%" stopColor="#4a6f8a" stopOpacity="0.055" />
                <stop offset="100%" stopColor="#4a6f8a" stopOpacity="0.006" />
              </linearGradient>
            </defs>

            {chart.yTicks.map((tick) => (
              <g key={`y-${tick.value}`}>
                <line
                  x1={PLOT.left}
                  x2={PLOT.left + chart.plotWidth}
                  y1={tick.y}
                  y2={tick.y}
                  stroke="#e3e0da"
                  strokeOpacity="0.75"
                  strokeDasharray="4 5"
                  vectorEffect="non-scaling-stroke"
                />
                <text x={PLOT.left - 10} y={tick.y + 4} textAnchor="end" fontSize="11" fill="#8a9ba9">
                  {Math.round(tick.value)}
                </text>
              </g>
            ))}

            {chart.xTickIndices.map((index) => {
              const x = chart.xForIndex(index);
              return (
                <g key={`x-${index}`}>
                  <line
                    x1={x}
                    x2={x}
                    y1={PLOT.top}
                    y2={PLOT.top + PLOT_HEIGHT}
                    stroke="#ece8e1"
                    strokeOpacity="0.62"
                    strokeDasharray="4 6"
                    vectorEffect="non-scaling-stroke"
                  />
                  <text x={x} y={VIEWBOX_HEIGHT - 9} textAnchor="middle" fontSize="11" fill="#8a9ba9">
                    {formatDateTick(rows[index]?.date ?? "")}
                  </text>
                </g>
              );
            })}

            {series.users && chart.paths.users.area ? (
              <path d={chart.paths.users.area} fill="url(#dashboardUsersArea)" opacity="0">
                <animate attributeName="opacity" from="0" to="1" dur="560ms" begin="120ms" fill="freeze" />
              </path>
            ) : null}

            {SERIES.map((meta, seriesIndex) => {
              if (!series[meta.key]) return null;
              const path = chart.paths[meta.key].line;
              if (!path) return null;
              return (
                <g key={meta.key}>
                  <path
                    d={path}
                    fill="none"
                    stroke={meta.color}
                    strokeWidth={meta.key === "users" ? "4.6" : "3.8"}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    opacity="0.055"
                    vectorEffect="non-scaling-stroke"
                    pathLength={1}
                    strokeDasharray="1"
                    strokeDashoffset="1"
                  >
                    <animate attributeName="stroke-dashoffset" from="1" to="0" dur="760ms" begin={`${90 + seriesIndex * 70}ms`} fill="freeze" />
                  </path>
                  <path
                    d={path}
                    fill="none"
                    stroke={meta.color}
                    strokeWidth={meta.key === "users" ? "2.05" : "1.75"}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    vectorEffect="non-scaling-stroke"
                    pathLength={1}
                    strokeDasharray="1"
                    strokeDashoffset="1"
                  >
                    <animate attributeName="stroke-dashoffset" from="1" to="0" dur="760ms" begin={`${90 + seriesIndex * 70}ms`} fill="freeze" />
                  </path>
                </g>
              );
            })}

            {hoveredX !== null ? (
              <line
                x1={hoveredX}
                x2={hoveredX}
                y1={PLOT.top}
                y2={PLOT.top + PLOT_HEIGHT}
                stroke="#2f74df"
                strokeOpacity="0.24"
                strokeWidth="1"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}

            {hoverIndex !== null
              ? SERIES.map((meta) => {
                  if (!series[meta.key]) return null;
                  const point = chart.paths[meta.key].points[hoverIndex];
                  if (!point) return null;
                  return (
                    <g key={`active-${meta.key}`}>
                      <circle cx={point.x} cy={point.y} r="8" fill={meta.glow} opacity="0.18" />
                      <circle cx={point.x} cy={point.y} r="4.2" fill={meta.color} stroke="#fff" strokeWidth="2" vectorEffect="non-scaling-stroke" />
                    </g>
                  );
                })
              : null}
          </svg>
        </div>
      ) : (
        <div className="grid h-[318px] min-h-[318px] min-w-0 place-items-center rounded-xl border border-dashed border-[var(--color-border)] text-sm text-[var(--color-text-hint)]">
          暂无趋势数据
        </div>
      )}
    </div>
  );
}
