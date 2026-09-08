"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  FileQuestion,
  Filter,
  Import,
  Layers3,
  Search,
  ShieldAlert,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { CustomSelect } from "@/components/ui/custom-select";
import { Input } from "@/components/ui/input";
import { apiRequest, toQuery } from "@/lib/api/client";
import type {
  CoverageMatrixItem,
  CoverageReportResponse,
  CoverageStatus,
  ExamYearCoverageItem,
  SyllabusVersionDetail,
  SyllabusVersionSummary,
} from "@/lib/api/types";

const STATUS_LABEL: Record<CoverageStatus, string> = {
  empty: "无题",
  insufficient: "不足",
  imbalanced: "结构失衡",
  healthy: "良好",
};

const STATUS_CLASS: Record<CoverageStatus, string> = {
  empty: "bg-red-50 text-red-700",
  insufficient: "bg-amber-50 text-amber-800",
  imbalanced: "bg-orange-50 text-orange-800",
  healthy: "bg-emerald-50 text-emerald-700",
};

const EXAM_STATUS_LABEL: Record<ExamYearCoverageItem["status"], string> = {
  missing: "缺失",
  draft: "草稿未发布",
  invalid: "发布态异常",
  complete: "完整",
  archived: "已归档",
};

const EXAM_STATUS_CLASS: Record<ExamYearCoverageItem["status"], string> = {
  missing: "bg-red-50 text-red-700",
  draft: "bg-amber-50 text-amber-800",
  invalid: "bg-red-50 text-red-700",
  complete: "bg-emerald-50 text-emerald-700",
  archived: "bg-slate-100 text-slate-600",
};

function questionBankHref(knowledgePointId: number) {
  return `/questions?${new URLSearchParams({
    is_active: "true",
    knowledge_point_id: String(knowledgePointId),
  }).toString()}`;
}

function questionIdHref(questionId: number) {
  return `/questions?${new URLSearchParams({
    is_active: "true",
    keyword: `#${questionId}`,
  }).toString()}`;
}

function StatCard({ label, value, hint, warning = false }: { label: string; value: number | string; hint: string; warning?: boolean }) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm text-[var(--color-text-secondary)]">{label}</p>
            <p className={`mt-1 text-2xl font-bold ${warning ? "text-amber-700" : "text-[var(--ink)]"}`}>{value}</p>
          </div>
          {warning ? <AlertTriangle className="mt-1 h-5 w-5 text-amber-600" /> : <CheckCircle2 className="mt-1 h-5 w-5 text-emerald-600" />}
        </div>
        <p className="mt-2 text-xs leading-5 text-[var(--color-text-tertiary)]">{hint}</p>
      </CardContent>
    </Card>
  );
}

export default function CoveragePage() {
  const [versionId, setVersionId] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [minQuestionsInput, setMinQuestionsInput] = useState("10");
  const [minQuestions, setMinQuestions] = useState(10);
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState<CoverageStatus | "">("");

  const versionsQuery = useQuery({
    queryKey: ["syllabus", "versions", "coverage"],
    queryFn: () => apiRequest<SyllabusVersionSummary[]>("/knowledge/syllabus/versions"),
    retry: false,
  });

  useEffect(() => {
    if (versionId || !versionsQuery.data?.length) return;
    const active = versionsQuery.data.find((item) => item.status === "active") ?? versionsQuery.data[0];
    if (active) setVersionId(String(active.id));
  }, [versionId, versionsQuery.data]);

  const selectedVersionId = versionId ? Number(versionId) : undefined;
  const versionDetailQuery = useQuery({
    queryKey: ["syllabus", "coverage-version", selectedVersionId],
    queryFn: () => apiRequest<SyllabusVersionDetail>(`/knowledge/syllabus/versions/${selectedVersionId}`),
    enabled: Boolean(selectedVersionId),
    retry: false,
  });

  const subjectOptions = useMemo(() => {
    const seen = new Map<number, { label: string; value: string }>();
    for (const item of versionDetailQuery.data?.knowledge_points ?? []) {
      if (!seen.has(item.subject_id)) {
        seen.set(item.subject_id, { label: item.subject_name, value: String(item.subject_id) });
      }
    }
    return Array.from(seen.values());
  }, [versionDetailQuery.data?.knowledge_points]);

  useEffect(() => {
    if (!subjectId) return;
    if (!subjectOptions.some((item) => item.value === subjectId)) setSubjectId("");
  }, [subjectId, subjectOptions]);

  const reportParams = useMemo(() => ({
    syllabus_version_id: selectedVersionId,
    subject_id: subjectId ? Number(subjectId) : undefined,
    min_questions: minQuestions,
    year_from: yearFrom ? Number(yearFrom) : undefined,
    year_to: yearTo ? Number(yearTo) : undefined,
  }), [selectedVersionId, subjectId, minQuestions, yearFrom, yearTo]);

  const reportQuery = useQuery({
    queryKey: ["coverage", "report", reportParams],
    queryFn: () => apiRequest<CoverageReportResponse>(`/coverage/report${toQuery(reportParams)}`),
    enabled: Boolean(selectedVersionId),
    retry: false,
  });

  const filteredItems = useMemo(() => {
    const normalized = keyword.trim().toLowerCase();
    return (reportQuery.data?.items ?? []).filter((item) => {
      if (status && item.status !== status) return false;
      if (!normalized) return true;
      return `${item.subject_name} ${item.subject_code} ${item.name}`.toLowerCase().includes(normalized);
    });
  }, [keyword, reportQuery.data?.items, status]);

  const summary = reportQuery.data?.summary;
  const quality = reportQuery.data?.quality_issues;
  const graph = reportQuery.data?.knowledge_graph_quality;

  const applyMinQuestions = () => {
    const parsed = Number(minQuestionsInput);
    if (Number.isFinite(parsed) && parsed >= 1 && parsed <= 500) setMinQuestions(Math.floor(parsed));
  };

  return (
    <div className="space-y-6 pb-10">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-blue-700"><Layers3 className="h-4 w-4" />408-COVERAGE</div>
          <h1 className="mt-1 font-display text-3xl font-bold text-[var(--ink)]">408 题库覆盖率 / 质量治理</h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-[var(--color-text-secondary)]">
            按考纲版本检查知识点题量、真题选择题、难度结构和内容质量；矩阵默认把最需要补题的知识点排在最前面。
          </p>
        </div>
        {reportQuery.data ? (
          <div className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-2 text-sm text-blue-800">
            {reportQuery.data.syllabus.name} · {reportQuery.data.syllabus.effective_year}
          </div>
        ) : null}
      </div>

      <Card>
        <CardHeader><h2 className="font-semibold text-[var(--ink)]">治理范围</h2></CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1.2fr_1fr_170px_150px_150px]">
            <CustomSelect
              value={versionId}
              onChange={(value) => { setVersionId(value); setSubjectId(""); }}
              options={(versionsQuery.data ?? []).map((item) => ({
                label: `${item.name} · ${item.effective_year} · ${item.status}`,
                value: String(item.id),
              }))}
              placeholder="选择考纲版本"
            />
            <CustomSelect
              value={subjectId}
              onChange={setSubjectId}
              options={[{ label: "408 四科全部", value: "" }, ...subjectOptions]}
            />
            <div className="flex gap-2">
              <Input inputMode="numeric" value={minQuestionsInput} onChange={(e) => setMinQuestionsInput(e.target.value.replace(/\D/g, "").slice(0, 3))} onBlur={applyMinQuestions} />
              <Button variant="secondary" onClick={applyMinQuestions}>阈值</Button>
            </div>
            <Input inputMode="numeric" placeholder="起始年份" value={yearFrom} onChange={(e) => setYearFrom(e.target.value.replace(/\D/g, "").slice(0, 4))} />
            <Input inputMode="numeric" placeholder="结束年份" value={yearTo} onChange={(e) => setYearTo(e.target.value.replace(/\D/g, "").slice(0, 4))} />
          </div>
          <p className="mt-3 text-xs leading-5 text-[var(--color-text-tertiary)]">
            “题量不足”阈值可调整，默认 10 题。年份留空时仅检查系统当前已知真题卷年份区间；指定起止年份后会明确标出缺失年份。
          </p>
        </CardContent>
      </Card>

      {reportQuery.isError ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">覆盖率报告加载失败，请确认当前账号同时具备题库读取与知识点读取权限，并检查 active/所选考纲版本。</div>
      ) : null}

      {summary ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="考纲知识点" value={summary.total_knowledge_points} hint={`良好 ${summary.healthy_knowledge_points}；无题 ${summary.empty_knowledge_points}`} warning={summary.empty_knowledge_points > 0} />
          <StatCard label="低覆盖 / 失衡" value={summary.insufficient_knowledge_points + summary.imbalanced_knowledge_points} hint={`不足 ${summary.insufficient_knowledge_points}；难度失衡 ${summary.imbalanced_knowledge_points}`} warning={summary.insufficient_knowledge_points + summary.imbalanced_knowledge_points > 0} />
          <StatCard label="408 有效题目" value={summary.total_questions} hint={`映射到本考纲 ${summary.mapped_questions}；未映射 ${summary.unmapped_questions}`} warning={summary.unmapped_questions > 0} />
          <StatCard label="内容质量问题" value={summary.missing_analysis_questions + summary.image_reference_anomaly_questions + summary.duplicate_suspect_questions} hint={`缺解析 ${summary.missing_analysis_questions} · 图片引用 ${summary.image_reference_anomaly_questions} · 重复疑似 ${summary.duplicate_suspect_questions}`} warning={summary.missing_analysis_questions + summary.image_reference_anomaly_questions + summary.duplicate_suspect_questions > 0} />
          <StatCard label="题目版本缺口" value={summary.unversioned_questions} hint="approved + active 408 题没有 current_version_id" warning={summary.unversioned_questions > 0} />
          <StatCard label="考纲快照缺口" value={summary.syllabus_snapshot_missing_questions} hint="当前题目版本的知识点关联缺少 syllabus snapshot" warning={summary.syllabus_snapshot_missing_questions > 0} />
          <StatCard label="知识图谱孤立点" value={Number(graph?.summary?.isolated_count ?? 0)} hint="复用现有 Knowledge Quality Report，并限制到当前考纲范围" warning={Number(graph?.summary?.isolated_count ?? 0) > 0} />
          <StatCard label="知识图谱循环" value={Number(graph?.summary?.cycle_count ?? 0)} hint="prerequisite 双向循环检查" warning={Number(graph?.summary?.cycle_count ?? 0) > 0} />
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <h2 className="font-semibold text-[var(--ink)]">知识点覆盖矩阵</h2>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">真题 / 模拟题计数来自 ExamPaper 固定题目版本快照，不根据文件导入类型推断，也不会随当前题目知识点编辑漂移。</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <label className="flex h-10 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white px-3">
                <Search className="h-4 w-4 text-[var(--color-text-hint)]" />
                <input className="w-48 border-0 bg-transparent text-sm outline-none" placeholder="搜索知识点" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
              </label>
              <CustomSelect
                className="w-36"
                value={status}
                onChange={(value) => setStatus(value as CoverageStatus | "")}
                options={[
                  { label: "全部状态", value: "" },
                  { label: "无题", value: "empty" },
                  { label: "题量不足", value: "insufficient" },
                  { label: "难度失衡", value: "imbalanced" },
                  { label: "良好", value: "healthy" },
                ]}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="min-w-[1240px] w-full text-sm">
            <thead className="border-y border-[var(--color-border)] bg-slate-50/80 text-left text-xs text-[var(--color-text-secondary)]">
              <tr>
                <th className="px-5 py-3">知识点</th>
                <th className="px-3 py-3 text-right">总题数</th>
                <th className="px-3 py-3 text-right">真题选择</th>
                <th className="px-3 py-3 text-right">模拟选择</th>
                <th className="px-3 py-3 text-right">简单</th>
                <th className="px-3 py-3 text-right">中等</th>
                <th className="px-3 py-3 text-right">困难</th>
                <th className="px-3 py-3 text-right">缺解析</th>
                <th className="px-3 py-3">状态</th>
                <th className="px-5 py-3 text-right">处理</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.map((item: CoverageMatrixItem) => (
                <tr key={item.syllabus_knowledge_point_id} className="border-b border-[var(--color-border)] align-top hover:bg-slate-50/50">
                  <td className="px-5 py-4">
                    <p className="font-semibold text-[var(--ink)]">{item.name}</p>
                    <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">{item.subject_name} · KP #{item.knowledge_point_id}</p>
                    <p className="mt-1 max-w-lg text-[11px] leading-5 text-[var(--color-text-tertiary)]">
                      年份 {item.years.length ? item.years.slice(0, 6).join("/") : "—"} · 题型 {Object.entries(item.question_type_counts).map(([type, count]) => `${type}:${count}`).join(" / ") || "—"}
                    </p>
                    <p className="max-w-lg truncate text-[11px] leading-5 text-[var(--color-text-tertiary)]" title={item.sources.join(" / ")}>来源 {item.sources.length ? item.sources.join(" / ") : "—"}</p>
                    {item.issues.length ? <p className="mt-2 max-w-md text-xs leading-5 text-amber-700">{item.issues.join("；")}</p> : null}
                  </td>
                  <td className="px-3 py-4 text-right font-semibold">{item.total_question_count}</td>
                  <td className="px-3 py-4 text-right">{item.past_exam_choice_count}</td>
                  <td className="px-3 py-4 text-right">{item.mock_choice_count}</td>
                  <td className="px-3 py-4 text-right">{item.difficulty_easy_count}</td>
                  <td className="px-3 py-4 text-right">{item.difficulty_medium_count}</td>
                  <td className="px-3 py-4 text-right">{item.difficulty_hard_count}</td>
                  <td className="px-3 py-4 text-right">{item.missing_analysis_count}</td>
                  <td className="px-3 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS_CLASS[item.status]}`}>{STATUS_LABEL[item.status]}</span></td>
                  <td className="px-5 py-4">
                    <div className="flex justify-end gap-2">
                      <Link href={questionBankHref(item.knowledge_point_id)} className="inline-flex h-9 items-center gap-1 rounded-lg border border-[var(--color-border)] bg-white px-3 text-xs font-semibold text-[var(--ink)] hover:bg-slate-50"><FileQuestion className="h-3.5 w-3.5" />看题库</Link>
                      <Link href="/imports/text-import" className="inline-flex h-9 items-center gap-1 rounded-lg bg-[var(--color-primary)] px-3 text-xs font-semibold text-white hover:opacity-90"><Import className="h-3.5 w-3.5" />去导题</Link>
                    </div>
                  </td>
                </tr>
              ))}
              {!reportQuery.isLoading && filteredItems.length === 0 ? <tr><td colSpan={10} className="px-5 py-12 text-center text-sm text-[var(--color-text-secondary)]">当前筛选没有知识点。</td></tr> : null}
              {reportQuery.isLoading ? <tr><td colSpan={10} className="px-5 py-12 text-center text-sm text-[var(--color-text-secondary)]">正在计算覆盖率…</td></tr> : null}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2"><BookOpen className="h-5 w-5 text-blue-700" /><h2 className="font-semibold text-[var(--ink)]">真题选择题年份完整性</h2></div>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">直接复用试卷发布校验；缺解析 / 固定题目版本缺知识点作为额外质量警告，不伪造“完整 408 总分”。</p>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="min-w-[920px] w-full text-sm">
            <thead className="border-y border-[var(--color-border)] bg-slate-50/80 text-left text-xs text-[var(--color-text-secondary)]"><tr><th className="px-5 py-3">年份</th><th className="px-3 py-3">状态</th><th className="px-3 py-3">代表试卷</th><th className="px-3 py-3 text-right">题数</th><th className="px-3 py-3 text-right">选择题分</th><th className="px-3 py-3">问题</th><th className="px-5 py-3 text-right">处理</th></tr></thead>
            <tbody>
              {(reportQuery.data?.exam_years ?? []).map((item) => (
                <tr key={item.year} className="border-b border-[var(--color-border)] align-top">
                  <td className="px-5 py-4 font-semibold">{item.year}</td>
                  <td className="px-3 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${EXAM_STATUS_CLASS[item.status]}`}>{EXAM_STATUS_LABEL[item.status]}</span></td>
                  <td className="px-3 py-4"><p className="font-medium text-[var(--ink)]">{item.paper_title ?? "—"}</p>{item.paper_version ? <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">v{item.paper_version} · {item.paper_status}</p> : null}</td>
                  <td className="px-3 py-4 text-right">{item.question_count}</td>
                  <td className="px-3 py-4 text-right">{item.total_choice_score}</td>
                  <td className="px-3 py-4"><div className="max-w-lg space-y-1 text-xs leading-5">{item.validation_errors.map((message) => <p key={`e-${message}`} className="text-red-700">{message}</p>)}{item.quality_warnings.map((message) => <p key={`w-${message}`} className="text-amber-700">{message}</p>)}{!item.validation_errors.length && !item.quality_warnings.length ? <span className="text-emerald-700">完整性检查通过</span> : null}</div></td>
                  <td className="px-5 py-4 text-right">{item.paper_id ? <Link href={`/exams/${item.paper_id}`} className="text-sm font-semibold text-blue-700 hover:underline">查看试卷</Link> : <Link href="/exams" className="text-sm font-semibold text-blue-700 hover:underline">去建卷</Link>}</td>
                </tr>
              ))}
              {!reportQuery.isLoading && (reportQuery.data?.exam_years.length ?? 0) === 0 ? <tr><td colSpan={7} className="px-5 py-10 text-center text-sm text-[var(--color-text-secondary)]">当前没有可推导的真题年份区间；可在上方输入起止年份进行显式完整性检查。</td></tr> : null}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader><div className="flex items-center gap-2"><ShieldAlert className="h-5 w-5 text-amber-600" /><h2 className="font-semibold">题库质量样本</h2></div></CardHeader>
          <CardContent className="space-y-4 text-sm">
            {quality ? (
              <>
                {[
                  ["未映射当前考纲", quality.unmapped_question_ids],
                  ["缺少解析", quality.missing_analysis_question_ids],
                  ["图片引用结构异常", quality.image_reference_anomaly_question_ids],
                  ["缺少 current version", quality.unversioned_question_ids],
                  ["缺少考纲语义快照", quality.syllabus_snapshot_missing_question_ids],
                ].map(([label, ids]) => {
                  const values = ids as number[];
                  return <div key={label as string}><p className="mb-2 font-semibold text-[var(--ink)]">{label as string} <span className="font-normal text-[var(--color-text-tertiary)]">样本 {values.length}</span></p><div className="flex flex-wrap gap-2">{values.slice(0, 12).map((id) => <Link key={id} href={questionIdHref(id)} className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-200">#{id}</Link>)}{values.length === 0 ? <span className="text-xs text-emerald-700">无样本</span> : null}</div></div>;
                })}
                <div><p className="mb-2 font-semibold text-[var(--ink)]">重复疑似 hash 组</p><div className="space-y-2">{quality.duplicate_groups.slice(0, 8).map((group) => <div key={group.question_hash} className="rounded-xl border border-[var(--color-border)] px-3 py-2"><p className="truncate font-mono text-[11px] text-[var(--color-text-tertiary)]">{group.question_hash}</p><div className="mt-1 flex flex-wrap gap-2">{group.question_ids.map((id) => <Link key={id} href={questionIdHref(id)} className="text-xs font-semibold text-blue-700 hover:underline">#{id}</Link>)}</div></div>)}{quality.duplicate_groups.length === 0 ? <span className="text-xs text-emerald-700">未发现重复 hash 组</span> : null}</div></div>
              </>
            ) : <p className="text-[var(--color-text-secondary)]">正在加载…</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><div className="flex items-center gap-2"><CircleHelp className="h-5 w-5 text-blue-700" /><h2 className="font-semibold">知识图谱质量联动</h2></div></CardHeader>
          <CardContent className="space-y-4 text-sm">
            <p className="leading-6 text-[var(--color-text-secondary)]">该区域复用现有 Knowledge Quality Report，并将统计范围限制到所选考纲知识点，避免另造一套孤立的质量规则。</p>
            {(graph?.warnings ?? []).length ? <div className="space-y-2">{(graph?.warnings ?? []).map((warning) => <div key={warning} className="rounded-xl bg-amber-50 px-3 py-2 text-amber-800">{warning}</div>)}</div> : <div className="rounded-xl bg-emerald-50 px-3 py-2 text-emerald-700">当前范围没有知识图谱质量警告。</div>}
            <div className="flex flex-wrap gap-2">
              <Link href="/knowledge-graph" className="inline-flex h-10 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white px-4 text-sm font-semibold text-[var(--ink)] hover:bg-slate-50"><Filter className="h-4 w-4" />进入知识图谱治理</Link>
              <Link href="/syllabus" className="inline-flex h-10 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white px-4 text-sm font-semibold text-[var(--ink)] hover:bg-slate-50"><BookOpen className="h-4 w-4" />考纲版本</Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
