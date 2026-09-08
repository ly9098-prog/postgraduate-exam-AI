"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Archive, ChevronRight, ClipboardCheck, History, Plus, RefreshCw } from "lucide-react";

import {
  EmptyState,
  FieldLabel,
  ManagementNotice,
  ManagementPage,
  ManagementPageHeader,
  ManagementPanel,
  MetricCard,
  MetricStrip,
  StatusBadge,
} from "@/components/admin/management-ui";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { Input } from "@/components/ui/input";
import { apiRequest } from "@/lib/api/client";
import type {
  AdminExamPaperDetail,
  AdminExamPaperListItem,
  AdminExamPaperType,
} from "@/lib/api/types";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";

const typeOptions = [
  { label: "历年真题 · 选择题", value: "past_exam_choice" },
  { label: "模拟卷 · 选择题", value: "mock_choice" },
];

function statusMeta(status: AdminExamPaperListItem["status"]) {
  if (status === "published") return { label: "已发布", tone: "success" as const };
  if (status === "archived") return { label: "已归档", tone: "neutral" as const };
  return { label: "草稿", tone: "warning" as const };
}

function paperKindLabel(paper: AdminExamPaperListItem) {
  if (paper.paper_type === "past_exam_choice") return `${paper.year ?? "年份未设置"} 真题`;
  return paper.year ? `${paper.year} 模拟卷` : "模拟卷";
}

export default function ExamPapersPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "question:write");
  const [title, setTitle] = useState("");
  const [paperType, setPaperType] = useState<AdminExamPaperType>("past_exam_choice");
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [durationMin, setDurationMin] = useState("75");

  const query = useQuery({
    queryKey: ["exam-papers"],
    queryFn: () => apiRequest<AdminExamPaperListItem[]>("/exams/papers"),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<AdminExamPaperDetail>("/exams/papers", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          paper_type: paperType,
          year: paperType === "past_exam_choice" ? Number(year) : (year ? Number(year) : null),
          duration_sec: durationMin ? Math.max(1, Number(durationMin)) * 60 : null,
        }),
      }),
    onSuccess: async (paper) => {
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
      router.push(`/exams/${paper.id}`);
    },
  });

  const papers = query.data ?? [];
  const summary = useMemo(() => ({
    total: papers.length,
    draft: papers.filter((paper) => paper.status === "draft").length,
    published: papers.filter((paper) => paper.status === "published").length,
    attempts: papers.reduce((total, paper) => total + paper.attempt_count, 0),
  }), [papers]);

  return (
    <ManagementPage>
      <ManagementPageHeader
        icon={<ClipboardCheck className="h-5 w-5" />}
        title="试卷管理"
        description="集中维护历年真题与模拟卷的题序、分值和发布状态。已发布试卷固定题目版本，题库后续编辑不会影响历史作答。"
        meta={
          <>
            <StatusBadge tone="accent">仅支持单选题</StatusBadge>
            <span>发布后冻结题序与题目版本</span>
          </>
        }
        actions={
          <Button variant="secondary" onClick={() => query.refetch()} disabled={query.isFetching}>
            <RefreshCw className={`h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} />
            刷新
          </Button>
        }
      />

      <MetricStrip className="sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={<ClipboardCheck className="h-4 w-4" />} label="全部试卷" value={summary.total} hint="包含草稿、已发布与已归档" />
        <MetricCard icon={<Plus className="h-4 w-4" />} label="待整理草稿" value={summary.draft} hint="仍可调整题目和基础信息" tone={summary.draft > 0 ? "warning" : "default"} />
        <MetricCard icon={<Archive className="h-4 w-4" />} label="已发布" value={summary.published} hint="题目版本已冻结" tone="success" />
        <MetricCard icon={<History className="h-4 w-4" />} label="历史作答" value={summary.attempts} hint="所有试卷累计作答次数" tone="accent" />
      </MetricStrip>

      {canWrite ? (
        <ManagementPanel
          variant="quiet"
          title="新建试卷"
          description="先建立草稿，再进入组卷页补充题目、分值和来源信息。"
          icon={<Plus className="h-4 w-4" />}
        >
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(260px,2fr)_minmax(180px,1fr)_140px_160px_auto] xl:items-end">
            <label>
              <FieldLabel>试卷名称</FieldLabel>
              <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：2025 年真题选择题" />
            </label>
            <label>
              <FieldLabel>类型</FieldLabel>
              <CustomSelect value={paperType} options={typeOptions} onChange={(value) => setPaperType(value as AdminExamPaperType)} clearable={false} />
            </label>
            <label>
              <FieldLabel>年份</FieldLabel>
              <Input value={year} onChange={(event) => setYear(event.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="2025" />
            </label>
            <label>
              <FieldLabel>建议时长（分钟）</FieldLabel>
              <Input value={durationMin} onChange={(event) => setDurationMin(event.target.value.replace(/\D/g, ""))} placeholder="75" />
            </label>
            <Button
              className="w-full xl:w-auto"
              onClick={() => createMutation.mutate()}
              disabled={!title.trim() || createMutation.isPending || (paperType === "past_exam_choice" && year.length !== 4)}
            >
              <Plus className="h-4 w-4" />
              创建草稿
            </Button>
          </div>
          {createMutation.isError ? <ManagementNotice className="mt-3" tone="danger">创建失败，请检查名称、年份和时长后重试。</ManagementNotice> : null}
        </ManagementPanel>
      ) : null}

      <ManagementPanel
        variant="focus"
        title="试卷列表"
        description={query.isLoading ? "正在读取试卷数据" : `共 ${papers.length} 份试卷，点击任意一行进入组卷详情。`}
        contentClassName="p-0"
      >
        <div className="hidden overflow-x-auto md:block">
          <table className="w-full min-w-[920px] text-sm">
            <thead className="bg-[#f4f7f9] text-left text-xs font-medium text-[var(--color-text-secondary)]">
              <tr>
                <th className="px-5 py-3">试卷</th>
                <th className="px-4 py-3">类型</th>
                <th className="px-4 py-3 text-right">题目 / 分值</th>
                <th className="px-4 py-3 text-right">建议时长</th>
                <th className="px-4 py-3 text-right">历史作答</th>
                <th className="px-4 py-3">状态</th>
                <th className="w-12 px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {papers.map((paper) => {
                const status = statusMeta(paper.status);
                return (
                  <tr
                    key={paper.id}
                    tabIndex={0}
                    role="button"
                    onClick={() => router.push(`/exams/${paper.id}`)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") router.push(`/exams/${paper.id}`);
                    }}
                    className="border-t border-[var(--color-border-light)] transition-colors hover:bg-[rgba(74,111,138,0.035)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-primary)]"
                  >
                    <td className="px-5 py-4">
                      <p className="max-w-[460px] truncate font-semibold text-[var(--ink)]">{paper.title}</p>
                      <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">版本 v{paper.version}{paper.source ? ` · ${paper.source}` : ""}</p>
                    </td>
                    <td className="px-4 py-4 text-[var(--color-text-secondary)]">{paperKindLabel(paper)}</td>
                    <td className="px-4 py-4 text-right tabular-nums"><span className="font-semibold text-[var(--ink)]">{paper.question_count}</span><span className="text-[var(--color-text-tertiary)]"> / {paper.total_choice_score} 分</span></td>
                    <td className="px-4 py-4 text-right tabular-nums text-[var(--color-text-secondary)]">{paper.duration_sec ? `${Math.round(paper.duration_sec / 60)} 分钟` : "不限时"}</td>
                    <td className="px-4 py-4 text-right tabular-nums text-[var(--color-text-secondary)]">{paper.attempt_count}</td>
                    <td className="px-4 py-4"><StatusBadge tone={status.tone}>{status.label}</StatusBadge></td>
                    <td className="px-4 py-4 text-[var(--color-text-tertiary)]"><ChevronRight className="h-4 w-4" /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="divide-y divide-[var(--color-border-light)] md:hidden">
          {papers.map((paper) => {
            const status = statusMeta(paper.status);
            return (
              <button key={paper.id} className="flex w-full items-start gap-3 px-4 py-4 text-left hover:bg-[rgba(74,111,138,0.035)]" onClick={() => router.push(`/exams/${paper.id}`)}>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-semibold text-[var(--ink)]">{paper.title}</p>
                    <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{paperKindLabel(paper)} · {paper.question_count} 题 · {paper.total_choice_score} 分</p>
                  <p className="mt-2 text-[11px] text-[var(--color-text-tertiary)]">v{paper.version} · 历史作答 {paper.attempt_count} 次</p>
                </div>
                <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-[var(--color-text-tertiary)]" />
              </button>
            );
          })}
        </div>

        {!query.isLoading && papers.length === 0 ? <EmptyState>还没有试卷。创建一份草稿后即可开始组卷。</EmptyState> : null}
        {query.isLoading ? <EmptyState>正在加载试卷列表...</EmptyState> : null}
      </ManagementPanel>
    </ManagementPage>
  );
}
