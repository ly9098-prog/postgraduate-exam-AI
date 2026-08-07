"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { DataTable } from "@/components/data-table/data-table";
import { apiRequest, toQuery } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import type { MetricsAggregateResponse, MetricsBackfillResponse, RecommendationMetricsDaily } from "@/lib/api/types";

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function daysAgoISO(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function showToast(msg: string, error = false) {
  const el = document.createElement("div");
  el.className = `fixed left-1/2 top-4 z-[200] -translate-x-1/2 rounded-xl border px-5 py-3 text-sm font-semibold shadow-[var(--shadow-card)] animate-rise-in bg-white ${
    error ? "border-[var(--color-danger)]/30 text-[var(--color-danger)]" : "border-[var(--color-success)]/30 text-[var(--color-success)]"
  }`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2500);
}

export default function RecommendationMetricsPage() {
  const permissions = useAuthStore((s) => s.permissions);
  const canWrite = hasPermission(permissions, "question:write");
  const queryClient = useQueryClient();

  const [dateFrom, setDateFrom] = useState(daysAgoISO(30));
  const [dateTo, setDateTo] = useState(todayISO());

  const metrics = useQuery({
    queryKey: ["recommendation", "metrics", dateFrom, dateTo],
    queryFn: () =>
      apiRequest<RecommendationMetricsDaily[]>(
        `/recommendation/metrics${toQuery({ date_from: dateFrom, date_to: dateTo })}`,
      ),
  });

  const aggregateMutation = useMutation({
    mutationFn: () =>
      apiRequest<MetricsAggregateResponse>("/recommendation/metrics/aggregate", { method: "POST", body: JSON.stringify({}) }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["recommendation", "metrics"] });
      showToast(`聚合完成：date=${data.target_date} rows=${data.aggregated_rows}`);
    },
    onError: (e) => showToast(getErrorMessage(e), true),
  });

  const backfillMutation = useMutation({
    mutationFn: () =>
      apiRequest<MetricsBackfillResponse>("/recommendation/metrics/backfill", {
        method: "POST",
        body: JSON.stringify({ date_from: dateFrom, date_to: dateTo }),
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["recommendation", "metrics"] });
      showToast(
        `补跑完成：成功 ${data.success_dates.length} 天，失败 ${data.failed_dates.length} 天${data.errors.length ? "（" + data.errors[0] + "）" : ""}`,
      );
    },
    onError: (e) => showToast(getErrorMessage(e), true),
  });

  const rows = metrics.data ?? [];

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">推荐每日指标</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            按 (日期, 科目, 场景, 策略) 聚合自 recommendation_logs；调度器每日自动聚合昨日数据
          </p>
        </div>
        {canWrite && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => aggregateMutation.mutate()} disabled={aggregateMutation.isPending}>
              <Play className="h-4 w-4" />
              {aggregateMutation.isPending ? "聚合中…" : "聚合今天"}
            </Button>
            <Button variant="secondary" onClick={() => backfillMutation.mutate()} disabled={backfillMutation.isPending}>
              <RotateCcw className="h-4 w-4" />
              {backfillMutation.isPending ? "补跑中…" : `补跑区间`}
            </Button>
          </div>
        )}
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-4">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">
              起始日期
              <input type="date" className="ml-2 rounded-xl border border-[var(--color-border)] px-3 py-2 text-sm" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </label>
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">
              结束日期
              <input type="date" className="ml-2 rounded-xl border border-[var(--color-border)] px-3 py-2 text-sm" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </label>
          </div>
        </CardHeader>
        <CardContent>
          <DataTable<RecommendationMetricsDaily>
            data={rows}
            emptyText="该区间暂无指标，点击「聚合今天」或「补跑区间」生成"
            columns={[
              { id: "date", header: "日期", accessorKey: "date" },
              { id: "subject", header: "科目", accessorKey: "subject_code" },
              { id: "scene", header: "场景", accessorKey: "scene" },
              { id: "strategy", header: "策略", accessorKey: "strategy" },
              { id: "variant", header: "分组", accessorKey: "variant_key" },
              { id: "exposure", header: "曝光", accessorKey: "exposure_count" },
              { id: "click", header: "点击", accessorKey: "click_count" },
              { id: "answer", header: "答题", accessorKey: "answer_count" },
              { id: "correct", header: "正确", accessorKey: "correct_count" },
              { id: "wrong", header: "错误", accessorKey: "wrong_count" },
              {
                id: "accuracy",
                header: "正确率",
                accessorKey: "accuracy",
                cell: ({ row }) => `${(row.original.accuracy * 100).toFixed(1)}%`,
              },
              {
                id: "ctr",
                header: "点击率",
                accessorKey: "ctr",
                cell: ({ row }) => `${(row.original.ctr * 100).toFixed(1)}%`,
              },
            ]}
          />
        </CardContent>
      </Card>

      {metrics.isFetching && (
        <div className="flex items-center gap-2 text-xs text-[var(--color-text-hint)]">
          <BarChart3 className="h-3.5 w-3.5 animate-pulse" /> 加载中…
        </div>
      )}
    </div>
  );
}
