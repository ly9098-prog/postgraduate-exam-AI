"use client";

import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import type { EChartsCoreOption } from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { DailyTrendPoint } from "@/lib/api/types";

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, CanvasRenderer]);

type Period = "7d" | "30d";

export function TrendChart({
  trends,
  loading,
}: {
  trends?: DailyTrendPoint[] | null;
  loading?: boolean;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const [period, setPeriod] = useState<Period>("7d");
  const [series, setSeries] = useState({
    calls: true,
    tokens: true,
    success: true,
    latency: true,
  });

  const data = (trends ?? []).slice(-(period === "7d" ? 7 : 30));

  useEffect(() => {
    if (!chartRef.current) return;
    if (!instanceRef.current) {
      instanceRef.current = echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    }
    const instance = instanceRef.current;

    const activeSeries: Record<string, unknown>[] = [];

    if (series.calls) {
      activeSeries.push({
        name: "调用次数",
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        lineStyle: { width: 3, color: "#5b7b9a" },
        itemStyle: { color: "#5b7b9a" },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(91,123,154,0.35)" },
            { offset: 1, color: "rgba(91,123,154,0.02)" },
          ]),
        },
        data: data.map((d) => d.calls),
        yAxisIndex: 0,
      });
    }
    if (series.tokens) {
      activeSeries.push({
        name: "Token 消耗 (K)",
        type: "line",
        smooth: true,
        symbol: "diamond",
        symbolSize: 6,
        lineStyle: { width: 2, color: "#9a7aba", type: "solid" },
        itemStyle: { color: "#9a7aba" },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(154,122,186,0.25)" },
            { offset: 1, color: "rgba(154,122,186,0.02)" },
          ]),
        },
        data: data.map((d) => Math.round(d.tokens / 1000)),
        yAxisIndex: 0,
      });
    }
    if (series.success) {
      activeSeries.push({
        name: "成功率 (%)",
        type: "line",
        smooth: true,
        symbol: "roundRect",
        symbolSize: 6,
        lineStyle: { width: 2, color: "#6b9b6b" },
        itemStyle: { color: "#6b9b6b" },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(107,155,107,0.2)" },
            { offset: 1, color: "rgba(107,155,107,0.02)" },
          ]),
        },
        data: data.map((d) => d.success_rate),
        yAxisIndex: 1,
      });
    }
    if (series.latency) {
      activeSeries.push({
        name: "平均耗时 (s)",
        type: "line",
        smooth: true,
        symbol: "triangle",
        symbolSize: 7,
        lineStyle: { width: 2, color: "#c49a6b" },
        itemStyle: { color: "#c49a6b" },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(196,154,107,0.2)" },
            { offset: 1, color: "rgba(196,154,107,0.02)" },
          ]),
        },
        data: data.map((d) => d.avg_latency_ms / 1000),
        yAxisIndex: 1,
      });
    }

    const hasData = data.length > 0;
    const option: EChartsCoreOption = {
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(255,255,255,0.92)",
        borderColor: "rgba(232,229,224,0.8)",
        borderWidth: 1,
        borderRadius: 12,
        padding: [12, 16],
        textStyle: { color: "#2d3e50", fontSize: 13 },
        axisPointer: {
          type: "cross",
          crossStyle: { color: "rgba(91,123,154,0.3)" },
          lineStyle: { color: "rgba(91,123,154,0.2)", type: "dashed" },
        },
      },
      legend: {
        data: [
          { name: "调用次数", icon: "circle" },
          { name: "Token 消耗 (K)", icon: "diamond" },
          { name: "成功率 (%)", icon: "roundRect" },
          { name: "平均耗时 (s)", icon: "triangle" },
        ],
        bottom: 0,
        left: "center",
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: "#6b7b8d", fontSize: 12 },
      },
      grid: { left: 48, right: 16, top: 16, bottom: 48 },
      xAxis: {
        type: "category",
        data: data.map((d) => d.date),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: "#9aabba", fontSize: 11 },
        boundaryGap: false,
      },
      yAxis: [
        {
          type: "value",
          name: "次数 / K",
          nameTextStyle: { color: "#9aabba", fontSize: 11 },
          splitLine: { lineStyle: { color: "rgba(232,229,224,0.6)", type: "dashed" } },
          axisLabel: { color: "#9aabba", fontSize: 11 },
        },
        {
          type: "value",
          name: "% / s",
          nameTextStyle: { color: "#9aabba", fontSize: 11 },
          splitLine: { show: false },
          axisLabel: { color: "#9aabba", fontSize: 11 },
        },
      ],
      series: hasData ? activeSeries : [],
      animationDuration: 800,
      animationEasing: "cubicOut" as const,
    };

    instance.setOption(option, true);
    instance.hideLoading();

    const handleResize = () => instance.resize();
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [data, series]);

  useEffect(() => {
    return () => {
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, []);

  const toggleSeries = (key: keyof typeof series) => {
    setSeries((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const seriesMeta = [
    { key: "calls" as const, label: "调用次数", color: "#5b7b9a" },
    { key: "tokens" as const, label: "Token 消耗", color: "#9a7aba" },
    { key: "success" as const, label: "成功率", color: "#6b9b6b" },
    { key: "latency" as const, label: "平均耗时", color: "#c49a6b" },
  ];

  return (
    <div className="rounded-2xl border border-[var(--color-border)]/80 bg-white/80 p-5 shadow-sm">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-display text-xl font-bold text-[var(--ink)]">AI 调用趋势</h3>
          <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">
            {loading ? "加载中..." : `最近 ${period === "7d" ? "7" : "30"} 天的 AI 服务运行状况`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-2 md:flex">
            {seriesMeta.map(({ key, label, color }) => (
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
                onClick={() => setPeriod(p)}
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
      <div ref={chartRef} className="h-72 w-full" />
    </div>
  );
}
