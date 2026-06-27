"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Eye,
  Search,
  FileText,
  Code2,
  X,
  CheckCircle2,
  Clock,
  XCircle,
  Globe,
  AlertTriangle,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { ImportQuestionItem, PaginatedResponse } from "@/lib/api/types";

function isMultiBlankChoice(item: ImportQuestionItem | null | undefined): boolean {
  return item?.question_type === "multi_blank_choice";
}

interface BlankOptionGroup {
  id?: string;
  options?: Array<{ key: string; text: string }>;
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

function optionDataFromImport(item: ImportQuestionItem | null | undefined) {
  if (!item) return null;
  const raw = item.raw_data;
  return item.parsed_options ?? raw?.options ?? raw?.parsed_options ?? raw?.option_text ?? raw?.optionText ?? null;
}

function renderOptions(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .map((item, index) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const entry = item as Record<string, unknown>;
          const label = entry.label ?? entry.key ?? entry.name;
          const content = [entry.content, entry.text, entry.stem, entry.option, entry.value, entry.answer]
            .map((part) => (typeof part === "string" || typeof part === "number" ? String(part) : ""))
            .find(Boolean);
          const prefix = label ? `${label}: ` : `选项${index + 1}: `;
          if (content) return `${prefix}${content}`;
        }
        return renderJson(item);
      })
      .join("\n");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length > 0) {
      return entries
        .map(([key, item]) => {
          if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
            return `${key}: ${item}`;
          }
          return `${key}: ${renderJson(item)}`;
        })
        .join("\n");
    }
  }
  return renderJson(value);
}

function statusIcon(status: string) {
  if (status === "approved") return CheckCircle2;
  if (status === "rejected") return XCircle;
  if (status === "published") return Globe;
  return Clock;
}

function statusColor(status: string) {
  if (status === "approved") return "text-green-600";
  if (status === "rejected") return "text-red-500";
  if (status === "published") return "text-blue-600";
  return "text-amber-500";
}

function statusTone(status: string) {
  if (status === "approved") return "success" as const;
  if (status === "rejected") return "danger" as const;
  if (status === "published") return "primary" as const;
  return "warning" as const;
}

function statusLabel(status: string) {
  if (status === "approved") return "已通过";
  if (status === "rejected") return "已拒绝";
  if (status === "published") return "已发布";
  if (status === "pending") return "待审核";
  return status;
}

function duplicateStatusTone(status: string | null | undefined) {
  if (status === "possible_duplicate") return "warning" as const;
  if (status === "normal") return "success" as const;
  return "neutral" as const;
}

const TYPE_LABELS: Record<string, string> = {
  single_choice: "单选题",
  multiple_choice: "多选题",
  true_false: "判断题",
  fill_blank: "填空题",
  multi_blank_choice: "多空选择",
  subjective: "问答题",
};

function typeLabel(t: string | null | undefined) {
  return TYPE_LABELS[t ?? ""] ?? t ?? "未知";
}

/** Compact detail modal */
function DetailModal({ item, onClose }: { item: ImportQuestionItem; onClose: () => void }) {
  const [detailView, setDetailView] = useState<"formatted" | "json">("formatted");

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[rgba(16,24,40,0.42)] px-4 py-10">
      <div className="relative mt-6 w-full max-w-2xl rounded-2xl border border-[var(--color-border)] bg-white shadow-[var(--shadow-floating)]">
        {/* ===== Header with large close hit area ===== */}
        <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] px-5 py-3 pr-14">
          <div className="flex items-center gap-3 min-w-0">
            <span className="shrink-0 font-mono text-xs text-[var(--color-text-hint)]">#{item.id}</span>
            <h3 className="truncate font-display text-base font-bold text-[var(--ink)]">导入题目详情</h3>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <div className="flex overflow-hidden rounded-lg border border-[var(--color-border)]">
              <button
                type="button"
                className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium transition ${detailView === "formatted" ? "bg-[var(--color-primary)] text-white" : "bg-transparent text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]"}`}
                onClick={() => setDetailView("formatted")}
              >
                <FileText className="h-3 w-3" />文本
              </button>
              <button
                type="button"
                className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium transition ${detailView === "json" ? "bg-[var(--color-primary)] text-white" : "bg-transparent text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]"}`}
                onClick={() => setDetailView("json")}
              >
                <Code2 className="h-3 w-3" />JSON
              </button>
            </div>
            <Link
              className="hidden sm:inline text-xs font-semibold text-[var(--color-primary-dark)] underline"
              href={`/imports/review?batch_id=${encodeURIComponent(item.batch_id)}`}
            >
              审核批次
            </Link>
          </div>
        </div>

        {/* Large close button — positioned absolutely to avoid crowded header */}
        <button
          className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-xl bg-white text-[var(--color-text-hint)] shadow-sm ring-1 ring-[var(--color-border)] transition hover:bg-[var(--color-bg-secondary)] hover:text-[var(--ink)] hover:ring-[var(--color-text-hint)] active:scale-95"
          onClick={onClose}
        >
          <X className="h-5 w-5" />
        </button>

        {/* ===== Scrollable body ===== */}
        <div className="overflow-y-auto max-h-[70vh] px-5 py-4">
          {detailView === "formatted" ? (
            <div className="space-y-3">
              <section>
                <p className="mb-1 text-xs font-semibold text-[var(--color-text-secondary)]">题干</p>
                <pre className="whitespace-pre-wrap rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2.5 text-xs leading-relaxed text-[var(--color-text-secondary)]">{textFromImport(item) || "—"}</pre>
              </section>

              {isMultiBlankChoice(item) ? (
                <section>
                  <p className="mb-1 text-xs font-semibold text-[var(--color-text-secondary)]">选项组</p>
                  <div className="space-y-2">
                    {(() => {
                      const groups = item?.parsed_content?.blank_option_groups;
                      const list: BlankOptionGroup[] = Array.isArray(groups) ? (groups as BlankOptionGroup[]) : [];
                      return list.length > 0 ? list.map((group, gi) => (
                        <div key={gi} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2.5">
                          <p className="mb-1.5 text-[10px] font-semibold text-[var(--color-text-secondary)]">空 {group.id ?? gi + 1}</p>
                          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-[var(--color-text-secondary)]">
                            {group.options?.map((opt, oi) => (
                              <span key={oi}><span className="font-bold text-[var(--ink)]">{opt.key}.</span> {opt.text}</span>
                            ))}
                          </div>
                        </div>
                      )) : <p className="text-xs text-[var(--color-text-hint)]">暂无选项组数据</p>;
                    })()}
                  </div>
                </section>
              ) : (
                <section>
                  <p className="mb-1 text-xs font-semibold text-[var(--color-text-secondary)]">选项</p>
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2.5 text-xs leading-relaxed text-[var(--color-text-secondary)]">{renderOptions(optionDataFromImport(item))}</pre>
                </section>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <section>
                  <p className="mb-1 text-xs font-semibold text-[var(--color-text-secondary)]">答案</p>
                  <pre className="whitespace-pre-wrap rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2.5 text-xs leading-relaxed text-[var(--color-text-secondary)]">{item.parsed_answer || "—"}</pre>
                </section>
                <section>
                  <p className="mb-1 text-xs font-semibold text-[var(--color-text-secondary)]">解析</p>
                  <pre className="whitespace-pre-wrap rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2.5 text-xs leading-relaxed text-[var(--color-text-secondary)]">{item.parsed_analysis || "—"}</pre>
                </section>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {[
                { title: "基础信息", data: { id: item.id, batch_id: item.batch_id, source_type: item.source_type, subject: item.subject, question_type: item.question_type, status: item.status, ai_generated: item.ai_generated, ai_answer_flag: item.ai_answer_flag, created_at: item.created_at, updated_at: item.updated_at } },
                { title: "解析数据", data: { parsed_content: item.parsed_content, parsed_options: item.parsed_options, parsed_answer: item.parsed_answer, parsed_analysis: item.parsed_analysis } },
                { title: "重复检测", data: { duplicate_status: item.duplicate_status, duplicate_of_question_id: item.duplicate_of_question_id, duplicate_of_import_id: item.duplicate_of_import_id, question_hash: item.question_hash } },
                { title: "OCR / AI 原始数据", data: { raw_data: item.raw_data, ai_metadata: item.ai_metadata } },
              ].map(({ title, data }) => (
                <section key={title}>
                  <p className="mb-1 text-xs font-semibold text-[var(--color-text-secondary)]">{title}</p>
                  <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2.5 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{renderJson(data)}</pre>
                </section>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
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

  // Fetch full detail when modal opens
  const detail = useQuery({
    queryKey: ["import-question-detail", previewId],
    queryFn: () => apiRequest<ImportQuestionItem>(`/imports/questions/${previewId}`),
    enabled: previewId !== null,
    retry: false,
  });

  const previewItem = detail.data ?? (items.find((item) => item.id === previewId) ?? null);

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
        <CardContent>
          {/* ===== Card-style question list ===== */}
          <section className="space-y-2">
            {items.map((item) => {
              const StatusIcon = statusIcon(item.status);
              return (
                <div
                  key={item.id}
                  className="rounded-xl border border-[var(--color-border)] bg-white px-4 py-3.5 transition hover:border-[var(--color-primary-light)] hover:shadow-sm"
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    {/* Left: main content */}
                    <div className="min-w-0 flex-1 space-y-2">
                      {/* Top row: status + metadata */}
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        {/* Status */}
                        <div className="flex items-center gap-1.5">
                          <StatusIcon className={`h-4 w-4 ${statusColor(item.status)}`} />
                          <StatusBadge tone={statusTone(item.status)}>
                            {statusLabel(item.status)}
                          </StatusBadge>
                        </div>

                        {/* Duplicate badge */}
                        {item.duplicate_status ? (
                          <StatusBadge tone={duplicateStatusTone(item.duplicate_status)}>
                            <AlertTriangle className="mr-0.5 inline h-2.5 w-2.5" />
                            {item.duplicate_status === "possible_duplicate" ? "疑似重复" : item.duplicate_status}
                          </StatusBadge>
                        ) : null}

                        {/* Separator */}
                        <span className="hidden h-3 w-px bg-[var(--color-border)] sm:block" />

                        {/* Subject + type pills */}
                        {item.subject ? (
                          <span className="rounded-md bg-[var(--color-primary-light)] px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-primary-dark)]">
                            {item.subject}
                          </span>
                        ) : null}
                        <span className="text-[11px] text-[var(--color-text-hint)]">
                          {typeLabel(item.question_type)}
                        </span>

                        {/* Batch ID */}
                        <span className="ml-auto truncate font-mono text-[10px] text-[var(--color-text-hint)] sm:ml-0" title={item.batch_id}>
                          {item.batch_id}
                        </span>
                      </div>

                      {/* Stem preview */}
                      <p className="line-clamp-2 whitespace-pre-wrap text-sm leading-relaxed text-[var(--ink)]">
                        {item.content_preview || textFromImport(item) || `导入题目 #${item.id}`}
                      </p>
                    </div>

                    {/* Right: action */}
                    <div className="flex shrink-0 items-start sm:pl-3">
                      <Button
                        variant="ghost"
className="h-9 gap-1.5 px-3 text-xs font-medium"
                        onClick={() => setPreviewId(item.id)}
                      >
                        <Eye className="h-4 w-4" />
                        查看
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
            {!questions.isLoading && items.length === 0 ? (
              <p className="py-16 text-center text-sm text-[var(--color-text-hint)]">暂无导入题目</p>
            ) : null}
          </section>

          {questions.isError ? (
            <p className="mt-4 text-sm text-[var(--color-danger)]">导入题目接口当前不可用。</p>
          ) : null}
        </CardContent>
      </Card>

      {/* ===== Detail modal ===== */}
      {previewItem ? (
        <DetailModal item={previewItem} onClose={() => setPreviewId(null)} />
      ) : null}
    </div>
  );
}
