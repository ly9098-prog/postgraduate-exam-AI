"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle, XCircle, Eye, EyeOff, Send, Clock, Tag, Layers,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { PaginatedResponse } from "@/lib/api/types";
import Link from "next/link";

type FormulaCard = {
  id: number; title: string; summary: string | null; status: string;
  formula_blocks: Array<{ label?: string; latex: string }>;
  tags: Array<{ id: number; code: string; name: string }>;
  version: number; rejection_reason: string | null;
  updated_at: string;
};

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿", pending_review: "待审核", approved: "已通过",
  rejected: "已驳回", published: "已发布", offline: "已下架",
};

export default function FormulaReviewPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const canReview = hasPermission(permissions, "formula:review");

  const [message, setMessage] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState("pending_review");
  const [page, setPage] = useState(1);
  const [confirmAction, setConfirmAction] = useState<{
    cardId: number; title: string; action: string;
  } | null>(null);
  const [reviewReason, setReviewReason] = useState("");

  const queryParams = { page, page_size: 20, status: activeFilter };

  const { data, isLoading } = useQuery({
    queryKey: ["admin-formulas", "review", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<FormulaCard>>(
      `/formulas${toQuery(queryParams)}`,
    ),
    enabled: canReview,
  });

  const reviewMutation = useMutation({
    mutationFn: async ({ cardId, action, reason }: { cardId: number; action: string; reason?: string }) => {
      const body: Record<string, unknown> = { action };
      if (reason) body.rejection_reason = reason;
      return apiRequest(`/formulas/${cardId}/review`, {
        method: "POST", body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      setMessage("操作成功。");
      setConfirmAction(null);
      setReviewReason("");
      queryClient.invalidateQueries({ queryKey: ["admin-formulas", "review"] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "操作失败"),
  });

  const filters = [
    { label: "待审核", value: "pending_review" },
    { label: "已通过", value: "approved" },
    { label: "已驳回", value: "rejected" },
    { label: "草稿", value: "draft" },
  ];

  const items = data?.items ?? [];

  return (
    <div className="space-y-6 pb-24">
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">公式审核</h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">审核公式卡片，通过后发布或驳回</p>
            </div>
          </div>

          <div className="flex gap-2">
            {filters.map((f) => (
              <button
                key={f.value}
                onClick={() => { setActiveFilter(f.value); setPage(1); }}
                className={`inline-flex h-9 items-center gap-1.5 rounded-xl border px-4 text-sm font-medium transition ${
                  activeFilter === f.value
                    ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                    : "border-[var(--color-border)] bg-white/80 text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {message ? (
            <div className="rounded-2xl border border-[var(--color-success)] bg-[var(--color-success-light)] px-4 py-3 text-sm font-medium">
              {message}
              <button className="ml-3" onClick={() => setMessage(null)}>✕</button>
            </div>
          ) : null}

          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }, (_, i) => (
                <div key={i} className="h-28 animate-pulse rounded-[1.6rem] border bg-white/60" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-[1.6rem] border border-dashed bg-white/60 py-16 text-center">
              <CheckCircle className="h-12 w-12 text-[var(--color-text-hint)]" />
              <p className="text-sm font-semibold text-[var(--color-text-secondary)]">暂无{STATUS_LABEL[activeFilter] || activeFilter}公式</p>
            </div>
          ) : (
            items.map((card) => (
              <article
                key={card.id}
                className="group relative overflow-hidden rounded-[1.6rem] border bg-white/78 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
              >
                <span className="absolute left-0 top-0 h-full w-1 bg-[var(--color-primary)]" />
                <div className="p-4 pl-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        {card.tags?.map((t) => (
                          <span key={t.id} className="inline-flex items-center gap-1 rounded-md border bg-white/80 px-1.5 py-0.5 text-[11px] text-[var(--color-text-secondary)]">
                            <Tag className="h-3 w-3" />{t.name}
                          </span>
                        ))}
                      </div>
                      <Link href={`/formulas/${card.id}`} className="mt-2 block">
                        <h4 className="font-semibold text-[var(--ink)] hover:text-[var(--color-primary)]">{card.title}</h4>
                      </Link>
                      {card.summary && (
                        <p className="mt-1 line-clamp-2 text-sm text-[var(--color-text-secondary)]">{card.summary}</p>
                      )}
                      <div className="mt-2 flex items-center gap-4 text-[11px] text-[var(--color-text-hint)]">
                        <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" />#{card.id}</span>
                        <span className="inline-flex items-center gap-1"><Layers className="h-3 w-3" />{card.formula_blocks?.length || 0} 块</span>
                        <span>v{card.version}</span>
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      <Link href={`/formulas/${card.id}`}>
                        <Button variant="secondary" size="sm">
                          <Eye className="h-3.5 w-3.5" /> 详情
                        </Button>
                      </Link>
                      {activeFilter === "pending_review" && (
                        <>
                          <Button size="sm" onClick={() => setConfirmAction({ cardId: card.id, title: card.title, action: "approve" })}>
                            <CheckCircle className="h-3.5 w-3.5" /> 通过
                          </Button>
                          <Button variant="danger" size="sm" onClick={() => setConfirmAction({ cardId: card.id, title: card.title, action: "reject" })}>
                            <XCircle className="h-3.5 w-3.5" /> 驳回
                          </Button>
                        </>
                      )}
                      {activeFilter === "approved" && (
                        <Button size="sm" onClick={() => setConfirmAction({ cardId: card.id, title: card.title, action: "publish" })}>
                          <Eye className="h-3.5 w-3.5" /> 发布
                        </Button>
                      )}
                      {activeFilter === "rejected" && (
                        <Button variant="secondary" size="sm" onClick={() => setConfirmAction({ cardId: card.id, title: card.title, action: "restore" })}>
                          <Send className="h-3.5 w-3.5" /> 重新提交
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              </article>
            ))
          )}

          {data && data.total_pages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <button disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="inline-flex h-9 items-center gap-1 rounded-xl border px-3 text-xs font-semibold disabled:opacity-40"
              >上一页</button>
              <span className="text-xs text-[var(--color-text-secondary)]">{data.page} / {data.total_pages}</span>
              <button disabled={page >= data.total_pages} onClick={() => setPage((p) => p + 1)}
                className="inline-flex h-9 items-center gap-1 rounded-xl border px-3 text-xs font-semibold disabled:opacity-40"
              >下一页</button>
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmAction !== null}
        title={confirmAction?.action === "reject" ? "驳回公式" :
               confirmAction?.action === "publish" ? "发布公式" :
               confirmAction?.action === "restore" ? "重新提交" : "通过公式"}
        description={
          confirmAction?.action === "reject"
            ? `确认驳回「${confirmAction?.title}」？需要填写驳回原因。`
            : `确认对「${confirmAction?.title}」执行此操作？`
        }
        confirmText={confirmAction?.action === "reject" ? "驳回" : "确认"}
        danger={confirmAction?.action === "reject"}
        loading={reviewMutation.isPending}
        onCancel={() => { setConfirmAction(null); setReviewReason(""); }}
        onConfirm={() => {
          if (!confirmAction) return;
          const actionMap: Record<string, string> = {
            approve: "approve", reject: "reject", publish: "publish", restore: "restore",
          };
          reviewMutation.mutate({
            cardId: confirmAction.cardId,
            action: actionMap[confirmAction.action] || confirmAction.action,
            reason: confirmAction.action === "reject" ? reviewReason : undefined,
          });
        }}
      >
        {confirmAction?.action === "reject" && (
          <div className="mt-4">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">驳回原因 *</label>
            <textarea
              className="mt-1 min-h-20 w-full rounded-xl border bg-[var(--color-bg-input)] p-3 text-sm"
              placeholder="请填写驳回原因..."
              value={reviewReason}
              onChange={(e) => setReviewReason(e.target.value)}
            />
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
