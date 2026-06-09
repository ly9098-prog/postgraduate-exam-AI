"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  Edit3,
  FileText,
  Loader2,
  Trash2,
  AlertTriangle,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest } from "@/lib/api/client";

type ParsedOption = { key: string; text: string };

type ParsedQuestion = {
  subject: string | null;
  question_type: string | null;
  stem: string;
  options: ParsedOption[];
  answer: string | string[] | boolean | null;
  analysis: string | null;
  knowledge_points: string[];
  difficulty: number;
  is_valid: boolean;
  errors: string[];
  warnings: string[];
  question_hash: string | null;
  stem_hash: string | null;
  block_index: number;
  detection_method: string;
};

type ParseResponse = {
  questions: ParsedQuestion[];
  warnings: string[];
  raw_count: number;
  valid_count: number;
};

type ImportResultItem = {
  block_index: number;
  import_id?: number;
  status: "ok" | "fail";
  error?: string;
};

type ImportResponse = {
  batch_id: string;
  items: ImportResultItem[];
  total: number;
  succeeded: number;
  failed: number;
};

const SUBJECTS = [
  { value: "math2", label: "数学二" },
  { value: "math2-calculus", label: "数学二 - 高等数学" },
  { value: "math2-linalg", label: "数学二 - 线性代数" },
  { value: "exam408", label: "408 计算机" },
  { value: "exam408-ds", label: "408 - 数据结构" },
  { value: "exam408-os", label: "408 - 操作系统" },
  { value: "exam408-co", label: "408 - 计算机组成" },
  { value: "exam408-cn", label: "408 - 计算机网络" },
  { value: "english", label: "英语" },
];

function renderAnswer(answer: string | string[] | boolean | null) {
  if (answer === null || answer === undefined || answer === "") return "—";
  if (typeof answer === "boolean") return answer ? "正确" : "错误";
  if (Array.isArray(answer)) return answer.join(", ");
  return String(answer);
}

function typeLabel(t: string | null) {
  const map: Record<string, string> = {
    single_choice: "单选题",
    multiple_choice: "多选题",
    true_false: "判断题",
    fill_blank: "填空题",
    multi_blank_choice: "多空选择",
    subjective: "问答题",
  };
  return map[t ?? ""] ?? t ?? "未知";
}

export default function TextImportPage() {
  const [text, setText] = useState("");
  const [subject, setSubject] = useState("");
  const [parseResult, setParseResult] = useState<ParseResponse | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<ParsedQuestion | null>(null);
  const [importStatus, setImportStatus] = useState<ImportResponse | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const charCount = text.length;

  const parseMutation = useMutation({
    mutationFn: () =>
      apiRequest<ParseResponse>("/imports/text-parse", {
        method: "POST",
        body: JSON.stringify({ text, subject }),
      }),
    onSuccess: (data) => {
      setParseResult(data);
      setImportStatus(null);
      setGlobalError(null);
    },
    onError: (err) => {
      setGlobalError(err instanceof Error ? err.message : "解析请求失败");
    },
  });

  const importMutation = useMutation({
    mutationFn: () =>
      apiRequest<ImportResponse>("/imports/text-import", {
        method: "POST",
        body: JSON.stringify({
          subject,
          questions: parseResult?.questions.filter((q) => q.is_valid) ?? [],
        }),
      }),
    onSuccess: (data) => {
      setImportStatus(data);
    },
    onError: (err) => {
      setGlobalError(err instanceof Error ? err.message : "导入请求失败");
    },
  });

  const handleParse = () => {
    if (!text.trim()) {
      setGlobalError("请输入题目文本");
      return;
    }
    parseMutation.mutate();
  };

  const handleDelete = (index: number) => {
    if (!parseResult) return;
    const next = parseResult.questions.filter((_, i) => i !== index);
    setParseResult({
      ...parseResult,
      questions: next,
      raw_count: next.length,
      valid_count: next.filter((q) => q.is_valid).length,
    });
  };

  const startEdit = (index: number) => {
    if (!parseResult) return;
    setEditingIndex(index);
    const q = parseResult.questions[index];
    setEditForm({
      ...q,
      options: q.options.map((o) => ({ ...o })),
      knowledge_points: [...(q.knowledge_points || [])],
    });
  };

  const saveEdit = () => {
    if (!parseResult || editingIndex === null || !editForm) return;
    const next = [...parseResult.questions];
    next[editingIndex] = {
      ...editForm,
      is_valid: true,
      errors: [],
      warnings: [],
      question_hash: null,
      stem_hash: null,
    };
    setParseResult({
      ...parseResult,
      questions: next,
      valid_count: next.filter((q) => q.is_valid).length,
    });
    setEditingIndex(null);
    setEditForm(null);
  };

  const handleImport = () => {
    if (!parseResult || parseResult.valid_count === 0) return;
    importMutation.mutate();
  };

  const hasValidQuestions = (parseResult?.valid_count ?? 0) > 0;

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">
          Text Import
        </p>
        <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">
          文本导入
        </h2>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          粘贴题目文本，自动解析为结构化题目数据
        </p>
      </div>

      <div className="grid gap-6 items-start xl:grid-cols-[1fr_1fr]">
        {/* ===== Left: Input ===== */}
        <Card className="min-w-0">
          <CardHeader>
            <h3 className="font-display text-xl font-bold text-[var(--ink)]">
              输入文本
            </h3>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-semibold text-[var(--ink)]">
                科目 <span className="text-xs text-[var(--color-text-hint)]">(选填，留空自动识别)</span>
              </label>
              <select
                className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
              >
                <option value="">自动识别</option>
                {SUBJECTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <div className="mb-1 flex items-center justify-between">
                <label className="text-sm font-semibold text-[var(--ink)]">
                  题目文本
                </label>
                <span className="font-mono text-xs text-[var(--color-text-hint)]">
                  {charCount} 字
                </span>
              </div>
              <textarea
                className="min-h-[320px] w-full resize-y rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4 font-mono text-sm leading-relaxed outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
                placeholder={`支持格式示例：

【题目】
操作系统采用时间片轮转调度算法的主要目的是（）。

【选项】
A. 提高系统吞吐量
B. 提高CPU利用率
C. 保证响应时间
D. 减少进程切换

【答案】
C

【解析】
时间片轮转属于分时系统调度算法。

====================

【题目】
第二题...
...
`}
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  setParseResult(null);
                  setImportStatus(null);
                  setEditingIndex(null);
                  setEditForm(null);
                }}
              />
            </div>

            <Button
              className="w-full h-12"
              onClick={handleParse}
              disabled={parseMutation.isPending || !text.trim()}
            >
              {parseMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowRight className="h-4 w-4" />
              )}
              {parseMutation.isPending ? "解析中..." : "解析文本"}
            </Button>

            {globalError ? (
              <div className="flex items-start gap-2 rounded-2xl border border-[var(--color-danger)] bg-red-50/70 px-4 py-3 text-sm text-[var(--color-danger)]">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{globalError}</span>
              </div>
            ) : null}
          </CardContent>
        </Card>

        {/* ===== Right: Results ===== */}
        <div className="flex flex-col gap-4 min-w-0">
          {parseResult ? (
            <>
              {/* Stats bar */}
              <Card className="shrink-0">
                <CardContent className="py-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 text-sm">
                      <span className="text-[var(--color-text-secondary)]">
                        解析结果
                      </span>
                      <span className="font-semibold text-[var(--ink)]">
                        {parseResult.raw_count} 题
                      </span>
                      <span className="text-green-600">
                        {parseResult.valid_count} 有效
                      </span>
                      {parseResult.raw_count - parseResult.valid_count > 0 ? (
                        <span className="text-red-500">
                          {parseResult.raw_count - parseResult.valid_count} 无效
                        </span>
                      ) : null}
                    </div>
                    <Button
                      variant="primary"
                      disabled={!hasValidQuestions || importMutation.isPending}
                      onClick={handleImport}
                    >
                      {importMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <CheckCircle2 className="h-4 w-4" />
                      )}
                      {importMutation.isPending ? "导入中..." : "确认导入"}
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Warnings */}
              {parseResult.warnings.length > 0 ? (
                <div className="flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-sm text-amber-700">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <ul className="list-inside list-disc space-y-1">
                    {parseResult.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {/* Import result */}
              {importStatus ? (
                <div className="flex items-center gap-2.5 rounded-2xl border border-green-200 bg-green-50/70 px-4 py-3 text-sm">
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600" />
                  <div>
                    <span className="font-semibold text-green-700">导入完成</span>
                    <span className="ml-2 text-green-600">
                      批次 {importStatus.batch_id}：成功 {importStatus.succeeded}
                      题，失败 {importStatus.failed} 题
                    </span>
                  </div>
                </div>
              ) : null}

              {/* Question list + edit panel */}
              <div className="flex flex-col gap-3">
                {/* Compact question cards — scrollable to keep right column bounded */}
                <div className="space-y-2 overflow-y-auto max-h-[55vh]">
                  {parseResult.questions.map((q, index) => (
                    <Card key={index}>
                      <CardContent className="px-4 py-3">
                        <div className="space-y-1.5">
                          {/* Header row */}
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                              <span className="shrink-0 text-sm font-semibold text-[var(--ink)]">
                                题 {index + 1}
                              </span>
                              <StatusBadge tone={q.is_valid ? "success" : "danger"}>
                                {q.is_valid ? "有效" : "无效"}
                              </StatusBadge>
                              <span className="text-[10px] text-[var(--color-text-hint)]">
                                {typeLabel(q.question_type)}
                              </span>
                              {q.subject ? (
                                <span className="rounded-full bg-[var(--color-primary-light)] px-1.5 py-0.5 text-[9px] font-medium text-[var(--color-primary-dark)]">
                                  {q.subject}
                                </span>
                              ) : null}
                            </div>
                            <div className="flex shrink-0 gap-0.5">
                              <Button variant="ghost" className="h-7 w-7 p-0" onClick={() => startEdit(index)}>
                                <Edit3 className="h-3.5 w-3.5" />
                              </Button>
                              <Button variant="ghost" className="h-7 w-7 p-0" onClick={() => handleDelete(index)}>
                                <Trash2 className="h-3.5 w-3.5 text-[var(--color-danger)]" />
                              </Button>
                            </div>
                          </div>

                          {/* Stem — single line truncated */}
                          <p className="truncate text-xs text-[var(--color-text-secondary)]" title={q.stem}>
                            {q.stem || "—"}
                          </p>

                          {/* Options inline — wrap naturally */}
                          {q.options.length > 0 ? (
                            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--color-text-hint)]">
                              {q.options.map((opt) => (
                                <span key={opt.key} className="truncate max-w-[30%]">
                                  <span className="font-semibold text-[var(--color-text-secondary)]">{opt.key}.</span>{" "}
                                  {opt.text}
                                </span>
                              ))}
                            </div>
                          ) : null}

                          {/* Answer + analysis + warnings — nowrap for key-value, wrap for content */}
                          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-[var(--color-text-hint)]">
                            <span className="whitespace-nowrap">
                              答案：<span className="font-semibold text-[var(--color-text-secondary)]">{renderAnswer(q.answer)}</span>
                            </span>
                            {q.analysis ? (
                              <span className="min-w-0 truncate" title={q.analysis}>
                                解析：<span className="text-[var(--color-text-secondary)]">{q.analysis}</span>
                              </span>
                            ) : null}
                            {q.warnings.length > 0 ? (
                              <span className="shrink-0 text-amber-500" title={q.warnings.join("；")}>
                                ⚠ {q.warnings.length}
                              </span>
                            ) : null}
                            {q.errors.length > 0 ? (
                              <span className="shrink-0 text-red-400" title={q.errors.join("、")}>
                                ✗ {q.errors.length}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {/* Edit panel — always below the question list, never inline */}
                {editingIndex !== null && editForm ? (
                  <Card className="shrink-0 border-[var(--color-primary)]">
                    <CardContent className="py-4">
                      <div className="space-y-4">
                        {/* Header */}
                        <div className="flex items-center justify-between">
                          <h4 className="font-display text-lg font-bold text-[var(--ink)]">
                            编辑 题目 {editingIndex + 1}
                          </h4>
                          <div className="flex gap-2">
                            <Button variant="ghost" onClick={() => { setEditingIndex(null); setEditForm(null); }}>
                              取消
                            </Button>
                            <Button onClick={saveEdit}>
                              <CheckCircle2 className="h-4 w-4" />
                              保存
                            </Button>
                          </div>
                        </div>

                        {/* Subject & Type */}
                        <div className="grid gap-3 sm:grid-cols-2">
                          <label className="block space-y-1">
                            <span className="text-xs font-semibold text-[var(--color-text-secondary)]">科目</span>
                            <select className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)]" value={editForm.subject ?? ""} onChange={(e) => setEditForm({ ...editForm, subject: e.target.value || null })}>
                              <option value="">未指定</option>
                              {SUBJECTS.map((s) => (
                                <option key={s.value} value={s.value}>{s.label}</option>
                              ))}
                            </select>
                          </label>
                          <label className="block space-y-1">
                            <span className="text-xs font-semibold text-[var(--color-text-secondary)]">题型</span>
                            <input className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)]" value={editForm.question_type ?? ""} onChange={(e) => setEditForm({ ...editForm, question_type: e.target.value || null })} />
                          </label>
                        </div>

                        {/* Stem */}
                        <label className="block space-y-1">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">题干</span>
                          <textarea className="mt-1 min-h-[80px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm outline-none transition focus:border-[var(--color-primary)]" value={editForm.stem} onChange={(e) => setEditForm({ ...editForm, stem: e.target.value })} />
                        </label>

                        {/* Options */}
                        <label className="block space-y-1">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">选项 <span className="text-[10px] text-[var(--color-text-hint)]">(每行一个，格式 A. xxx)</span></span>
                          <textarea className="mt-1 min-h-[60px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm font-mono outline-none transition focus:border-[var(--color-primary)]" value={editForm.options.map((o) => `${o.key}. ${o.text}`).join("\n")} onChange={(e) => {
                            const lines = e.target.value.split("\n");
                            const opts: ParsedOption[] = [];
                            for (const line of lines) {
                              const m = line.match(/^([A-Da-d])\s*[.．、:：)）]?\s*(.+)/);
                              if (m) opts.push({ key: m[1].toUpperCase(), text: m[2].trim() });
                            }
                            setEditForm({ ...editForm, options: opts });
                          }} />
                        </label>

                        {/* Answer */}
                        <div className="grid gap-3 sm:grid-cols-2">
                          <label className="block space-y-1">
                            <span className="text-xs font-semibold text-[var(--color-text-secondary)]">答案</span>
                            <input className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)]" value={typeof editForm.answer === "boolean" ? (editForm.answer ? "正确" : "错误") : Array.isArray(editForm.answer) ? editForm.answer.join(",") : String(editForm.answer ?? "")} onChange={(e) => setEditForm({ ...editForm, answer: e.target.value })} />
                          </label>
                        </div>

                        {/* Analysis */}
                        <label className="block space-y-1">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">解析</span>
                          <textarea className="mt-1 min-h-[60px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm outline-none transition focus:border-[var(--color-primary)]" value={editForm.analysis ?? ""} onChange={(e) => setEditForm({ ...editForm, analysis: e.target.value })} />
                        </label>
                      </div>
                    </CardContent>
                  </Card>
                ) : null}
              </div>
            </>
          ) : (
            <Card>
              <CardContent className="flex flex-col items-center py-16 text-center">
                <FileText className="h-12 w-12 text-[var(--color-text-hint)]" />
                <p className="mt-4 text-sm text-[var(--color-text-secondary)]">
                  在左侧粘贴题目文本并点击"解析文本"
                </p>
                <p className="mt-1 text-xs text-[var(--color-text-hint)]">
                  支持标签格式（【题目】/【选项】/【答案】/【解析】）和无标签格式
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
