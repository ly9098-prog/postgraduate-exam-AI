"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Eye, Search } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { ImportQuestionItem, PaginatedResponse } from "@/lib/api/types";

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

function statusTone(status: string) {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  if (status === "published") return "primary";
  return "warning";
}

function duplicateStatusTone(status: string | null | undefined) {
  if (status === "possible_duplicate") return "warning";
  if (status === "normal") return "success";
  return "neutral";
}

export default function ImportQuestionsPage() {
  const searchParams = useSearchParams();
  const batchIdParam = searchParams.get("batch_id") || "";
  const [filters, setFilters] = useState({ batch_id: "", status: "", subject: "", source_type: "", keyword: "" });
  const [previewId, setPreviewId] = useState<number | null>(null);

  const queryParams = useMemo(
    () => ({ page: 1, page_size: 50, batch_id: filters.batch_id || batchIdParam, status: filters.status, subject: filters.subject, source_type: filters.source_type, keyword: filters.keyword }),
    [batchIdParam, filters],
  );

  const questions = useQuery({
    queryKey: ["import-questions", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<ImportQuestionItem>>(`/imports/review-queue${toQuery(queryParams)}`),
    retry: false,
  });

  const items = questions.data?.items ?? [];
  const previewItem = items.find((item) => item.id === previewId) ?? null;

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPreviewId(null);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">导入题目列表</h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">查看 question_imports 暂存题目、重复检测与 OCR/AI 元数据。</p>
            </div>
            <Link href="/imports/review" className="inline-flex h-11 items-center justify-center rounded-2xl border border-[var(--color-primary)] bg-[var(--color-primary-light)] px-4 text-sm font-semibold text-[var(--color-primary-dark)] transition hover:bg-white">
              进入审核
            </Link>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <label className="relative xl:col-span-2">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input className="pl-9" placeholder="搜索题干 / OCR 原文" value={filters.keyword} onChange={(event) => updateFilter("keyword", event.target.value)} />
            </label>
            <Input placeholder="批次 ID" value={filters.batch_id || batchIdParam} onChange={(event) => updateFilter("batch_id", event.target.value)} />
            <Input placeholder="科目" value={filters.subject} onChange={(event) => updateFilter("subject", event.target.value)} />
            <select className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
              <option value="">全部状态</option>
              <option value="pending">pending</option>
              <option value="approved">approved</option>
              <option value="rejected">rejected</option>
              <option value="published">published</option>
            </select>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <section className="overflow-hidden rounded-3xl border border-[var(--color-border)] bg-white/70">
              <div className="grid grid-cols-[0.7fr_1.8fr_0.8fr_0.8fr_0.7fr] gap-3 border-b border-[var(--color-border)] px-4 py-3 text-xs font-semibold text-[var(--color-text-secondary)]">
                <span>状态</span>
                <span>题干</span>
                <span>科目</span>
                <span>批次</span>
                <span>操作</span>
              </div>
              {items.map((item) => (
                <div key={item.id} className="grid grid-cols-[0.7fr_1.8fr_0.8fr_0.8fr_0.7fr] gap-3 border-b border-[var(--color-border)] px-4 py-4 text-sm last:border-b-0">
                  <div className="space-y-1">
                    <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
                    {item.duplicate_status ? <StatusBadge tone={duplicateStatusTone(item.duplicate_status)}>{item.duplicate_status}</StatusBadge> : null}
                  </div>
                  <p className="line-clamp-3 whitespace-pre-wrap font-semibold text-[var(--ink)]">{textFromImport(item) || `导入题目 #${item.id}`}</p>
                  <div className="text-xs text-[var(--color-text-secondary)]">
                    <p>{item.subject || "—"}</p>
                    <p>{item.question_type || "—"}</p>
                  </div>
                  <p className="break-all font-mono text-xs text-[var(--color-text-secondary)]">{item.batch_id}</p>
                  <Button variant="ghost" onClick={() => setPreviewId(item.id)}>
                    <Eye className="h-4 w-4" />
                    查看
                  </Button>
                </div>
              ))}
              {!questions.isLoading && items.length === 0 ? <p className="py-10 text-center text-sm text-[var(--color-text-hint)]">暂无导入题目</p> : null}
            </section>

            <aside className="rounded-3xl border border-[var(--color-border)] bg-white/70 p-5">
              {!previewItem ? <p className="text-sm text-[var(--color-text-hint)]">选择一题查看详情。</p> : null}
              {previewItem ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-mono text-xs text-[var(--color-text-hint)]">#{previewItem.id}</p>
                      <h4 className="font-display text-xl font-bold text-[var(--ink)]">导入题目详情</h4>
                    </div>
                    <Link className="text-sm font-semibold text-[var(--color-primary-dark)] underline" href={`/imports/review?batch_id=${encodeURIComponent(previewItem.batch_id)}`}>审核该批次</Link>
                  </div>
                  <section>
                    <p className="font-semibold text-[var(--ink)]">题干</p>
                    <pre className="mt-2 whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-xs text-[var(--color-text-secondary)]">{textFromImport(previewItem) || "—"}</pre>
                  </section>
                  <section>
                    <p className="font-semibold text-[var(--ink)]">选项</p>
                    <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-xs text-[var(--color-text-secondary)]">{renderJson(previewItem.parsed_options)}</pre>
                  </section>
                  <section>
                    <p className="font-semibold text-[var(--ink)]">答案与解析</p>
                    <pre className="mt-2 whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-xs text-[var(--color-text-secondary)]">{renderJson({ answer: previewItem.parsed_answer, analysis: previewItem.parsed_analysis })}</pre>
                  </section>
                  <section>
                    <p className="font-semibold text-[var(--ink)]">重复检测</p>
                    <pre className="mt-2 whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-xs text-[var(--color-text-secondary)]">{renderJson({ duplicate_status: previewItem.duplicate_status, duplicate_of_question_id: previewItem.duplicate_of_question_id, duplicate_of_import_id: previewItem.duplicate_of_import_id, question_hash: previewItem.question_hash })}</pre>
                  </section>
                  <section>
                    <p className="font-semibold text-[var(--ink)]">OCR / AI 原始信息</p>
                    <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-xs text-[var(--color-text-secondary)]">{renderJson({ raw_data: previewItem.raw_data, ai_metadata: previewItem.ai_metadata })}</pre>
                  </section>
                </div>
              ) : null}
            </aside>
          </div>
          {questions.isError ? <p className="text-sm text-[var(--color-danger)]">导入题目接口当前不可用。</p> : null}
        </CardContent>
      </Card>
    </div>
  );
}
