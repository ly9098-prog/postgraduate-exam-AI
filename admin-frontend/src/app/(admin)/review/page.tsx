"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Eye, Filter, Search, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { apiRequest, toQuery } from "@/lib/api/client";
import { normalizeStructuredTableSegment } from "@/lib/structured-table";
import type { AdminQuestion, AdminQuestionDetail, AdminQuestionImportSummary, PaginatedResponse, QuestionVersionDetail } from "@/lib/api/types";

type ConfirmState =
  | { action: "approve"; id: number }
  | { action: "reject"; id: number }
  | null;

function unresolvedTableCount(content: unknown): number {
  if (!content || typeof content !== "object" || Array.isArray(content)) return 0;
  const segments = (content as Record<string, unknown>).segments;
  if (!Array.isArray(segments)) return 0;
  return segments.reduce((count, segment) => {
    const table = normalizeStructuredTableSegment(segment);
    return count + (table?.requires_review ? 1 : 0);
  }, 0);
}

function textFromContent(content: Record<string, unknown> | string | null | undefined) {
  if (!content) return "";
  if (typeof content === "string") return content;
  const candidate = content.stem ?? content.text ?? content.question ?? content.title;
  if (typeof candidate === "string") return candidate;
  return JSON.stringify(content, null, 2);
}

function renderJson(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function statusTone(status: string) {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  if (status === "re_pending") return "warning";
  return "primary";
}

function duplicateStatusTone(status: string | null | undefined) {
  if (status === "possible_duplicate") return "warning";
  if (status === "normal") return "success";
  return "neutral";
}

function renderDuplicateInfo(importRecord: AdminQuestionImportSummary | null | undefined) {
  if (!importRecord) return null;
  const status = importRecord.duplicate_status || "normal";
  const isSuspicious = status === "possible_duplicate";
  return (
    <section className="blueprint-panel relative overflow-hidden rounded-3xl border border-[rgba(196,154,107,0.42)] bg-[var(--color-warning-light)] shadow-[var(--shadow-crisp)]">
      <span className="absolute left-0 top-0 h-full w-1 bg-[var(--color-warning)]" aria-hidden="true" />
      <div className="relative z-10">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[rgba(196,154,107,0.28)] bg-white/55 px-4 py-3 backdrop-blur-sm">
          <div className="min-w-0">
            <p className="font-mono text-[10px] uppercase tracking-[0.32em] text-[var(--color-text-hint)]">Duplicate scan</p>
            <p className="mt-1 font-display text-lg font-bold text-[var(--ink)]">重复检测</p>
          </div>
          <StatusBadge tone={duplicateStatusTone(status)}>{status}</StatusBadge>
        </div>
        <div className="space-y-3 px-4 py-4">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl border border-[rgba(91,123,154,0.18)] bg-[rgba(255,253,248,0.72)] p-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--color-text-hint)]">题目 hash</p>
              <p className="mt-1 break-all font-mono text-xs text-[var(--ink)]">{importRecord.question_hash || "—"}</p>
            </div>
            <div className="rounded-2xl border border-[rgba(91,123,154,0.18)] bg-[rgba(255,253,248,0.72)] p-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--color-text-hint)]">重复正式题</p>
              <p className="mt-1 font-mono text-xs text-[var(--ink)]">{importRecord.duplicate_of_question_id ? `#${importRecord.duplicate_of_question_id}` : "—"}</p>
            </div>
            <div className="rounded-2xl border border-[rgba(91,123,154,0.18)] bg-[rgba(255,253,248,0.72)] p-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--color-text-hint)]">重复导入项</p>
              <p className="mt-1 font-mono text-xs text-[var(--ink)]">{importRecord.duplicate_of_import_id ? `#${importRecord.duplicate_of_import_id}` : "—"}</p>
            </div>
          </div>
          <p className="rounded-2xl border border-[rgba(91,123,154,0.14)] bg-white/55 px-3 py-2 text-xs text-[var(--color-text-secondary)]">
            {isSuspicious ? "需要人工核对来源关系" : "未发现重复关联"}
          </p>
        </div>
      </div>
    </section>
  );
}

function renderDiff(label: string, current: unknown, previous: unknown) {
  const cur = renderJson(current);
  const prev = renderJson(previous);
  const changed = cur !== prev;
  return (
    <section key={label} className="space-y-1">
      <p className="font-semibold text-[var(--ink)]">{label}</p>
      {changed ? (
        <div className="space-y-1 rounded-2xl border border-[var(--color-warning)] bg-[var(--color-warning-light)] p-3">
          <p className="text-xs font-semibold text-[var(--color-warning)]">变更前</p>
          <pre className="whitespace-pre-wrap text-xs text-[var(--color-text-secondary)] line-through">{prev}</pre>
          <p className="text-xs font-semibold text-[var(--color-success)]">变更后</p>
          <pre className="whitespace-pre-wrap text-xs text-[var(--color-success)]">{cur}</pre>
        </div>
      ) : (
        <pre className="whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-xs text-[var(--color-text-secondary)]">{cur}</pre>
      )}
    </section>
  );
}

export default function ReviewPage() {
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState("");
  const [tab, setTab] = useState<"pending" | "re_pending">("pending");
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);

  const questions = useQuery({
    queryKey: ["review-questions", tab, keyword],
    queryFn: () =>
      apiRequest<PaginatedResponse<AdminQuestion>>(
        `/questions${toQuery({ page: 1, page_size: 50, review_status: tab, keyword })}`,
      ),
    retry: false,
  });

  const preview = useQuery({
    queryKey: ["review-preview", previewId],
    queryFn: () => apiRequest<AdminQuestionDetail>(`/questions/${previewId}`),
    enabled: previewId !== null,
    retry: false,
  });

  const previewVersions = useQuery({
    queryKey: ["review-preview", previewId, "versions"],
    queryFn: () => apiRequest<PaginatedResponse<{ version: number }>>(`/questions/${previewId}/versions${toQuery({ page: 1, page_size: 1 })}`),
    enabled: previewId !== null && tab === "re_pending",
    retry: false,
  });

  const previewVersionDetail = useQuery({
    queryKey: ["review-preview", previewId, "version-detail"],
    queryFn: () => apiRequest<QuestionVersionDetail>(`/questions/${previewId}/versions/${previewVersions.data?.items?.[0]?.version}`),
    enabled: previewId !== null && tab === "re_pending" && Boolean(previewVersions.data?.items?.[0]?.version),
    retry: false,
  });

  const items = useMemo(() => questions.data?.items ?? [], [questions.data]);

  const reviewMutation = useMutation({
    mutationFn: async (state: Exclude<ConfirmState, null>) => {
      if (state.action === "approve") {
        const target = preview.data?.id === state.id
          ? preview.data
          : await apiRequest<AdminQuestionDetail>(`/questions/${state.id}`);
        const tableCount = unresolvedTableCount(target.content);
        if (tableCount > 0) {
          throw new Error(`无法通过：仍有 ${tableCount} 个结构化表格需要在题库编辑页完成核验。`);
        }
        return apiRequest<AdminQuestion>(`/questions/${state.id}/approve`, { method: "POST" });
      }
      return apiRequest<AdminQuestion>(`/questions/${state.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: rejectReason }),
      });
    },
    onSuccess: (result, variables) => {
      const label = variables.action === "approve" ? "已通过" : "已拒绝";
      setMessage(`操作成功，题目 #${result.id} ${label}。`);
      setConfirmState(null);
      setRejectReason("");
      queryClient.invalidateQueries({ queryKey: ["review-questions"] });
      if (previewId === result.id) {
        queryClient.invalidateQueries({ queryKey: ["review-preview", previewId] });
      }
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
    },
  });

  const pendingQuestion: AdminQuestionDetail | undefined = preview.data;
  const pendingQuestionTableReviewCount = unresolvedTableCount(pendingQuestion?.content);
  const previousVersion = previewVersionDetail.data;
  const baselineVersion = previewVersions.data?.items?.[0]?.version;
  const diffUnreliable = tab === "re_pending" && (
    previewVersions.isError ||
    previewVersionDetail.isError ||
    (!previewVersions.isLoading && !baselineVersion) ||
    (Boolean(baselineVersion) && !previewVersionDetail.isLoading && !previousVersion)
  );

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">Review</p>
        <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">审核工作台</h2>
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">待审题目</h3>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">支持快速审核、diff 预览、驳回说明，提交后自动刷新列表。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant={tab === "pending" ? "primary" : "secondary"} onClick={() => { setTab("pending"); setPreviewId(null); }}>
              <Filter className="h-4 w-4" />
              pending
            </Button>
            <Button variant={tab === "re_pending" ? "primary" : "secondary"} onClick={() => { setTab("re_pending"); setPreviewId(null); }}>
              <AlertTriangle className="h-4 w-4" />
              re_pending
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {message ? (
            <p className="rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">{message}</p>
          ) : null}
          <label className="relative block max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
            <Input
              className="pl-9"
              placeholder="搜索题干 / 科目"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
            />
          </label>
          <div className="grid gap-4 xl:grid-cols-2">
            {items.map((question) => (
              <article key={question.id} className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-5">
                <div className="flex items-center justify-between gap-4">
                  <StatusBadge tone={statusTone(question.review_status)}>{question.review_status || "pending"}</StatusBadge>
                  <div className="flex gap-2">
                    <Button variant="ghost" onClick={() => setPreviewId(question.id)}>
                      <Eye className="h-4 w-4" />
                      预览
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={unresolvedTableCount(question.content) > 0}
                      onClick={() => setConfirmState({ action: "approve", id: question.id })}
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      通过
                    </Button>
                    <Button variant="danger" onClick={() => setConfirmState({ action: "reject", id: question.id })}>
                      <XCircle className="h-4 w-4" />
                      拒绝
                    </Button>
                  </div>
                </div>
                <h4 className="mt-4 whitespace-pre-wrap text-sm font-semibold text-[var(--ink)]">
                  {textFromContent(question.content) || `题目 #${question.id}`}
                </h4>
                <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
                  {question.subject_name || "未分类"} · 难度 {question.difficulty} · {question.question_type || "未标注题型"}
                </p>
                {unresolvedTableCount(question.content) > 0 ? (
                  <div className="mt-2"><StatusBadge tone="warning">表格待核验</StatusBadge></div>
                ) : null}
                {tab === "re_pending" ? (
                  <div className="mt-2"><StatusBadge tone="warning">re_pending</StatusBadge></div>
                ) : null}
              </article>
            ))}
          </div>
          {!questions.isLoading && items.length === 0 ? (
            <p className="py-10 text-center text-sm text-[var(--color-text-hint)]">暂无待审题目</p>
          ) : null}
          {questions.isError ? <p className="text-sm text-[var(--color-danger)]">题库接口当前不可用，若 router 未挂载则属于后端阻塞。</p> : null}
        </CardContent>
      </Card>

      {previewId !== null && pendingQuestion ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.28)]" onClick={() => setPreviewId(null)}>
          <aside className="h-full w-full max-w-3xl overflow-y-auto bg-white p-6 shadow-[var(--shadow-floating)]" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">题目详情与 Diff</h3>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  disabled={pendingQuestionTableReviewCount > 0}
                  onClick={() => setConfirmState({ action: "approve", id: previewId })}
                >
                  <CheckCircle2 className="h-4 w-4" />
                  通过
                </Button>
                <Button variant="danger" onClick={() => setConfirmState({ action: "reject", id: previewId })}>
                  <XCircle className="h-4 w-4" />
                  拒绝
                </Button>
                <Button variant="ghost" onClick={() => setPreviewId(null)}>关闭</Button>
              </div>
            </div>
            <div className="mt-6 space-y-4 text-sm">
              {renderDuplicateInfo(pendingQuestion.import_record)}
              {tab === "re_pending" ? (
                <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                  <p className="font-semibold text-[var(--ink)]">
                    对比基线：当前题目 vs {previousVersion ? `v${previousVersion.version} 历史快照` : "历史快照"}
                  </p>
                  {diffUnreliable ? <p className="mt-2 text-sm font-semibold text-[var(--color-warning)]">无法获取历史版本，diff 不可靠</p> : null}
                </div>
              ) : null}
              {pendingQuestionTableReviewCount > 0 ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
                  当前题目仍有 {pendingQuestionTableReviewCount} 个结构化表格需要人工核验，暂不能审核通过。
                </div>
              ) : null}
              <section className="rounded-2xl border border-[var(--color-primary-light)] bg-[var(--porcelain)] p-4">
                <p className="mb-3 font-semibold text-[var(--ink)]">当前题干预览</p>
                <QuestionContentRenderer
                  content={pendingQuestion.content}
                  fallbackText={textFromContent(pendingQuestion.content)}
                  showTableMetadata
                />
              </section>
              {renderDiff("题干", textFromContent(pendingQuestion.content), previousVersion ? textFromContent(previousVersion.content) : "")}
              {renderDiff("选项", pendingQuestion.options ?? null, previousVersion ? previousVersion.options ?? null : null)}
              {renderDiff("答案", pendingQuestion.answer, previousVersion ? previousVersion.answer : "")}
              {renderDiff("解析", pendingQuestion.analysis ?? null, previousVersion ? previousVersion.analysis ?? null : null)}
              {renderDiff("难度", pendingQuestion.difficulty, previousVersion ? previousVersion.difficulty : null)}
              {renderDiff("知识点", pendingQuestion.knowledge_points ?? null, previousVersion ? previousVersion.knowledge_points ?? null : null)}
            </div>
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmState !== null}
        title="确认审核操作"
        description={
          confirmState?.action === "reject"
            ? "拒绝题目需要填写原因，确认后将提交到后端审核接口。"
            : "确认后将提交审核通过操作，请确保题目内容已经完成检查。"
        }
        confirmText="提交"
        danger={confirmState?.action === "reject"}
        loading={reviewMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => {
          if (!confirmState) return;
          reviewMutation.mutate(confirmState);
        }}
      />
      {confirmState?.action === "reject" ? (
        <div className="fixed inset-x-0 bottom-6 z-[60] mx-auto w-full max-w-md px-4">
          <textarea
            className="min-h-24 w-full rounded-2xl border border-[var(--color-border)] bg-white p-3 text-sm outline-none focus:border-[var(--color-primary)]"
            placeholder="请输入拒绝原因"
            value={rejectReason}
            onChange={(event) => setRejectReason(event.target.value)}
          />
        </div>
      ) : null}
    </div>
  );
}
