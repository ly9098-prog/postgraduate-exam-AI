"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Filter, Search } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { AuditLog, PaginatedResponse } from "@/lib/api/types";

const severityOptions = ["", "critical", "important", "normal", "low"];
const statusOptions = ["", "success", "failed"];

const formatDate = (dateStr: string | null | undefined) => {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

const toneMap: Record<string, "danger" | "warning" | "primary" | "neutral"> = {
  critical: "danger",
  important: "warning",
  normal: "primary",
  low: "neutral",
};

export default function AuditLogsPage() {
  const [keyword, setKeyword] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [detailId, setDetailId] = useState<number | null>(null);

  const queryParams = useMemo(
    () => ({
      page,
      pageSize: 20,
      keyword,
      severity,
      status,
      resourceType: resourceType,
      from: dateFrom,
      to: dateTo,
    }),
    [page, keyword, severity, status, resourceType, dateFrom, dateTo],
  );

  const logs = useQuery({
    queryKey: ["audit-logs", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<AuditLog>>(`/audit-logs${toQuery(queryParams)}`),
    retry: false,
  });

  const detail = useQuery({
    queryKey: ["audit-logs", detailId],
    queryFn: () => apiRequest<AuditLog>(`/audit-logs/${detailId}`),
    enabled: detailId !== null,
    retry: false,
  });

  const renderDetail = (value: unknown) => {
    if (value === undefined || value === null || value === "") return "—";
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
    return JSON.stringify(value, null, 2);
  };

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">Audit Logs</p>
        <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">审计日志</h2>
      </div>
      <Card className="overflow-hidden">
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">日志列表</h3>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">支持多维过滤、单条详情查看、JSON 原文展开。</p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => { setSeverity(""); setStatus(""); setResourceType(""); setKeyword(""); setDateFrom(""); setDateTo(""); setPage(1); }}>
              <Filter className="h-4 w-4" />
              重置
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <label className="relative xl:col-span-2">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input className="pl-9" placeholder="搜索动作 / 资源" value={keyword} onChange={(event) => { setKeyword(event.target.value); setPage(1); }} />
            </label>
            <select className="h-11 w-full min-w-0 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={severity} onChange={(event) => { setSeverity(event.target.value); setPage(1); }}>
              {severityOptions.map((s) => (
                <option key={s || "all"} value={s}>{s || "全部级别"}</option>
              ))}
            </select>
            <select className="h-11 w-full min-w-0 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
              {statusOptions.map((s) => (
                <option key={s || "all"} value={s}>{s || "全部状态"}</option>
              ))}
            </select>
            <Input placeholder="资源类型" value={resourceType} onChange={(event) => { setResourceType(event.target.value); setPage(1); }} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">日期范围</span>
            <Input className="min-w-0 flex-1 sm:flex-none sm:w-44" type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setPage(1); }} />
            <span className="text-[var(--color-text-hint)]">—</span>
            <Input className="min-w-0 flex-1 sm:flex-none sm:w-44" type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setPage(1); }} />
          </div>
          <div className="space-y-3">
            {logs.data?.items?.map((log) => (
              <button key={log.id} className="w-full rounded-2xl border border-[var(--color-border)] bg-white/70 p-4 text-left transition hover:border-[var(--color-primary)] hover:bg-white hover:shadow-sm" onClick={() => setDetailId(log.id)}>
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge tone={toneMap[log.severity] ?? "neutral"}>{log.severity}</StatusBadge>
                  <StatusBadge tone={log.status === "failed" ? "danger" : log.status === "success" ? "success" : "neutral"}>{log.status ?? "—"}</StatusBadge>
                  <span className="text-sm font-semibold text-[var(--ink)]">{log.action}</span>
                  <span className="text-xs text-[var(--color-text-hint)]">by {log.operator_name ?? log.operator_id ?? "system"}</span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-4 text-sm text-[var(--color-text-secondary)]">
                  <span>{log.resource_type || "resource"} {log.resource_id ? `#${log.resource_id}` : ""}</span>
                  <span>{log.ip || ""}</span>
                  <span>{formatDate(log.created_at)}</span>
                </div>
                {log.error_message ? (
                  <p className="mt-2 rounded-2xl bg-[var(--color-danger-light)] px-3 py-2 text-xs text-[var(--color-danger)]">{log.error_message}</p>
                ) : null}
              </button>
            ))}
          </div>
          {logs.isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="animate-pulse rounded-2xl border border-[var(--color-border)] bg-white/70 p-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="h-5 w-16 rounded-full bg-[var(--color-border)]" />
                    <div className="h-5 w-14 rounded-full bg-[var(--color-border)]" />
                    <div className="h-4 w-32 rounded bg-[var(--color-border)]" />
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-4">
                    <div className="h-3 w-24 rounded bg-[var(--color-border)]" />
                    <div className="h-3 w-36 rounded bg-[var(--color-border)]" />
                  </div>
                </div>
              ))}
            </div>
          ) : (logs.data?.items?.length ?? 0) === 0 ? (
            <p className="py-10 text-center text-sm text-[var(--color-text-hint)]">暂无审计日志</p>
          ) : null}
          <div className="mt-4 flex items-center justify-between text-sm text-[var(--color-text-secondary)]">
            <span>共 {logs.data?.total ?? 0} 条</span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</Button>
              <Button variant="secondary" disabled={page >= (logs.data?.total_pages ?? 1)} onClick={() => setPage((value) => value + 1)}>下一页</Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {detailId !== null ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.28)]" onClick={() => setDetailId(null)}>
          <aside className="h-full w-full max-w-2xl overflow-y-auto bg-white p-6 shadow-[var(--shadow-floating)]" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">审计日志详情</h3>
              <Button variant="ghost" onClick={() => setDetailId(null)}>关闭</Button>
            </div>
            <div className="mt-6 space-y-4 text-sm">
              {detail.data ? (
                <>
                  {[["动作", detail.data.action], ["资源类型", detail.data.resource_type], ["资源ID", detail.data.resource_id], ["级别", detail.data.severity], ["状态", detail.data.status], ["操作人", detail.data.operator_name ?? detail.data.operator_id], ["IP", detail.data.ip], ["UA", detail.data.user_agent], ["错误", detail.data.error_message], ["详情 JSON", renderDetail(detail.data.detail)]].map(([label, value]) => (
                    <section key={String(label)} className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                      <p className="font-semibold text-[var(--ink)]">{label}</p>
                      <pre className="mt-2 whitespace-pre-wrap font-sans text-[var(--color-text-secondary)]">{renderDetail(value)}</pre>
                    </section>
                  ))}
                </>
              ) : (
                <p className="text-sm text-[var(--color-text-secondary)]">正在加载详情...</p>
              )}
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
