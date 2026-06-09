"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Code2, Eye, FileText, Save, Search, Send, Sparkles, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { AdminImportCompleteResponse, ImportActionResponse, ImportPublishResponse, ImportQuestionItem, PaginatedResponse } from "@/lib/api/types";

type ConfirmState =
  | { action: "approve"; id: number }
  | { action: "reject"; id: number }
  | { action: "batch-approve" }
  | { action: "batch-reject" }
  | { action: "publish"; batchId: string }
  | null;

type EditState = {
  subject: string;
  question_type: string;
  stem: string;
  options: Array<{ key: string; text: string }>;
  answer: string;
  analysis: string;
};

function parseOptionsToEditable(item: ImportQuestionItem | null | undefined): Array<{ key: string; text: string }> {
  if (!item) return [];
  const raw = item.raw_data;
  const source = item.parsed_options ?? raw?.options ?? raw?.parsed_options ?? raw?.option_text ?? raw?.optionText ?? null;
  if (!source || (Array.isArray(source) && source.length === 0)) {
    if (item.question_type === "multi_blank_choice") {
      const groups = item.parsed_content?.blank_option_groups ?? raw?.blank_option_groups;
      if (Array.isArray(groups)) {
        const result: Array<{ key: string; text: string; _groupId?: string }> = [];
        for (const group of groups) {
          if (!group || typeof group !== "object") continue;
          const g = group as Record<string, unknown>;
          const groupId = String(g.id ?? "");
          const opts = g.options;
          if (Array.isArray(opts)) {
            for (const opt of opts) {
              if (opt && typeof opt === "object") {
                const o = opt as Record<string, unknown>;
                const key = String(o.key ?? "");
                const text = String(o.text ?? "");
                if (key && text) result.push({ key, text });
              }
            }
          } else if (opts && typeof opts === "object") {
            for (const [key, text] of Object.entries(opts as Record<string, unknown>)) {
              if (key && text) result.push({ key, text: String(text) });
            }
          }
        }
        return result;
      }
    }
    return [];
  }
  if (Array.isArray(source)) {
    return source
      .map((entry, index) => {
        if (typeof entry === "string") {
          const key = String.fromCharCode(65 + index);
          return { key, text: entry };
        }
        if (entry && typeof entry === "object") {
          const obj = entry as Record<string, unknown>;
          const key = String(obj.key ?? obj.label ?? obj.name ?? String.fromCharCode(65 + index));
          const text = String(obj.text ?? obj.content ?? obj.value ?? obj.stem ?? "");
          return { key, text };
        }
        return { key: String.fromCharCode(65 + index), text: "" };
      })
      .filter((opt) => opt.key && opt.text);
  }
  if (typeof source === "object") {
    return Object.entries(source as Record<string, unknown>)
      .map(([key, value]) => ({ key, text: typeof value === "string" ? value : String(value ?? "") }))
      .filter((opt) => opt.key && opt.text);
  }
  return [];
}

function isMultiChoice(questionType: string): boolean {
  return /多选|多空|多项/i.test(questionType);
}

function textFromImport(item: ImportQuestionItem | null | undefined) {
  if (!item) return "";
  const content = item.parsed_content;
  const raw = item.raw_data;
  const candidate = content?.stem ?? content?.text ?? content?.question ?? raw?.stem ?? raw?.text ?? raw?.question;
  if (typeof candidate === "string") return candidate;
  return "";
}

function renderJson(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function completeSuggestionFromItem(item: ImportQuestionItem | null | undefined) {
  const suggestion = item?.ai_metadata?.complete_suggestion;
  if (suggestion && typeof suggestion === "object" && !Array.isArray(suggestion)) return suggestion as Record<string, unknown>;
  return null;
}

function stringSuggestion(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function statusTone(status: string) {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  if (status === "published") return "primary";
  return "warning";
}

function editStateFromItem(item: ImportQuestionItem): EditState {
  return {
    subject: item.subject || "",
    question_type: item.question_type || "",
    stem: textFromImport(item),
    options: parseOptionsToEditable(item),
    answer: item.parsed_answer || "",
    analysis: item.parsed_analysis || "",
  };
}

export default function ImportReviewPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const batchIdParam = searchParams.get("batch_id") || "";
  const [filters, setFilters] = useState({ batch_id: "", status: "pending", subject: "", source_type: "", keyword: "" });
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [completedItem, setCompletedItem] = useState<ImportQuestionItem | null>(null);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [detailView, setDetailView] = useState<"formatted" | "json">("formatted");

  const queryParams = useMemo(
    () => ({ page: 1, page_size: 50, batch_id: filters.batch_id || batchIdParam, status: filters.status, subject: filters.subject, source_type: filters.source_type, keyword: filters.keyword }),
    [batchIdParam, filters],
  );

  const queue = useQuery({
    queryKey: ["import-review-queue", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<ImportQuestionItem>>(`/imports/review-queue${toQuery(queryParams)}`),
    retry: false,
  });

  const items = queue.data?.items ?? [];
  const queuedPreviewItem = items.find((item) => item.id === previewId) ?? null;
  const previewItem = completedItem?.id === previewId ? completedItem : queuedPreviewItem;
  const completeSuggestion = completeSuggestionFromItem(previewItem);
  const answerSuggestion = stringSuggestion(completeSuggestion?.answer);
  const allChecked = items.length > 0 && items.every((item) => selectedIds.has(item.id));

  const actionMutation = useMutation({
    mutationFn: async (state: Exclude<ConfirmState, null>) => {
      if (state.action === "approve") return apiRequest<ImportActionResponse>(`/imports/questions/${state.id}/approve`, { method: "POST" });
      if (state.action === "reject") return apiRequest<ImportActionResponse>(`/imports/questions/${state.id}/reject`, { method: "POST", body: JSON.stringify({ reason: rejectReason }) });
      if (state.action === "batch-approve") return apiRequest<ImportActionResponse>(`/imports/${filters.batch_id}/approve`, { method: "POST" });
      if (state.action === "batch-reject") return apiRequest<ImportActionResponse>(`/imports/${filters.batch_id}/reject`, { method: "POST", body: JSON.stringify({ reason: rejectReason }) });
      return apiRequest<ImportPublishResponse>(`/imports/${state.batchId}/publish`, { method: "POST" });
    },
    onSuccess: (result, variables) => {
      if (variables.action === "publish") {
        const published = "published" in result ? result.published : 0;
        setMessage(`发布完成，已发布 ${published} 题。`);
      } else if (variables.action === "approve") {
        setMessage(`导入题目 #${variables.id} 已通过审核。`);
      } else if (variables.action === "reject") {
        setMessage(`导入题目 #${variables.id} 已驳回。`);
      } else if (variables.action === "batch-approve") {
        const affected = "affected_count" in result ? result.affected_count : 0;
        setMessage(`批量审核通过完成，影响 ${affected} 条导入题目。`);
      } else {
        const affected = "affected_count" in result ? result.affected_count : 0;
        setMessage(`批量驳回完成，影响 ${affected} 条导入题目。`);
      }
      setSelectedIds(new Set());
      setConfirmState(null);
      setRejectReason("");
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["import-batches"] });
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
    },
  });

  const updateMutation = useMutation({
    mutationFn: async () => {
      if (!previewId || !editState) throw new Error("请选择要编辑的题目");
      const { options, ...rest } = editState;
      const body = {
        ...rest,
        options: options.map((o) => ({ key: o.key, text: o.text })),
      };
      return apiRequest<ImportQuestionItem>(`/imports/questions/${previewId}`, { method: "PUT", body: JSON.stringify(body) });
    },
    onSuccess: (result) => {
      setMessage(`导入题目 #${result.id} 已保存。`);
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "保存失败，请稍后重试。");
    },
  });

  const completeMutation = useMutation({
    mutationFn: async (id: number) => apiRequest<AdminImportCompleteResponse>(`/imports/questions/${id}/complete`, { method: "POST" }),
    onSuccess: (result) => {
      setMessage(result.missing.length === 0 ? "当前题目信息已完整，无需补全。" : "AI 补全完成，请复核后保存/通过。");
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      setPreviewId(result.item.id);
      setCompletedItem(result.item);
      const suggestion = completeSuggestionFromItem(result.item);
      if (suggestion) {
        setEditState((prev) => ({
          ...prev,
          subject: prev.subject || (typeof suggestion.subject === "string" ? suggestion.subject : ""),
          question_type: prev.question_type || (typeof suggestion.question_type === "string" ? suggestion.question_type : ""),
          analysis: prev.analysis || (typeof suggestion.analysis === "string" ? suggestion.analysis : ""),
        }));
      }
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "AI 补全失败，请稍后重试。");
    },
  });

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setSelectedIds(new Set());
    setPreviewId(null);
    setCompletedItem(null);
    setEditState(null);
  };

  const toggleAll = () => {
    setSelectedIds(() => (allChecked ? new Set() : new Set(items.map((item) => item.id))));
  };

  const toggleOne = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openPreview = (item: ImportQuestionItem) => {
    setPreviewId(item.id);
    setCompletedItem(null);
    setEditState(editStateFromItem(item));
  };

  const canBatchOperate = Boolean(filters.batch_id || batchIdParam) && items.length > 0;

  return (
    <div className="space-y-6">
      {message ? (
        <div role="status" aria-live="polite" className="fixed right-6 top-6 z-[60] max-w-sm rounded-2xl border border-[var(--color-success)] bg-white px-5 py-4 text-sm font-medium text-[var(--ink)] shadow-[var(--shadow-floating)]">
          {message}
        </div>
      ) : null}
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">待审核题目</h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">审核 question_imports 暂存题目，通过后再发布到正式题库。</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" disabled={!canBatchOperate} onClick={() => setConfirmState({ action: "batch-approve" })}>
                <CheckCircle2 className="h-4 w-4" />
                批量通过当前批次
              </Button>
              <Button variant="danger" disabled={!canBatchOperate} onClick={() => setConfirmState({ action: "batch-reject" })}>
                <XCircle className="h-4 w-4" />
                批量驳回当前批次
              </Button>
              <Button variant="primary" disabled={!(filters.batch_id || batchIdParam)} onClick={() => setConfirmState({ action: "publish", batchId: filters.batch_id || batchIdParam })}>
                <Send className="h-4 w-4" />
                发布已通过
              </Button>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <label className="relative xl:col-span-2">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input className="pl-9" placeholder="搜索题干 / OCR 原文" value={filters.keyword} onChange={(event) => updateFilter("keyword", event.target.value)} />
            </label>
            <Input placeholder="批次 ID" value={filters.batch_id || batchIdParam} onChange={(event) => updateFilter("batch_id", event.target.value)} />
            <Input placeholder="科目" value={filters.subject} onChange={(event) => updateFilter("subject", event.target.value)} />
            <select className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
              <option value="pending">pending</option>
              <option value="approved">approved</option>
              <option value="rejected">rejected</option>
              <option value="published">published</option>
              <option value="">全部状态</option>
            </select>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
            <section className="space-y-3">
              <label className="flex items-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">
                <input type="checkbox" checked={allChecked} onChange={toggleAll} />
                全选当前结果
              </label>
              {items.map((item) => (
                <article key={item.id} className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => toggleOne(item.id)} />
                      <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
                      {item.duplicate_status ? <StatusBadge tone={item.duplicate_status === "possible_duplicate" ? "warning" : "neutral"}>{item.duplicate_status}</StatusBadge> : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button variant="ghost" onClick={() => openPreview(item)}>
                        <Eye className="h-4 w-4" />
                        预览
                      </Button>
                      <Button variant="ghost" disabled={item.status !== "pending" || completeMutation.isPending} onClick={() => completeMutation.mutate(item.id)}>
                        <Sparkles className="h-4 w-4" />
                        AI补全
                      </Button>
                      <Button variant="secondary" disabled={item.status === "published"} onClick={() => setConfirmState({ action: "approve", id: item.id })}>
                        <CheckCircle2 className="h-4 w-4" />
                        通过
                      </Button>
                      <Button variant="danger" disabled={item.status === "published"} onClick={() => setConfirmState({ action: "reject", id: item.id })}>
                        <XCircle className="h-4 w-4" />
                        驳回
                      </Button>
                    </div>
                  </div>
                  <h4 className="mt-4 whitespace-pre-wrap text-sm font-semibold text-[var(--ink)]">{textFromImport(item) || `导入题目 #${item.id}`}</h4>
                  <p className="mt-2 text-xs text-[var(--color-text-secondary)]">{item.subject || "未分类"} · {item.question_type || "未标注题型"} · {item.batch_id}</p>
                </article>
              ))}
              {!queue.isLoading && items.length === 0 ? <p className="py-10 text-center text-sm text-[var(--color-text-hint)]">暂无待审核题目</p> : null}
              {queue.isError ? <p className="text-sm text-[var(--color-danger)]">待审核接口当前不可用。</p> : null}
            </section>

            <aside className="rounded-3xl border border-[var(--color-border)] bg-white/70 p-5">
              {!previewItem || !editState ? <p className="text-sm text-[var(--color-text-hint)]">选择一题查看 OCR 原文、解析结果并编辑。</p> : null}
              {previewItem && editState ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-mono text-xs text-[var(--color-text-hint)]">#{previewItem.id}</p>
                      <h4 className="font-display text-xl font-bold text-[var(--ink)]">导入题目详情</h4>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex overflow-hidden rounded-xl border border-[var(--color-border)]">
                        <button
                          type="button"
                          className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition ${detailView === "formatted" ? "bg-[var(--color-primary)] text-white" : "bg-transparent text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]"}`}
                          onClick={() => setDetailView("formatted")}
                        >
                          <FileText className="h-3.5 w-3.5" />
                          文本
                        </button>
                        <button
                          type="button"
                          className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition ${detailView === "json" ? "bg-[var(--color-primary)] text-white" : "bg-transparent text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]"}`}
                          onClick={() => setDetailView("json")}
                        >
                          <Code2 className="h-3.5 w-3.5" />
                          JSON
                        </button>
                      </div>
                      <Button disabled={completeMutation.isPending || previewItem.status !== "pending"} onClick={() => completeMutation.mutate(previewItem.id)}>
                        <Sparkles className="h-4 w-4" />
                        AI补全
                      </Button>
                      <Button disabled={updateMutation.isPending || previewItem.status === "published"} onClick={() => updateMutation.mutate()}>
                        <Save className="h-4 w-4" />
                        保存编辑
                      </Button>
                    </div>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <Input placeholder="科目" value={editState.subject} onChange={(event) => setEditState({ ...editState, subject: event.target.value })} />
                    <Input placeholder="题型" value={editState.question_type} onChange={(event) => setEditState({ ...editState, question_type: event.target.value })} />
                  </div>
                  <label className="block space-y-1">
                    <span className="text-xs font-semibold text-[var(--color-text-secondary)]">题干</span>
                    <textarea className="min-h-36 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm" value={editState.stem} onChange={(event) => setEditState({ ...editState, stem: event.target.value })} />
                  </label>
                  {detailView === "formatted" ? (
                    <div className="space-y-4">
                      <section>
                        <p className="mb-2 font-semibold text-[var(--ink)]">选项</p>
                        {editState.question_type === "multi_blank_choice" ? (
                          <div className="space-y-3">
                            {(() => {
                              const groups = previewItem?.parsed_content?.blank_option_groups ?? previewItem?.raw_data?.blank_option_groups;
                              const groupList: Array<{ id?: string; options?: Array<{ key: string; text: string }> }> = Array.isArray(groups) ? groups : [];
                              return groupList.length > 0 ? groupList.map((group, gi) => (
                                <div key={gi} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3">
                                  <p className="mb-2 text-xs font-semibold text-[var(--color-text-hint)]">空 {group.id ?? gi + 1}</p>
                                  <div className="space-y-1.5">
                                    {group.options?.map((opt, oi) => (
                                      <div key={oi} className="flex items-center gap-2">
                                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--color-primary-light)] text-[10px] font-bold text-[var(--color-primary-dark)]">{opt.key}</span>
                                        <span className="text-sm text-[var(--color-text-secondary)]">{opt.text}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )) : null;
                            })()}
                            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">多空选择题选项由导入管线管理，如需修改请切换 JSON 视图编辑 parsed_content.blank_option_groups。</p>
                          </div>
                        ) : (
                          <div className="space-y-2">
                            {editState.options.length === 0 ? <p className="text-sm text-[var(--color-text-hint)]">暂无可编辑选项</p> : null}
                            {editState.options.map((opt, index) => (
                              <div key={index} className="flex items-center gap-2">
                                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--color-primary-light)] text-xs font-bold text-[var(--color-primary-dark)]">{opt.key}</span>
                                <input
                                  className="h-9 flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)]"
                                  value={opt.text}
                                  onChange={(event) => {
                                    const next = [...editState.options];
                                    next[index] = { ...next[index], text: event.target.value };
                                    setEditState({ ...editState, options: next });
                                  }}
                                />
                              </div>
                            ))}
                          </div>
                        )}
                      </section>
                      <section>
                        <p className="mb-1 font-semibold text-[var(--ink)]">快速选择答案</p>
                        {editState.question_type === "multi_blank_choice" ? <p className="mb-2 text-[10px] text-[var(--color-text-hint)]">多空选择题：单击切换各空答案，以逗号分隔</p> : null}
                        {editState.options.length === 0 ? <p className="text-sm text-[var(--color-text-hint)]">请先编辑选项</p> : null}
                        {editState.options.length > 0 ? (
                          <div className="flex flex-wrap gap-2">
                            {editState.options.map((opt) => {
                              const selected = isMultiChoice(editState.question_type)
                                ? editState.answer.split(/[,，\s]+/).includes(opt.key)
                                : editState.answer === opt.key;
                              return (
                                <button
                                  key={opt.key}
                                  type="button"
                                  className={`inline-flex h-9 items-center gap-1.5 rounded-xl border px-4 text-sm font-medium transition ${
                                    selected
                                      ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                                      : "border-[var(--color-border)] bg-transparent text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:text-[var(--color-primary-dark)]"
                                  }`}
                                  onClick={() => {
                                    if (isMultiChoice(editState.question_type)) {
                                      const keys = editState.answer.split(/[,，\s]+/).filter(Boolean);
                                      const next = keys.includes(opt.key) ? keys.filter((k) => k !== opt.key) : [...keys, opt.key];
                                      setEditState({ ...editState, answer: next.join(",") });
                                    } else {
                                      setEditState({ ...editState, answer: editState.answer === opt.key ? "" : opt.key });
                                    }
                                  }}
                                >
                                  {opt.key}
                                </button>
                              );
                            })}
                          </div>
                        ) : null}
                      </section>
                      <label className="block space-y-1">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">答案</span>
                        <Input value={editState.answer} onChange={(event) => setEditState({ ...editState, answer: event.target.value })} />
                        {editState.question_type === "multi_blank_choice" ? <p className="text-[10px] text-amber-600">多空选择题答案格式：各空答案用逗号分隔（如 A,B 表示第1空选A、第2空选B）</p> : null}
                      </label>
                      <label className="block space-y-1">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">解析</span>
                        <textarea className="min-h-28 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm" value={editState.analysis} onChange={(event) => setEditState({ ...editState, analysis: event.target.value })} />
                      </label>
                      {completeSuggestion ? (
                        <section>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="font-semibold text-[var(--ink)]">AI 补全建议</p>
                            {answerSuggestion ? (
                              <Button variant="ghost" onClick={() => setEditState({ ...editState, answer: answerSuggestion })}>
                                应用答案建议
                              </Button>
                            ) : null}
                          </div>
                          <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-xs text-[var(--color-text-secondary)]">{renderJson(completeSuggestion)}</pre>
                        </section>
                      ) : null}
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <section>
                        <p className="font-semibold text-[var(--ink)]">基础信息</p>
                        <pre className="mt-2 whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 font-mono text-xs text-[var(--color-text-secondary)]">{renderJson({ id: previewItem.id, batch_id: previewItem.batch_id, source_type: previewItem.source_type, subject: previewItem.subject, question_type: previewItem.question_type, status: previewItem.status, ai_generated: previewItem.ai_generated, ai_answer_flag: previewItem.ai_answer_flag, created_at: previewItem.created_at, updated_at: previewItem.updated_at })}</pre>
                      </section>
                      <section>
                        <p className="font-semibold text-[var(--ink)]">解析数据</p>
                        <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 font-mono text-xs text-[var(--color-text-secondary)]">{renderJson({ parsed_content: previewItem.parsed_content, parsed_options: previewItem.parsed_options, parsed_answer: previewItem.parsed_answer, parsed_analysis: previewItem.parsed_analysis })}</pre>
                      </section>
                      <section>
                        <p className="font-semibold text-[var(--ink)]">重复检测</p>
                        <pre className="mt-2 whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 font-mono text-xs text-[var(--color-text-secondary)]">{renderJson({ duplicate_status: previewItem.duplicate_status, duplicate_of_question_id: previewItem.duplicate_of_question_id, duplicate_of_import_id: previewItem.duplicate_of_import_id, question_hash: previewItem.question_hash })}</pre>
                      </section>
                      <section>
                        <p className="font-semibold text-[var(--ink)]">OCR / AI 原始数据</p>
                        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 font-mono text-xs text-[var(--color-text-secondary)]">{renderJson({ raw_data: previewItem.raw_data, ai_metadata: previewItem.ai_metadata })}</pre>
                      </section>
                    </div>
                  )}
                </div>
              ) : null}
            </aside>
          </div>
        </CardContent>
      </Card>

      {confirmState?.action === "reject" || confirmState?.action === "batch-reject" ? (
        <Card>
          <CardContent className="pt-6">
            <Input placeholder="驳回原因" value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} />
          </CardContent>
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmState !== null}
        title={confirmState?.action.includes("reject") ? "驳回导入题目" : confirmState?.action === "publish" ? "发布已通过题目" : "通过导入题目"}
        description={confirmState?.action === "publish" ? "将当前批次中已通过的题目发布到正式题库。" : "操作会更新 question_imports 暂存审核状态。"}
        confirmText={confirmState?.action.includes("reject") ? "驳回" : confirmState?.action === "publish" ? "发布" : "通过"}
        danger={Boolean(confirmState?.action.includes("reject"))}
        loading={actionMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => confirmState && actionMutation.mutate(confirmState)}
      />
    </div>
  );
}
