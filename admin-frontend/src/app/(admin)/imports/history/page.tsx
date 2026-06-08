"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, RefreshCw, Send, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { ImportBatchDetail, ImportBatchListItem, ImportDeleteResponse, ImportPublishResponse, PaginatedResponse } from "@/lib/api/types";

type ConfirmState =
  | { action: "publish"; batchId: string }
  | { action: "delete"; batchId: string }
  | null;

function statusTone(count: number) {
  return count > 0 ? "warning" : "neutral";
}

export default function ImportHistoryPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const batchIdParam = searchParams.get("batch_id") || "";
  const [filters, setFilters] = useState({ status: "", source_type: "" });
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);

  const queryParams = useMemo(
    () => ({ page: 1, page_size: 30, batch_id: batchIdParam, status: filters.status, source_type: filters.source_type }),
    [batchIdParam, filters],
  );

  const batches = useQuery({
    queryKey: ["import-batches", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<ImportBatchListItem>>(`/imports${toQuery(queryParams)}`),
    retry: false,
  });

  const detail = useQuery({
    queryKey: ["import-batches", selectedBatchId, "detail"],
    queryFn: () => apiRequest<ImportBatchDetail>(`/imports/${selectedBatchId}${toQuery({ page: 1, page_size: 50 })}`),
    enabled: selectedBatchId !== null,
    retry: false,
  });

  const actionMutation = useMutation({
    mutationFn: async (state: Exclude<ConfirmState, null>) => {
      if (state.action === "publish") return apiRequest<ImportPublishResponse>(`/imports/${state.batchId}/publish`, { method: "POST" });
      return apiRequest<ImportDeleteResponse>(`/imports/${state.batchId}`, { method: "DELETE" });
    },
    onSuccess: (result, variables) => {
      if (variables.action === "publish") {
        const published = "published" in result ? result.published : 0;
        setMessage(`批次 ${variables.batchId} 发布完成，已发布 ${published} 题。`);
      } else {
        const deleted = "deleted_count" in result ? result.deleted_count : 0;
        setMessage(`批次 ${variables.batchId} 已删除，删除 ${deleted} 条记录。`);
        if (selectedBatchId === variables.batchId) setSelectedBatchId(null);
      }
      setConfirmState(null);
      queryClient.invalidateQueries({ queryKey: ["import-batches"] });
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
    },
  });

  const items = batches.data?.items ?? [];
  const selectedBatch = detail.data;

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">导入记录</h3>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">查看批次统计，发布已通过题目，删除未发布批次。</p>
          </div>
          <Button variant="secondary" disabled={batches.isFetching} onClick={() => batches.refetch()}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {message ? <p className="rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">{message}</p> : null}
          <div className="grid gap-3 md:grid-cols-3">
            <Input placeholder="批次 ID" value={batchIdParam} readOnly />
            <select className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
              <option value="">全部状态</option>
              <option value="pending">pending</option>
              <option value="approved">approved</option>
              <option value="rejected">rejected</option>
              <option value="published">published</option>
            </select>
            <Input placeholder="来源类型" value={filters.source_type} onChange={(event) => updateFilter("source_type", event.target.value)} />
          </div>
          <div className="overflow-hidden rounded-3xl border border-[var(--color-border)] bg-white/70">
            <div className="grid grid-cols-[1.4fr_0.7fr_1.2fr_1.3fr_1.2fr] gap-3 border-b border-[var(--color-border)] px-4 py-3 text-xs font-semibold text-[var(--color-text-secondary)]">
              <span>批次</span>
              <span>来源</span>
              <span>统计</span>
              <span>时间</span>
              <span>操作</span>
            </div>
            {items.map((batch) => (
              <div key={batch.batch_id} className="grid grid-cols-[1.4fr_0.7fr_1.2fr_1.3fr_1.2fr] gap-3 border-b border-[var(--color-border)] px-4 py-4 text-sm last:border-b-0">
                <div className="min-w-0">
                  <p className="break-all font-mono text-xs font-semibold text-[var(--ink)]">{batch.batch_id}</p>
                  <p className="mt-1 truncate text-xs text-[var(--color-text-hint)]">{batch.source_file || "—"}</p>
                </div>
                <span className="text-[var(--color-text-secondary)]">{batch.source_type || "—"}</span>
                <div className="flex flex-wrap gap-1">
                  <StatusBadge tone="neutral">总 {batch.total_count}</StatusBadge>
                  <StatusBadge tone={statusTone(batch.pending_count)}>待审 {batch.pending_count}</StatusBadge>
                  <StatusBadge tone="success">通过 {batch.approved_count}</StatusBadge>
                  <StatusBadge tone="danger">拒绝 {batch.rejected_count}</StatusBadge>
                  <StatusBadge tone="primary">发布 {batch.published_count}</StatusBadge>
                </div>
                <div className="text-xs text-[var(--color-text-secondary)]">
                  <p>{batch.created_at || "—"}</p>
                  <p>{batch.updated_at || "—"}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="ghost" onClick={() => setSelectedBatchId(batch.batch_id)}>
                    <Eye className="h-4 w-4" />
                    查看
                  </Button>
                  <Button variant="secondary" disabled={batch.approved_count === 0} onClick={() => setConfirmState({ action: "publish", batchId: batch.batch_id })}>
                    <Send className="h-4 w-4" />
                    发布
                  </Button>
                  <Button variant="danger" disabled={batch.published_count > 0} onClick={() => setConfirmState({ action: "delete", batchId: batch.batch_id })}>
                    <Trash2 className="h-4 w-4" />
                    删除
                  </Button>
                </div>
              </div>
            ))}
          </div>
          {!batches.isLoading && items.length === 0 ? <p className="py-10 text-center text-sm text-[var(--color-text-hint)]">暂无导入记录</p> : null}
          {batches.isError ? <p className="text-sm text-[var(--color-danger)]">导入记录接口当前不可用。</p> : null}
        </CardContent>
      </Card>

      {selectedBatch ? (
        <Card>
          <CardHeader>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">批次详情</h3>
            <p className="mt-1 break-all text-sm text-[var(--color-text-secondary)]">{selectedBatch.batch_id}</p>
          </CardHeader>
          <CardContent className="space-y-3">
            {selectedBatch.items.map((item) => (
              <article key={item.id} className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <StatusBadge tone={item.status === "published" ? "primary" : item.status === "approved" ? "success" : item.status === "rejected" ? "danger" : "warning"}>{item.status}</StatusBadge>
                  <Link className="text-sm font-semibold text-[var(--color-primary-dark)] underline" href={`/imports/review?batch_id=${encodeURIComponent(item.batch_id)}`}>进入审核</Link>
                </div>
                <p className="mt-3 whitespace-pre-wrap text-sm font-semibold text-[var(--ink)]">{String(item.parsed_content?.text ?? item.parsed_content?.stem ?? item.raw_data?.text ?? `导入题目 #${item.id}`)}</p>
                <p className="mt-2 text-xs text-[var(--color-text-secondary)]">{item.subject || "未分类"} · {item.question_type || "未标注题型"}</p>
              </article>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmState !== null}
        title={confirmState?.action === "delete" ? "删除导入批次" : "发布导入批次"}
        description={confirmState?.action === "delete" ? "仅未发布且未关联正式题目的批次可删除，确认后不可恢复。" : "将发布该批次中已通过的题目到正式题库。"}
        confirmText={confirmState?.action === "delete" ? "删除" : "发布"}
        danger={confirmState?.action === "delete"}
        loading={actionMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => confirmState && actionMutation.mutate(confirmState)}
      />
    </div>
  );
}
