"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useParams } from "next/navigation";
import { Trash2, ArrowLeft, Eye, EyeOff, Send, CheckCircle, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { LatexRenderer } from "@/components/ui/latex-renderer";
import { MixedLatexRenderer } from "@/components/ui/mixed-latex-renderer";
import { FormulaEditorForm } from "@/components/formulas/formula-editor-form";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest } from "@/lib/api/client";
import Link from "next/link";

type FormulaCard = {
  id: number; title: string; category_id: number; summary: string | null;
  formula_blocks: Array<{ label?: string | null; latex: string; note?: string | null }>;
  conditions: string | null; symbol_notes: string | null;
  secondary_conclusions: string | null; error_tips: string | null;
  examples: Array<{ question: string; short_solution: string; answer: string; error_tip?: string | null }> | null;
  status: string; tags: Array<{ id: number; code: string; name: string }>;
  version: number; published_at: string | null;
  rejection_reason: string | null; aliases: string[] | null;
  sort_order: number;
};

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-gray-50 text-gray-600 border-gray-200",
  pending_review: "bg-amber-50 text-amber-700 border-amber-200",
  approved: "bg-green-50 text-green-700 border-green-200",
  rejected: "bg-red-50 text-red-700 border-red-200",
  published: "bg-emerald-50 text-emerald-700 border-emerald-200",
  offline: "bg-slate-50 text-slate-600 border-slate-200",
};
const STATUS_LABEL: Record<string, string> = {
  draft: "草稿", pending_review: "待审核", approved: "已通过",
  rejected: "已驳回", published: "已发布", offline: "已下架",
};

export default function EditFormulaPage() {
  const router = useRouter();
  const params = useParams();
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const cardId = Number(params.id);

  const canUpdate = hasPermission(permissions, "formula:update");
  const canReview = hasPermission(permissions, "formula:review");
  const canDelete = hasPermission(permissions, "formula:delete");

  const [isEditing, setIsEditing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<string | null>(null);
  const [reviewReason, setReviewReason] = useState("");

  const { data: card, isLoading } = useQuery({
    queryKey: ["admin-formulas", cardId],
    queryFn: () => apiRequest<FormulaCard>(`/formulas/${cardId}`),
    enabled: !!cardId,
  });

  // Review action
  const reviewMutation = useMutation({
    mutationFn: async ({ action, reason }: { action: string; reason?: string }) => {
      const body: Record<string, unknown> = { action };
      if (reason) body.rejection_reason = reason;
      return apiRequest<{ new_status: string }>(`/formulas/${cardId}/review`, {
        method: "POST", body: JSON.stringify(body),
      });
    },
    onSuccess: (result) => {
      setMessage(`状态已更新为「${STATUS_LABEL[result.new_status] || result.new_status}」`);
      setConfirmAction(null);
      setReviewReason("");
      queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "操作失败"),
  });

  // Delete
  const deleteMutation = useMutation({
    mutationFn: () => apiRequest(`/formulas/${cardId}`, { method: "DELETE" }),
    onSuccess: () => {
      setMessage("已删除");
      setTimeout(() => router.push("/formulas"), 1000);
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "删除失败"),
  });

  if (isLoading) {
    return <div className="flex items-center justify-center p-12 text-sm text-[var(--color-text-secondary)]">加载中...</div>;
  }

  if (!card) {
    return <div className="p-12 text-sm">公式未找到</div>;
  }

  // If editing, show the shared form
  if (isEditing) {
    return (
      <FormulaEditorForm
        mode="edit"
        cardId={cardId}
        initialData={{
          categoryId: card.category_id,
          title: card.title,
          aliases: card.aliases?.join(", ") || "",
          summary: card.summary || "",
          conditions: card.conditions || "",
          symbolNotes: card.symbol_notes || "",
          secondaryConclusions: card.secondary_conclusions || "",
          errorTips: card.error_tips || "",
          selectedTags: card.tags?.map((t) => t.code) || [],
          blocks: card.formula_blocks?.length ? card.formula_blocks : [{ latex: "" }],
          examples: card.examples || [],
          sortOrder: card.sort_order || 0,
        }}
        onSaveSuccess={() => {
          setIsEditing(false);
          queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
          queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
        }}
      />
    );
  }

  // ── Readonly Detail View ──
  return (
    <div className="space-y-6 pb-24">
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link href="/formulas">
                <Button variant="ghost" size="sm">
                  <ArrowLeft className="h-4 w-4" />
                </Button>
              </Link>
              <div>
                <div className="flex items-center gap-3">
                  <h3 className="font-display text-2xl font-bold text-[var(--ink)]">{card.title}</h3>
                  <span className={`inline-flex items-center gap-1 rounded-xl border px-3 py-1 text-xs font-semibold ${STATUS_BADGE[card.status] || ""}`}>
                    {STATUS_LABEL[card.status] || card.status}
                  </span>
                </div>
                <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                  #{card.id} · v{card.version}
                  {card.published_at ? ` · 发布于 ${new Date(card.published_at).toLocaleDateString()}` : ""}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {canUpdate && (
                <Button variant="secondary" onClick={() => setIsEditing(true)}>编辑</Button>
              )}
              <Link href="/formulas">
                <Button variant="ghost">返回列表</Button>
              </Link>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {message ? (
            <div className={`rounded-2xl border px-4 py-3 text-sm font-medium ${
              message.includes("成功") ? "border-[var(--color-success)] bg-[var(--color-success-light)]" : "border-red-200 bg-red-50"
            }`}>
              {message}
              <button className="ml-3" onClick={() => setMessage(null)}>✕</button>
            </div>
          ) : null}

          <div className="space-y-5 text-sm">
            {/* Tags */}
            {card.tags?.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                {card.tags.map((t) => (
                  <span key={t.id} className="rounded-lg border bg-white/60 px-2 py-1 text-xs text-[var(--color-text-secondary)]">{t.name}</span>
                ))}
              </div>
            )}

            {/* Summary */}
            {card.summary && (
              <section className="rounded-[1.6rem] border border-[var(--color-primary-light)] bg-[var(--porcelain)] p-5">
                <p className="text-sm leading-6 text-[var(--color-text-secondary)]">{card.summary}</p>
              </section>
            )}

            {/* Formula blocks */}
            <section className="rounded-[1.6rem] border bg-white/80 p-5">
              <p className="font-semibold text-[var(--ink)]">公式块</p>
              <div className="mt-3 space-y-4">
                {card.formula_blocks?.map((block, i) => (
                  <div key={i} className="rounded-xl border bg-white p-4">
                    {block.label && <p className="mb-1 text-xs font-semibold text-[var(--color-text-hint)]">{block.label}</p>}
                    <LatexRenderer latex={block.latex} displayMode={true} />
                    {block.note && <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{block.note}</p>}
                  </div>
                ))}
              </div>
            </section>

            {card.conditions && (
              <section className="rounded-[1.6rem] border border-amber-200 bg-amber-50/60 p-4">
                <p className="font-semibold text-amber-800">适用条件</p>
                <div className="mt-2 text-sm text-amber-900">
                  <MixedLatexRenderer text={card.conditions} />
                </div>
              </section>
            )}

            {card.symbol_notes && (
              <section className="rounded-[1.6rem] border bg-white/80 p-4">
                <p className="font-semibold text-[var(--ink)]">符号说明</p>
                <p className="mt-2 text-sm text-[var(--color-text-secondary)]">{card.symbol_notes}</p>
              </section>
            )}

            {card.error_tips && (
              <section className="rounded-[1.6rem] border border-red-200 bg-red-50/60 p-4">
                <p className="font-semibold text-red-700">易错提醒</p>
                <div className="mt-2 text-sm leading-6 text-red-800">
                  <MixedLatexRenderer text={card.error_tips} />
                </div>
              </section>
            )}

            {card.examples && card.examples.length > 0 && (
              <section className="rounded-[1.6rem] border bg-white/70 p-5">
                <p className="font-semibold text-[var(--ink)]">例题</p>
                <div className="mt-3 space-y-4">
                  {card.examples.map((ex, i) => (
                    <div key={i} className="rounded-xl border bg-white p-4">
                      <p className="font-semibold text-[var(--ink)]">题目：{ex.question}</p>
                      <p className="mt-1 text-sm text-[var(--color-text-secondary)]">解法：{ex.short_solution}</p>
                      <p className="mt-1 text-sm font-semibold text-[var(--color-success)]">答案：{ex.answer}</p>
                      {ex.error_tip && <p className="mt-1 text-sm text-red-600">注意：{ex.error_tip}</p>}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Rejection reason */}
            {card.status === "rejected" && card.rejection_reason && (
              <section className="rounded-[1.6rem] border border-red-200 bg-red-50/50 p-4">
                <p className="font-semibold text-red-700">驳回原因</p>
                <p className="mt-2 text-sm text-red-800">{card.rejection_reason}</p>
              </section>
            )}

            {/* State machine actions */}
            {canReview && (
              <div className="flex flex-wrap gap-2 border-t pt-4">
                {card.status === "draft" && (
                  <Button onClick={() => setConfirmAction("pending_review")}>
                    <Send className="h-4 w-4" /> 提交审核
                  </Button>
                )}
                {card.status === "pending_review" && (
                  <>
                    <Button onClick={() => setConfirmAction("approved")}>
                      <CheckCircle className="h-4 w-4" /> 通过
                    </Button>
                    <Button variant="danger" onClick={() => setConfirmAction("rejected")}>
                      <XCircle className="h-4 w-4" /> 驳回
                    </Button>
                  </>
                )}
                {card.status === "approved" && (
                  <Button onClick={() => setConfirmAction("published")}>
                    <Eye className="h-4 w-4" /> 发布
                  </Button>
                )}
                {card.status === "published" && (
                  <Button variant="secondary" onClick={() => setConfirmAction("offline")}>
                    <EyeOff className="h-4 w-4" /> 下架
                  </Button>
                )}
                {card.status === "rejected" && (
                  <Button variant="secondary" onClick={() => setConfirmAction("draft")}>
                    <Send className="h-4 w-4" /> 重新提交
                  </Button>
                )}
                {card.status === "offline" && (
                  <Button onClick={() => setConfirmAction("published")}>
                    <Eye className="h-4 w-4" /> 重新发布
                  </Button>
                )}
              </div>
            )}

            {/* Delete */}
            {canDelete && card.status !== "published" && (
              <div className="flex gap-2 border-t pt-4">
                <Button variant="danger" onClick={() => { if (confirm("确认删除？")) deleteMutation.mutate(); }}>
                  <Trash2 className="h-4 w-4" /> 删除
                </Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmAction !== null}
        title={confirmAction === "rejected" ? "驳回公式" : "确认操作"}
        description={
          confirmAction === "rejected"
            ? "请填写驳回原因"
            : `确认执行「${STATUS_LABEL[confirmAction || ""] || confirmAction}」操作？`
        }
        confirmText={confirmAction === "rejected" ? "驳回" : "确认"}
        danger={confirmAction === "rejected" || confirmAction === "offline"}
        loading={reviewMutation.isPending}
        onCancel={() => { setConfirmAction(null); setReviewReason(""); }}
        onConfirm={() => {
          if (!confirmAction) return;
          const actionMap: Record<string, string> = {
            pending_review: "approve", approved: "approve", rejected: "reject",
            published: "publish", offline: "offline", draft: "restore",
          };
          reviewMutation.mutate({
            action: actionMap[confirmAction] || confirmAction,
            reason: confirmAction === "rejected" ? reviewReason : undefined,
          });
        }}
      >
        {confirmAction === "rejected" && (
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
