"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  ClipboardCheck,
  History,
  ListOrdered,
  Plus,
  Sigma,
  Timer,
  Save,
  Search,
  Trash2,
  GripVertical,
} from "lucide-react";

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
  ManagementSkeletonRows,
} from "@/components/admin/management-ui";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { CustomSelect } from "@/components/ui/custom-select";
import { Input } from "@/components/ui/input";
import { apiRequest, toQuery } from "@/lib/api/client";
import type {
  AdminExamPastExamCandidatesResponse,
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

const CORE_SUBJECT_CODES = new Set([
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

function statusMeta(status: AdminExamPaperDetail["status"]) {
  if (status === "published") return { label: "已发布", tone: "success" as const, summary: "题序与题目版本已冻结" };
  if (status === "archived") return { label: "已归档", tone: "neutral" as const, summary: "不再出现在前台试卷列表" };
  return { label: "草稿", tone: "warning" as const, summary: "可继续编辑题目与基础信息" };
}

function normalizeQuickYear(value: string): number | null {
  const digits = value.replace(/\D/g, "");
  if (digits.length === 2) return 2000 + Number(digits);
  if (digits.length === 4) return Number(digits);
  return null;
}

export default function ExamPaperDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const paperRef = params.id;
  const isLegacyNumericRef = /^\d+$/.test(paperRef);
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "question:write");
  const [title, setTitle] = useState("");
  const [paperType, setPaperType] = useState<AdminExamPaperType>("past_exam_choice");
  const [year, setYear] = useState("");
  const [source, setSource] = useState("");
  const [durationMin, setDurationMin] = useState("");
  const [items, setItems] = useState<DraftItem[]>([]);
  const [keyword, setKeyword] = useState("");
  const [quickYear, setQuickYear] = useState("");
  const [quickMessage, setQuickMessage] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<"publish" | "archive" | null>(null);

  const paperQuery = useQuery({
    queryKey: ["exam-paper", paperRef],
    queryFn: () =>
      apiRequest<AdminExamPaperDetail>(
        isLegacyNumericRef
          ? `/exams/papers/${encodeURIComponent(paperRef)}`
          : `/exams/papers/public/${encodeURIComponent(paperRef)}`,
      ),
    enabled: Boolean(paperRef),
  });
  const paper = paperQuery.data;
  const isDraft = paper?.status === "draft";
  const mutationPaperRef = paper?.public_id || paperRef;

  useEffect(() => {
    if (!paper || !isLegacyNumericRef) return;
    router.replace(`/exams/${paper.public_id}`);
  }, [isLegacyNumericRef, paper, router]);

  useEffect(() => {
    if (!paper) return;
    setTitle(paper.title);
    setPaperType(paper.paper_type);
    setYear(paper.year ? String(paper.year) : "");
    setSource(paper.source || "");
    setDurationMin(paper.duration_sec ? String(Math.round(paper.duration_sec / 60)) : "");
    setItems(paper.items.map(toDraftItem));
    setQuickYear((current) => current || (paper.year ? String(paper.year).slice(-2) : ""));
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
    () => (candidateQuery.data?.items || []).filter((question) => CORE_SUBJECT_CODES.has(String(question.subject_code || "")) && !selectedIds.has(question.id)),
    [candidateQuery.data, selectedIds],
  );

  const metaMutation = useMutation({
    mutationFn: () =>
      apiRequest<AdminExamPaperDetail>(`/exams/papers/public/${encodeURIComponent(mutationPaperRef)}`, {
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
      await queryClient.invalidateQueries({ queryKey: ["exam-paper", paperRef] });
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
    },
  });

  const itemsMutation = useMutation({
    mutationFn: () =>
      apiRequest<AdminExamPaperDetail>(`/exams/papers/public/${encodeURIComponent(mutationPaperRef)}/items`, {
        method: "PUT",
        body: JSON.stringify({
          items: items.map((item) => ({ question_id: item.question_id, score: Number(item.score) })),
        }),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["exam-paper", paperRef] });
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
    },
  });

  const stateMutation = useMutation({
    mutationFn: (action: "publish" | "archive") =>
      apiRequest<AdminExamPaperDetail>(`/exams/papers/public/${encodeURIComponent(mutationPaperRef)}/${action}`, { method: "POST" }),
    onSuccess: async () => {
      setConfirmAction(null);
      await queryClient.invalidateQueries({ queryKey: ["exam-paper", paperRef] });
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
    },
  });

  const quickPastExamMutation = useMutation({
    mutationFn: async () => {
      const targetYear = normalizeQuickYear(quickYear);
      if (!targetYear || targetYear < 2000 || targetYear > 2100) {
        throw new Error("请输入 2 位年份，例如 14；也可输入完整年份 2014。");
      }
      if (paper?.paper_type === "past_exam_choice" && paper.year && targetYear !== paper.year) {
        throw new Error(`当前试卷年份为 ${paper.year}，请输入 ${String(paper.year).slice(-2)}。`);
      }
      return apiRequest<AdminExamPastExamCandidatesResponse>(
        `/exams/past-exam-candidates${toQuery({ year: targetYear })}`,
      );
    },
    onSuccess: (result) => {
      const existing = new Set(items.map((item) => item.question_id));
      const addable = result.items.filter((item) => !existing.has(item.question_id));
      if (addable.length) {
        setItems((current) => [
          ...current,
          ...addable.map((item) => ({
            question_id: item.question_id,
            score: "2",
            subject_name: item.subject_name,
            subject_code: item.subject_code,
            content: item.content,
            year: item.year,
            source: item.source,
            version_is_current: true,
          })),
        ]);
      }
      const skipped = result.total - addable.length;
      setQuickMessage(
        result.total
          ? `已匹配 ${result.total} 道 ${result.year} 真题，新增 ${addable.length} 道${skipped ? `，跳过已添加 ${skipped} 道` : ""}。`
          : `未找到题干以【${result.year}统考真题】或【${result.year} 统考真题】开头的可用单选题。`,
      );
    },
    onError: (error) => {
      setQuickMessage(error instanceof Error ? error.message : "真题匹配失败，请稍后重试。");
    },
  });

  function addCandidate(question: AdminQuestion) {
    setItems((current) => [
      ...current,
      {
        question_id: question.id,
        score: "2",
        subject_name: question.subject_name || "未归类",
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

  if (paperQuery.isLoading) {
    return (
      <ManagementPage>
        <ManagementPageHeader icon={<ClipboardCheck className="h-5 w-5" />} title="试卷工作台" description="正在载入固定题序、版本状态与发布校验。" meta={<span>读取试卷数据</span>} />
        <ManagementPanel variant="focus" title="正在加载" description="题目较多时可能需要几秒钟。" contentClassName="p-0">
          <ManagementSkeletonRows rows={6} />
        </ManagementPanel>
      </ManagementPage>
    );
  }
  if (!paper) {
    return (
      <ManagementPage>
        <ManagementPageHeader icon={<ClipboardCheck className="h-5 w-5" />} title="试卷不可用" description="试卷不存在，或当前账号没有读取权限。" actions={<Button variant="secondary" onClick={() => router.push("/exams")}><ArrowLeft className="h-4 w-4" />返回列表</Button>} />
        <ManagementNotice tone="danger" title="无法打开试卷">请返回列表确认试卷是否仍存在，或检查当前账号权限。</ManagementNotice>
      </ManagementPage>
    );
  }

  const status = statusMeta(paper.status);
  const draftScore = items.reduce((total, item) => total + (Number(item.score) || 0), 0);
  const hasStaleVersion = items.some((item) => item.version_is_current === false);
  const metaDirty = Boolean(isDraft && (
    title.trim() !== paper.title
    || paperType !== paper.paper_type
    || (year ? Number(year) : null) !== (paper.year ?? null)
    || (source.trim() || null) !== (paper.source || null)
    || (durationMin ? Number(durationMin) * 60 : null) !== (paper.duration_sec ?? null)
  ));
  const itemsDirty = Boolean(isDraft && (
    items.length !== paper.items.length
    || items.some((item, index) => {
      const saved = paper.items[index];
      return !saved || saved.question_id !== item.question_id || Number(saved.score) !== Number(item.score);
    })
  ));

  return (
    <ManagementPage>
      <ManagementPageHeader
        icon={<ClipboardCheck className="h-5 w-5" />}
        title={paper.title}
        description={isDraft && (metaDirty || itemsDirty) ? `${status.summary} · 当前有未保存修改` : status.summary}
        meta={
          <>
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            <span>版本 v{paper.version}</span>
            {paper.source ? <span>{paper.source}</span> : null}
          </>
        }
        actions={
          <>
            <Button variant="secondary" onClick={() => router.push("/exams")}>
              <ArrowLeft className="h-4 w-4" />
              返回列表
            </Button>
            {paper.status === "draft" && canWrite ? (
              <Button onClick={() => setConfirmAction("publish")} disabled={paper.validation_errors.length > 0 || stateMutation.isPending}>
                <CheckCircle2 className="h-4 w-4" />
                发布
              </Button>
            ) : null}
            {paper.status !== "archived" && canWrite ? (
              <Button variant="secondary" onClick={() => setConfirmAction("archive")} disabled={stateMutation.isPending}>
                归档
              </Button>
            ) : null}
          </>
        }
      />

      <MetricStrip className="sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={<ListOrdered className="h-4 w-4" />} label="当前题目" value={items.length} hint={isDraft ? "保存组卷后写入固定题序" : "已按发布版本冻结"} />
        <MetricCard icon={<Sigma className="h-4 w-4" />} label="选择题总分" value={`${draftScore} 分`} hint={isDraft ? `已保存 ${paper.total_choice_score} 分` : "发布时固定"} tone="accent" />
        <MetricCard icon={<History className="h-4 w-4" />} label="历史作答" value={paper.attempt_count} hint="已产生的考试记录" />
        <MetricCard icon={<Timer className="h-4 w-4" />} label="建议时长" value={paper.duration_sec ? `${Math.round(paper.duration_sec / 60)} 分` : "不限时"} hint={hasStaleVersion ? "题库存在新版本，已固定版本不受影响" : "题目版本状态正常"} tone={hasStaleVersion ? "warning" : "default"} />
      </MetricStrip>

      {paper.validation_errors.length > 0 ? (
        <ManagementNotice tone="warning" title={`发布前还有 ${paper.validation_errors.length} 项需要处理`}>
          <ul className="space-y-1 text-xs leading-5">
            {paper.validation_errors.map((error) => <li key={error}>• {error}</li>)}
          </ul>
        </ManagementNotice>
      ) : null}

      {hasStaleVersion ? (
        <ManagementNotice tone="info" title="题库中已有题目的新版本">
          当前试卷仍引用已固定的题目版本；这不会改变历史试卷。如需采用新版本，请在草稿卷中重新添加对应题目。
        </ManagementNotice>
      ) : null}

      {isDraft && canWrite && paper.paper_type === "past_exam_choice" ? (
        <ManagementPanel
          variant="quiet"
          title="快速添加真题"
          description="只输入年份后两位即可一次匹配该年份全部可用单选题；同时兼容题干前缀中有无空格。"
          icon={<Plus className="h-4 w-4" />}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-[132px_minmax(0,1fr)] sm:items-end">
              <label>
                <FieldLabel>年份后两位</FieldLabel>
                <Input
                  className="h-10 text-center font-semibold tabular-nums"
                  value={quickYear}
                  onChange={(event) => {
                    setQuickYear(event.target.value.replace(/\D/g, "").slice(0, 4));
                    setQuickMessage(null);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !quickPastExamMutation.isPending) {
                      event.preventDefault();
                      quickPastExamMutation.mutate();
                    }
                  }}
                  placeholder="14"
                  inputMode="numeric"
                  aria-label="真题年份"
                />
              </label>
              <div className="min-w-0 rounded-xl border border-[var(--color-border-light)] bg-[rgba(239,235,229,0.34)] px-3 py-2.5 text-xs leading-5 text-[var(--color-text-secondary)]">
                输入 <strong className="font-semibold text-[var(--ink)]">14</strong> 将匹配
                <span className="mx-1 font-mono text-[11px]">【2014统考真题】</span>
                与
                <span className="ml-1 font-mono text-[11px]">【2014 统考真题】</span>
                开头的题目；重复题目自动跳过。
              </div>
            </div>
            <Button
              className="h-10 shrink-0 px-5"
              onClick={() => quickPastExamMutation.mutate()}
              disabled={!quickYear || quickPastExamMutation.isPending}
            >
              <Plus className="h-4 w-4" />
              {quickPastExamMutation.isPending ? "正在匹配" : "匹配并加入"}
            </Button>
          </div>
          {quickMessage ? (
            <div className={`mt-3 rounded-xl border px-3 py-2.5 text-xs leading-5 ${quickPastExamMutation.isError ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}>
              {quickMessage}
            </div>
          ) : null}
        </ManagementPanel>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.75fr)] xl:items-start">
        <ManagementPanel
          variant="focus"
          title="固定题序"
          description="草稿阶段可调整题序与分值。保存组卷时会固定当前 QuestionVersion，发布后不再直接替换。"
          actions={isDraft && canWrite ? (
            <>
              <StatusBadge tone={itemsDirty ? "warning" : "success"}>{itemsDirty ? "题序未保存" : "题序已同步"}</StatusBadge>
              <Button className="transition-transform active:scale-[0.98] motion-reduce:transform-none" onClick={() => itemsMutation.mutate()} disabled={!items.length || !itemsDirty || itemsMutation.isPending || items.some((item) => Number(item.score) <= 0)}>
                <Save className="h-4 w-4" />
                保存组卷
              </Button>
            </>
          ) : <StatusBadge tone="neutral">只读题序</StatusBadge>}
          contentClassName="p-0"
        >
          <div className="divide-y divide-[var(--color-border-light)]">
            {items.map((item, index) => (
              <div key={`${item.question_id}-${index}`} className="group relative flex gap-3 px-4 py-4 transition-colors duration-200 before:absolute before:bottom-[-1px] before:left-[35px] before:top-12 before:w-px before:bg-[var(--mgmt-line)] last:before:hidden hover:bg-[rgba(74,111,138,0.032)] sm:px-5 sm:before:left-[39px]">
                <div className="relative z-[1] grid h-8 w-8 shrink-0 place-items-center rounded-[9px] border border-[rgba(74,111,138,0.16)] bg-[var(--mgmt-steel)] text-xs font-bold tabular-nums text-[var(--color-primary-dark)] shadow-[0_0_0_4px_var(--mgmt-paper)] transition-[transform,background-color] duration-200 group-hover:-translate-y-px group-hover:bg-white motion-reduce:transform-none">
                  {index + 1}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--color-text-tertiary)]">
                    <span className="font-semibold text-[var(--color-text-secondary)]">{item.subject_name}</span>
                    <span>Q#{item.question_id}</span>
                    {item.year ? <span>{item.year}</span> : null}
                    {item.version_is_current === false ? <StatusBadge tone="warning">题库已有新版本</StatusBadge> : null}
                  </div>
                  <p className="mt-2 line-clamp-3 text-sm leading-6 text-[var(--ink)]">{stemFromContent(item.content) || "题干包含结构化内容或图片"}</p>
                  {item.source ? <p className="mt-1 truncate text-[11px] text-[var(--color-text-tertiary)]">来源：{item.source}</p> : null}
                </div>
                <div className="flex shrink-0 items-start gap-2.5">
                  {isDraft && canWrite ? <GripVertical className="mt-8 hidden h-4 w-4 text-[var(--color-text-hint)] opacity-50 transition-opacity group-hover:opacity-100 lg:block" aria-hidden="true" /> : null}
                  <label className="w-20">
                    <FieldLabel>分值</FieldLabel>
                    <Input
                      className="text-center tabular-nums"
                      value={item.score}
                      disabled={!isDraft || !canWrite}
                      onChange={(event) => setItems((current) => current.map((entry, itemIndex) => itemIndex === index ? { ...entry, score: event.target.value.replace(/[^\d.]/g, "") } : entry))}
                    />
                  </label>
                  {isDraft && canWrite ? (
                    <div className="flex flex-col gap-1.5 pt-[22px]">
                      <Button className="h-8 w-8 px-0 transition-[background-color,transform] hover:-translate-y-px active:translate-y-0 motion-reduce:transform-none" size="sm" variant="ghost" onClick={() => moveItem(index, -1)} disabled={index === 0} aria-label="上移题目">
                        <ArrowUp className="h-4 w-4" />
                      </Button>
                      <Button className="h-8 w-8 px-0 transition-[background-color,transform] hover:translate-y-px active:translate-y-0 motion-reduce:transform-none" size="sm" variant="ghost" onClick={() => moveItem(index, 1)} disabled={index === items.length - 1} aria-label="下移题目">
                        <ArrowDown className="h-4 w-4" />
                      </Button>
                      <Button className="h-8 w-8 px-0 text-red-600 transition-[background-color,transform,color] hover:scale-[1.04] hover:bg-red-50 hover:text-red-700 active:scale-100 motion-reduce:transform-none" size="sm" variant="ghost" onClick={() => setItems((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label="移除题目">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
          {!items.length ? <EmptyState>还没有题目。草稿阶段可从下方题库中添加单选题。</EmptyState> : null}
        </ManagementPanel>

        <ManagementPanel
          variant="quiet"
          title="试卷信息"
          description={isDraft ? "基础信息可在草稿阶段修改。" : "当前试卷已锁定为只读。"}
          className="xl:sticky xl:top-5"
          actions={<StatusBadge tone={metaDirty ? "warning" : isDraft ? "success" : "neutral"}>{metaDirty ? "信息未保存" : isDraft ? "信息已同步" : "只读"}</StatusBadge>}
        >
          <div className="grid gap-x-4 gap-y-4 sm:grid-cols-2">
            <label className="sm:col-span-2">
              <FieldLabel>名称</FieldLabel>
              <Input className="h-10" value={title} disabled={!isDraft || !canWrite} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label>
              <FieldLabel>类型</FieldLabel>
              <CustomSelect className="h-10" value={paperType} disabled={!isDraft || !canWrite} options={typeOptions} onChange={(value) => setPaperType(value as AdminExamPaperType)} clearable={false} />
            </label>
            <label>
              <FieldLabel>年份</FieldLabel>
              <Input className="h-10 tabular-nums" value={year} disabled={!isDraft || !canWrite} onChange={(event) => setYear(event.target.value.replace(/\D/g, "").slice(0, 4))} />
            </label>
            <label>
              <FieldLabel>建议时长（分钟）</FieldLabel>
              <Input className="h-10 tabular-nums" value={durationMin} disabled={!isDraft || !canWrite} onChange={(event) => setDurationMin(event.target.value.replace(/\D/g, ""))} />
            </label>
            <label>
              <FieldLabel>来源</FieldLabel>
              <Input className="h-10" value={source} disabled={!isDraft || !canWrite} onChange={(event) => setSource(event.target.value)} placeholder="全国硕士研究生招生考试" />
            </label>
            {isDraft && canWrite ? (
              <div className="flex justify-end border-t border-[var(--color-border-light)] pt-4 sm:col-span-2">
                <Button className="w-full transition-transform active:scale-[0.99] motion-reduce:transform-none sm:w-auto" onClick={() => metaMutation.mutate()} disabled={!title.trim() || !metaDirty || metaMutation.isPending}>
                  <Save className="h-4 w-4" />
                  保存信息
                </Button>
              </div>
            ) : null}
          </div>
        </ManagementPanel>
      </div>

      {isDraft && canWrite ? (
        <ManagementPanel
          variant="quiet"
          title="从题库添加单选题"
          description={`仅展示已审核、已启用且属于核心科目的单选题；当前可选 ${candidates.length} 道。`}
          icon={<Plus className="h-4 w-4" />}
          actions={
            <label className="relative block w-full sm:w-72">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-tertiary)]" />
              <Input className="pl-9" value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索题干关键词" />
            </label>
          }
          contentClassName="p-0"
        >
          <div className="grid md:grid-cols-2">
            {candidates.map((question) => (
              <div key={question.id} className="group flex gap-3 border-b border-[var(--color-border-light)] px-4 py-4 transition-colors duration-200 hover:bg-[rgba(74,111,138,0.03)] md:odd:border-r md:px-5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap gap-2 text-[11px] text-[var(--color-text-tertiary)]">
                    <span className="font-semibold text-[var(--color-text-secondary)]">{question.subject_name}</span>
                    <span>Q#{question.id}</span>
                    {question.year ? <span>{question.year}</span> : null}
                  </div>
                  <p className="mt-2 line-clamp-3 text-sm leading-6 text-[var(--ink)]">{stemFromContent(question.content) || "结构化题干"}</p>
                </div>
                <Button className="h-9 w-9 shrink-0 px-0 transition-[transform,box-shadow] duration-200 group-hover:-translate-y-px group-hover:shadow-[0_6px_14px_rgba(31,49,61,0.08)] active:translate-y-0 motion-reduce:transform-none" variant="secondary" onClick={() => addCandidate(question)} aria-label={`添加题目 ${question.id}`}>
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
          {!candidateQuery.isLoading && candidates.length === 0 ? <EmptyState>没有更多符合条件的单选题。</EmptyState> : null}
          {candidateQuery.isLoading ? <ManagementSkeletonRows rows={4} /> : null}
        </ManagementPanel>
      ) : null}

      {(metaMutation.isError || itemsMutation.isError || stateMutation.isError) ? (
        <ManagementNotice tone="danger" title="操作未完成">请检查发布校验，或刷新数据后重试。</ManagementNotice>
      ) : null}

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
    </ManagementPage>
  );
}
