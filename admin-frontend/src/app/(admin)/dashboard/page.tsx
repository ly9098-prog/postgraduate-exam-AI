"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BrainCircuit,
  CalendarDays,
  CheckCircle2,
  CircleDot,
  Clock3,
  Cpu,
  Database,
  FileClock,
  FileStack,
  HardDrive,
  Layers3,
  Network,
  RefreshCw,
  Server,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  UserPlus,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { apiRequest, toQuery } from "@/lib/api/client";
import {
  numberValue,
  toPieData,
  normalizeSeries,
  computeReviewRate,
  computeQueuePending,
  computeQueueErrors,
  computeRedisStatus,
  computeTaskQueueStatus,
} from "@/lib/dashboard-utils";
import type {
  AIStatsResponse,
  DashboardDailyPoint,
  DashboardOverview,
  DashboardQuestionStats,
  ReadyHealthResponse,
  TaskDiagnosticsResponse,
} from "@/lib/api/types";
import { useAuthStore } from "@/lib/auth/auth-store";
import { chinaDateString } from "@/lib/time";
import { DashboardTrendChart } from "./components/dashboard-trend-chart";
import { ReviewStatusChart } from "./components/review-status-chart";

type Period = "7d" | "30d";
type Tone = "blue" | "green" | "orange" | "red" | "purple" | "slate";

type MetricCard = {
  label: string;
  value?: number | null;
  icon: LucideIcon;
  tone: Tone;
  hint: string;
  hintTone?: "positive" | "negative" | "neutral";
  sparkline?: number[];
};

const TONE_STYLES: Record<Tone, { icon: string; iconBg: string; line: string }> = {
  blue: { icon: "text-[var(--color-primary)]", iconBg: "bg-[var(--color-primary-light)]", line: "#4a6f8a" },
  green: { icon: "text-[#648764]", iconBg: "bg-[#edf4ed]", line: "#6d906d" },
  orange: { icon: "text-[#ad8259]", iconBg: "bg-[var(--color-warning-light)]", line: "#b58a62" },
  red: { icon: "text-[#b85c57]", iconBg: "bg-[var(--color-danger-light)]", line: "#b96862" },
  purple: { icon: "text-[#82758f]", iconBg: "bg-[#f1eef3]", line: "#8b7c97" },
  slate: { icon: "text-[#6f8391]", iconBg: "bg-[#eef2f4]", line: "#78909f" },
};

function MiniSparkline({ values, color }: { values?: number[]; color: string }) {
  if (!values || values.length < 2) return null;

  const clean = values.filter((value) => Number.isFinite(value));
  if (clean.length < 2) return null;

  const min = Math.min(...clean);
  const max = Math.max(...clean);
  if (max === min) {
    return (
      <span className="shrink-0 rounded-full border border-[var(--color-border-light)] bg-white/70 px-2 py-1 text-[9px] font-semibold text-[var(--color-text-hint)]">
        7日平稳
      </span>
    );
  }

  const width = 66;
  const height = 26;
  const range = max - min;
  const points = clean
    .map((value, index) => {
      const x = (index / (clean.length - 1)) * width;
      const y = height - 4 - ((value - min) / range) * (height - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = points.split(" ").at(-1)?.split(",") ?? [String(width), String(height / 2)];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-7 w-[66px] shrink-0 overflow-visible" aria-hidden="true" focusable="false">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeOpacity="0.14"
        strokeWidth="5.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength={1}
        strokeDasharray="1"
        strokeDashoffset="1"
      >
        <animate attributeName="stroke-dashoffset" from="1" to="0" dur="620ms" fill="freeze" />
      </polyline>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength={1}
        strokeDasharray="1"
        strokeDashoffset="1"
      >
        <animate attributeName="stroke-dashoffset" from="1" to="0" dur="620ms" fill="freeze" />
      </polyline>
      <circle cx={Number(last[0])} cy={Number(last[1])} r="4.4" fill={color} opacity="0.12" />
      <circle cx={Number(last[0])} cy={Number(last[1])} r="2.2" fill={color} stroke="white" strokeWidth="1.3" />
    </svg>
  );
}

function MetricCardView({ item, index }: { item: MetricCard; index: number }) {
  const Icon = item.icon;
  const style = TONE_STYLES[item.tone];
  const hintClass =
    item.hintTone === "positive"
      ? "text-emerald-600"
      : item.hintTone === "negative"
        ? "text-red-500"
        : "text-[var(--color-text-hint)]";

  return (
    <section
      className="dashboard-motion-safe group min-w-0 rounded-2xl border border-[var(--color-border-light)] bg-white/[0.84] px-4 py-3.5 shadow-[0_4px_16px_rgba(27,39,51,0.04)] backdrop-blur-sm transition-[border-color,box-shadow,background-color,transform] duration-300 hover:-translate-y-0.5 hover:border-[#d3dce1] hover:bg-white/[0.94] hover:shadow-[0_8px_22px_rgba(27,39,51,0.075)]"
      style={{ animation: `dashboard-card-in 520ms cubic-bezier(.2,.8,.2,1) ${index * 45}ms both` }}
    >
      <div className="flex min-w-0 items-center gap-3">
        <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/60 transition-transform duration-300 group-hover:scale-[1.04] ${style.iconBg}`}>
          <Icon className={`h-[18px] w-[18px] transition-transform duration-300 ${style.icon}`} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[11px] font-semibold text-[var(--color-text-secondary)]">{item.label}</p>
          <p className="mt-1 truncate font-display text-[26px] font-bold leading-none tracking-tight text-[var(--ink)] tabular-nums">
            {numberValue(item.value)}
          </p>
          <p className={`mt-1.5 truncate text-[10px] font-medium ${hintClass}`}>{item.hint}</p>
        </div>
        <MiniSparkline values={item.sparkline} color={style.line} />
      </div>
    </section>
  );
}

function StatusPill({ tone, children }: { tone: "ok" | "warning" | "error" | "muted"; children: ReactNode }) {
  const classes = {
    ok: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warning: "border-amber-200 bg-amber-50 text-amber-700",
    error: "border-red-200 bg-red-50 text-red-700",
    muted: "border-slate-200 bg-slate-50 text-slate-500",
  }[tone];

  return <span className={`rounded-md border px-2 py-1 text-[10px] font-semibold ${classes}`}>{children}</span>;
}

function DetailMetric({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="min-w-0 text-center">
      <p className="truncate text-[10px] text-[var(--color-text-hint)]">{label}</p>
      <p className={`mt-1 truncate text-base font-bold tabular-nums ${accent ?? "text-[var(--ink)]"}`}>{value}</p>
    </div>
  );
}

export default function DashboardPage() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isBootstrapping = useAuthStore((state) => state.isBootstrapping);
  const canRequestDashboard = isAuthenticated && !isBootstrapping;
  const [period, setPeriod] = useState<Period>("7d");
  const [manualRefreshing, setManualRefreshing] = useState(false);

  const dailyQuery = useMemo(() => ({
    from: chinaDateString(-(period === "7d" ? 6 : 29)),
    to: chinaDateString(),
  }), [period]);

  const overview = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: () => apiRequest<DashboardOverview>("/dashboard/overview"),
    enabled: canRequestDashboard,
    staleTime: 30_000,
  });
  const daily = useQuery({
    queryKey: ["dashboard", "daily", dailyQuery],
    queryFn: () => apiRequest<DashboardDailyPoint[]>(`/dashboard/daily${toQuery(dailyQuery)}`),
    enabled: canRequestDashboard,
    staleTime: 30_000,
  });
  const stats = useQuery({
    queryKey: ["dashboard", "questions-stats"],
    queryFn: () => apiRequest<DashboardQuestionStats>("/dashboard/questions-stats"),
    enabled: canRequestDashboard,
    staleTime: 60_000,
  });
  const readyHealth = useQuery({
    queryKey: ["dashboard", "ready-health"],
    queryFn: () => apiRequest<ReadyHealthResponse>("/health/ready"),
    enabled: canRequestDashboard,
    staleTime: 30_000,
    retry: 1,
  });
  const aiStats = useQuery({
    queryKey: ["dashboard", "ai-stats"],
    queryFn: () => apiRequest<AIStatsResponse>("/dashboard/ai-stats?days=7"),
    enabled: canRequestDashboard,
    staleTime: 60_000,
    retry: false,
  });
  const taskDiagnostics = useQuery({
    queryKey: ["dashboard", "task-diagnostics"],
    queryFn: () => apiRequest<TaskDiagnosticsResponse>("/tasks/diagnostics"),
    enabled: canRequestDashboard,
    staleTime: 30_000,
    retry: false,
  });

  const dailyPoints = daily.data ?? [];
  const todayPoint = dailyPoints.at(-1);
  const pieData = toPieData(stats.data?.by_review_status);
  const usersSpark = normalizeSeries(dailyPoints.map((item) => item.users_new));
  const questionsSpark = normalizeSeries(dailyPoints.map((item) => item.questions_new));
  const importsSpark = normalizeSeries(dailyPoints.map((item) => item.imports_new));
  const auditsSpark = normalizeSeries(dailyPoints.map((item) => item.audits_total));
  const aiSpark = normalizeSeries(aiStats.data?.daily_trends.map((item) => item.calls) ?? []);

  const metrics: MetricCard[] = [
    {
      label: "小程序用户",
      value: overview.data?.users_total,
      icon: Users,
      tone: "blue",
      hint: `今日 +${numberValue(overview.data?.users_new_today)}`,
      hintTone: (overview.data?.users_new_today ?? 0) > 0 ? "positive" : "neutral",
      sparkline: usersSpark,
    },
    {
      label: "今日新增用户",
      value: overview.data?.users_new_today,
      icon: UserPlus,
      tone: "blue",
      hint: "今日实时新增",
      sparkline: usersSpark,
    },
    {
      label: "题目总量",
      value: overview.data?.questions_total,
      icon: Database,
      tone: "blue",
      hint: `今日 +${numberValue(todayPoint?.questions_new)}`,
      hintTone: (todayPoint?.questions_new ?? 0) > 0 ? "positive" : "neutral",
      sparkline: questionsSpark,
    },
    {
      label: "待审核题目",
      value: overview.data?.questions_pending_review,
      icon: ShieldCheck,
      tone: "orange",
      hint: "当前审核队列",
      hintTone: (overview.data?.questions_pending_review ?? 0) > 0 ? "negative" : "neutral",
    },
    {
      label: "导入批次",
      value: overview.data?.imports_total,
      icon: UploadCloud,
      tone: "blue",
      hint: `今日 +${numberValue(todayPoint?.imports_new)}`,
      hintTone: (todayPoint?.imports_new ?? 0) > 0 ? "positive" : "neutral",
      sparkline: importsSpark,
    },
    {
      label: "待处理导入",
      value: overview.data?.imports_pending,
      icon: FileClock,
      tone: "purple",
      hint: "当前待处理任务",
      hintTone: (overview.data?.imports_pending ?? 0) > 0 ? "negative" : "neutral",
    },
    {
      label: "今日关键审计",
      value: overview.data?.audit_critical_today,
      icon: ShieldAlert,
      tone: "red",
      hint: "高优先级事件",
      hintTone: (overview.data?.audit_critical_today ?? 0) > 0 ? "negative" : "neutral",
      sparkline: auditsSpark,
    },
    {
      label: "今日 AI 调用",
      value: aiStats.data?.today_calls,
      icon: BrainCircuit,
      tone: "purple",
      hint: aiStats.data ? `成功率 ${aiStats.data.success_rate.toFixed(1)}%` : "AI 运行指标暂不可用",
      hintTone: aiStats.data && aiStats.data.success_rate >= 95 ? "positive" : "neutral",
      sparkline: aiSpark,
    },
  ];

  const reviewTotal = pieData.reduce((sum, item) => sum + item.count, 0);
  const reviewedRate = computeReviewRate(pieData);
  const subjects = [...(stats.data?.by_subject ?? [])].filter((item) => item.count > 0);
  const difficultyCount = (stats.data?.by_difficulty ?? []).filter((item) => item.count > 0).length;
  const topSubject = subjects.sort((a, b) => b.count - a.count)[0];

  const queueTotals = taskDiagnostics.data?.redis.totals;
  const queuePending = computeQueuePending(queueTotals);
  const queueErrors = computeQueueErrors(queueTotals);

  const dateLabel = chinaDateString();

  const redisConfigured = taskDiagnostics.data?.redis.configured === true;
  const redisAvailable = redisConfigured && taskDiagnostics.data?.redis.available === true;
  const redisStatus = computeRedisStatus(taskDiagnostics.isLoading, taskDiagnostics.data?.redis);
  const taskQueueStatus = computeTaskQueueStatus(
    taskDiagnostics.isLoading,
    taskDiagnostics.data?.redis,
    queuePending,
    queueErrors,
  );

  const refreshAll = async () => {
    setManualRefreshing(true);
    try {
      await Promise.allSettled([
        overview.refetch(),
        daily.refetch(),
        stats.refetch(),
        readyHealth.refetch(),
        aiStats.refetch(),
        taskDiagnostics.refetch(),
      ]);
    } finally {
      setManualRefreshing(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-[1680px] space-y-4 pb-2">
      <style jsx global>{`
        @keyframes dashboard-card-in {
          from { opacity: 0; translate: 0 10px; scale: .985; }
          to { opacity: 1; translate: 0 0; scale: 1; }
        }
        @media (prefers-reduced-motion: reduce) {
          .dashboard-motion-safe { animation: none !important; transition: none !important; }
        }
      `}</style>
      {manualRefreshing ? (
        <div
          className="fixed right-6 top-5 z-[100] flex items-center gap-3 rounded-xl border border-[var(--color-border-light)] bg-white/95 px-4 py-3 shadow-[0_12px_34px_rgba(27,39,51,0.12)] backdrop-blur-md"
          role="status"
          aria-live="polite"
          aria-label="正在刷新仪表盘数据"
        >
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--color-primary-light)] text-[var(--color-primary)]">
            <RefreshCw className="h-4 w-4 animate-spin" />
          </span>
          <div>
            <p className="text-xs font-bold text-[var(--ink)]">正在刷新运营数据</p>
            <p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">页面可继续使用，数据完成后自动更新</p>
          </div>
        </div>
      ) : null}
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-[var(--color-text-hint)]">Dashboard</p>
          <h2 className="mt-1 font-display text-3xl font-bold tracking-tight text-[var(--ink)]">运营蓝图总览</h2>
          <p className="mt-1 text-xs text-[var(--color-text-hint)]">聚合用户、题库、审核、AI 与系统状态的实时运营视图</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => {
              void refreshAll();
            }}
            disabled={manualRefreshing}
            className="inline-flex h-10 items-center gap-2 rounded-xl border border-[var(--color-border-light)] bg-white/[0.9] px-3.5 text-xs font-semibold text-[var(--color-text-secondary)] shadow-[0_3px_10px_rgba(27,39,51,0.04)] transition hover:border-[#cfd9df] hover:bg-white hover:text-[var(--ink)] disabled:cursor-wait disabled:opacity-75"
          >
            <RefreshCw className={`h-4 w-4 ${manualRefreshing ? "animate-spin" : ""}`} />
            <span>{manualRefreshing ? "刷新中" : "刷新数据"}</span>
          </button>
          <div className="inline-flex h-10 min-w-[132px] items-center gap-2 rounded-xl border border-[var(--color-border-light)] bg-white/[0.9] px-3.5 text-xs font-semibold text-[var(--color-text-secondary)] shadow-[0_3px_10px_rgba(27,39,51,0.04)]">
            <CalendarDays className="h-4 w-4 text-[var(--color-primary)]" />
            <span>{dateLabel}</span>
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((item, index) => (
          <MetricCardView key={item.label} item={item} index={index} />
        ))}
      </div>

      <div className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.58fr)_minmax(360px,0.92fr)]">
        <DashboardTrendChart data={daily.data} loading={daily.isLoading} period={period} onPeriodChange={setPeriod} />

        <div className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-1">
          <section className="min-w-0 overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-white/[0.84] shadow-[0_5px_20px_rgba(27,39,51,0.045)] backdrop-blur-sm">
            <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-5 py-3.5">
              <div>
                <h3 className="font-display text-lg font-bold text-[var(--ink)]">审核状态分布</h3>
                <p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">按当前题目审核状态统计</p>
              </div>
              <span className="rounded-lg bg-[var(--color-primary-light)] px-2 py-1 text-[10px] font-semibold tabular-nums text-[var(--color-primary-dark)]">{numberValue(reviewTotal)} 题</span>
            </div>
            <div className="h-[252px]">
              <ReviewStatusChart data={pieData} animationKey={stats.dataUpdatedAt} />
            </div>
          </section>

          <section className="min-w-0 rounded-2xl border border-[var(--color-border-light)] bg-white/[0.84] px-5 py-4 shadow-[0_5px_20px_rgba(27,39,51,0.045)] backdrop-blur-sm">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <div><h3 className="font-display text-lg font-bold text-[var(--ink)]">系统运行概览</h3><p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">核心依赖与异步服务健康状态</p></div>
              </div>
              <a href="/system/tasks" className="text-[11px] font-semibold text-[var(--color-primary)] hover:underline">查看详情 ›</a>
            </div>

            <div className="grid overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-white/45 sm:grid-cols-2 sm:divide-x sm:divide-[var(--color-border-light)]">
              <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-3 py-2.5 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><Server className="h-4 w-4 shrink-0 text-[var(--color-primary)]" />Dashboard API</span>
                <StatusPill tone={overview.isError ? "error" : overview.isLoading ? "muted" : "ok"}>{overview.isError ? "异常" : overview.isLoading ? "检测中" : "正常"}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-3 py-2.5 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><Database className="h-4 w-4 shrink-0 text-[var(--color-primary)]" />数据库</span>
                <StatusPill tone={readyHealth.data?.db === "ok" ? "ok" : readyHealth.isLoading ? "muted" : "error"}>{readyHealth.isLoading ? "检测中" : readyHealth.data?.db === "ok" ? "正常" : "异常"}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-3 py-2.5 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><HardDrive className={`h-4 w-4 shrink-0 ${redisConfigured ? "text-[var(--color-primary)]" : "text-slate-400"}`} />Redis</span>
                <StatusPill tone={redisStatus.tone}>{redisStatus.label}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-3 py-2.5 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><Network className={`h-4 w-4 shrink-0 ${redisConfigured ? "text-[var(--color-primary)]" : "text-slate-400"}`} />Task Queue</span>
                <StatusPill tone={taskQueueStatus.tone}>{taskQueueStatus.label}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-3 py-2.5 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><BrainCircuit className="h-4 w-4 shrink-0 text-[#82758f]" />AI Metrics API</span>
                <StatusPill tone={aiStats.data ? "ok" : aiStats.isLoading ? "muted" : "warning"}>{aiStats.data ? "正常" : aiStats.isLoading ? "检测中" : "异常"}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-3 py-2.5 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><CheckCircle2 className="h-4 w-4 shrink-0 text-[#648764]" />系统就绪</span>
                <StatusPill tone={readyHealth.data?.status === "ok" ? "ok" : readyHealth.isLoading ? "muted" : "warning"}>{readyHealth.isLoading ? "检测中" : readyHealth.data?.status === "ok" ? "Ready" : "Degraded"}</StatusPill>
              </div>
            </div>
          </section>
        </div>
      </div>

      <section className="rounded-2xl border border-[var(--color-border-light)] bg-white/[0.8] p-4 shadow-[0_5px_20px_rgba(27,39,51,0.045)] backdrop-blur-sm">
        <div className="mb-3 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-[var(--color-primary)]" />
          <h3 className="font-display text-lg font-bold text-[var(--ink)]">运营重点</h3>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <article className="rounded-xl border border-[var(--color-border-light)] bg-white/62 p-4 transition-colors hover:bg-white/82">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[var(--color-primary-light)] text-[var(--color-primary)]"><FileStack className="h-4 w-4" /></span>
              <h4 className="text-sm font-bold text-[var(--ink)]">待办事项</h4>
            </div>
            <div className="space-y-2.5 text-xs text-[var(--color-text-secondary)]">
              <p className="flex items-center justify-between gap-3"><span className="flex items-center gap-2"><CircleDot className="h-3 w-3 text-[var(--color-primary)]" />待审核题目</span><strong className="tabular-nums text-[var(--ink)]">{numberValue(overview.data?.questions_pending_review)}</strong></p>
              <p className="flex items-center justify-between gap-3"><span className="flex items-center gap-2"><CircleDot className="h-3 w-3 text-amber-500" />待处理导入</span><strong className="tabular-nums text-[var(--ink)]">{numberValue(overview.data?.imports_pending)}</strong></p>
              <p className="flex items-center justify-between gap-3"><span className="flex items-center gap-2"><CircleDot className="h-3 w-3 text-red-500" />关键审计</span><strong className="tabular-nums text-[var(--ink)]">{numberValue(overview.data?.audit_critical_today)}</strong></p>
            </div>
          </article>

          <article className="rounded-xl border border-[var(--color-border-light)] bg-white/62 p-4 transition-colors hover:bg-white/82">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[#edf4ed] text-[#648764]"><Layers3 className="h-4 w-4" /></span>
              <div className="min-w-0"><h4 className="text-sm font-bold text-[var(--ink)]">题库结构</h4>{topSubject && <p className="mt-0.5 truncate text-[10px] text-[var(--color-text-hint)]">题量最多：{topSubject.name}</p>}</div>
            </div>
            <div className="grid grid-cols-3 divide-x divide-[var(--color-border-light)]">
              <DetailMetric label="科目数" value={stats.isLoading ? "--" : String(subjects.length)} />
              <DetailMetric label="难度层级" value={stats.isLoading ? "--" : String(difficultyCount)} />
              <DetailMetric label="已通过占比" value={reviewedRate} accent="text-[#648764]" />
            </div>
          </article>

          <article className="rounded-xl border border-[var(--color-border-light)] bg-white/62 p-4 transition-colors hover:bg-white/82">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[#f1eef3] text-[#82758f]"><Cpu className="h-4 w-4" /></span>
              <h4 className="text-sm font-bold text-[var(--ink)]">AI 运行</h4>
            </div>
            {aiStats.data ? (
              <div className="grid grid-cols-3 divide-x divide-[var(--color-border-light)]">
                <DetailMetric label="成功率" value={`${aiStats.data.success_rate.toFixed(1)}%`} accent="text-[#648764]" />
                <DetailMetric label="平均响应" value={`${(aiStats.data.avg_latency_ms / 1000).toFixed(1)}s`} />
                <DetailMetric label="7日 Token" value={aiStats.data.total_tokens >= 1000 ? `${(aiStats.data.total_tokens / 1000).toFixed(1)}k` : String(aiStats.data.total_tokens)} />
              </div>
            ) : (
              <p className="rounded-lg bg-[var(--color-bg-input)]/55 px-3 py-3 text-xs text-[var(--color-text-hint)]">AI 运行指标暂不可用，请稍后刷新</p>
            )}
          </article>

          <article className="rounded-xl border border-[var(--color-border-light)] bg-white/62 p-4 transition-colors hover:bg-white/82">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[#eef3f5] text-[#67889a]"><Clock3 className="h-4 w-4" /></span>
              <h4 className="text-sm font-bold text-[var(--ink)]">异步任务</h4>
            </div>
            {taskDiagnostics.data && redisConfigured ? (
              <div className="grid grid-cols-3 divide-x divide-[var(--color-border-light)]">
                <DetailMetric label="等待" value={String(queueTotals?.ready ?? 0)} />
                <DetailMetric label="处理中" value={String(queueTotals?.processing ?? 0)} accent="text-[var(--color-primary)]" />
                <DetailMetric label="异常" value={String(queueErrors)} accent={queueErrors > 0 ? "text-[var(--color-danger)]" : "text-[#648764]"} />
              </div>
            ) : taskDiagnostics.data && !redisConfigured ? (
              <p className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-3 text-xs text-slate-500"><HardDrive className="h-3.5 w-3.5" />Redis 未配置，当前不展示队列计数</p>
            ) : (
              <p className="flex items-center gap-2 rounded-lg bg-[var(--color-bg-input)]/55 px-3 py-3 text-xs text-[var(--color-text-hint)]"><AlertTriangle className="h-3.5 w-3.5" />需要导入管理读取权限后展示队列指标</p>
            )}
          </article>
        </div>
      </section>
    </div>
  );
}
