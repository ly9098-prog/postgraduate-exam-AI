"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileQuestion, Search, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { AdminQuestion, AdminQuestionDetail, BatchResult, PaginatedResponse, QuestionVersion, QuestionVersionDetail } from "@/lib/api/types";

const reviewStatuses = ["", "pending", "re_pending", "approved", "rejected"];
const activeOptions = [
  { label: "全部状态", value: "" },
  { label: "启用", value: "true" },
  { label: "停用", value: "false" },
];

type ConfirmState =
  | { action: "single-approve" | "single-reject"; id: number }
  | { action: "batch-approve" | "batch-reject" }
  | null;

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

function statusTone(status: string) {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  if (status === "re_pending") return "warning";
  return "primary";
}

export default function QuestionsPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState({ subject: "", review_status: "", is_active: "", question_type: "", keyword: "", year: "" });
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectedQuestionId, setSelectedQuestionId] = useState<number | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);

  const queryParams = useMemo(
    () => ({
      page: 1,
      page_size: 20,
      subject: filters.subject,
      review_status: filters.review_status,
      is_active: filters.is_active,
      question_type: filters.question_type,
      keyword: filters.keyword,
      year: filters.year,
    }),
    [filters],
  );

  const questions = useQuery({
    queryKey: ["questions", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<AdminQuestion>>(`/questions${toQuery(queryParams)}`),
    retry: false,
  });

  const detail = useQuery({
    queryKey: ["questions", selectedQuestionId, "detail"],
    queryFn: () => apiRequest<AdminQuestionDetail>(`/questions/${selectedQuestionId}`),
    enabled: selectedQuestionId !== null,
    retry: false,
  });

  const versions = useQuery({
    queryKey: ["questions", selectedQuestionId, "versions"],
    queryFn: () => apiRequest<PaginatedResponse<QuestionVersion>>(`/questions/${selectedQuestionId}/versions${toQuery({ page: 1, page_size: 20 })}`),
    enabled: selectedQuestionId !== null,
    retry: false,
  });

  const versionDetail = useQuery({
    queryKey: ["questions", selectedQuestionId, "versions", selectedVersion],
    queryFn: () => apiRequest<QuestionVersionDetail>(`/questions/${selectedQuestionId}/versions/${selectedVersion}`),
    enabled: selectedQuestionId !== null && selectedVersion !== null,
    retry: false,
  });

  const reviewMutation = useMutation({
    mutationFn: async (state: Exclude<ConfirmState, null>) => {
      if (state.action === "single-approve") return apiRequest<AdminQuestion>(`/questions/${state.id}/approve`, { method: "POST" });
      if (state.action === "single-reject") return apiRequest<AdminQuestion>(`/questions/${state.id}/reject`, { method: "POST", body: JSON.stringify({ reason: rejectReason }) });
      if (state.action === "batch-approve") return apiRequest<BatchResult>("/questions/batch-approve", { method: "POST", body: JSON.stringify({ ids: Array.from(selectedIds) }) });
      return apiRequest<BatchResult>("/questions/batch-reject", { method: "POST", body: JSON.stringify({ ids: Array.from(selectedIds), reason: rejectReason }) });
    },
    onSuccess: (result) => {
      if ("id" in result) {
        setMessage(`操作成功，题目 #${result.id} 已处理。`);
      } else {
        const successIds = result.success_ids ?? result.successIds ?? [];
        const failedItems = result.failed_items ?? result.failedItems ?? [];
        const failures = failedItems.length
          ? `失败 ${failedItems.length} 条：${failedItems.map((item) => `#${item.id} ${item.error}`).join("；")}`
          : "无失败项";
        setMessage(`批量操作完成，成功 ${successIds.length} 条，${failures}。`);
      }
      setSelectedIds(new Set());
      setConfirmState(null);
      setRejectReason("");
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
    },
  });

  const items = questions.data?.items ?? [];
  const allChecked = items.length > 0 && items.every((item) => selectedIds.has(item.id));
  const selectedQuestion = detail.data;

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const toggleAll = () => {
    setSelectedIds(() => {
      if (allChecked) return new Set();
      return new Set(items.map((item) => item.id));
    });
  };

  const toggleOne = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openDetail = (id: number) => {
    setSelectedQuestionId(id);
    setSelectedVersion(null);
  };

  const confirmDescription = confirmState?.action.includes("reject")
    ? "拒绝题目需要填写原因，确认后将提交到后端审核接口。"
    : "确认后将提交审核通过操作。";

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">Questions</p>
        <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">题库</h2>
      </div>
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">题目列表</h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">支持多条件筛选、批量审核、详情查看与版本历史。</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" disabled={selectedIds.size === 0} onClick={() => setConfirmState({ action: "batch-approve" })}>
                <CheckCircle2 className="h-4 w-4" />
                批量通过
              </Button>
              <Button variant="danger" disabled={selectedIds.size === 0} onClick={() => setConfirmState({ action: "batch-reject" })}>
                <XCircle className="h-4 w-4" />
                批量拒绝
              </Button>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <label className="relative xl:col-span-2">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input className="pl-9" placeholder="搜索题干 / 科目" value={filters.keyword} onChange={(event) => updateFilter("keyword", event.target.value)} />
            </label>
            <Input placeholder="科目" value={filters.subject} onChange={(event) => updateFilter("subject", event.target.value)} />
            <Input placeholder="题型" value={filters.question_type} onChange={(event) => updateFilter("question_type", event.target.value)} />
            <Input placeholder="年份" value={filters.year} onChange={(event) => updateFilter("year", event.target.value)} />
            <select className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={filters.review_status} onChange={(event) => updateFilter("review_status", event.target.value)}>
              {reviewStatuses.map((status) => (
                <option key={status || "all"} value={status}>{status || "全部审核"}</option>
              ))}
            </select>
            <select className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={filters.is_active} onChange={(event) => updateFilter("is_active", event.target.value)}>
              {activeOptions.map((option) => (
                <option key={option.value || "all"} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {message ? <p className="rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">{message}</p> : null}
          <label className="inline-flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
            <input type="checkbox" checked={allChecked} onChange={toggleAll} />
            选择当前页全部题目
          </label>
          {items.map((question) => (
            <div key={question.id} className="rounded-2xl border border-[var(--color-border)] bg-white/70 p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="flex min-w-0 gap-3">
                  <input className="mt-1" type="checkbox" checked={selectedIds.has(question.id)} onChange={() => toggleOne(question.id)} />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge tone={statusTone(question.review_status)}>{question.review_status || "pending"}</StatusBadge>
                      <StatusBadge tone={question.is_active ? "success" : "neutral"}>{question.is_active ? "启用" : "停用"}</StatusBadge>
                      <span className="text-xs text-[var(--color-text-hint)]">{question.subject || "未分类"} · {question.question_type || "未标注题型"} · 难度 {question.difficulty}</span>
                    </div>
                    <p className="mt-3 whitespace-pre-wrap font-semibold text-[var(--ink)]">{textFromContent(question.content) || `题目 #${question.id}`}</p>
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap gap-2">
                  <Button variant="secondary" onClick={() => openDetail(question.id)}>
                    <FileQuestion className="h-4 w-4" />
                    详情
                  </Button>
                  <Button variant="secondary" onClick={() => setConfirmState({ action: "single-approve", id: question.id })}>通过</Button>
                  <Button variant="danger" onClick={() => setConfirmState({ action: "single-reject", id: question.id })}>拒绝</Button>
                </div>
              </div>
            </div>
          ))}
          {!questions.isLoading && items.length === 0 ? <p className="py-10 text-center text-sm text-[var(--color-text-hint)]">暂无题目</p> : null}
          {questions.isError ? <p className="text-sm text-[var(--color-danger)]">题库接口当前不可用，若 router 未挂载则属于后端阻塞。</p> : null}
        </CardContent>
      </Card>

      {selectedQuestionId !== null ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.28)]" onClick={() => setSelectedQuestionId(null)}>
          <aside className="h-full w-full max-w-3xl overflow-y-auto bg-white p-6 shadow-[var(--shadow-floating)]" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">题目详情</h3>
              <Button variant="ghost" onClick={() => setSelectedQuestionId(null)}>关闭</Button>
            </div>
            {selectedQuestion ? (
              <div className="mt-6 space-y-5 text-sm">
                {[
                  ["题干", textFromContent(selectedQuestion.content)],
                  ["选项", renderJson(selectedQuestion.options)],
                  ["答案", selectedQuestion.answer],
                  ["解析", selectedQuestion.analysis],
                  ["知识点", renderJson(selectedQuestion.knowledge_points)],
                  ["难度", selectedQuestion.difficulty],
                ].map(([label, value]) => (
                  <section key={String(label)} className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                    <p className="font-semibold text-[var(--ink)]">{label}</p>
                    <pre className="mt-2 whitespace-pre-wrap font-sans text-[var(--color-text-secondary)]">{renderJson(value)}</pre>
                  </section>
                ))}
                <section className="rounded-2xl border border-[var(--color-border)] p-4">
                  <p className="font-semibold text-[var(--ink)]">版本历史</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(versions.data?.items ?? []).map((version) => (
                      <Button key={version.id} variant={selectedVersion === version.version ? "primary" : "secondary"} onClick={() => setSelectedVersion(version.version)}>
                        v{version.version}
                      </Button>
                    ))}
                  </div>
                  {versionDetail.data ? (
                    <div className="mt-4 space-y-4">
                      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                        <p className="font-semibold text-[var(--ink)]">对比基线：当前题目 vs v{versionDetail.data.version} 历史快照</p>
                      </div>
                      {renderDiff("题干", textFromContent(selectedQuestion.content), textFromContent(versionDetail.data.content))}
                      {renderDiff("选项", selectedQuestion.options ?? null, versionDetail.data.options ?? null)}
                      {renderDiff("答案", selectedQuestion.answer, versionDetail.data.answer)}
                      {renderDiff("解析", selectedQuestion.analysis ?? null, versionDetail.data.analysis ?? null)}
                      {renderDiff("难度", selectedQuestion.difficulty, versionDetail.data.difficulty)}
                      {renderDiff("知识点", selectedQuestion.knowledge_points ?? null, versionDetail.data.knowledge_points ?? null)}
                      <details className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                        <summary className="cursor-pointer font-semibold text-[var(--ink)]">原始 JSON</summary>
                        <pre className="mt-4 max-h-80 overflow-auto text-xs text-[var(--color-text-secondary)]">
                          {JSON.stringify(versionDetail.data, null, 2)}
                        </pre>
                      </details>
                    </div>
                  ) : null}
                </section>
              </div>
            ) : (
              <p className="mt-6 text-sm text-[var(--color-text-secondary)]">正在加载详情...</p>
            )}
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmState !== null}
        title="确认审核操作"
        description={confirmDescription}
        confirmText="提交"
        danger={confirmState?.action.includes("reject")}
        loading={reviewMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => {
          if (!confirmState) return;
          reviewMutation.mutate(confirmState);
        }}
      />
      {confirmState?.action.includes("reject") ? (
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
