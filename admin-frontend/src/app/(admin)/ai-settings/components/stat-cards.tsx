"use client";

import { useEffect, useRef, useState } from "react";
import { Activity, CalendarCheck, CheckCircle, Clock, DollarSign, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AIStatsResponse } from "@/lib/api/types";

function useAnimatedValue(target: number, duration = 1200) {
  const [value, setValue] = useState(0);
  const startTime = useRef<number | null>(null);
  const rafId = useRef<number>(0);

  useEffect(() => {
    startTime.current = null;
    const animate = (now: number) => {
      if (startTime.current === null) startTime.current = now;
      const elapsed = now - startTime.current;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(target * eased));
      if (progress < 1) rafId.current = requestAnimationFrame(animate);
    };
    rafId.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafId.current);
  }, [target, duration]);

  return value;
}

const EMPTY_STATS: AIStatsResponse = {
  today_calls: 0,
  monthly_calls: 0,
  success_rate: 0,
  avg_latency_ms: 0,
  total_tokens: 0,
  estimated_cost: 0,
  daily_trends: [],
};

const CARD_META = [
  { key: "today" as const, label: "今日解析", suffix: "次", trend: "up" as const, change: "--", icon: Activity, gradient: "from-[#5b7b9a] to-[#355f83]", bgGlow: "rgba(91,123,154,0.08)", valueKey: "today_calls" as const, valueType: "int" as const },
  { key: "monthly" as const, label: "本月解析", suffix: "次", trend: "up" as const, change: "--", icon: CalendarCheck, gradient: "from-[#6b9b6b] to-[#4a7a4a]", bgGlow: "rgba(107,155,107,0.08)", valueKey: "monthly_calls" as const, valueType: "int" as const },
  { key: "success" as const, label: "AI 调用成功率", suffix: "%", trend: "up" as const, change: "--", icon: CheckCircle, gradient: "from-[#5baa6b] to-[#3d8a4d]", bgGlow: "rgba(91,170,107,0.08)", valueKey: "success_rate" as const, valueType: "float1" as const },
  { key: "latency" as const, label: "平均响应时间", suffix: "s", trend: "down" as const, change: "--", icon: Clock, gradient: "from-[#c49a6b] to-[#a67a4b]", bgGlow: "rgba(196,154,107,0.08)", valueKey: "avg_latency_ms" as const, valueType: "latency" as const },
  { key: "tokens" as const, label: "Token 消耗量", suffix: "K", trend: "up" as const, change: "--", icon: Zap, gradient: "from-[#9a7aba] to-[#7a5a9a]", bgGlow: "rgba(154,122,186,0.08)", valueKey: "total_tokens" as const, valueType: "tokens" as const },
  { key: "cost" as const, label: "预计费用", suffix: "¥", trend: "up" as const, change: "--", icon: DollarSign, gradient: "from-[#c47a7a] to-[#a45a5a]", bgGlow: "rgba(196,122,122,0.08)", valueKey: "estimated_cost" as const, valueType: "cost" as const },
];

function StatCard({
  label,
  suffix,
  icon: Icon,
  gradient,
  value,
  loading,
}: {
  label: string;
  suffix: string;
  icon: React.ElementType;
  gradient: string;
  value: number;
  loading: boolean;
}) {
  const displayValue = useAnimatedValue(loading ? 0 : value * 100) / 100;

  const formatted = (() => {
    if (loading) return "---";
    if (suffix === "s") return displayValue.toFixed(2);
    if (suffix === "%" || suffix === "¥") return displayValue.toFixed(1);
    if (displayValue >= 1000) return Math.round(displayValue).toLocaleString("zh-CN");
    if (Number.isInteger(displayValue)) return String(Math.round(displayValue));
    return displayValue.toFixed(1);
  })();

  return (
    <div className="group relative overflow-hidden rounded-2xl border border-[var(--color-border)]/80 bg-white/80 p-5 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg">
      <div
        className="absolute -right-8 -top-8 h-24 w-24 rounded-full opacity-0 blur-2xl transition-opacity duration-500 group-hover:opacity-100"
        style={{ background: `radial-gradient(circle, ${gradient.replace("from-", "").replace("to-", "")}, transparent)` }}
      />
      <div className="relative z-10">
        <div className="flex items-start justify-between">
          <p className="text-sm font-semibold text-[var(--color-text-secondary)]">{label}</p>
          <div className="grid h-10 w-10 place-items-center rounded-xl border border-[var(--color-border)]/60 bg-white/60 shadow-sm transition-transform duration-300 group-hover:scale-110 group-hover:-translate-y-0.5">
            <Icon className="h-5 w-5" style={{ color: gradient.match(/#[a-fA-F0-9]{6}/)?.[0] || "var(--color-primary)" }} />
          </div>
        </div>
        <div className="mt-3 flex items-baseline gap-1.5">
          <span className={cn(
            "font-display text-3xl font-bold tracking-tight tabular-nums",
            loading ? "text-[var(--color-border)]" : "text-[var(--ink)]",
          )}>
            {formatted}
          </span>
          {!loading && <span className="text-sm font-medium text-[var(--color-text-hint)]">{suffix}</span>}
          {loading && <span className="text-sm text-[var(--color-border)]">{suffix}</span>}
        </div>
      </div>
    </div>
  );
}

export function StatCards({ stats, loading }: { stats?: AIStatsResponse | null; loading?: boolean }) {
  const data = loading ? EMPTY_STATS : (stats ?? EMPTY_STATS);

  const getValue = (meta: typeof CARD_META[number]): number => {
    const raw = data[meta.valueKey as keyof AIStatsResponse] as number;
    if (meta.valueType === "latency") return raw / 1000; // ms → s
    if (meta.valueType === "tokens") return raw / 1000;  // raw → K
    if (meta.valueType === "cost") return raw;            // ¥
    return raw;
  };

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {CARD_META.map((meta) => (
        <StatCard
          key={meta.key}
          label={meta.label}
          suffix={meta.suffix}
          icon={meta.icon}
          gradient={meta.gradient}
          value={getValue(meta)}
          loading={loading ?? false}
        />
      ))}
    </div>
  );
}
