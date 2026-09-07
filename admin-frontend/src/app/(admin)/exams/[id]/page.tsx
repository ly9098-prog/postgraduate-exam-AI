"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  Plus,
  Save,
  Search,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { apiRequest, toQuery } from "@/lib/api/client";
import type {
  AdminExamPaperDetail,
  AdminExamPaperQuestionItem,
  AdminExamPaperType,
  AdminQuestion,
  PaginatedResponse,
} from "@/lib/api/types";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";

const typeOptions = [
  { label: "历年真题 · 选择题", value: "past_exam_choice" },
  { label: "模拟卷 · 选择题", value: "mock_choice" },
];
const CORE_408 = new Set([
  "data_structure",
  "computer_organization",
  "operating_system",
  "computer_network",
]);

type DraftItem = {
  question_id: number;
  score: string;
  subject_name: string;
  subject_code: string;
  content: Record<string, unknown>;
  year?: number | null;
  source?: string | null;
  question_version_id?: number;
  version_is_current?: boolean;
};

function stemFromContent(content: unknown): string {
  if (!content || typeof content !== "object" || Array.isArray(content)) return "";
  const record = content as Record<string, unknown>;
  for (const key of ["stem", "text", "question", "content"]) {
    if (typeof record[key] === "string" && String(record[key]).trim()) return String(record[key]).trim();
  }
  if (Array.isArray(record.segments)) {
    return record.segments
      .map((segment) => {
        if (!segment || typeof segment !== "object" || Array.isArray(segment)) return "";
        const item = segment as Record<string, unknown>;
        return typeof item.text === "string" ? item.text : "";
      })
      .filter(Boolean)
      .join(" ")
      .trim();
  }
  return "";
}

function toDraftItem(item: AdminExamPaperQuestionItem): DraftItem {
  return {
    question_id: item.question_id,
    score: String(item.score),
    subject_name: item.subject_name,
    subject_code: item.subject_code,
    content: item.content,
    year: item.year,
    source: item.source,
    question_version_id: item.question_version_id,
    version_is_current: item.version_is_current,
  };
}

export default function ExamPaperDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const paperId = Number(params.id);
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "question:write");
  const [title, setTitle] = useState("");
  const [paperType, setPaperType] = useState<AdminExamPaperType>("past_exam_choice");
  const [year, setYear] = useState("");
  const [source, setSource] = useState("");
  const [durationMin, setDurationMin] = useState("");
  const [items, setItems] = useState<DraftItem[]>([]);
  const [keyword, setKeyword] = useState("");
  const [confirmAction, setConfirmAction] = useState<"publish" | "archive" | null>(null);

  const paperQuery = useQuery({
    queryKey: ["exam-paper", paperId],
    queryFn: () => apiRequest<AdminExamPaperDetail>(`/exams/papers/${paperId}`),
    enabled: Number.isFinite(paperId) && paperId > 0,
  });
  const paper = paperQuery.data;
  const isDraft = paper?.status === "draft";

  useEffect(() => {
    if (!paper) return;
    setTitle(paper.title);
    setPaperType(paper.paper_type);
    setYear(paper.year ? String(paper.year) : "");
    setSource(paper.source || "");
    setDurationMin(paper.duration_sec ? String(Math.round(paper.duration_sec / 60)) : "");
    setItems(paper.items.map(toDraftItem));
  }, [paper]);

  const candidateQuery = useQuery({
    queryKey: ["exam-question-candidates", keyword],
    queryFn: () =>
      apiRequest<PaginatedResponse<AdminQuestion>>(
        `/questions?${toQuery({
          page: 1,
          page_size: 100,
          question_type: "single_choice",
          review_status: "approved",
          is_active: true,
          keyword: keyword.trim() || undefined,
        })}`,
      ),
    enabled: Boolean(isDraft && canWrite),
  });

  const selectedIds = useMemo(() => new Set(items.map((item) => item.question_id)), [items]);
  const candidates = useMemo(
    () => (candidateQuery.data?.items || []).filter((question) => CORE_408.has(String(question.subject_code || "")) && !selectedIds.has(question.id)),
    [candidateQuery.data, selectedIds],
  );

  const metaMutation = useMutation({
    mutationFn: () =>
      apiRequest<AdminExamPaperDetail>(`/exams/papers/${paperId}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: title.trim(),
          paper_type: paperType,
          year: year ? Number(year) : null,
          source: source.trim() || null,
          duration_sec: durationMin ? Number(durationMin) * 60 : null,
        }),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["exam-paper", paperId] });
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
    },
  });

  const itemsMutation = useMutation({
    mutationFn: () =>
      apiRequest<AdminExamPaperDetail>(`/exams/papers/${paperId}/items`, {
        method: "PUT",
        body: JSON.stringify({
          items: items.map((item) => ({ question_id: item.question_id, score: Number(item.score) })),
        }),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["exam-paper", paperId] });
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
    },
  });

  const stateMutation = useMutation({
    mutationFn: (action: "publish" | "archive") =>
      apiRequest<AdminExamPaperDetail>(`/exams/papers/${paperId}/${action}`, { method: "POST" }),
    onSuccess: async () => {
      setConfirmAction(null);
      await queryClient.invalidateQueries({ queryKey: ["exam-paper", paperId] });
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
    },
  });

  function addCandidate(question: AdminQuestion) {
    setItems((current) => [
      ...current,
      {
        question_id: question.id,
        score: "2",
        subject_name: question.subject_name || "408",
        subject_code: question.subject_code || "",
        content: question.content,
        year: question.year,
        source: question.source,
        version_is_current: true,
      },
    ]);
  }

  function moveItem(index: number, delta: -1 | 1) {
    setItems((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  if (paperQuery.isLoading) return <div className="py-16 text-center text-sm text-[var(--color-text-secondary)]">正在加载试卷...</div>;
  if (!paper) return <div className="py-16 text-center text-sm text-red-600">试卷不存在或加载失败。</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <Button variant="secondary" onClick={() => router.push("/exams")}><ArrowLeft className="h-4 w-4" /></Button>
          <div>
            <p className="text-sm font-semibold text-[var(--color-primary)]">408-EXAM · v{paper.version}</p>
            <h1 className="font-display text-3xl font-bold text-[var(--ink)]">{paper.title}</h1>
            <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
              {paper.question_count} 题 · 选择题总分 {paper.total_choice_score} · {paper.attempt_count} 次历史作答 · {paper.status === "draft" ? "草稿可编辑" : paper.status === "published" ? "已发布，题目版本已冻结" : "已归档"}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {paper.status === "draft" && canWrite ? <Button onClick={() => setConfirmAction("publish")} disabled={paper.validation_errors.length > 0 || stateMutation.isPending}><CheckCircle2 className="mr-2 h-4 w-4" />发布</Button> : null}
          {paper.status !== "archived" && canWrite ? <Button variant="secondary" onClick={() => setConfirmAction("archive")} disabled={stateMutation.isPending}>归档</Button> : null}
        </div>
      </div>

      {paper.validation_errors.length > 0 ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <div className="flex gap-3"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" /><div><p className="font-semibold">发布前还有 {paper.validation_errors.length} 项需要处理</p><ul className="mt-2 list-disc space-y-1 pl-5">{paper.validation_errors.map((error) => <li key={error}>{error}</li>)}</ul></div></div>
        </div>
      ) : null}

      <Card>
        <CardHeader><h2 className="font-display text-xl font-bold text-[var(--ink)]">试卷信息</h2></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-5">
          <div className="md:col-span-2"><label className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">名称</label><Input value={title} disabled={!isDraft || !canWrite} onChange={(e) => setTitle(e.target.value)} /></div>
          <div><label className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">类型</label><CustomSelect value={paperType} disabled={!isDraft || !canWrite} options={typeOptions} onChange={(value) => setPaperType(value as AdminExamPaperType)} /></div>
          <div><label className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">年份</label><Input value={year} disabled={!isDraft || !canWrite} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} /></div>
          <div><label className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">建议时长（分钟）</label><Input value={durationMin} disabled={!isDraft || !canWrite} onChange={(e) => setDurationMin(e.target.value.replace(/\D/g, ""))} /></div>
          <div className="md:col-span-4"><label className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">来源</label><Input value={source} disabled={!isDraft || !canWrite} onChange={(e) => setSource(e.target.value)} placeholder="例如：全国硕士研究生招生考试" /></div>
          {isDraft && canWrite ? <div className="flex items-end justify-end"><Button onClick={() => metaMutation.mutate()} disabled={!title.trim() || metaMutation.isPending}><Save className="mr-2 h-4 w-4" />保存信息</Button></div> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div><h2 className="font-display text-xl font-bold text-[var(--ink)]">固定题序</h2><p className="mt-1 text-sm text-[var(--color-text-secondary)]">保存组卷时固定当前 QuestionVersion；发布后不可直接替换。</p></div>
            {isDraft && canWrite ? <Button onClick={() => itemsMutation.mutate()} disabled={!items.length || itemsMutation.isPending || items.some((item) => Number(item.score) <= 0)}><Save className="mr-2 h-4 w-4" />保存组卷</Button> : null}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {items.map((item, index) => (
            <div key={`${item.question_id}-${index}`} className="rounded-2xl border border-[var(--color-border)] p-4">
              <div className="flex gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 font-bold text-blue-700">{index + 1}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-secondary)]"><span className="font-semibold text-[var(--ink)]">{item.subject_name}</span><span>Q#{item.question_id}</span>{item.year ? <span>{item.year}</span> : null}{item.source ? <span>{item.source}</span> : null}{item.version_is_current === false ? <span className="font-semibold text-amber-700">题库已产生新版本</span> : null}</div>
                  <p className="mt-2 line-clamp-3 text-sm leading-6 text-[var(--ink)]">{stemFromContent(item.content) || "（题干包含结构化内容/图片）"}</p>
                </div>
                <div className="w-24 shrink-0"><label className="mb-1 block text-xs text-[var(--color-text-secondary)]">分值</label><Input value={item.score} disabled={!isDraft || !canWrite} onChange={(e) => setItems((current) => current.map((entry, i) => i === index ? { ...entry, score: e.target.value.replace(/[^\d.]/g, "") } : entry))} /></div>
                {isDraft && canWrite ? <div className="flex shrink-0 flex-col gap-1"><Button variant="secondary" onClick={() => moveItem(index, -1)} disabled={index === 0}><ArrowUp className="h-4 w-4" /></Button><Button variant="secondary" onClick={() => moveItem(index, 1)} disabled={index === items.length - 1}><ArrowDown className="h-4 w-4" /></Button><Button variant="secondary" onClick={() => setItems((current) => current.filter((_, i) => i !== index))}><Trash2 className="h-4 w-4" /></Button></div> : null}
              </div>
            </div>
          ))}
          {!items.length ? <div className="py-10 text-center text-sm text-[var(--color-text-secondary)]">还没有题目。V1 只允许 single_choice。</div> : null}
        </CardContent>
      </Card>

      {isDraft && canWrite ? (
        <Card>
          <CardHeader><h2 className="font-display text-xl font-bold text-[var(--ink)]">从 408 题库添加单选题</h2></CardHeader>
          <CardContent className="space-y-4">
            <div className="relative max-w-xl"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-tertiary)]" /><Input className="pl-9" value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="按题干关键词搜索（最多显示 100 条）" /></div>
            <div className="grid gap-3 xl:grid-cols-2">
              {candidates.map((question) => (
                <div key={question.id} className="flex gap-3 rounded-2xl border border-[var(--color-border)] p-4">
                  <div className="min-w-0 flex-1"><div className="flex flex-wrap gap-2 text-xs text-[var(--color-text-secondary)]"><span className="font-semibold text-[var(--ink)]">{question.subject_name}</span><span>Q#{question.id}</span>{question.year ? <span>{question.year}</span> : null}</div><p className="mt-2 line-clamp-3 text-sm leading-6">{stemFromContent(question.content) || "（结构化题干）"}</p></div>
                  <Button variant="secondary" onClick={() => addCandidate(question)}><Plus className="h-4 w-4" /></Button>
                </div>
              ))}
            </div>
            {!candidateQuery.isLoading && candidates.length === 0 ? <p className="py-6 text-center text-sm text-[var(--color-text-secondary)]">没有更多符合条件的 408 单选题。</p> : null}
          </CardContent>
        </Card>
      ) : null}

      {(metaMutation.isError || itemsMutation.isError || stateMutation.isError) ? <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">操作失败，请检查发布校验或刷新后重试。</div> : null}

      <ConfirmDialog
        open={Boolean(confirmAction)}
        title={confirmAction === "publish" ? "确认发布这份选择题卷？" : "确认归档这份试卷？"}
        description={confirmAction === "publish" ? "发布后将冻结题目版本和题序，不能直接修改；如需调整应新建版本。" : "归档后不会再出现在小程序试卷列表，但历史考试结果仍可查看。"}
        confirmText={confirmAction === "publish" ? "确认发布" : "确认归档"}
        danger={confirmAction === "archive"}
        loading={stateMutation.isPending}
        onCancel={() => setConfirmAction(null)}
        onConfirm={() => confirmAction && stateMutation.mutate(confirmAction)}
      />
    </div>
  );
}
