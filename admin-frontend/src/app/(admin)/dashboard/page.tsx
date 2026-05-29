"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Database, FileStack, ShieldAlert, Users } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest } from "@/lib/api/client";
import type { DashboardDailyPoint, DashboardOverview, DashboardQuestionStats } from "@/lib/api/types";

const COLORS = ["#5b7b9a", "#6b9b6b", "#c49a6b", "#c47a7a", "#9aabba"];

function numberValue(value: unknown) {
  return typeof value === "number" ? value.toLocaleString("zh-CN") : "--";
}

function toPieData(input?: DashboardQuestionStats["by_review_status"]) {
  if (!input) return [];
  if (Array.isArray(input)) return input;
  return Object.entries(input).map(([name, count]) => ({ name, count }));
}

export default function DashboardPage() {
  const overview = useQuery({ queryKey: ["dashboard", "overview"], queryFn: () => apiRequest<DashboardOverview>("/dashboard/overview") });
  const daily = useQuery({ queryKey: ["dashboard", "daily"], queryFn: () => apiRequest<DashboardDailyPoint[]>("/dashboard/daily") });
  const stats = useQuery({ queryKey: ["dashboard", "questions-stats"], queryFn: () => apiRequest<DashboardQuestionStats>("/dashboard/questions-stats") });
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
        <Card>
          <CardHeader>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">近日日活与内容变化</h3>
          </CardHeader>
          <CardContent className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={daily.data ?? []} margin={{ left: -20, right: 12 }}>
                <defs>
                  <linearGradient id="users" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#5b7b9a" stopOpacity={0.32} />
                    <stop offset="95%" stopColor="#5b7b9a" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(91,123,154,0.16)" strokeDasharray="4 4" />
                <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#6b7b8d" }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#6b7b8d" }} />
                <Tooltip />
                <Area type="monotone" dataKey="users_new" stroke="#5b7b9a" fill="url(#users)" strokeWidth={3} />
                <Area type="monotone" dataKey="questions_new" stroke="#6b9b6b" fill="transparent" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">审核状态分布</h3>
          </CardHeader>
          <CardContent className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} dataKey="count" nameKey="name" innerRadius={58} outerRadius={92} paddingAngle={4}>
                  {pieData.map((entry, index) => (
                    <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
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
