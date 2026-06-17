"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Database, FileStack, ShieldAlert, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest, toQuery } from "@/lib/api/client";
import { useAuthStore } from "@/lib/auth/auth-store";
import type { DashboardDailyPoint, DashboardOverview, DashboardQuestionStats } from "@/lib/api/types";
import { DashboardTrendChart } from "./components/dashboard-trend-chart";
import { ReviewStatusChart } from "./components/review-status-chart";


function numberValue(value: unknown) {
  return typeof value === "number" ? value.toLocaleString("zh-CN") : "--";
}

function toPieData(input?: DashboardQuestionStats["by_review_status"]): Array<{ name: string; count: number }> {
  if (!input) return [];
  if (Array.isArray(input)) return input;
  return Object.entries(input).map(([name, count]) => ({ name, count: Number(count) }));
}

export default function DashboardPage() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isBootstrapping = useAuthStore((state) => state.isBootstrapping);
  const canRequestDashboard = isAuthenticated && !isBootstrapping;
  const [period, setPeriod] = useState<"7d" | "30d">("7d");

  const dailyQuery = useMemo(() => {
    const to = new Date();
    const from = new Date(to);
    from.setDate(from.getDate() - (period === "7d" ? 7 : 30));
    return {
      from: from.toISOString().slice(0, 10),
      to: to.toISOString().slice(0, 10),
    };
  }, [period]);

  const overview = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: () => apiRequest<DashboardOverview>("/dashboard/overview"),
    enabled: canRequestDashboard,
  });
  const daily = useQuery({
    queryKey: ["dashboard", "daily", dailyQuery],
    queryFn: () => apiRequest<DashboardDailyPoint[]>(`/dashboard/daily${toQuery(dailyQuery)}`),
    enabled: canRequestDashboard,
  });
  const stats = useQuery({
    queryKey: ["dashboard", "questions-stats"],
    queryFn: () => apiRequest<DashboardQuestionStats>("/dashboard/questions-stats"),
    enabled: canRequestDashboard,
  });
  const pieData = toPieData(stats.data?.by_review_status);

  const cards = [
    { label: "小程序用户", value: overview.data?.users_total, icon: Users, tone: "primary" as const },
    { label: "今日新增用户", value: overview.data?.users_new_today, icon: Users, tone: "primary" as const },
    { label: "题目总量", value: overview.data?.questions_total, icon: Database, tone: "success" as const },
    { label: "待审核题目", value: overview.data?.questions_pending_review, icon: Database, tone: "warning" as const },
    { label: "导入批次", value: overview.data?.imports_total, icon: FileStack, tone: "warning" as const },
    { label: "待处理导入", value: overview.data?.imports_pending, icon: FileStack, tone: "warning" as const },
    { label: "今日关键审计", value: overview.data?.audit_critical_today, icon: ShieldAlert, tone: "danger" as const },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">Dashboard</p>
          <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">运营蓝图总览</h2>
        </div>
        <StatusBadge tone={overview.isError ? "danger" : "success"}>{overview.isError ? "接口待联调" : "实时 API"}</StatusBadge>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((item) => {
          const Icon = item.icon;
          return (
            <Card key={item.label} className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-semibold text-[var(--color-text-secondary)]">{item.label}</p>
                  <p className="mt-4 font-display text-4xl font-bold text-[var(--ink)]">{numberValue(item.value)}</p>
                </div>
                <div className="grid h-12 w-12 place-items-center rounded-2xl border border-[var(--color-border)] bg-white/70">
                  <Icon className="h-6 w-6 text-[var(--color-primary)]" />
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_0.8fr]">
        <DashboardTrendChart data={daily.data} loading={daily.isLoading} period={period} onPeriodChange={setPeriod} />

        <Card className="overflow-hidden">
          <CardHeader>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">审核状态分布</h3>
          </CardHeader>
          <CardContent className="h-80 p-0">
            <ReviewStatusChart data={pieData} />
          </CardContent>
        </Card>
      </div>

      <Card className="blueprint-panel p-6">
        <div className="relative z-10 flex items-start gap-4">
          <Activity className="mt-1 h-6 w-6 text-[var(--color-primary-dark)]" />
          <div>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">联调提示</h3>
            <p className="mt-2 max-w-3xl text-sm leading-7 text-[var(--color-text-secondary)]">
              当前 Dashboard 仅请求已挂载的 /dashboard API。题库、导入与科目后台 API 若返回 404，应记录为后端 router 挂载阻塞，不在本阶段修改后端。
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
