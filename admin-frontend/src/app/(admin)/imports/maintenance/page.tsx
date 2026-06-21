"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, RefreshCw, Trash2, Wrench } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api/client";
import type { ImportPipelineSummaryItem, PipelinesListResponse, CleanupResponse, AlertItem } from "@/lib/api/types";

function alertTone(level: string) {
  if (level === "error") return "red";
  if (level === "warning") return "amber";
  return "blue";
}

function alertBg(level: string) {
  if (level === "error") return "bg-red-50 text-red-700 border-red-200";
  if (level === "warning") return "bg-amber-50 text-amber-700 border-amber-200";
  return "bg-blue-50 text-blue-700 border-blue-200";
}

export default function ImportMaintenancePage() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [cleanupResult, setCleanupResult] = useState<CleanupResponse | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isCleaningUp, setIsCleaningUp] = useState(false);

  // Fetch recent pipelines for health summary
  const pipelines = useQuery({
    queryKey: ["import-pipelines", "recent"],
    queryFn: () => apiRequest<PipelinesListResponse>("/imports/pipelines?page=1&page_size=20&sort_by=started_at"),
    retry: false,
  });

  // Fetch a recent completed pipeline for alerts (if any)
  const completedPipelines = useMemo(() => {
    const items = pipelines.data?.items ?? [];
    return items.filter((p) =>
      ["completed", "success", "finished", "failed", "error"].includes(p.status)
    );
  }, [pipelines.data]);

  // Collect alerts from recent pipelines
  const recentAlerts = useMemo(() => {
    const all: Array<AlertItem & { pipeline_id: string }> = [];
    for (const p of completedPipelines.slice(0, 5)) {
      if (p.alerts) {
        for (const a of p.alerts) {
          all.push({ ...a, pipeline_id: p.pipeline_id });
        }
      }
    }
    return all.slice(0, 20); // cap at 20
  }, [completedPipelines]);

  // Health calculations from last 10 completed pipelines
  const healthStats = useMemo(() => {
    const completed = completedPipelines.slice(0, 10);
    const total = completed.length;
    if (total === 0) return null;

    const succeeded = completed.filter((p) => p.status === "completed" || p.status === "success" || p.status === "finished").length;
    const failed = completed.filter((p) => p.status === "failed" || p.status === "error").length;
    const successRate = total > 0 ? (succeeded / total) * 100 : 0;

    let totalDuration = 0;
    let durationCount = 0;
    let totalQuestions = 0;
    let questionCount = 0;

    for (const p of completed) {
      const qr = p.quality_report;
      if (qr) {
        if (qr.total_questions) {
          totalQuestions += qr.total_questions;
          questionCount += 1;
        }
        if (qr.performance_summary?.total_duration_ms) {
          totalDuration += qr.performance_summary.total_duration_ms;
          durationCount += 1;
        }
      }
    }

    return {
      total,
      succeeded,
      failed,
      successRate: Math.round(successRate * 10) / 10,
      avgDuration: durationCount > 0 ? Math.round(totalDuration / durationCount / 1000) : null,
      totalQuestions,
    };
  }, [completedPipelines]);

  // Dry-run cleanup
  const runDryRun = async () => {
    setMessage(null);
    setCleanupResult(null);
    setShowConfirm(false);
    try {
      const result = await apiRequest<CleanupResponse>("/imports/maintenance/cleanup", {
        method: "POST",
        body: JSON.stringify({ target: "all", dry_run: true }),
        headers: { "Content-Type": "application/json" },
      });
      setCleanupResult(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Dry-run 请求失败");
    }
  };

  // Real cleanup (after confirm)
  const runCleanup = async () => {
    setIsCleaningUp(true);
    setMessage(null);
    try {
      const result = await apiRequest<CleanupResponse>("/imports/maintenance/cleanup", {
        method: "POST",
        body: JSON.stringify({ target: "all", dry_run: false }),
        headers: { "Content-Type": "application/json" },
      });
      setCleanupResult(result);
      setShowConfirm(false);
      setMessage("清理完成");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "清理请求失败");
    } finally {
      setIsCleaningUp(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Wrench className="h-5 w-5 text-[var(--color-text-hint)]" />
        <h3 className="font-display text-xl font-bold text-[var(--ink)]">导入系统运维</h3>
      </div>

      {/* Message banner */}
      {message ? (
        <div className="flex items-center gap-2.5 rounded-2xl border border-[var(--color-border)] bg-white/80 px-4 py-3 text-sm">
          {message.includes("失败") || message.includes("error") ? (
            <AlertCircle className="h-4 w-4 shrink-0 text-red-500" />
          ) : (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
          )}
          {message}
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-2">
        {/* ===== Health Summary ===== */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <h4 className="font-display text-base font-bold text-[var(--ink)]">导入健康摘要</h4>
              <Button variant="secondary" disabled={pipelines.isFetching} onClick={() => pipelines.refetch()} className="h-8 px-3 text-[10px]">
                <RefreshCw className={`h-3 w-3 ${pipelines.isFetching ? "animate-spin" : ""}`} />
                刷新
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {pipelines.isLoading ? (
              <p className="text-sm text-[var(--color-text-hint)]">加载中...</p>
            ) : !healthStats ? (
              <p className="text-sm text-[var(--color-text-hint)]">暂无已完成导入记录</p>
            ) : (
              <div className="grid grid-cols-2 gap-3 text-[11px]">
                <div className="rounded-lg bg-white/70 p-3">
                  <span className="text-[9px] uppercase tracking-wider text-[var(--color-text-hint)]">最近导入</span>
                  <p className="mt-1 text-lg font-bold text-[var(--ink)]">{healthStats.total}</p>
                </div>
                <div className="rounded-lg bg-green-50/70 p-3">
                  <span className="text-[9px] uppercase tracking-wider text-green-600">成功率</span>
                  <p className="mt-1 text-lg font-bold text-green-700">{healthStats.successRate}%</p>
                  <p className="text-[9px] text-green-600">成功 {healthStats.succeeded} / 失败 {healthStats.failed}</p>
                </div>
                {healthStats.avgDuration !== null ? (
                  <div className="rounded-lg bg-blue-50/70 p-3">
                    <span className="text-[9px] uppercase tracking-wider text-blue-600">平均耗时</span>
                    <p className="mt-1 text-lg font-bold text-blue-700">{healthStats.avgDuration}s</p>
                  </div>
                ) : null}
                {healthStats.totalQuestions > 0 ? (
                  <div className="rounded-lg bg-purple-50/70 p-3">
                    <span className="text-[9px] uppercase tracking-wider text-purple-600">总导入题数</span>
                    <p className="mt-1 text-lg font-bold text-purple-700">{healthStats.totalQuestions}</p>
                  </div>
                ) : null}
              </div>
            )}
          </CardContent>
        </Card>

        {/* ===== Recent Alerts ===== */}
        <Card>
          <CardHeader>
            <h4 className="font-display text-base font-bold text-[var(--ink)]">最近告警</h4>
          </CardHeader>
          <CardContent>
            {pipelines.isLoading ? (
              <p className="text-sm text-[var(--color-text-hint)]">加载中...</p>
            ) : recentAlerts.length === 0 ? (
              <div className="flex flex-col items-center py-6 text-center">
                <CheckCircle2 className="mb-2 h-6 w-6 text-green-400" />
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">暂无告警</p>
                <p className="mt-1 text-[10px] text-[var(--color-text-hint)]">最近 5 条已完成导入均未触发告警规则</p>
              </div>
            ) : (
              <div className="space-y-2">
                {recentAlerts.map((alert, i) => (
                  <div key={`${alert.pipeline_id}-${i}`} className={`rounded-lg border px-3 py-2.5 text-[11px] ${alertBg(alert.level)}`}>
                    <div className="flex items-center gap-2">
                      <span className="text-[9px] font-semibold uppercase">{alert.level}</span>
                      <span className="font-semibold">{alert.message}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] opacity-80">
                      {alert.value !== undefined ? <span>当前值: {String(alert.value)}</span> : null}
                      {alert.threshold !== undefined ? <span>阈值: {String(alert.threshold)}</span> : null}
                      {alert.suggested_action ? <span>建议: {alert.suggested_action}</span> : null}
                      <span className="text-[9px] text-[var(--color-text-hint)]">{alert.pipeline_id.slice(0, 8)}...</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ===== Cleanup Section ===== */}
      <Card>
        <CardHeader>
          <h4 className="font-display text-base font-bold text-[var(--ink)]">存储清理</h4>
          <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
            清理过期 pipeline artifact 和 OCR 缓存。先运行 Dry-Run 查看可清理量，确认后再执行。
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Action buttons */}
          <div className="flex items-center gap-3">
            <Button onClick={runDryRun} disabled={pipelines.isFetching} className="h-10 px-4">
              <RefreshCw className="h-4 w-4" />
              {cleanupResult ? "重新 Dry-Run" : "运行 Dry-Run"}
            </Button>
            {cleanupResult && !cleanupResult.dry_run ? (
              <div className="flex items-center gap-2 text-sm text-green-700">
                <CheckCircle2 className="h-4 w-4" />
                清理完成
              </div>
            ) : null}
            {cleanupResult?.dry_run ? (
              !showConfirm ? (
                <Button variant="secondary" onClick={() => setShowConfirm(true)} className="h-10 px-4">
                  <Trash2 className="h-4 w-4" />
                  确认清理
                </Button>
              ) : (
                <div className="flex items-center gap-2">
                  <Button variant="secondary" onClick={() => setShowConfirm(false)} className="h-10 px-4">
                    取消
                  </Button>
                  <Button onClick={runCleanup} disabled={isCleaningUp} className="h-10 px-4">
                    {isCleaningUp ? "清理中..." : "确认并执行清理"}
                  </Button>
                </div>
              )
            ) : null}
          </div>

          {/* Dry-run / Cleanup results table */}
          {cleanupResult ? (
            <div className="space-y-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">
                {cleanupResult.dry_run ? "Dry-Run 结果（未删除任何文件）" : "清理结果"}
              </p>
              <div className="overflow-hidden rounded-xl border border-[var(--color-border)]">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-[var(--color-bg-input)] text-[10px] font-semibold text-[var(--color-text-secondary)]">
                      <th className="px-3 py-2 text-left">目标</th>
                      <th className="px-3 py-2 text-right">扫描数</th>
                      <th className="px-3 py-2 text-right">可清理/已清理</th>
                      <th className="px-3 py-2 text-right">释放空间</th>
                      <th className="px-3 py-2 text-right">跳过</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--color-border)]">
                    {Object.entries(cleanupResult.targets || {}).map(([target, data]) => {
                      const d = data as Record<string, unknown>;
                      return (
                        <tr key={target} className="bg-white/50">
                          <td className="px-3 py-2 font-medium text-[var(--ink)]">{target}</td>
                          <td className="px-3 py-2 text-right text-[var(--color-text-secondary)]">
                            {typeof d.scanned_count === "number" ? d.scanned_count : String(d.status || "—")}
                          </td>
                          <td className="px-3 py-2 text-right text-[var(--color-text-secondary)]">
                            {typeof d.deleted_count === "number" ? d.deleted_count : "—"}
                          </td>
                          <td className="px-3 py-2 text-right text-[var(--color-text-secondary)]">
                            {typeof d.freed_bytes === "number"
                              ? d.freed_bytes > 1048576
                                ? `${(d.freed_bytes / 1048576).toFixed(1)} MB`
                                : d.freed_bytes > 1024
                                  ? `${(d.freed_bytes / 1024).toFixed(1)} KB`
                                  : `${d.freed_bytes} B`
                              : "—"}
                          </td>
                          <td className="px-3 py-2 text-right text-[var(--color-text-secondary)]">
                            {typeof d.skipped_running_count === "number"
                              ? d.skipped_running_count
                              : typeof d.skipped_count === "number"
                                ? d.skipped_count
                                : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {cleanupResult.dry_run ? (
                <p className="text-[10px] text-amber-600">
                  ⚠️ Dry-Run 仅扫描不删除。确认清理前请检查以上结果。
                </p>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
