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
    if (!subject) {
      setGlobalError("请选择科目");
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

      <div className="grid gap-6 xl:grid-cols-2">
        {/* 左侧：输入区 */}
        <Card>
          <CardHeader>
            <h3 className="font-display text-xl font-bold text-[var(--ink)]">
              输入文本
            </h3>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* 科目选择 */}
            <div>
              <label className="mb-1 block text-sm font-semibold text-[var(--ink)]">
                科目 <span className="text-[var(--color-danger)]">*</span>
              </label>
              <select
                className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
              >
                <option value="">请选择科目</option>
                {SUBJECTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>

            {/* 文本输入 */}
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
                className="min-h-[320px] w-full resize-y rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4 font-mono text-sm leading-relaxed outline-none focus:border-[var(--color-primary)]"
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
                }}
              />
            </div>

            <Button
              className="w-full"
              onClick={handleParse}
              disabled={parseMutation.isPending || !text.trim() || !subject}
            >
              {parseMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowRight className="h-4 w-4" />
              )}
              {parseMutation.isPending ? "解析中..." : "解析文本"}
            </Button>

            {globalError ? (
              <div className="flex items-start gap-2 rounded-2xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] p-3 text-sm text-[var(--color-danger)]">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{globalError}</span>
              </div>
            ) : null}
          </CardContent>
        </Card>

        {/* 右侧：解析结果 */}
        <div className="space-y-4">
          {parseResult ? (
            <>
              {/* 统计栏 */}
              <Card>
                <CardContent className="py-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4 text-sm">
                      <span className="text-[var(--color-text-secondary)]">
                        解析结果
                      </span>
                      <span className="font-semibold text-[var(--ink)]">
                        {parseResult.raw_count} 题
                      </span>
                      <span className="text-[var(--color-success)]">
                        {parseResult.valid_count} 有效
                      </span>
                      {parseResult.raw_count - parseResult.valid_count > 0 ? (
                        <span className="text-[var(--color-danger)]">
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

              {/* 全局警告 */}
              {parseResult.warnings.length > 0 ? (
                <div className="flex items-start gap-2 rounded-2xl border border-[var(--color-warning)] bg-[var(--color-warning-light)] p-3 text-sm text-[var(--color-warning-dark)]">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <ul className="list-inside list-disc space-y-1">
                    {parseResult.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {/* 导入结果 */}
              {importStatus ? (
                <div className="rounded-2xl border border-[var(--color-success)] bg-[var(--color-success-light)] p-4 text-sm">
                  <p className="font-semibold text-[var(--color-success)]">
                    导入完成
                  </p>
                  <p className="mt-1 text-[var(--color-text-secondary)]">
                    批次 {importStatus.batch_id}：成功 {importStatus.succeeded}{" "}
                    题，失败 {importStatus.failed} 题
                  </p>
                </div>
              ) : null}

              {/* 题目列表 */}
              <div className="max-h-[600px] space-y-3 overflow-y-auto">
                {parseResult.questions.map((q, index) => (
                  <Card key={index}>
                    <CardContent className="py-4">
                      {editingIndex === index && editForm ? (
                        /* 编辑模式 */
                        <div className="space-y-3">
                          <div className="flex items-center justify-between">
                            <h4 className="font-semibold text-[var(--ink)]">
                              编辑 题目 {index + 1}
                            </h4>
                            <div className="flex gap-2">
                              <Button
                                variant="secondary"
                                onClick={() => {
                                  setEditingIndex(null);
                                  setEditForm(null);
                                }}
                              >
                                取消
                              </Button>
                              <Button onClick={saveEdit}>保存</Button>
                            </div>
                          </div>
                          <label className="block">
                            <span className="text-xs font-semibold">题干</span>
                            <textarea
                              className="mt-1 min-h-[80px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2 text-sm"
                              value={editForm.stem}
                              onChange={(e) =>
                                setEditForm({ ...editForm, stem: e.target.value })
                              }
                            />
                          </label>
                          <label className="block">
                            <span className="text-xs font-semibold">选项</span>
                            <textarea
                              className="mt-1 min-h-[60px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2 text-sm font-mono"
                              value={editForm.options
                                .map((o) => `${o.key}. ${o.text}`)
                                .join("\n")}
                              onChange={(e) => {
                                const lines = e.target.value.split("\n");
                                const opts: ParsedOption[] = [];
                                for (const line of lines) {
                                  const m = line.match(
                                    /^([A-Da-d])\s*[.．、:：)）]?\s*(.+)/,
                                  );
                                  if (m) {
                                    opts.push({
                                      key: m[1].toUpperCase(),
                                      text: m[2].trim(),
                                    });
                                  }
                                }
                                setEditForm({ ...editForm, options: opts });
                              }}
                            />
                          </label>
                          <label className="block">
                            <span className="text-xs font-semibold">答案</span>
                            <input
                              className="mt-1 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2 text-sm"
                              value={
                                typeof editForm.answer === "boolean"
                                  ? editForm.answer
                                    ? "正确"
                                    : "错误"
                                  : Array.isArray(editForm.answer)
                                    ? editForm.answer.join(",")
                                    : String(editForm.answer ?? "")
                              }
                              onChange={(e) =>
                                setEditForm({
                                  ...editForm,
                                  answer: e.target.value,
                                })
                              }
                            />
                          </label>
                          <label className="block">
                            <span className="text-xs font-semibold">解析</span>
                            <textarea
                              className="mt-1 min-h-[60px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2 text-sm"
                              value={editForm.analysis ?? ""}
                              onChange={(e) =>
                                setEditForm({
                                  ...editForm,
                                  analysis: e.target.value,
                                })
                              }
                            />
                          </label>
                        </div>
                      ) : (
                        /* 预览模式 */
                        <div className="space-y-2">
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-semibold text-[var(--ink)]">
                                题目 {index + 1}
                              </span>
                              <StatusBadge
                                tone={q.is_valid ? "success" : "danger"}
                              >
                                {q.is_valid ? "有效" : "无效"}
                              </StatusBadge>
                              <span className="text-xs text-[var(--color-text-hint)]">
                                [{typeLabel(q.question_type)}]
                              </span>
                              <span className="text-xs text-[var(--color-text-hint)]">
                                [{q.detection_method}]
                              </span>
                            </div>
                            <div className="flex shrink-0 gap-1">
                              <Button
                                variant="ghost"
                                onClick={() => startEdit(index)}
                              >
                                <Edit3 className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                onClick={() => handleDelete(index)}
                              >
                                <Trash2 className="h-3.5 w-3.5 text-[var(--color-danger)]" />
                              </Button>
                            </div>
                          </div>

                          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm">
                            <p className="font-semibold text-[var(--ink)]">题干</p>
                            <pre className="mt-1 whitespace-pre-wrap font-sans text-[var(--color-text-secondary)]">
                              {q.stem || "—"}
                            </pre>
                          </div>

                          {q.options.length > 0 ? (
                            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm">
                              <p className="font-semibold text-[var(--ink)]">选项</p>
                              <ul className="mt-1 space-y-0.5">
                                {q.options.map((opt) => (
                                  <li
                                    key={opt.key}
                                    className="text-[var(--color-text-secondary)]"
                                  >
                                    <span className="font-semibold">
                                      {opt.key}.
                                    </span>{" "}
                                    {opt.text}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ) : null}

                          <div className="grid grid-cols-2 gap-2">
                            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm">
                              <p className="font-semibold text-[var(--ink)]">答案</p>
                              <p className="mt-1 text-[var(--color-text-secondary)]">
                                {renderAnswer(q.answer)}
                              </p>
                            </div>
                            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm">
                              <p className="font-semibold text-[var(--ink)]">解析</p>
                              <p className="mt-1 text-[var(--color-text-secondary)]">
                                {q.analysis || "—"}
                              </p>
                            </div>
                          </div>

                          {q.warnings.length > 0 ? (
                            <div className="flex items-start gap-1.5 text-xs text-[var(--color-warning)]">
                              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                              <span>{q.warnings.join("；")}</span>
                            </div>
                          ) : null}

                          {q.errors.length > 0 ? (
                            <div className="text-xs text-[var(--color-danger)]">
                              错误：{q.errors.join("、")}
                            </div>
                          ) : null}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}
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
