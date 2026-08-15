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
import type {
  AIStatsResponse,
  DashboardDailyPoint,
  DashboardOverview,
  DashboardQuestionStats,
  ReadyHealthResponse,
  TaskDiagnosticsResponse,
} from "@/lib/api/types";
import { useAuthStore } from "@/lib/auth/auth-store";
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
  blue: { icon: "text-[#2f74df]", iconBg: "bg-[#edf4ff]", line: "#2f74df" },
  green: { icon: "text-[#14936f]", iconBg: "bg-[#eaf8f3]", line: "#14936f" },
  orange: { icon: "text-[#df7a22]", iconBg: "bg-[#fff4e9]", line: "#df7a22" },
  red: { icon: "text-[#d95454]", iconBg: "bg-[#fff0f0]", line: "#d95454" },
  purple: { icon: "text-[#7c61d6]", iconBg: "bg-[#f2efff]", line: "#7c61d6" },
  slate: { icon: "text-[#53708d]", iconBg: "bg-[#edf3f7]", line: "#53708d" },
};

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN") : "--";
}

function toPieData(input?: DashboardQuestionStats["by_review_status"]): Array<{ name: string; count: number }> {
  if (!input) return [];
  if (Array.isArray(input)) return input;
  return Object.entries(input).map(([name, count]) => ({ name, count: Number(count) }));
}

function normalizeSeries(values: Array<number | undefined | null>) {
  return values.map((value) => (typeof value === "number" && Number.isFinite(value) ? value : 0));
}

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
      className="dashboard-motion-safe group min-w-0 rounded-2xl border border-[var(--color-border-light)] bg-white/[0.86] px-4 py-3.5 shadow-[0_5px_18px_rgba(37,61,89,0.045)] backdrop-blur-sm transition-all duration-300 hover:-translate-y-1 hover:border-[#c4d8ed] hover:bg-white/[0.94] hover:shadow-[0_12px_30px_rgba(37,82,132,0.10)]"
      style={{ animation: `dashboard-card-in 520ms cubic-bezier(.2,.8,.2,1) ${index * 45}ms both` }}
    >
      <div className="flex min-w-0 items-center gap-3">
        <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-full transition-transform duration-300 group-hover:scale-110 ${style.iconBg}`}>
          <Icon className={`h-[18px] w-[18px] transition-transform duration-300 group-hover:-rotate-3 ${style.icon}`} />
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

  const dailyQuery = useMemo(() => {
    const to = new Date();
    const from = new Date(to);
    from.setDate(from.getDate() - (period === "7d" ? 6 : 29));
    return {
      from: from.toISOString().slice(0, 10),
      to: to.toISOString().slice(0, 10),
    };
  }, [period]);

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
    queryFn: () => apiRequest<AIStatsResponse>("/ai-settings/stats?days=7"),
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
      hint: aiStats.data ? `成功率 ${aiStats.data.success_rate.toFixed(1)}%` : "需 AI 设置读取权限",
      hintTone: aiStats.data && aiStats.data.success_rate >= 95 ? "positive" : "neutral",
      sparkline: aiSpark,
    },
  ];

  const reviewTotal = pieData.reduce((sum, item) => sum + item.count, 0);
  const reviewedCount = pieData
    .filter((item) => ["approved", "published"].includes(item.name))
    .reduce((sum, item) => sum + item.count, 0);
  const reviewedRate = reviewTotal > 0 ? `${((reviewedCount / reviewTotal) * 100).toFixed(1)}%` : "--";
  const subjects = [...(stats.data?.by_subject ?? [])].filter((item) => item.count > 0);
  const difficultyCount = (stats.data?.by_difficulty ?? []).filter((item) => item.count > 0).length;
  const topSubject = subjects.sort((a, b) => b.count - a.count)[0];

  const queueTotals = taskDiagnostics.data?.redis.totals;
  const queuePending = (queueTotals?.ready ?? 0) + (queueTotals?.processing ?? 0) + (queueTotals?.retry ?? 0);
  const queueErrors = (queueTotals?.dead ?? 0) + (queueTotals?.corrupt ?? 0);

  const dateLabel = new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date())
    .replaceAll("/", "-");

  const redisConfigured = taskDiagnostics.data?.redis.configured === true;
  const redisAvailable = redisConfigured && taskDiagnostics.data?.redis.available === true;
  const redisStatus = taskDiagnostics.isLoading
    ? { tone: "muted" as const, label: "检测中" }
    : taskDiagnostics.data
      ? !redisConfigured
        ? { tone: "muted" as const, label: "未配置" }
        : redisAvailable
          ? { tone: "ok" as const, label: "正常" }
          : { tone: "error" as const, label: "不可用" }
      : { tone: "muted" as const, label: "未获取" };
  const taskQueueStatus = taskDiagnostics.isLoading
    ? { tone: "muted" as const, label: "检测中" }
    : taskDiagnostics.data
      ? !redisConfigured
        ? { tone: "muted" as const, label: "未启用" }
        : queueErrors > 0
          ? { tone: "error" as const, label: `异常 ${queueErrors}` }
          : queuePending > 0
            ? { tone: "warning" as const, label: `积压 ${queuePending}` }
            : { tone: "ok" as const, label: "正常" }
      : { tone: "muted" as const, label: "未获取" };

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
        @keyframes dashboard-loading {
          0% { transform: translateX(-110%); }
          50% { transform: translateX(55%); }
          100% { transform: translateX(220%); }
        }
        @media (prefers-reduced-motion: reduce) {
          .dashboard-motion-safe { animation: none !important; transition: none !important; }
        }
      `}</style>
      {manualRefreshing ? (
        <div
          className="fixed inset-0 z-[100] grid place-items-center bg-[#eef3f7]/72 backdrop-blur-[3px]"
          role="status"
          aria-live="polite"
          aria-label="正在刷新仪表盘数据"
        >
          <div className="flex min-w-[210px] flex-col items-center rounded-3xl border border-white/80 bg-white/92 px-8 py-7 shadow-[0_22px_60px_rgba(35,62,94,0.18)]">
            <div className="relative grid h-14 w-14 place-items-center rounded-2xl bg-[#edf4ff] text-[#2f74df]">
              <span className="absolute inset-0 rounded-2xl border border-[#2f74df]/20 animate-ping" />
              <RefreshCw className="h-6 w-6 animate-spin" />
            </div>
            <p className="mt-4 text-sm font-bold text-[var(--ink)]">正在刷新运营数据</p>
            <p className="mt-1 text-xs text-[var(--color-text-hint)]">正在同步 Dashboard 最新状态…</p>
            <div className="mt-4 h-1.5 w-32 overflow-hidden rounded-full bg-[#e9f0f7]">
              <div className="h-full w-1/2 animate-[dashboard-loading_1s_ease-in-out_infinite] rounded-full bg-[#2f74df]" />
            </div>
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
            className="inline-flex h-11 items-center gap-2 rounded-2xl border border-[var(--color-border-light)] bg-white/[0.92] px-4 text-sm font-semibold text-[var(--color-text-secondary)] shadow-[0_4px_14px_rgba(37,61,89,0.06)] transition hover:-translate-y-0.5 hover:border-[#c7d7e7] hover:text-[var(--ink)] disabled:cursor-wait disabled:opacity-75"
          >
            <RefreshCw className="h-4 w-4" />
            <span>刷新数据</span>
          </button>
          <div className="inline-flex h-11 min-w-[138px] items-center gap-2 rounded-2xl border border-[var(--color-border-light)] bg-white/[0.92] px-4 text-sm font-semibold text-[var(--color-text-secondary)] shadow-[0_4px_14px_rgba(37,61,89,0.06)]">
            <CalendarDays className="h-4 w-4 text-[#2f74df]" />
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
          <section className="min-w-0 overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-white/[0.82] shadow-[0_6px_24px_rgba(37,61,89,0.055)] backdrop-blur-sm">
            <div className="flex items-center gap-2 border-b border-[var(--color-border-light)] px-5 py-4">
              <h3 className="font-display text-xl font-bold text-[var(--ink)]">审核状态分布</h3>
              <span className="grid h-4 w-4 place-items-center rounded-full border border-[var(--color-border)] text-[9px] font-semibold text-[var(--color-text-hint)]">i</span>
            </div>
            <div className="h-[252px]">
              <ReviewStatusChart data={pieData} animationKey={stats.dataUpdatedAt} />
            </div>
          </section>

          <section className="min-w-0 rounded-2xl border border-[var(--color-border-light)] bg-white/[0.82] px-5 py-4 shadow-[0_6px_24px_rgba(37,61,89,0.055)] backdrop-blur-sm">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <h3 className="font-display text-xl font-bold text-[var(--ink)]">系统运行概览</h3>
                <span className="grid h-4 w-4 place-items-center rounded-full border border-[var(--color-border)] text-[9px] font-semibold text-[var(--color-text-hint)]">i</span>
              </div>
              <a href="/system/tasks" className="text-[11px] font-semibold text-[#2f74df] hover:underline">查看详情 ›</a>
            </div>

            <div className="grid gap-x-5 gap-y-2 sm:grid-cols-2">
              <div className="flex items-center justify-between gap-3 rounded-lg py-1.5">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><Server className="h-4 w-4 shrink-0 text-[#2f74df]" />Dashboard API</span>
                <StatusPill tone={overview.isError ? "error" : overview.isLoading ? "muted" : "ok"}>{overview.isError ? "异常" : overview.isLoading ? "检测中" : "正常"}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg py-1.5">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><Database className="h-4 w-4 shrink-0 text-[#2f74df]" />数据库</span>
                <StatusPill tone={readyHealth.data?.db === "ok" ? "ok" : readyHealth.isLoading ? "muted" : "error"}>{readyHealth.isLoading ? "检测中" : readyHealth.data?.db === "ok" ? "正常" : "异常"}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg py-1.5">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><HardDrive className={`h-4 w-4 shrink-0 ${redisConfigured ? "text-[#2f74df]" : "text-slate-400"}`} />Redis</span>
                <StatusPill tone={redisStatus.tone}>{redisStatus.label}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg py-1.5">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><Network className={`h-4 w-4 shrink-0 ${redisConfigured ? "text-[#2f74df]" : "text-slate-400"}`} />Task Queue</span>
                <StatusPill tone={taskQueueStatus.tone}>{taskQueueStatus.label}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg py-1.5">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><BrainCircuit className="h-4 w-4 shrink-0 text-[#7c61d6]" />AI Settings API</span>
                <StatusPill tone={aiStats.data ? "ok" : aiStats.isLoading ? "muted" : "warning"}>{aiStats.data ? "正常" : aiStats.isLoading ? "检测中" : "未授权"}</StatusPill>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg py-1.5">
                <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]"><CheckCircle2 className="h-4 w-4 shrink-0 text-[#14936f]" />系统就绪</span>
                <StatusPill tone={readyHealth.data?.status === "ok" ? "ok" : readyHealth.isLoading ? "muted" : "warning"}>{readyHealth.isLoading ? "检测中" : readyHealth.data?.status === "ok" ? "Ready" : "Degraded"}</StatusPill>
              </div>
            </div>
          </section>
        </div>
      </div>

      <section className="rounded-2xl border border-[var(--color-border-light)] bg-white/[0.78] p-4 shadow-[0_6px_24px_rgba(37,61,89,0.05)] backdrop-blur-sm">
        <div className="mb-3 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-[#2f74df]" />
          <h3 className="font-display text-lg font-bold text-[var(--ink)]">运营重点</h3>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <article className="rounded-xl border border-[var(--color-border-light)] bg-white/70 p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[#edf4ff] text-[#2f74df]"><FileStack className="h-4 w-4" /></span>
              <h4 className="text-sm font-bold text-[var(--ink)]">待办事项</h4>
            </div>
            <div className="space-y-2.5 text-xs text-[var(--color-text-secondary)]">
              <p className="flex items-center justify-between gap-3"><span className="flex items-center gap-2"><CircleDot className="h-3 w-3 text-[#2f74df]" />待审核题目</span><strong className="tabular-nums text-[var(--ink)]">{numberValue(overview.data?.questions_pending_review)}</strong></p>
              <p className="flex items-center justify-between gap-3"><span className="flex items-center gap-2"><CircleDot className="h-3 w-3 text-amber-500" />待处理导入</span><strong className="tabular-nums text-[var(--ink)]">{numberValue(overview.data?.imports_pending)}</strong></p>
              <p className="flex items-center justify-between gap-3"><span className="flex items-center gap-2"><CircleDot className="h-3 w-3 text-red-500" />关键审计</span><strong className="tabular-nums text-[var(--ink)]">{numberValue(overview.data?.audit_critical_today)}</strong></p>
            </div>
          </article>

          <article className="rounded-xl border border-[var(--color-border-light)] bg-white/70 p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[#eaf8f3] text-[#14936f]"><Layers3 className="h-4 w-4" /></span>
              <div className="min-w-0"><h4 className="text-sm font-bold text-[var(--ink)]">题库结构</h4>{topSubject && <p className="mt-0.5 truncate text-[10px] text-[var(--color-text-hint)]">题量最多：{topSubject.name}</p>}</div>
            </div>
            <div className="grid grid-cols-3 divide-x divide-[var(--color-border-light)]">
              <DetailMetric label="科目数" value={stats.isLoading ? "--" : String(subjects.length)} />
              <DetailMetric label="难度层级" value={stats.isLoading ? "--" : String(difficultyCount)} />
              <DetailMetric label="已通过占比" value={reviewedRate} accent="text-emerald-600" />
            </div>
          </article>

          <article className="rounded-xl border border-[var(--color-border-light)] bg-white/70 p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[#f2efff] text-[#7c61d6]"><Cpu className="h-4 w-4" /></span>
              <h4 className="text-sm font-bold text-[var(--ink)]">AI 运行</h4>
            </div>
            {aiStats.data ? (
              <div className="grid grid-cols-3 divide-x divide-[var(--color-border-light)]">
                <DetailMetric label="成功率" value={`${aiStats.data.success_rate.toFixed(1)}%`} accent="text-emerald-600" />
                <DetailMetric label="平均响应" value={`${(aiStats.data.avg_latency_ms / 1000).toFixed(1)}s`} />
                <DetailMetric label="7日 Token" value={aiStats.data.total_tokens >= 1000 ? `${(aiStats.data.total_tokens / 1000).toFixed(1)}k` : String(aiStats.data.total_tokens)} />
              </div>
            ) : (
              <p className="rounded-lg bg-[var(--color-bg-input)]/55 px-3 py-3 text-xs text-[var(--color-text-hint)]">需要 AI 设置读取权限后展示调用质量指标</p>
            )}
          </article>

          <article className="rounded-xl border border-[var(--color-border-light)] bg-white/70 p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[#edf7fb] text-[#2787a8]"><Clock3 className="h-4 w-4" /></span>
              <h4 className="text-sm font-bold text-[var(--ink)]">异步任务</h4>
            </div>
            {taskDiagnostics.data && redisConfigured ? (
              <div className="grid grid-cols-3 divide-x divide-[var(--color-border-light)]">
                <DetailMetric label="等待" value={String(queueTotals?.ready ?? 0)} />
                <DetailMetric label="处理中" value={String(queueTotals?.processing ?? 0)} accent="text-[#2f74df]" />
                <DetailMetric label="异常" value={String(queueErrors)} accent={queueErrors > 0 ? "text-red-500" : "text-emerald-600"} />
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
