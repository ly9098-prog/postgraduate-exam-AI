"use client";

import { useState, useMemo, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useParams } from "next/navigation";
import { Save, X, Trash2, Plus, ArrowLeft, Eye, EyeOff, Send, CheckCircle, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest } from "@/lib/api/client";
import Link from "next/link";

type FormulaCategory = {
  id: number; parent_id: number | null; code: string; name: string; node_type: string; children: FormulaCategory[];
};
type TagOption = { id: number; code: string; name: string };
type FormulaBlock = { label?: string | null; latex: string; note?: string | null };
type FormulaExample = { question: string; short_solution: string; answer: string; error_tip?: string | null };
type FormulaCard = {
  id: number; title: string; category_id: number; summary: string | null;
  formula_blocks: FormulaBlock[]; conditions: string | null; symbol_notes: string | null;
  secondary_conclusions: string | null; error_tips: string | null; examples: FormulaExample[] | null;
  status: string; tags: TagOption[]; version: number; published_at: string | null;
  rejection_reason: string | null; aliases: string[] | null; search_text: string | null;
  card_type: string; source_title: string | null; sort_order: number;
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
  draft: "草稿", pending_review: "待审核", approved: "已通过", rejected: "已驳回", published: "已发布", offline: "已下架",
};
const TAG_NAMES: Record<string, string> = {
  basic: "基础", high_frequency: "高频", error_prone: "易错", must_memorize: "必背",
};

function flattenCats(cats: FormulaCategory[], depth = 0): Array<{ id: number; label: string; depth: number }> {
  const result: Array<{ id: number; label: string; depth: number }> = [];
  for (const cat of cats) {
    result.push({ id: cat.id, label: "  ".repeat(depth) + cat.name, depth });
    if (cat.children?.length) result.push(...flattenCats(cat.children, depth + 1));
  }
  return result;
}

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

  // Form fields
  const [categoryId, setCategoryId] = useState(0);
  const [title, setTitle] = useState("");
  const [aliases, setAliases] = useState("");
  const [summary, setSummary] = useState("");
  const [conditions, setConditions] = useState("");
  const [symbolNotes, setSymbolNotes] = useState("");
  const [errorTips, setErrorTips] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [blocks, setBlocks] = useState<FormulaBlock[]>([{ latex: "" }]);
  const [examples, setExamples] = useState<FormulaExample[]>([]);
  const [sortOrder, setSortOrder] = useState(0);

  // Load card
  const { data: card, isLoading } = useQuery({
    queryKey: ["admin-formulas", cardId],
    queryFn: () => apiRequest<FormulaCard>(`/formulas/${cardId}`),
    enabled: !!cardId,
  });

  // Init form from card data
  useEffect(() => {
    if (!card) return;
    setCategoryId(card.category_id);
    setTitle(card.title);
    setAliases(card.aliases?.join(", ") || "");
    setSummary(card.summary || "");
    setConditions(card.conditions || "");
    setSymbolNotes(card.symbol_notes || "");
    setErrorTips(card.error_tips || "");
    setSelectedTags(card.tags?.map((t) => t.code) || []);
    setBlocks(card.formula_blocks?.length ? card.formula_blocks : [{ latex: "" }]);
    setExamples(card.examples || []);
    setSortOrder(card.sort_order || 0);
  }, [card]);

  // Load categories
  const categories = useQuery({
    queryKey: ["admin-formula-categories"],
    queryFn: () => apiRequest<{ items: FormulaCategory[] }>("/formulas/categories"),
    staleTime: 60000,
  });
  const flatCats = useMemo(() => flattenCats(categories.data?.items ?? []), [categories.data]);

  // Load tags
  const tags = useQuery({
    queryKey: ["admin-formula-tags"],
    queryFn: () => apiRequest<{ items: TagOption[] }>("/formulas/tags"),
    staleTime: 60000,
  });
  const tagMap = useMemo(() => {
    const m: Record<string, number> = {};
    tags.data?.items?.forEach((t) => { m[t.code] = t.id; });
    return m;
  }, [tags.data]);

  const toggleTag = (code: string) => {
    setSelectedTags((prev) => prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]);
  };

  const updateBlock = (i: number, field: keyof FormulaBlock, value: string) => {
    setBlocks((prev) => prev.map((b, idx) => (idx === i ? { ...b, [field]: value } : b)));
  };
  const addBlock = () => setBlocks((prev) => [...prev, { latex: "" }]);
  const removeBlock = (i: number) => {
    if (blocks.length <= 1) return;
    setBlocks((prev) => prev.filter((_, idx) => idx !== i));
  };

  const addExample = () => {
    if (examples.length >= 3) return;
    setExamples((prev) => [...prev, { question: "", short_solution: "", answer: "" }]);
  };
  const updateExample = (i: number, field: keyof FormulaExample, value: string) => {
    setExamples((prev) => prev.map((ex, idx) => (idx === i ? { ...ex, [field]: value } : ex)));
  };
  const removeExample = (i: number) => setExamples((prev) => prev.filter((_, idx) => idx !== i));

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: async () => {
      const validBlocks = blocks.filter((b) => b.latex.trim());
      if (validBlocks.length < 1) throw new Error("至少需要一个公式块");
      const tagIds = selectedTags.map((code) => tagMap[code]).filter(Boolean);
      const aliasesList = aliases.split(/[,，、\s]+/).filter(Boolean);

      return apiRequest(`/formulas/${cardId}`, {
        method: "PUT",
        body: JSON.stringify({
          category_id: categoryId,
          title: title.trim(),
          aliases: aliasesList.length > 0 ? aliasesList : null,
          search_text: aliasesList.length > 0 ? aliasesList.join(" ") : null,
          summary: summary.trim() || null,
          formula_blocks: validBlocks,
          conditions: conditions.trim() || null,
          symbol_notes: symbolNotes.trim() || null,
          error_tips: errorTips.trim() || null,
          examples: examples.length > 0 ? examples : null,
          tag_ids: tagIds,
          sort_order: sortOrder,
        }),
      });
    },
    onSuccess: () => {
      setMessage("保存成功！");
      setIsEditing(false);
      queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "保存失败"),
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

  const allowedActions: Record<string, string[]> = {
    draft: ["pending_review"],
    pending_review: ["approved", "rejected"],
    rejected: ["draft"],
    approved: ["published"],
    published: ["offline"],
    offline: ["published"],
  };

  if (isLoading) {
    return <div className="flex items-center justify-center p-12 text-sm text-[var(--color-text-secondary)]">加载中...</div>;
  }

  if (!card) {
    return <div className="p-12 text-sm">公式未找到</div>;
  }

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
                  <h3 className="font-display text-2xl font-bold text-[var(--ink)]">
                    {isEditing ? "编辑公式" : card.title}
                  </h3>
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
              {!isEditing && canUpdate && (
                <Button variant="secondary" onClick={() => setIsEditing(true)}>
                  编辑
                </Button>
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

          {isEditing ? (
            /* ██ Edit form ██ */
            <div className="space-y-6">
              <section className="space-y-2">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">分类</label>
                <select
                  className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                  value={categoryId}
                  onChange={(e) => setCategoryId(Number(e.target.value))}
                >
                  {flatCats.filter((c) => c.depth === 2).map((c) => (
                    <option key={c.id} value={c.id}>{c.label}</option>
                  ))}
                </select>
              </section>

              <section className="space-y-2">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">标题</label>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} />
              </section>

              <section className="space-y-2">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">别名</label>
                <Input value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="逗号分隔" />
              </section>

              <section className="space-y-2">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">摘要</label>
                <textarea className="min-h-16 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm" value={summary} onChange={(e) => setSummary(e.target.value)} />
              </section>

              {/* Tags */}
              <section className="space-y-2">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">标签</label>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(TAG_NAMES).map(([code, name]) => (
                    <button key={code} type="button" onClick={() => toggleTag(code)}
                      className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition ${
                        selectedTags.includes(code) ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]" : "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)]"
                      }`}
                    >
                      {selectedTags.includes(code) && <CheckIcon className="h-3 w-3" />}
                      {name}
                    </button>
                  ))}
                </div>
              </section>

              {/* Formula blocks */}
              <section className="space-y-3 rounded-xl border bg-white/60 p-4">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-[var(--color-text-secondary)]">公式块</label>
                  {blocks.length < 8 && (
                    <Button variant="secondary" size="sm" onClick={addBlock}><Plus className="h-3 w-3" /> 添加</Button>
                  )}
                </div>
                {blocks.map((block, i) => (
                  <div key={i} className="rounded-xl border bg-white p-3 shadow-sm">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold text-[var(--color-text-hint)]">#{i + 1}</span>
                      {blocks.length > 1 && (
                        <button onClick={() => removeBlock(i)} className="text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
                      )}
                    </div>
                    <div className="grid gap-2">
                      <Input value={block.label || ""} onChange={(e) => updateBlock(i, "label", e.target.value)} placeholder="标题（可选）" />
                      <textarea className="min-h-16 w-full rounded-xl border bg-[var(--color-bg-input)] p-3 font-mono text-sm"
                        value={block.latex} onChange={(e) => updateBlock(i, "latex", e.target.value)} placeholder="LaTeX" />
                      <Input value={block.note || ""} onChange={(e) => updateBlock(i, "note", e.target.value)} placeholder="注释（可选）" />
                    </div>
                  </div>
                ))}
              </section>

              <section className="space-y-2">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">适用条件</label>
                <textarea className="min-h-16 w-full rounded-xl border bg-[var(--color-bg-input)] p-3 text-sm" value={conditions} onChange={(e) => setConditions(e.target.value)} />
              </section>

              <section className="space-y-2">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">符号说明</label>
                <textarea className="min-h-16 w-full rounded-xl border bg-[var(--color-bg-input)] p-3 text-sm" value={symbolNotes} onChange={(e) => setSymbolNotes(e.target.value)} />
              </section>

              <section className="space-y-2">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">易错提醒</label>
                <textarea className="min-h-16 w-full rounded-xl border bg-[var(--color-bg-input)] p-3 text-sm" value={errorTips} onChange={(e) => setErrorTips(e.target.value)} />
              </section>

              {/* Examples */}
              <section className="space-y-3 rounded-xl border bg-white/60 p-4">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-[var(--color-text-secondary)]">例题</label>
                  {examples.length < 3 && (
                    <Button variant="secondary" size="sm" onClick={addExample}><Plus className="h-3 w-3" /> 添加</Button>
                  )}
                </div>
                {examples.map((ex, i) => (
                  <div key={i} className="rounded-xl border bg-white p-3 shadow-sm">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold text-[var(--color-text-hint)]">例题 #{i + 1}</span>
                      <button onClick={() => removeExample(i)} className="text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                    <div className="grid gap-2">
                      <Input value={ex.question} onChange={(e) => updateExample(i, "question", e.target.value)} placeholder="题目" />
                      <Input value={ex.short_solution} onChange={(e) => updateExample(i, "short_solution", e.target.value)} placeholder="解法" />
                      <Input value={ex.answer} onChange={(e) => updateExample(i, "answer", e.target.value)} placeholder="答案" />
                      <Input value={ex.error_tip || ""} onChange={(e) => updateExample(i, "error_tip", e.target.value)} placeholder="易错点（可选）" />
                    </div>
                  </div>
                ))}
              </section>

              <section className="space-y-2">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">排序</label>
                <Input type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))} />
              </section>

              <div className="flex justify-end gap-3 border-t pt-4">
                <Button variant="secondary" onClick={() => setIsEditing(false)}>
                  <X className="h-4 w-4" /> 取消
                </Button>
                <Button onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>
                  <Save className="h-4 w-4" />
                  {updateMutation.isPending ? "保存中..." : "保存"}
                </Button>
              </div>
            </div>
          ) : (
            /* ██ Read-only detail ██ */
            <div className="space-y-5 text-sm">
              {/* Tags */}
              <div className="flex flex-wrap items-center gap-2">
                {card.tags?.map((t) => (
                  <span key={t.id} className="rounded-lg border bg-white/60 px-2 py-1 text-xs text-[var(--color-text-secondary)]">{t.name}</span>
                ))}
              </div>

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
                      <pre className="overflow-x-auto font-mono text-sm text-[var(--ink)]">{block.latex}</pre>
                      {block.note && <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{block.note}</p>}
                    </div>
                  ))}
                </div>
              </section>

              {card.conditions && (
                <section className="rounded-[1.6rem] border border-amber-200 bg-amber-50/60 p-4">
                  <p className="font-semibold text-amber-800">适用条件</p>
                  <p className="mt-2 text-sm text-amber-900">{card.conditions}</p>
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
                  <p className="mt-2 text-sm leading-6 text-red-800">{card.error_tips}</p>
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
          )}
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
            pending_review: "approve",
            approved: "approve",
            rejected: "reject",
            published: "publish",
            offline: "offline",
            draft: "restore",
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

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}
