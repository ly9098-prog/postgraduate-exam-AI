"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, RefreshCw, Search, ServerCrash } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest } from "@/lib/api/client";
import type { TaskDiagnosticsResponse, TaskTraceResponse } from "@/lib/api/types";

function duration(seconds?: number | null) {
  const value = Math.max(0, Number(seconds || 0));
  if (value < 60) return `${Math.round(value)} 秒`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟`;
  return `${(value / 3600).toFixed(value >= 36_000 ? 0 : 1)} 小时`;
}

function healthTone(severity: "ok" | "warning" | "error") {
  if (severity === "ok") return "success" as const;
  if (severity === "warning") return "warning" as const;
  return "danger" as const;
}

function queueStatusTone(status?: string | null) {
  if (status === "completed") return "success" as const;
  if (["failed", "dead", "corrupt"].includes(status || "")) return "danger" as const;
  if (["processing", "retry", "pending"].includes(status || "")) return "warning" as const;
  return "neutral" as const;
}

function MetricCard({ label, value, hint }: { label: string; value: string | number; hint: string }) {
  return (
    <Card>
      <CardContent className="space-y-1 p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">{label}</p>
        <p className="text-2xl font-bold text-[var(--ink)]">{value}</p>
        <p className="text-xs text-[var(--color-text-secondary)]">{hint}</p>
      </CardContent>
    </Card>
  );
}

export default function SystemTasksPage() {
  const [traceInput, setTraceInput] = useState("");
  const [traceId, setTraceId] = useState("");

  const diagnostics = useQuery({
    queryKey: ["task-diagnostics"],
    queryFn: () => apiRequest<TaskDiagnosticsResponse>("/tasks/diagnostics"),
    refetchInterval: 15_000,
    staleTime: 5_000,
    retry: 1,
  });

  const traceQuery = useQuery({
    queryKey: ["task-trace", traceId],
    queryFn: () => apiRequest<TaskTraceResponse>(`/tasks/trace/${encodeURIComponent(traceId)}`),
    enabled: Boolean(traceId),
    retry: false,
  });

  const retryOutbox = useMutation({
    mutationFn: (outboxId: number) => apiRequest(`/tasks/outbox/${outboxId}/retry`, { method: "POST" }),
    onSuccess: () => diagnostics.refetch(),
  });

  const data = diagnostics.data;
  const health = data?.health;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-[var(--color-primary)]" />
            <h1 className="text-2xl font-bold text-[var(--ink)]">异步任务诊断</h1>
          </div>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            PostgreSQL Outbox、Redis 队列与答题 Projection 的实时一致性快照。
          </p>
        </div>
        <Button variant="secondary" onClick={() => diagnostics.refetch()} disabled={diagnostics.isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${diagnostics.isFetching ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {diagnostics.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 p-5 text-sm text-[var(--color-danger)]">
            <ServerCrash className="h-5 w-5" />
            无法获取任务诊断状态，请检查后端服务与管理员权限。
          </CardContent>
        </Card>
      ) : null}

      {data && health ? (
        <>
          <Card>
            <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
              <div className="flex items-center gap-3">
                {health.severity === "ok" ? (
                  <CheckCircle2 className="h-6 w-6 text-[var(--color-success)]" />
                ) : (
                  <AlertTriangle className={`h-6 w-6 ${health.severity === "error" ? "text-[var(--color-danger)]" : "text-[var(--color-warning)]"}`} />
                )}
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-[var(--ink)]">异步任务链路</span>
                    <StatusBadge tone={healthTone(health.severity)}>
                      {health.severity === "ok" ? "正常" : health.severity === "warning" ? "需关注" : "异常"}
                    </StatusBadge>
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                    {data.async_runtime_expected
                      ? `Redis ${data.redis.available ? "可用" : "不可用"} · 最近快照 ${new Date(data.generated_at).toLocaleString()}`
                      : "当前为本地 Web-only 模式，异步运行时未启用；积压不会触发运行时告警。"}
                  </p>
                </div>
              </div>
              <StatusBadge tone={data.redis.available ? "success" : data.redis.configured ? "danger" : "neutral"}>
                Redis {data.redis.available ? "Connected" : data.redis.configured ? "Unavailable" : "Not configured"}
              </StatusBadge>
            </CardContent>
          </Card>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Outbox 未发布" value={data.outbox.unpublished} hint={`最老等待 ${duration(data.outbox.oldest_unpublished_seconds)}`} />
            <MetricCard label="Redis Ready" value={data.redis.totals.ready} hint={`最老等待 ${duration(data.redis.oldest_ready_seconds)}`} />
            <MetricCard label="重试 / 死信" value={`${data.redis.totals.retry} / ${data.redis.totals.dead + data.redis.totals.corrupt}`} hint={`处理中 ${data.redis.totals.processing}`} />
            <MetricCard label="未完成 Projection" value={data.projection.unprojected} hint={`24h 自动补偿 ${data.projection.repairs_scheduled_24h}`} />
          </div>

          {health.issues.length > 0 ? (
            <Card>
              <CardHeader>
                <h2 className="font-semibold text-[var(--ink)]">当前需要关注</h2>
              </CardHeader>
              <CardContent className="space-y-3">
                {health.issues.map((issue) => (
                  <div key={issue.code} className="flex items-start gap-3 rounded-2xl border border-[var(--color-border)] bg-white/60 p-4">
                    <StatusBadge tone={issue.severity === "error" ? "danger" : "warning"}>{issue.code}</StatusBadge>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-[var(--ink)]">{issue.message}</p>
                      {issue.value !== undefined && issue.value !== null ? (
                        <p className="mt-1 text-xs text-[var(--color-text-hint)]">当前值：{issue.value}</p>
                      ) : null}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <h2 className="font-semibold text-[var(--ink)]">队列状态</h2>
            </CardHeader>
            <CardContent className="overflow-x-auto p-0">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="border-b border-[var(--color-border)] bg-white/50 text-left text-xs text-[var(--color-text-hint)]">
                  <tr>
                    <th className="px-6 py-3">任务类型</th>
                    <th className="px-4 py-3">Ready</th>
                    <th className="px-4 py-3">Processing</th>
                    <th className="px-4 py-3">Retry</th>
                    <th className="px-4 py-3">Dead/Corrupt</th>
                    <th className="px-4 py-3">最老 Ready</th>
                  </tr>
                </thead>
                <tbody>
                  {data.redis.queues.length ? data.redis.queues.map((queue) => (
                    <tr key={queue.task_type} className="border-b border-[var(--color-border)] last:border-0">
                      <td className="px-6 py-3 font-mono text-xs text-[var(--ink)]">{queue.task_type}</td>
                      <td className="px-4 py-3">{queue.ready}</td>
                      <td className="px-4 py-3">{queue.processing}</td>
                      <td className="px-4 py-3">{queue.retry}</td>
                      <td className="px-4 py-3">{queue.dead + queue.corrupt}</td>
                      <td className="px-4 py-3">{duration(queue.oldest_ready_seconds)}</td>
                    </tr>
                  )) : (
                    <tr><td className="px-6 py-6 text-[var(--color-text-secondary)]" colSpan={6}>当前没有活跃队列任务。</td></tr>
                  )}
                </tbody>
              </table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <h2 className="font-semibold text-[var(--ink)]">Trace 链路查询</h2>
              <p className="mt-1 text-xs text-[var(--color-text-secondary)]">输入前端/后端日志中的 trace_id，关联 Outbox、Redis Task 与答题 Projection 回执。</p>
            </CardHeader>
            <CardContent className="space-y-4">
              <form
                className="flex flex-col gap-2 sm:flex-row"
                onSubmit={(event) => {
                  event.preventDefault();
                  const value = traceInput.trim();
                  if (value) setTraceId(value);
                }}
              >
                <Input value={traceInput} onChange={(event) => setTraceInput(event.target.value)} placeholder="例如 tr_a1b2c3d4e5f6" />
                <Button type="submit"><Search className="mr-2 h-4 w-4" />查询</Button>
              </form>

              {traceQuery.isFetching ? <p className="text-sm text-[var(--color-text-secondary)]">正在查询链路...</p> : null}
              {traceQuery.isError ? <p className="text-sm text-[var(--color-danger)]">Trace 查询失败，请确认 ID 格式和服务状态。</p> : null}
              {traceQuery.data && traceQuery.data.items.length === 0 ? <p className="text-sm text-[var(--color-text-secondary)]">最近 Outbox 记录中未找到该 Trace。</p> : null}
              {traceQuery.data?.items.map((item) => (
                <div key={item.outbox_id} className="rounded-2xl border border-[var(--color-border)] bg-white/60 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-[var(--ink)]">{item.task_id}</span>
                    <StatusBadge tone={queueStatusTone(item.queue?.status || item.outbox_status)}>{item.queue?.status || item.outbox_status}</StatusBadge>
                    <span className="text-xs text-[var(--color-text-hint)]">{item.task_type}</span>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-[var(--color-text-secondary)] md:grid-cols-2 xl:grid-cols-4">
                    <span>Request: <code>{item.request_id || "—"}</code></span>
                    <span>Outbox: {item.outbox_status} / retry {item.outbox_retry_count}</span>
                    <span>Redis: {item.queue?.status || "记录不存在"}</span>
                    <span>Projection: {item.practice_record_id ? (item.projection_receipt_at ? "已完成" : "未见回执") : "不适用"}</span>
                  </div>
                  {(item.outbox_error || item.queue?.last_error) ? (
                    <p className="mt-3 break-words rounded-xl bg-[var(--color-bg-input)] px-3 py-2 font-mono text-xs text-[var(--color-text-secondary)]">
                      {item.outbox_error || item.queue?.last_error}
                    </p>
                  ) : null}
                </div>
              ))}
            </CardContent>
          </Card>

          {data.outbox.recent_failures.length > 0 ? (
            <Card>
              <CardHeader><h2 className="font-semibold text-[var(--ink)]">最近 Outbox 永久失败</h2></CardHeader>
              <CardContent className="space-y-3">
                {data.outbox.recent_failures.map((failure) => (
                  <div key={failure.outbox_id} className="rounded-2xl border border-[var(--color-border)] bg-white/60 p-4 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge tone="danger">failed</StatusBadge>
                      <code className="text-xs font-semibold text-[var(--ink)]">{failure.task_id}</code>
                      <span className="text-xs text-[var(--color-text-hint)]">retry={failure.retry_count}</span>
                    </div>
                    <p className="mt-2 break-words text-xs text-[var(--color-text-secondary)]">{failure.last_error || "无失败摘要"}</p>
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      {failure.trace_id ? (
                        <button className="text-xs font-semibold text-[var(--color-primary)] hover:underline" onClick={() => { setTraceInput(failure.trace_id || ""); setTraceId(failure.trace_id || ""); }}>
                          查看 Trace {failure.trace_id}
                        </button>
                      ) : null}
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={retryOutbox.isPending}
                        onClick={() => retryOutbox.mutate(failure.outbox_id)}
                      >
                        重新发布
                      </Button>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
