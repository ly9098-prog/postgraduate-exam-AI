"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle, AlertTriangle, CheckCircle2, Database, HardDrive,
  Info, RefreshCw, ShieldAlert, Trash2, Wrench,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api/client";
import type { PipelinesListResponse, CleanupResponse, AlertItem } from "@/lib/api/types";

function alertIcon(level: string) {
  if (level === "error") return <ShieldAlert className="h-4 w-4 shrink-0 text-red-600" />;
  if (level === "warning") return <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" />;
  return <Info className="h-4 w-4 shrink-0 text-blue-500" />;
}

function alertBorder(level: string) {
  if (level === "error") return "border-l-red-500 bg-red-50/60";
  if (level === "warning") return "border-l-amber-400 bg-amber-50/60";
  return "border-l-blue-400 bg-blue-50/60";
}

export default function ImportMaintenancePage() {
  const [message, setMessage] = useState<string | null>(null);
  const [cleanupResult, setCleanupResult] = useState<CleanupResponse | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isDryRunning, setIsDryRunning] = useState(false);
  const [isCleaningUp, setIsCleaningUp] = useState(false);

  // Fetch recent pipelines for alerts
  const pipelines = useQuery({
    queryKey: ["import-pipelines", "recent"],
    queryFn: () => apiRequest<PipelinesListResponse>("/imports/pipelines?page=1&page_size=20&sort_by=started_at"),
    retry: false,
  });

  // Collect alerts from recent pipelines
  const completedPipelines = useMemo(() => {
    const items = pipelines.data?.items ?? [];
    return items.filter((p) =>
      ["completed", "success", "finished", "failed", "error"].includes(p.status)
    );
  }, [pipelines.data]);

  const recentAlerts = useMemo(() => {
    const all: Array<AlertItem & { pipeline_id: string }> = [];
    for (const p of completedPipelines.slice(0, 5)) {
      if (p.alerts) {
        for (const a of p.alerts) {
          all.push({ ...a, pipeline_id: p.pipeline_id });
        }
      }
    }
    return all.slice(0, 20);
  }, [completedPipelines]);

  // Dry-run cleanup
  const runDryRun = async () => {
    setMessage(null);
    setShowConfirm(false);
    setIsDryRunning(true);
    try {
      const result = await apiRequest<CleanupResponse>("/imports/maintenance/cleanup", {
        method: "POST",
        body: JSON.stringify({ target: "all", dry_run: true }),
        headers: { "Content-Type": "application/json" },
      });
      setCleanupResult(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Dry-run 请求失败");
    } finally {
      setIsDryRunning(false);
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
    <div className="space-y-8">
      {/* ===== Page Header ===== */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <div className="rounded-2xl bg-gradient-to-br from-slate-100 to-slate-200 p-3.5 shadow-sm ring-1 ring-slate-200">
            <Wrench className="h-6 w-6 text-slate-700" />
          </div>
          <div>
            <h2 className="font-display text-2xl font-bold tracking-tight text-[var(--ink)]">运维中心</h2>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
              导入系统运行状态与存储清理
            </p>
          </div>
        </div>
        <Button
          variant="secondary"
          disabled={pipelines.isFetching}
          onClick={() => pipelines.refetch()}
          className="h-9 px-3.5 text-xs"
        >
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${pipelines.isFetching ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {/* ===== Message Banner ===== */}
      {message ? (
        <div className="flex items-center gap-2.5 rounded-2xl border border-[var(--color-border)] bg-white/80 px-5 py-3.5 text-sm shadow-sm">
          {message.includes("失败") || message.includes("error") ? (
            <AlertCircle className="h-4 w-4 shrink-0 text-red-500" />
          ) : (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
          )}
          <span className="text-[var(--ink)]">{message}</span>
        </div>
      ) : null}

      {/* ===== Alerts Section ===== */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-[var(--color-text-hint)]" />
          <h3 className="font-display text-lg font-bold text-[var(--ink)]">最近告警</h3>
          {recentAlerts.length > 0 ? (
            <span className="ml-auto rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-semibold text-amber-700">
              {recentAlerts.length} 条
            </span>
          ) : null}
        </div>
        <Card className="overflow-hidden">
          <CardContent className="p-0">
            {recentAlerts.length === 0 ? (
              <div className="flex flex-col items-center py-12 text-center">
                <div className="mb-3 rounded-full bg-green-100 p-3">
                  <CheckCircle2 className="h-7 w-7 text-green-500" />
                </div>
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">暂无告警</p>
                <p className="mt-1 text-xs text-[var(--color-text-hint)]">最近 5 条已完成导入均未触发告警规则</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100">
                {recentAlerts.map((alert, i) => (
                  <div
                    key={`${alert.pipeline_id}-${i}`}
                    className={`border-l-4 px-5 py-3.5 transition-colors hover:bg-white/80 ${alertBorder(alert.level)}`}
                  >
                    <div className="flex items-start gap-3">
                      {alertIcon(alert.level)}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="rounded bg-white/70 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-hint)]">
                            {alert.level}
                          </span>
                          <span className="text-sm font-semibold text-[var(--ink)]">{alert.message}</span>
                        </div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-text-secondary)]">
                          {alert.value !== undefined ? (
                            <span className="inline-flex items-center gap-1">
                              <span className="text-[10px] text-[var(--color-text-hint)]">当前值:</span>
                              <span className="font-medium">{String(alert.value)}</span>
                            </span>
                          ) : null}
                          {alert.threshold !== undefined ? (
                            <span className="inline-flex items-center gap-1">
                              <span className="text-[10px] text-[var(--color-text-hint)]">阈值:</span>
                              <span className="font-medium">{String(alert.threshold)}</span>
                            </span>
                          ) : null}
                          {alert.suggested_action ? (
                            <span className="inline-flex items-center gap-1">
                              <span className="text-[10px] text-[var(--color-text-hint)]">建议:</span>
                              <span>{alert.suggested_action}</span>
                            </span>
                          ) : null}
                          <span className="ml-auto font-mono text-[10px] text-[var(--color-text-hint)]">
                            {alert.pipeline_id.slice(0, 8)}...
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      {/* ===== Storage Cleanup Section ===== */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <HardDrive className="h-5 w-5 text-[var(--color-text-hint)]" />
          <h3 className="font-display text-lg font-bold text-[var(--ink)]">存储清理</h3>
        </div>
        <Card>
          <CardHeader>
            <p className="text-sm text-[var(--color-text-secondary)]">
              清理过期 pipeline artifact 和 OCR 缓存文件，释放磁盘空间。建议先运行 Dry-Run 预览可清理量，确认后再执行。
            </p>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* Workflow steps */}
            <div className="flex flex-wrap items-center gap-3">
              {/* Step 1: Dry-Run */}
              <div className="flex items-center gap-3 rounded-xl border border-[var(--color-border)] bg-white/60 px-4 py-3">
                <div className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-100 text-[11px] font-bold text-slate-600">1</div>
                <div>
                  <p className="text-xs font-semibold text-[var(--ink)]">扫描分析</p>
                  <p className="text-[10px] text-[var(--color-text-hint)]">预估可清理空间</p>
                </div>
              </div>
              <div className="hidden h-px w-8 border-t border-dashed border-[var(--color-border)] sm:block" />
              {/* Step 2: Review */}
              <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${cleanupResult ? "border-[var(--color-border)] bg-white/60" : "border-dashed border-[var(--color-border)] bg-white/30"}`}>
                <div className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold ${cleanupResult ? "bg-slate-100 text-slate-600" : "bg-gray-100 text-gray-400"}`}>2</div>
                <div>
                  <p className="text-xs font-semibold text-[var(--ink)]">确认结果</p>
                  <p className="text-[10px] text-[var(--color-text-hint)]">{cleanupResult ? "检查扫描结果" : "等待上一步"}</p>
                </div>
              </div>
              <div className="hidden h-px w-8 border-t border-dashed border-[var(--color-border)] sm:block" />
              {/* Step 3: Execute */}
              <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${cleanupResult?.dry_run ? "border-[var(--color-border)] bg-white/60" : "border-dashed border-[var(--color-border)] bg-white/30"}`}>
                <div className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold ${cleanupResult?.dry_run ? "bg-slate-100 text-slate-600" : "bg-gray-100 text-gray-400"}`}>3</div>
                <div>
                  <p className="text-xs font-semibold text-[var(--ink)]">执行清理</p>
                  <p className="text-[10px] text-[var(--color-text-hint)]">{cleanupResult?.dry_run ? "确认后删除" : "等待上一步"}</p>
                </div>
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={runDryRun} disabled={isDryRunning} className="h-10 gap-2 px-5">
                <RefreshCw className={`h-4 w-4 ${isDryRunning ? "animate-spin" : ""}`} />
                {isDryRunning ? "扫描中..." : cleanupResult ? "重新 Dry-Run" : "运行 Dry-Run"}
              </Button>
              {cleanupResult && !cleanupResult.dry_run ? (
                <div className="flex items-center gap-2 rounded-xl border border-green-200 bg-green-50/80 px-4 py-2 text-sm text-green-700">
                  <CheckCircle2 className="h-4 w-4" />
                  清理完成
                </div>
              ) : null}
              {cleanupResult?.dry_run ? (
                !showConfirm ? (
                  <Button variant="secondary" onClick={() => setShowConfirm(true)} className="h-10 gap-2 px-5">
                    <Trash2 className="h-4 w-4" />
                    确认清理
                  </Button>
                ) : (
                  <div className="flex items-center gap-2">
                    <Button variant="secondary" onClick={() => setShowConfirm(false)} className="h-10 px-5">
                      取消
                    </Button>
                    <Button onClick={runCleanup} disabled={isCleaningUp} className="h-10 gap-2 px-5">
                      {isCleaningUp ? "清理中..." : "确认并执行清理"}
                    </Button>
                  </div>
                )
              ) : null}
            </div>

            {/* Results table */}
            {(cleanupResult || isDryRunning) ? (
              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">
                  {isDryRunning ? "正在扫描..." : cleanupResult?.dry_run ? "Dry-Run 结果（未删除任何文件）" : "清理结果"}
                </p>
                <div className="overflow-hidden rounded-xl border border-[var(--color-border)]">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-[var(--color-bg-input)] text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
                        <th className="px-4 py-2.5 text-left">目标</th>
                        <th className="px-4 py-2.5 text-right">扫描数</th>
                        <th className="px-4 py-2.5 text-right">可清理</th>
                        <th className="px-4 py-2.5 text-right">释放空间</th>
                        <th className="px-4 py-2.5 text-right">跳过</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--color-border)]">
                      {isDryRunning && !cleanupResult ? (
                        <tr>
                          <td className="px-4 py-8 text-center text-[var(--color-text-hint)]" colSpan={5}>扫描中...</td>
                        </tr>
                      ) : (
                        Object.entries(cleanupResult?.targets || {}).map(([target, data]) => {
                        const d = data as Record<string, unknown>;
                        return (
                          <tr key={target} className="bg-white/50 transition-colors hover:bg-white/80">
                            <td className="px-4 py-2.5 font-medium text-[var(--ink)]">
                              <span className="inline-flex items-center gap-1.5">
                                <Database className="h-3.5 w-3.5 text-[var(--color-text-hint)]" />
                                {target}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-right tabular-nums text-[var(--color-text-secondary)]">
                              {typeof d.scanned_count === "number" ? d.scanned_count.toLocaleString() : String(d.status || "—")}
                            </td>
                            <td className="px-4 py-2.5 text-right tabular-nums text-[var(--color-text-secondary)]">
                              {typeof d.deleted_count === "number" ? d.deleted_count.toLocaleString() : "—"}
                            </td>
                            <td className="px-4 py-2.5 text-right tabular-nums text-[var(--color-text-secondary)]">
                              {typeof d.freed_bytes === "number"
                                ? d.freed_bytes > 1048576
                                  ? `${(d.freed_bytes / 1048576).toFixed(1)} MB`
                                  : d.freed_bytes > 1024
                                    ? `${(d.freed_bytes / 1024).toFixed(1)} KB`
                                    : `${d.freed_bytes} B`
                                : "—"}
                            </td>
                            <td className="px-4 py-2.5 text-right tabular-nums text-[var(--color-text-secondary)]">
                              {typeof d.skipped_running_count === "number"
                                ? d.skipped_running_count.toLocaleString()
                                : typeof d.skipped_count === "number"
                                  ? d.skipped_count.toLocaleString()
                                  : "—"}
                            </td>
                          </tr>
                        );
                      })
                      )}
                    </tbody>
                  </table>
                </div>
                {cleanupResult?.dry_run ? (
                  <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-4 py-2.5 text-xs text-amber-700">
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    Dry-Run 仅扫描不删除。请检查以上结果，确认后执行清理。
                  </div>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
