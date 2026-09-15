"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Archive, ChevronDown, ChevronRight, ClipboardCheck, History, Plus, RefreshCw, Search } from "lucide-react";

import {
  EmptyState,
  FieldLabel,
  ManagementNotice,
  ManagementPage,
  ManagementPageHeader,
  ManagementPanel,
  ManagementSkeletonRows,
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
import { DEFAULT_EXAM_YEAR, EXAM_YEAR_OPTIONS, isSupportedExamYear } from "@/lib/exam-years";

const typeOptions = [
  { label: "历年真题 · 选择题", value: "past_exam_choice" },
  { label: "模拟卷 · 选择题", value: "mock_choice" },
];

const statusOptions = [
  { label: "全部状态", value: "" },
  { label: "草稿", value: "draft" },
  { label: "已发布", value: "published" },
  { label: "已归档", value: "archived" },
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
  const [year, setYear] = useState(DEFAULT_EXAM_YEAR);
  const [durationMin, setDurationMin] = useState("75");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [settledKeyword, setSettledKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [displayStatusFilter, setDisplayStatusFilter] = useState("");
  const [displayKeyword, setDisplayKeyword] = useState("");
  const [resultsTransitionPhase, setResultsTransitionPhase] = useState<"idle" | "leaving" | "pre-enter" | "entering">("idle");
  const displayedFilterRef = useRef({ status: "", keyword: "" });
  const targetFilterRef = useRef({ status: "", keyword: "" });
  const resultsTransitionPhaseRef = useRef<"idle" | "leaving" | "pre-enter" | "entering">("idle");
  const leaveFallbackTimerRef = useRef<number | null>(null);
  const enterFallbackTimerRef = useRef<number | null>(null);
  const enterFrameRef = useRef<number | null>(null);
  const enterFrame2Ref = useRef<number | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setSettledKeyword(keyword), 160);
    return () => window.clearTimeout(timer);
  }, [keyword]);

  const query = useQuery({
    queryKey: ["exam-papers"],
    queryFn: () => apiRequest<AdminExamPaperListItem[]>("/exams/papers"),
    staleTime: 30_000,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<AdminExamPaperDetail>("/exams/papers", {
        method: "POST",
        exposeErrorDetail: true,
        body: JSON.stringify({
          title: title.trim(),
          paper_type: paperType,
          year: paperType === "past_exam_choice" ? Number(year) : (year ? Number(year) : null),
          duration_sec: durationMin ? Math.max(1, Number(durationMin)) * 60 : null,
        }),
      }),
    onSuccess: async (paper) => {
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
      router.push(`/exams/${paper.public_id}`);
    },
  });

  const papers = query.data ?? [];
  const summary = useMemo(() => ({
    total: papers.length,
    draft: papers.filter((paper) => paper.status === "draft").length,
    published: papers.filter((paper) => paper.status === "published").length,
    attempts: papers.reduce((total, paper) => total + paper.attempt_count, 0),
  }), [papers]);
  const normalizedKeyword = settledKeyword.trim().toLowerCase();

  const updateResultsTransitionPhase = useCallback((phase: "idle" | "leaving" | "pre-enter" | "entering") => {
    resultsTransitionPhaseRef.current = phase;
    setResultsTransitionPhase(phase);
  }, []);

  const clearLeaveFallback = useCallback(() => {
    if (leaveFallbackTimerRef.current !== null) {
      window.clearTimeout(leaveFallbackTimerRef.current);
      leaveFallbackTimerRef.current = null;
    }
  }, []);

  const clearEnterFallback = useCallback(() => {
    if (enterFallbackTimerRef.current !== null) {
      window.clearTimeout(enterFallbackTimerRef.current);
      enterFallbackTimerRef.current = null;
    }
  }, []);

  const clearEnterFrames = useCallback(() => {
    if (enterFrameRef.current !== null) {
      window.cancelAnimationFrame(enterFrameRef.current);
      enterFrameRef.current = null;
    }
    if (enterFrame2Ref.current !== null) {
      window.cancelAnimationFrame(enterFrame2Ref.current);
      enterFrame2Ref.current = null;
    }
  }, []);

  const commitDisplayedFilter = useCallback((nextFilter: { status: string; keyword: string }) => {
    displayedFilterRef.current = nextFilter;
    setDisplayStatusFilter(nextFilter.status);
    setDisplayKeyword(nextFilter.keyword);
  }, []);

  const startResultsEnter = useCallback(() => {
    clearEnterFrames();
    clearEnterFallback();
    updateResultsTransitionPhase("pre-enter");
    enterFrameRef.current = window.requestAnimationFrame(() => {
      enterFrameRef.current = null;
      enterFrame2Ref.current = window.requestAnimationFrame(() => {
        enterFrame2Ref.current = null;
        if (resultsTransitionPhaseRef.current !== "pre-enter") return;
        updateResultsTransitionPhase("entering");
        enterFallbackTimerRef.current = window.setTimeout(() => {
          enterFallbackTimerRef.current = null;
          if (resultsTransitionPhaseRef.current === "entering") updateResultsTransitionPhase("idle");
        }, 260);
      });
    });
  }, [clearEnterFallback, clearEnterFrames, updateResultsTransitionPhase]);

  const finishResultsLeave = useCallback(() => {
    if (resultsTransitionPhaseRef.current !== "leaving") return;
    clearLeaveFallback();
    commitDisplayedFilter(targetFilterRef.current);
    startResultsEnter();
  }, [clearLeaveFallback, commitDisplayedFilter, startResultsEnter]);

  useEffect(() => {
    const nextFilter = { status: statusFilter, keyword: normalizedKeyword };
    targetFilterRef.current = nextFilter;
    const currentFilter = displayedFilterRef.current;
    const isSameAsDisplayed = currentFilter.status === nextFilter.status && currentFilter.keyword === nextFilter.keyword;

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      clearLeaveFallback();
      clearEnterFallback();
      clearEnterFrames();
      if (!isSameAsDisplayed) commitDisplayedFilter(nextFilter);
      updateResultsTransitionPhase("idle");
      return undefined;
    }

    if (isSameAsDisplayed) {
      if (resultsTransitionPhaseRef.current === "leaving") {
        clearLeaveFallback();
        clearEnterFallback();
        updateResultsTransitionPhase("entering");
        enterFallbackTimerRef.current = window.setTimeout(() => {
          enterFallbackTimerRef.current = null;
          if (resultsTransitionPhaseRef.current === "entering") updateResultsTransitionPhase("idle");
        }, 260);
      }
      return undefined;
    }

    if (resultsTransitionPhaseRef.current === "pre-enter") {
      commitDisplayedFilter(nextFilter);
      return undefined;
    }

    if (resultsTransitionPhaseRef.current === "leaving") return undefined;

    clearEnterFallback();
    clearEnterFrames();
    updateResultsTransitionPhase("leaving");
    clearLeaveFallback();
    leaveFallbackTimerRef.current = window.setTimeout(finishResultsLeave, 180);
    return undefined;
  }, [
    clearEnterFallback,
    clearEnterFrames,
    clearLeaveFallback,
    commitDisplayedFilter,
    finishResultsLeave,
    normalizedKeyword,
    statusFilter,
    updateResultsTransitionPhase,
  ]);

  useEffect(() => () => {
    clearLeaveFallback();
    clearEnterFallback();
    clearEnterFrames();
  }, [clearEnterFallback, clearEnterFrames, clearLeaveFallback]);

  const filteredPapers = useMemo(() => papers.filter((paper) => {
    if (displayStatusFilter && paper.status !== displayStatusFilter) return false;
    if (!displayKeyword) return true;
    return `${paper.title} ${paper.source ?? ""} ${paper.year ?? ""} ${paper.version}`.toLowerCase().includes(displayKeyword);
  }), [displayKeyword, displayStatusFilter, papers]);
  const isSearchSettling = settledKeyword !== keyword;
  const isResultsTransitioning = isSearchSettling || resultsTransitionPhase !== "idle";
  const stableDesktopListHeight = papers.length > 0
    ? Math.max(260, Math.min(720, 46 + papers.length * 78))
    : 260;
  const stableMobileListHeight = papers.length > 0
    ? Math.max(240, Math.min(560, papers.length * 96))
    : 240;
  const statusSegments = [
    { value: "", label: "全部", count: summary.total },
    { value: "draft", label: "草稿", count: summary.draft },
    { value: "published", label: "已发布", count: summary.published },
    { value: "archived", label: "已归档", count: papers.filter((paper) => paper.status === "archived").length },
  ];

  return (
    <ManagementPage className="space-y-6">
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
          <>
            {canWrite ? (
              <Button onClick={() => setShowCreateForm((value) => !value)} aria-expanded={showCreateForm}>
                <Plus className={`h-4 w-4 transition-transform duration-200 motion-reduce:transition-none ${showCreateForm ? "rotate-45" : ""}`} />
                {showCreateForm ? "收起新建" : "新建试卷"}
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => query.refetch()} disabled={query.isFetching}>
              <RefreshCw className={`h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} />
              刷新
            </Button>
          </>
        }
      />

      <MetricStrip className="sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={<ClipboardCheck className="h-4 w-4" />} label="全部试卷" value={summary.total} hint="包含草稿、已发布与已归档" />
        <MetricCard icon={<Plus className="h-4 w-4" />} label="待整理草稿" value={summary.draft} hint="仍可调整题目和基础信息" tone={summary.draft > 0 ? "warning" : "default"} />
        <MetricCard icon={<Archive className="h-4 w-4" />} label="已发布" value={summary.published} hint="题目版本已冻结" tone="success" progress={summary.total ? (summary.published / summary.total) * 100 : 0} />
        <MetricCard icon={<History className="h-4 w-4" />} label="历史作答" value={summary.attempts} hint="所有试卷累计作答次数" tone="accent" />
      </MetricStrip>

      {canWrite ? (
        <div className={`grid transition-[grid-template-rows,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${showCreateForm ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
          <div className="overflow-hidden">
            <ManagementPanel
              variant="quiet"
              title="新建试卷"
              description="先建立草稿，再进入组卷页补充题目、分值和来源信息。"
              icon={<Plus className="h-4 w-4" />}
              actions={
                <Button size="sm" variant="ghost" onClick={() => setShowCreateForm(false)}>
                  收起
                  <ChevronDown className="h-4 w-4 rotate-180" />
                </Button>
              }
            >
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(280px,2fr)_minmax(180px,1fr)_140px_170px_minmax(124px,auto)] xl:items-end">
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
                  <CustomSelect
                    value={year}
                    options={[...EXAM_YEAR_OPTIONS]}
                    onChange={setYear}
                    placeholder="选择年份"
                    clearable={paperType !== "past_exam_choice"}
                  />
                </label>
                <label>
                  <FieldLabel>建议时长（分钟）</FieldLabel>
                  <Input value={durationMin} onChange={(event) => setDurationMin(event.target.value.replace(/\D/g, ""))} placeholder="75" />
                </label>
                <Button
                  className="w-full xl:w-auto"
                  onClick={() => createMutation.mutate()}
                  disabled={
                    !title.trim()
                    || createMutation.isPending
                    || (paperType === "past_exam_choice" && !isSupportedExamYear(year))
                    || (paperType === "mock_choice" && Boolean(year) && !isSupportedExamYear(year))
                  }
                >
                  <Plus className="h-4 w-4" />
                  创建草稿
                </Button>
              </div>
              {createMutation.isError ? (
                <ManagementNotice className="mt-3" tone="danger">
                  {createMutation.error instanceof Error ? createMutation.error.message : "创建失败，请检查名称、年份和时长后重试。"}
                </ManagementNotice>
              ) : null}
            </ManagementPanel>
          </div>
        </div>
      ) : null}

      <ManagementPanel
        variant="focus"
        title="试卷列表"
        description={query.isLoading ? "正在读取试卷数据" : `显示 ${filteredPapers.length} / ${papers.length} 份试卷，点击任意一行进入组卷详情。`}
        actions={
          <div className="flex w-full flex-col gap-2.5 lg:w-auto lg:flex-row lg:items-center">
            <div className="hidden items-center rounded-[11px] border border-[var(--mgmt-line)] bg-[rgba(237,243,246,0.48)] p-1 sm:flex" role="group" aria-label="按状态筛选试卷">
              {statusSegments.map((segment) => {
                const active = statusFilter === segment.value;
                return (
                  <button
                    key={segment.value || "all"}
                    type="button"
                    onClick={() => setStatusFilter(segment.value)}
                    className={`flex h-8 items-center gap-1.5 rounded-[8px] px-3 text-xs font-semibold transition-[background-color,color,box-shadow,transform] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgba(74,111,138,0.28)] active:scale-[0.98] motion-reduce:transform-none ${active ? "bg-white text-[var(--ink)] shadow-[0_2px_8px_rgba(31,49,61,0.08)]" : "text-[var(--color-text-secondary)] hover:bg-white/70 hover:text-[var(--ink)]"}`}
                    aria-pressed={active}
                  >
                    {segment.label}
                    <span className={`text-[10px] tabular-nums ${active ? "text-[var(--color-primary-dark)]" : "text-[var(--color-text-tertiary)]"}`}>{segment.count}</span>
                  </button>
                );
              })}
            </div>
            <label className="relative block w-full sm:w-72">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input className="h-10 bg-white pl-9 pr-3 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.6)]" value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索名称、来源或年份" aria-label="搜索试卷" />
            </label>
            <CustomSelect className="h-10 w-full bg-white sm:hidden" value={statusFilter} onChange={setStatusFilter} options={statusOptions} placeholder="全部状态" />
          </div>
        }
        contentClassName="p-0"
      >
        {query.isLoading ? (
          <div className="min-h-[300px]">
            <ManagementSkeletonRows rows={4} />
          </div>
        ) : (
          <div
            aria-busy={isResultsTransitioning}
            onTransitionEnd={(event) => {
              if (event.currentTarget !== event.target || event.propertyName !== "opacity") return;
              if (resultsTransitionPhaseRef.current === "leaving") {
                finishResultsLeave();
              } else if (resultsTransitionPhaseRef.current === "entering") {
                clearEnterFallback();
                updateResultsTransitionPhase("idle");
              }
            }}
            className={`transition-opacity motion-reduce:transition-none motion-reduce:opacity-100 ${
              resultsTransitionPhase === "leaving"
                ? "pointer-events-none opacity-0 duration-[110ms] ease-[cubic-bezier(0.4,0,1,1)] will-change-[opacity]"
                : resultsTransitionPhase === "pre-enter"
                  ? "pointer-events-none opacity-0 duration-0 will-change-[opacity]"
                  : resultsTransitionPhase === "entering"
                    ? "opacity-100 duration-[190ms] ease-[cubic-bezier(0.16,1,0.3,1)] will-change-[opacity]"
                    : "opacity-100 duration-0"
            }`}
          >
            <div
              className="hidden max-h-[720px] overflow-auto [scrollbar-gutter:stable] md:block"
              style={{ minHeight: stableDesktopListHeight }}
            >
              {filteredPapers.length > 0 ? (
                <table className="w-full min-w-[920px] text-sm">
                  <thead className="sticky top-0 z-10 bg-[rgba(244,247,249,0.96)] text-left text-[11px] font-semibold tracking-[0.015em] text-[var(--color-text-secondary)] shadow-[0_1px_0_var(--mgmt-line)] backdrop-blur-md">
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
                    {filteredPapers.map((paper) => {
                      const status = statusMeta(paper.status);
                      return (
                        <tr
                          key={paper.id}
                          tabIndex={0}
                          role="button"
                          onClick={() => router.push(`/exams/${paper.public_id}`)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") router.push(`/exams/${paper.public_id}`);
                          }}
                          className="group relative border-t border-[var(--color-border-light)] transition-[background-color,box-shadow] duration-200 hover:bg-[rgba(74,111,138,0.04)] hover:shadow-[inset_3px_0_0_rgba(74,111,138,0.35)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-primary)] motion-reduce:transition-none"
                        >
                          <td className="px-5 py-4">
                            <div className="flex min-w-0 items-center gap-2">
                              {paper.year ? <span className="shrink-0 rounded-md border border-[var(--mgmt-line)] bg-[var(--mgmt-steel)] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-[var(--color-primary-dark)]">{paper.year}</span> : null}
                              <p className="max-w-[430px] truncate font-semibold leading-5 text-[var(--ink)]">{paper.title}</p>
                            </div>
                            <p className="mt-1 text-[11px] leading-5 text-[var(--color-text-tertiary)]">版本 v{paper.version}{paper.source ? ` · ${paper.source}` : ""}</p>
                          </td>
                          <td className="px-4 py-4 text-[var(--color-text-secondary)]">{paperKindLabel(paper)}</td>
                          <td className="px-4 py-4 text-right tabular-nums"><span className="font-semibold text-[var(--ink)]">{paper.question_count}</span><span className="text-[var(--color-text-tertiary)]"> / {paper.total_choice_score} 分</span></td>
                          <td className="px-4 py-4 text-right tabular-nums text-[var(--color-text-secondary)]">{paper.duration_sec ? `${Math.round(paper.duration_sec / 60)} 分钟` : "不限时"}</td>
                          <td className="px-4 py-4 text-right tabular-nums text-[var(--color-text-secondary)]">{paper.attempt_count}</td>
                          <td className="px-4 py-4"><StatusBadge tone={status.tone}>{status.label}</StatusBadge></td>
                          <td className="px-4 py-4 text-[var(--color-text-tertiary)]"><ChevronRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1 motion-reduce:transition-none" /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : (
                <div className="grid h-full min-h-[176px] place-items-center">
                  <EmptyState>{papers.length === 0 ? "还没有试卷。创建一份草稿后即可开始组卷。" : "当前筛选没有匹配的试卷。清空搜索或切换状态后再试。"}</EmptyState>
                </div>
              )}
            </div>

            <div
              className="divide-y divide-[var(--color-border-light)] md:hidden"
              style={{ minHeight: stableMobileListHeight }}
            >
              {filteredPapers.length > 0 ? filteredPapers.map((paper) => {
                const status = statusMeta(paper.status);
                return (
                  <button key={paper.id} className="group flex w-full items-start gap-3 px-4 py-4 text-left transition-colors hover:bg-[rgba(74,111,138,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-primary)]" onClick={() => router.push(`/exams/${paper.public_id}`)}>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <p className="font-semibold leading-5 text-[var(--ink)]">{paper.title}</p>
                        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
                      </div>
                      <p className="mt-1 text-xs leading-5 text-[var(--color-text-secondary)]">{paperKindLabel(paper)} · {paper.question_count} 题 · {paper.total_choice_score} 分</p>
                      <p className="mt-2 text-[11px] text-[var(--color-text-tertiary)]">v{paper.version} · 历史作答 {paper.attempt_count} 次</p>
                    </div>
                    <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-[var(--color-text-tertiary)] transition-transform duration-200 group-hover:translate-x-1" />
                  </button>
                );
              }) : (
                <div className="grid h-full min-h-[176px] place-items-center">
                  <EmptyState>{papers.length === 0 ? "还没有试卷。创建一份草稿后即可开始组卷。" : "当前筛选没有匹配的试卷。清空搜索或切换状态后再试。"}</EmptyState>
                </div>
              )}
            </div>
          </div>
        )}
      </ManagementPanel>
    </ManagementPage>
  );
}
