"use client";

import { useMemo, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";

const COLORS = ["#5b7b9a", "#6b9b6b", "#c49a6b", "#c47a7a", "#9aabba"];

const STATUS_LABELS: Record<string, string> = {
  pending: "待审核",
  approved: "已审核",
  rejected: "已驳回",
  reviewing: "审核中",
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
  error: "异常",
};

const VISUAL_LAYERS = [
  { outerRadius: 108, innerRadius: 86, bgOpacity: 0.15, shadow: false },
  { outerRadius: 84, innerRadius: 62, bgOpacity: 0.45, shadow: false },
  { outerRadius: 60, innerRadius: 38, bgOpacity: 1, shadow: true },
];

export function ReviewStatusChart({
  data,
}: {
  data: Array<{ name: string; count: number }>;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [clicked, setClicked] = useState<string | null>(null);

  const total = useMemo(() => data.reduce((s, d) => s + d.count, 0), [data]);

  const enriched = useMemo(
    () =>
      data.map((d, i) => ({
        ...d,
        name: STATUS_LABELS[d.name] ?? d.name,
        color: COLORS[i % COLORS.length],
        pct: total > 0 ? ((d.count / total) * 100).toFixed(1) : "0",
      })),
    [data, total],
  );

  const handleMouseEnter = (name: string) => setHovered(name);
  const handleMouseLeave = () => setHovered(null);
  const handleClick = (name: string) => {
    setClicked(name);
    setTimeout(() => setClicked(null), 400);
  };

  return (
    <div className="flex h-full flex-col gap-1">
      <svg className="absolute w-0 h-0">
        <defs>
          <filter id="layerShadow">
            <feDropShadow dx="0" dy="1" stdDeviation="3" floodColor="#000" floodOpacity="0.12" />
          </filter>
          <filter id="layerShadowStrong">
            <feDropShadow dx="0" dy="2" stdDeviation="4" floodColor="#000" floodOpacity="0.18" />
          </filter>
          <filter id="clickPulse">
            <feDropShadow dx="0" dy="0" stdDeviation="6" floodColor="#fff" floodOpacity="0.6" />
          </filter>
        </defs>
      </svg>
      <style>{`.recharts-pie path { outline: none !important; }`}</style>

      <div className="relative flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            {/* Visual layers — no pointer events so they don't block the overlay */}
            {VISUAL_LAYERS.map((layer, li) => (
              <Pie
                key={`v${li}`}
                data={enriched}
                dataKey="count"
                nameKey="name"
                outerRadius={layer.outerRadius}
                innerRadius={layer.innerRadius}
                strokeWidth={0}
                startAngle={90}
                endAngle={-270}
                animationBegin={li * 250}
                animationDuration={900}
                animationEasing="ease-out"
                pointerEvents="none"
              >
                {enriched.map((entry) => {
                  const isActive = hovered === null || hovered === entry.name;
                  const dim = hovered !== null && !isActive;
                  const opacity = dim ? 0.06 : layer.bgOpacity;

                  return (
                    <Cell
                      key={entry.name}
                      fill={entry.color}
                      fillOpacity={opacity}
                      stroke="none"
                      style={{
                        outline: "none",
                        filter:
                          dim || !layer.shadow
                            ? "none"
                            : `url(#layerShadow${li === 2 ? "Strong" : ""})`,
                        transition: "fill-opacity 0.25s ease",
                      }}
                    />
                  );
                })}
              </Pie>
            ))}

            {/* Interactive overlay — transparent, covers full radius, handles all events */}
            <Pie
              data={enriched}
              dataKey="count"
              nameKey="name"
              outerRadius={108}
              innerRadius={38}
              strokeWidth={0}
              startAngle={90}
              endAngle={-270}
              animationDuration={0}
            >
              {enriched.map((entry) => {
                const isHovered = hovered === entry.name;
                const isClicked = clicked === entry.name;

                return (
                  <Cell
                    key={entry.name}
                    fill={isHovered ? entry.color : "transparent"}
                    fillOpacity={isHovered ? 0.2 : 0}
                    stroke={isClicked ? entry.color : isHovered ? entry.color : "none"}
                    strokeWidth={isClicked ? 3 : isHovered ? 2 : 0}
                    strokeOpacity={isClicked ? 0.7 : isHovered ? 0.4 : 0}
                    style={{
                      outline: "none",
                      cursor: "pointer",
                      transition: "all 0.2s ease",
                      filter: isClicked
                        ? "url(#clickPulse)"
                        : isHovered
                          ? `drop-shadow(0 0 8px ${entry.color}66)`
                          : "none",
                    }}
                    onMouseEnter={() => handleMouseEnter(entry.name)}
                    onMouseLeave={handleMouseLeave}
                    onClick={() => handleClick(entry.name)}
                  />
                );
              })}
            </Pie>
          </PieChart>
        </ResponsiveContainer>

        {/* Center total */}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div
            className="flex flex-col items-center justify-center rounded-full"
            style={{
              width: 76,
              height: 76,
              background:
                "radial-gradient(circle at 50% 38%, #f5f6f8, #e8ebef 70%, #dce0e6)",
              boxShadow:
                "inset 0 2px 4px rgba(0,0,0,0.10), 0 1px 2px rgba(255,255,255,0.5)",
            }}
          >
            <p className="font-display text-xl font-bold text-[var(--ink)] leading-none">
              {total.toLocaleString("zh-CN")}
            </p>
            <p className="mt-1 text-[10px] text-[var(--color-text-hint)] leading-none">
              总题数
            </p>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap justify-center gap-x-5 gap-y-1.5 px-2 pb-4">
        {enriched.map((entry) => {
          const isActive = hovered === null || hovered === entry.name;
          const dim = hovered !== null && !isActive;
          return (
            <button
              key={entry.name}
              onMouseEnter={() => setHovered(entry.name)}
              onMouseLeave={() => setHovered(null)}
              className={cn(
                "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs transition-all duration-200",
                dim ? "opacity-30" : "hover:bg-[var(--color-bg-input)]",
              )}
            >
              <span
                className="inline-block h-3 w-3 rounded-full ring-1 ring-inset ring-black/10"
                style={{ backgroundColor: entry.color }}
              />
              <span className="font-medium text-[var(--ink)]">{entry.name}</span>
              <span className="text-[var(--color-text-secondary)]">
                {entry.count.toLocaleString("zh-CN")}
              </span>
              <span className="text-[var(--color-text-hint)]">{entry.pct}%</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
