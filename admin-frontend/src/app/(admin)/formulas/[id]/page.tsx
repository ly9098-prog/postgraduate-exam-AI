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
import { FormulaEditWorkbench } from "@/components/formulas/formula-edit-workbench";
import { FormulaGraphAssetPanel } from "@/components/formulas/formula-graph-asset-panel";
import { FormulaGraphSpecPanel } from "@/components/formulas/formula-graph-spec-panel";
import { FunctionPropertiesPanel } from "@/components/formulas/function-properties-panel";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest } from "@/lib/api/client";
import type { FormulaGraphAsset } from "@/lib/api/types";
import { decodeApiText, normalizeLatexExpression } from "@/lib/math-text";
import Link from "next/link";

/* ── Structured content renderers for JSON-encoded fields ── */

function parseJsonValue(raw: string): unknown {
  let value: unknown = raw;
  for (let i = 0; i < 3 && typeof value === "string"; i += 1) {
    const text = value.trim();
    if (!text) return value;
    try {
      value = JSON.parse(text);
    } catch {
      return value;
    }
  }
  return value;
}

function MathAwareText({ text }: { text: unknown }) {
  return <MixedLatexRenderer text={decodeApiText(text)} />;
}

function renderJsonStringArray(raw: string | null | undefined) {
  if (!raw) return null;
  const parsed = parseJsonValue(raw);
  if (!Array.isArray(parsed)) return <MathAwareText text={raw} />;

  return (
    <ul className="list-disc space-y-1.5 pl-4">
      {parsed.map((item, index) => (
        <li key={index}><MathAwareText text={item} /></li>
      ))}
    </ul>
  );
}

function renderSymbolNotes(raw: string | null | undefined) {
  if (!raw) return null;
  const parsed = parseJsonValue(raw);
  if (!Array.isArray(parsed)) return <MathAwareText text={raw} />;

  return (
    <ul className="list-none space-y-1.5">
      {parsed.map((item, index) => {
        const record = typeof item === "object" && item !== null
          ? item as Record<string, unknown>
          : null;
        const symbol = typeof item === "string" ? item : record?.symbol ?? "";
        const note = record?.note ?? "";
        return (
          <li key={index}>
            <MathAwareText text={symbol} />
            {Boolean(note) && (
              <span className="ml-2 text-[var(--color-text-secondary)]">
                — <MathAwareText text={note} />
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function renderStructuredConditions(raw: string | null | undefined) {
  if (!raw) return null;
  const parsed = parseJsonValue(raw);
  if (!Array.isArray(parsed)) return <MathAwareText text={raw} />;

  return (
    <ul className="list-none space-y-1.5">
      {parsed.map((item, index) => {
        const record = typeof item === "object" && item !== null
          ? item as Record<string, unknown>
          : null;
        const expression = typeof item === "string" ? item : record?.expression ?? "";
        const note = record?.note ?? "";
        return (
          <li key={index}>
            <MathAwareText text={expression} />
            {Boolean(note) && (
              <span className="ml-2 text-[var(--color-text-secondary)]">
                — <MathAwareText text={note} />
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function renderStructuredErrorTips(raw: string | null | undefined) {
  if (!raw) return null;
  const parsed = parseJsonValue(raw);
  if (!Array.isArray(parsed)) return <MathAwareText text={raw} />;

  return (
    <ul className="list-disc space-y-1 pl-4">
      {parsed.map((item, index) => (
        <li key={index}><MathAwareText text={item} /></li>
      ))}
    </ul>
  );
}

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
  card_type: string;
  is_function_graph: boolean;
  function_properties: Record<string, unknown> | null;
  graph_asset: import("@/lib/api/types").FormulaGraphAsset | null;
  graph_assets: import("@/lib/api/types").FormulaGraphAsset[];
  graph_spec: import("@/lib/api/types").GraphSpec | null;
  draft_graph_spec: import("@/lib/api/types").GraphSpec | null;
  graph_status: string;
  graph_last_error: string | null;
  graph_generated_at: string | null;
  graph_confirmed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  updated_by: number | null;
};

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-gray-50 text-gray-600 border-gray-200",
  pending_review: "bg-amber-50 text-amber-700 border-amber-200",
  rejected: "bg-red-50 text-red-700 border-red-200",
  published: "bg-emerald-50 text-emerald-700 border-emerald-200",
  offline: "bg-slate-50 text-slate-600 border-slate-200",
};
const STATUS_LABEL: Record<string, string> = {
  draft: "草稿", pending_review: "待审核",
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
      if (result.new_status === "published") {
        setMessage("审核通过，公式已自动发布。");
      } else {
        setMessage(`状态已更新为「${STATUS_LABEL[result.new_status] || result.new_status}」`);
      }
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

  // Editors land directly in the Scheme C workbench. The previous read-only
  // detail page created a redundant second “编辑” click between the list and
  // the actual editor. Users without update permission still receive the
  // read-only detail view below.
  if (canUpdate) {
    return (
      <FormulaEditWorkbench
        cardId={cardId}
        initialData={{
          categoryId: card.category_id,
          title: card.title,
          aliases: card.aliases,
          summary: card.summary,
          conditions: card.conditions,
          symbolNotes: card.symbol_notes,
          secondaryConclusions: card.secondary_conclusions,
          errorTips: card.error_tips,
          tags: card.tags || [],
          blocks: card.formula_blocks?.length ? card.formula_blocks : [{ latex: "" }],
          examples: card.examples,
          sortOrder: card.sort_order || 0,
          cardType: card.card_type || "auto",
          functionProperties: card.function_properties ?? null,
          status: card.status,
          version: card.version,
          publishedAt: card.published_at,
          createdAt: card.created_at,
          updatedAt: card.updated_at,
          updatedBy: card.updated_by,
        }}
        onClose={() => router.push("/formulas")}
        onSaved={() => {
          queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
          queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
        }}
      />
    );
  }

  // ── Readonly Detail View (no formula:update permission) ──
  return (
    <div className="space-y-6 px-4 py-6 pb-24 lg:px-8">
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
                  <h3 className="font-display text-2xl font-bold text-[var(--ink)]"><MathAwareText text={card.title} /></h3>
                  <span className={`inline-flex items-center gap-1 rounded-xl border px-3 py-1 text-xs font-semibold ${STATUS_BADGE[card.status] || ""}`}>
                    {STATUS_LABEL[card.status] || card.status}
                  </span>
                  {card.card_type === "function_graph" && (
                    <span className="inline-flex items-center gap-1 rounded-xl border border-[var(--color-primary-light)] bg-[var(--color-primary-light)]/50 px-3 py-1 text-xs font-semibold text-[var(--color-primary-dark)]">
                      函数图像
                    </span>
                  )}
                  {card.card_type === "auto" && card.is_function_graph && (
                    <span className="inline-flex items-center gap-1 rounded-xl border border-[var(--color-primary-light)] bg-[var(--color-primary-light)]/25 px-3 py-1 text-xs font-semibold text-[var(--color-primary-dark)]">
                      公式 + 函数图像
                    </span>
                  )}
                  {card.card_type === "function_graph" && !card.graph_asset && (
                    <span className="inline-flex items-center gap-1 rounded-xl border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                      缺少图像
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                  #{card.id} · v{card.version}
                  {card.published_at ? ` · 发布于 ${new Date(card.published_at).toLocaleDateString()}` : ""}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
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
                <div className="text-sm leading-6 text-[var(--color-text-secondary)]">
                  <MathAwareText text={card.summary} />
                </div>
              </section>
            )}

            {/* Formula blocks */}
            <section className="rounded-[1.6rem] border bg-white/80 p-5">
              <p className="font-semibold text-[var(--ink)]">公式块</p>
              <div className="mt-3 space-y-4">
                {card.formula_blocks?.map((block, i) => (
                  <div key={i} className="rounded-xl border bg-white p-4">
                    {block.label && <p className="mb-1 text-xs font-semibold text-[var(--color-text-hint)]">{block.label}</p>}
                    <LatexRenderer latex={normalizeLatexExpression(block.latex)} displayMode={true} />
                    {block.note && <div className="mt-1 text-xs text-[var(--color-text-secondary)]"><MathAwareText text={block.note} /></div>}
                  </div>
                ))}
              </div>
            </section>

            {card.conditions && (
              <section className="rounded-[1.6rem] border border-amber-200 bg-amber-50/60 p-4">
                <p className="font-semibold text-amber-800">适用条件</p>
                <div className="mt-2 text-sm text-amber-900 whitespace-pre-wrap break-words max-w-full overflow-x-auto">
                  {renderStructuredConditions(card.conditions)}
                </div>
              </section>
            )}

            {card.secondary_conclusions && (
              <section className="rounded-[1.6rem] border bg-white/80 p-4">
                <p className="font-semibold text-[var(--ink)]">二级结论</p>
                <div className="mt-2 space-y-2 text-sm text-[var(--color-text-secondary)] break-words max-w-full overflow-x-auto">
                  {renderJsonStringArray(card.secondary_conclusions)}
                </div>
              </section>
            )}

            {/* Function graph asset & properties */}
            {card.card_type !== "pure_formula" && (
              <>
                {(card.card_type === "function_graph" || card.graph_asset) && (
                  <FormulaGraphAssetPanel cardId={card.id} canUpdate={canUpdate} />
                )}
                {canUpdate && card.card_type !== "pure_formula" && (
                  <FormulaGraphSpecPanel
                    cardId={card.id}
                    cardVersion={card.version}
                    initialSpec={card.graph_spec || card.draft_graph_spec}
                    initialStatus={card.graph_status}
                    canUpdate={canUpdate}
                    graphLastError={card.graph_last_error}
                    graphGeneratedAt={card.graph_generated_at}
                    graphConfirmedAt={card.graph_confirmed_at}
                  />
                )}
                {!canUpdate && card.card_type !== "pure_formula" && (
                  <FormulaGraphSpecPanel
                    cardId={card.id}
                    cardVersion={card.version}
                    initialSpec={card.graph_spec || card.draft_graph_spec}
                    initialStatus={card.graph_status}
                    canUpdate={false}
                    graphLastError={card.graph_last_error}
                    graphGeneratedAt={card.graph_generated_at}
                    graphConfirmedAt={card.graph_confirmed_at}
                  />
                )}
                {card.function_properties && (
                  <FunctionPropertiesPanel properties={card.function_properties} />
                )}
              </>
            )}

            {card.symbol_notes && (
              <section className="rounded-[1.6rem] border bg-white/80 p-4">
                <p className="font-semibold text-[var(--ink)]">符号说明</p>
                <div className="mt-2 text-sm text-[var(--color-text-secondary)]">
                  {renderSymbolNotes(card.symbol_notes)}
                </div>
              </section>
            )}

            {card.error_tips && (
              <section className="rounded-[1.6rem] border border-red-200 bg-red-50/60 p-4">
                <p className="font-semibold text-red-700">易错提醒</p>
                <div className="mt-2 text-sm leading-6 text-red-800 whitespace-pre-wrap break-words max-w-full overflow-x-auto">
                  {renderStructuredErrorTips(card.error_tips)}
                </div>
              </section>
            )}

            {card.examples && card.examples.length > 0 && (
              <section className="rounded-[1.6rem] border bg-white/70 p-5">
                <p className="font-semibold text-[var(--ink)]">例题</p>
                <div className="mt-3 space-y-4">
                  {card.examples.map((ex, i) => (
                    <div key={i} className="rounded-xl border bg-white p-4">
                      <p className="font-semibold text-[var(--ink)]">题目：<MathAwareText text={ex.question} /></p>
                      <p className="mt-1 text-sm text-[var(--color-text-secondary)]">解法：<MathAwareText text={ex.short_solution} /></p>
                      <p className="mt-1 text-sm font-semibold text-[var(--color-success)]">答案：<MathAwareText text={ex.answer} /></p>
                      {ex.error_tip && <p className="mt-1 text-sm text-red-600">注意：<MathAwareText text={ex.error_tip} /></p>}
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
                    <Button onClick={() => setConfirmAction("approve")}>
                      <CheckCircle className="h-4 w-4" /> 通过并发布
                    </Button>
                    <Button variant="danger" onClick={() => setConfirmAction("rejected")}>
                      <XCircle className="h-4 w-4" /> 驳回
                    </Button>
                  </>
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
        title={confirmAction === "rejected" ? "驳回公式" :
               confirmAction === "approve" ? "通过并发布" : "确认操作"}
        description={
          confirmAction === "rejected"
            ? "请填写驳回原因"
            : confirmAction === "approve"
            ? "审核通过后该公式将立即发布。"
            : `确认执行此操作？`
        }
        confirmText={confirmAction === "rejected" ? "驳回" :
                     confirmAction === "approve" ? "通过并发布" : "确认"}
        danger={confirmAction === "rejected" || confirmAction === "offline"}
        loading={reviewMutation.isPending}
        onCancel={() => { setConfirmAction(null); setReviewReason(""); }}
        onConfirm={() => {
          if (!confirmAction) return;
          const actionMap: Record<string, string> = {
            approve: "approve", rejected: "reject",
            published: "publish", offline: "offline", draft: "restore", pending_review: "approve",
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
