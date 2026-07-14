"use client";

import { useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DashboardDailyPoint } from "@/lib/api/types";

type Period = "7d" | "30d";

interface SeriesMeta {
  key: keyof SeriesState;
  label: string;
  color: string;
  gradientId: string;
}

interface SeriesState {
  users: boolean;
  questions: boolean;
  imports: boolean;
  audits: boolean;
}

const SERIES: SeriesMeta[] = [
  { key: "users", label: "新增用户", color: "#5b7b9a", gradientId: "gradUsers" },
  { key: "questions", label: "新增题目", color: "#6b9b6b", gradientId: "gradQuestions" },
  { key: "imports", label: "导入批次", color: "#c49a6b", gradientId: "gradImports" },
  { key: "audits", label: "审计事件", color: "#9a7aba", gradientId: "gradAudits" },
];

function CustomTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-[rgba(232,229,224,0.8)] bg-[rgba(255,255,255,0.92)] px-4 py-3 shadow-lg text-sm">
      <p className="mb-2 font-semibold text-[var(--ink)]">{label}</p>
      {payload.map((entry: { name: string; value: number; color: string }) => (
        <p key={entry.name} className="flex items-center gap-2 leading-6 text-[var(--color-text-secondary)]">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
          {entry.name}: <span className="font-semibold text-[var(--ink)]">{entry.value?.toLocaleString("zh-CN") ?? entry.value}</span>
        </p>
      ))}
    </div>
  );
}

export function DashboardTrendChart({
  data,
  loading,
  period,
  onPeriodChange,
}: {
  data?: DashboardDailyPoint[] | null;
  loading?: boolean;
  period: "7d" | "30d";
  onPeriodChange: (p: "7d" | "30d") => void;
}) {
  const [series, setSeries] = useState<SeriesState>({
    users: true,
    questions: true,
    imports: false,
    audits: false,
  });

  const hasData = (data ?? []).length > 0;

  const toggleSeries = (key: keyof SeriesState) => {
    setSeries((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="rounded-2xl border border-[var(--color-border)]/80 bg-white/80 p-5 shadow-sm">
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-center lg:gap-x-6">
        <div className="shrink-0">
          <h3 className="font-display text-xl font-bold text-[var(--ink)]">近日日活与内容变化</h3>
          <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">
            {loading ? "加载中..." : `最近 ${period === "7d" ? "7" : "30"} 天的平台运营趋势`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="hidden items-center gap-2 md:flex">
            {SERIES.map(({ key, label, color }) => (
              <button
                key={key}
                onClick={() => toggleSeries(key)}
                className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors"
                style={{
                  backgroundColor: series[key] ? `${color}14` : "transparent",
                  color: series[key] ? color : "var(--color-text-hint)",
                }}
              >
                <span
                  className="h-2 w-2 rounded-full transition-all"
                  style={{ backgroundColor: series[key] ? color : "var(--color-border)" }}
                />
                {label}
              </button>
            ))}
          </div>
          <div className="flex overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] p-0.5">
            {(["7d", "30d"] as Period[]).map((p) => (
              <button
                key={p}
                onClick={() => onPeriodChange(p)}
                className="rounded-md px-3 py-1 text-xs font-semibold transition-all"
                style={{
                  backgroundColor: period === p ? "white" : "transparent",
                  color: period === p ? "var(--ink)" : "var(--color-text-hint)",
                  boxShadow: period === p ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                }}
              >
                {p === "7d" ? "最近 7 天" : "最近 30 天"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <div className="h-72 w-full animate-pulse rounded-xl bg-[var(--color-bg-input)]" />
      ) : (
        <div className="h-72 w-full">
          {hasData ? (
            <ResponsiveContainer key={period} width="100%" height="100%">
              <AreaChart data={data ?? []} margin={{ left: -16, right: 12 }}>
                <defs>
                  <linearGradient id="gradUsers" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#5b7b9a" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#5b7b9a" stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="gradQuestions" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6b9b6b" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#6b9b6b" stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="gradImports" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#c49a6b" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#c49a6b" stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="gradAudits" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#9a7aba" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#9a7aba" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(91,123,154,0.12)" strokeDasharray="4 4" />
                <XAxis
                  dataKey="date"
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 12, fill: "#6b7b8d" }}
                />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 12, fill: "#6b7b8d" }}
                  width={40}
                />
                <Tooltip content={<CustomTooltip />} />
                {series.users && (
                  <Area
                    type="monotone"
                    dataKey="users_new"
                    name="新增用户"
                    stroke="#5b7b9a"
                    fill="url(#gradUsers)"
                    strokeWidth={2.5}
                    dot={false}
                    activeDot={{ r: 5, fill: "#5b7b9a", stroke: "white", strokeWidth: 2 }}
                  />
                )}
                {series.questions && (
                  <Area
                    type="monotone"
                    dataKey="questions_new"
                    name="新增题目"
                    stroke="#6b9b6b"
                    fill="url(#gradQuestions)"
                    strokeWidth={2.5}
                    dot={false}
                    activeDot={{ r: 5, fill: "#6b9b6b", stroke: "white", strokeWidth: 2 }}
                  />
                )}
                {series.imports && (
                  <Area
                    type="monotone"
                    dataKey="imports_new"
                    name="导入批次"
                    stroke="#c49a6b"
                    fill="url(#gradImports)"
                    strokeWidth={2.5}
                    dot={false}
                    activeDot={{ r: 5, fill: "#c49a6b", stroke: "white", strokeWidth: 2 }}
                  />
                )}
                {series.audits && (
                  <Area
                    type="monotone"
                    dataKey="audits_total"
                    name="审计事件"
                    stroke="#9a7aba"
                    fill="url(#gradAudits)"
                    strokeWidth={2.5}
                    dot={false}
                    activeDot={{ r: 5, fill: "#9a7aba", stroke: "white", strokeWidth: 2 }}
                  />
                )}
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-[var(--color-text-hint)]">
              暂无趋势数据
            </div>
          )}
        </div>
      )}
    </div>
  );
}
