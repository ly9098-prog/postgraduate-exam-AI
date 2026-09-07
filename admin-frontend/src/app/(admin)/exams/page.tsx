"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { BookOpenCheck, Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
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

function statusLabel(status: string) {
  if (status === "published") return "已发布";
  if (status === "archived") return "已归档";
  return "草稿";
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

  const papers = query.data || [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-[var(--color-primary)]">408-EXAM · CHOICE ONLY</p>
          <h1 className="font-display text-3xl font-bold text-[var(--ink)]">408 选择题试卷</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--color-text-secondary)]">
            真题与模拟卷只管理 single_choice。已发布试卷固定题目版本，历史成绩不会随题库后续编辑改变。
          </p>
        </div>
        <Button variant="secondary" onClick={() => query.refetch()} disabled={query.isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} />刷新
        </Button>
      </div>

      {canWrite ? (
        <Card>
          <CardHeader>
            <h2 className="font-display text-xl font-bold text-[var(--ink)]">新建选择题卷</h2>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-5">
            <div className="md:col-span-2">
              <label className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">试卷名称</label>
              <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：2025 年 408 真题 · 选择题" />
            </div>
            <div>
              <label className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">类型</label>
              <CustomSelect value={paperType} options={typeOptions} onChange={(value) => setPaperType(value as AdminExamPaperType)} />
            </div>
            <div>
              <label className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">年份</label>
              <Input value={year} onChange={(event) => setYear(event.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="2025" />
            </div>
            <div>
              <label className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">建议时长（分钟）</label>
              <Input value={durationMin} onChange={(event) => setDurationMin(event.target.value.replace(/\D/g, ""))} placeholder="75" />
            </div>
            <div className="md:col-span-5 flex justify-end">
              <Button
                onClick={() => createMutation.mutate()}
                disabled={!title.trim() || createMutation.isPending || (paperType === "past_exam_choice" && year.length !== 4)}
              >
                <Plus className="mr-2 h-4 w-4" />创建并组卷
              </Button>
            </div>
            {createMutation.isError ? <p className="md:col-span-5 text-sm text-red-600">创建失败，请检查名称、年份和时长。</p> : null}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        {papers.map((paper) => (
          <Card key={paper.id} className="cursor-pointer transition hover:-translate-y-0.5" onClick={() => router.push(`/exams/${paper.id}`)}>
            <CardContent className="flex gap-4">
              <div className="rounded-2xl bg-blue-50 p-3 text-blue-700"><BookOpenCheck className="h-6 w-6" /></div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="truncate font-display text-lg font-bold text-[var(--ink)]">{paper.title}</h2>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">{statusLabel(paper.status)}</span>
                </div>
                <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
                  {paper.paper_type === "past_exam_choice" ? `${paper.year || "—"} 真题` : "模拟卷"} · {paper.question_count} 题 · 选择题总分 {paper.total_choice_score} · {paper.duration_sec ? `${Math.round(paper.duration_sec / 60)} 分钟` : "不限时"}
                </p>
                <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">历史考试记录 {paper.attempt_count} 次 · 试卷版本 v{paper.version}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {!query.isLoading && papers.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-sm text-[var(--color-text-secondary)]">还没有选择题试卷，先创建一份草稿。</CardContent></Card>
      ) : null}
    </div>
  );
}
