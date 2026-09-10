"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  Edit3,
  FileText,
  Loader2,
  Trash2,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import { CustomSelect } from "@/components/ui/custom-select";
import { apiRequest } from "@/lib/api/client";
import { ImportMetric, ImportPanelHeader, ImportWorkspaceHeader } from "../components/import-workspace";
import { getQuestionTypeLabel, QUESTION_TYPE_OPTIONS, canonicalizeQuestionType, formatUnknownType } from "@/lib/question-types";

type ParsedOption = { key: string; text: string };

type ParsedQuestion = {
  subject_id?: number | null;
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
  status: "ok" | "fail" | "duplicate";
  error?: string;
};

type ImportResponse = {
  batch_id: string;
  items: ImportResultItem[];
  total: number;
  succeeded: number;
  failed: number;
  duplicates_filtered: number;
};

function renderAnswer(answer: string | string[] | boolean | null) {
  if (answer === null || answer === undefined || answer === "") return "—";
  if (typeof answer === "boolean") return answer ? "正确" : "错误";
  if (Array.isArray(answer)) return answer.join(", ");
  return String(answer);
}

function typeLabel(t: string | null) {
  return getQuestionTypeLabel(t);
}

export default function TextImportPage() {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [subjectOptions, setSubjectOptions] = useState<Array<{id: number; code: string; name: string}>>([]);
  useEffect(() => {
    apiRequest<Array<{id: number; code: string; name: string; path: string; level: number}>>("/imports/subject-options")
      .then(setSubjectOptions)
      .catch(() => {});
  }, []);
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
        body: JSON.stringify({ text, subject_id: null }),
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
          subject_id: null,
          questions: parseResult?.questions.filter((q) => q.is_valid) ?? [],
        }),
      }),
    onSuccess: (data) => {
      setImportStatus(data);
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
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
    <div className="space-y-6 pb-4">
      <ImportWorkspaceHeader
        icon={FileText}
        title="文本导入"
        description="粘贴结构化或自然语言题目，先解析校验，再把有效题目送入审核队列。编辑与异常信息集中在同一工作台内，减少上下文切换。"
        meta={
          <div className="inline-flex h-9 items-center gap-2 rounded-full border border-[var(--color-border)] bg-white/70 px-3 text-xs text-[var(--color-text-secondary)]">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]" aria-hidden="true" />
            解析后确认入库
          </div>
        }
      />

      {globalError ? (
        <div role="alert" className="flex items-start gap-3 rounded-2xl border border-[rgba(196,77,77,0.28)] bg-[var(--color-danger-light)] px-4 py-3.5 text-sm text-[var(--color-danger)] import-feedback-in">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-semibold">操作未完成</p>
            <p className="mt-0.5 text-xs leading-5">{globalError}</p>
          </div>
        </div>
      ) : null}

      <section className="overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.82)] shadow-[var(--shadow-card)] import-enter" style={{ animationDelay: "55ms" }}>
        <div className="grid min-h-[620px] xl:grid-cols-[minmax(0,0.88fr)_minmax(0,1.12fr)]">
          <div className="min-w-0 border-b border-[var(--color-border-light)] xl:border-b-0 xl:border-r">
            <ImportPanelHeader
              title="原始文本"
              description="支持标签格式与无标签题目；修改文本会清空当前解析结果。"
              trailing={<span className="font-mono text-[11px] tabular-nums text-[var(--color-text-hint)]">{charCount.toLocaleString()} 字</span>}
            />
            <div className="flex h-[calc(100%-4rem)] min-h-[555px] flex-col p-4 sm:p-5">
              <label htmlFor="question-import-text" className="sr-only">题目文本</label>
              <textarea
                id="question-import-text"
                className="min-h-[430px] flex-1 resize-y rounded-xl border border-[var(--color-border)] bg-[rgba(239,235,229,0.62)] px-4 py-3.5 font-mono text-[13px] leading-6 text-[var(--ink)] outline-none transition-[border-color,background-color,box-shadow] duration-150 placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]"
                placeholder={`【题目】\n操作系统采用时间片轮转调度算法的主要目的是（）。\n\n【选项】\nA. 提高系统吞吐量\nB. 提高CPU利用率\nC. 保证响应时间\nD. 减少进程切换\n\n【答案】\nC\n\n【解析】\n时间片轮转属于分时系统调度算法。`}
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  setParseResult(null);
                  setImportStatus(null);
                  setEditingIndex(null);
                  setEditForm(null);
                }}
              />

              <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs leading-5 text-[var(--color-text-hint)]">
                  可识别 【题目】/【选项】/【答案】/【解析】，多题可直接连续粘贴。
                </p>
                <Button
                  className="h-11 min-w-32 import-interactive group"
                  onClick={handleParse}
                  disabled={parseMutation.isPending || !text.trim()}
                >
                  {parseMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transform-none" aria-hidden="true" />}
                  {parseMutation.isPending ? "解析中" : "解析文本"}
                </Button>
              </div>
            </div>
          </div>

          <div className="min-w-0 bg-white/30">
            {parseResult ? (
              <div className="flex min-h-[620px] flex-col import-panel-swap">
                <ImportPanelHeader
                  title="解析结果"
                  description="先处理无效项与警告，再确认导入。"
                  trailing={
                    <Button
                      className="h-11"
                      disabled={!hasValidQuestions || importMutation.isPending}
                      onClick={handleImport}
                    >
                      {importMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
                      {importMutation.isPending ? "导入中" : "确认导入"}
                    </Button>
                  }
                />

                <div className="grid grid-cols-3 divide-x divide-[var(--color-border-light)] border-b border-[var(--color-border-light)] bg-white/55" aria-live="polite">
                  <ImportMetric label="识别题目" value={parseResult.raw_count} />
                  <ImportMetric label="有效" value={parseResult.valid_count} tone="success" />
                  <ImportMetric label="需处理" value={Math.max(0, parseResult.raw_count - parseResult.valid_count)} tone={parseResult.raw_count - parseResult.valid_count > 0 ? "danger" : "neutral"} />
                </div>

                {parseResult.warnings.length > 0 ? (
                  <div role="status" className="mx-4 mt-4 flex items-start gap-2.5 rounded-xl border border-[rgba(196,154,107,0.35)] bg-[var(--color-warning-light)] px-3.5 py-3 text-xs leading-5 text-[var(--color-text-primary)] sm:mx-5 import-feedback-in">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    <div className="space-y-1">
                      {parseResult.warnings.map((w, i) => <p key={i}>{w}</p>)}
                    </div>
                  </div>
                ) : null}

                {importStatus ? (
                  <div role="status" className="mx-4 mt-4 flex items-start gap-2.5 rounded-xl border border-[rgba(91,140,91,0.3)] bg-[var(--color-success-light)] px-3.5 py-3 text-xs leading-5 text-[var(--color-success)] sm:mx-5 import-feedback-in">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    <div>
                      <p className="font-semibold">导入完成 · 批次 {importStatus.batch_id}</p>
                      <p className="mt-0.5">
                        成功 {importStatus.succeeded} 题
                        {importStatus.duplicates_filtered > 0 ? ` · 过滤重复 ${importStatus.duplicates_filtered} 题` : ""}
                        {importStatus.failed > 0 ? ` · 失败 ${importStatus.failed} 题` : ""}
                      </p>
                    </div>
                  </div>
                ) : null}

                <div className="min-h-0 flex-1 p-4 sm:p-5">
                  <div className="max-h-[440px] overflow-y-auto rounded-xl border border-[var(--color-border-light)] bg-white/65">
                    {parseResult.questions.map((q, index) => (
                      <article key={index} className="group border-b border-[var(--color-border-light)] px-4 py-3.5 last:border-b-0 hover:bg-[rgba(74,111,138,0.035)] import-list-item import-interactive" style={{ animationDelay: `${Math.min(index, 8) * 28}ms` }}>
                        <div className="flex items-start gap-3">
                          <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${q.is_valid ? "bg-[var(--color-success)]" : "bg-[var(--color-danger)]"}`} aria-hidden="true" />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                              <span className="text-xs font-semibold text-[var(--ink)]">题目 {index + 1}</span>
                              <StatusBadge tone={q.is_valid ? "success" : "danger"}>{q.is_valid ? "有效" : "无效"}</StatusBadge>
                              <span className="text-[11px] text-[var(--color-text-hint)]">{typeLabel(q.question_type)}</span>
                              {q.subject_id ? (
                                <span className="rounded-full border border-[rgba(74,111,138,0.18)] bg-[var(--color-primary-light)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-primary-dark)]">
                                  {subjectOptions.find((s) => s.id === q.subject_id)?.name || `#${q.subject_id}`}
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-2 line-clamp-2 text-sm leading-6 text-[var(--color-text-secondary)]" title={q.stem}>{q.stem || "—"}</p>

                            {q.options.length > 0 ? (
                              <div className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-2">
                                {q.options.slice(0, 4).map((opt) => (
                                  <p key={opt.key} className="min-w-0 truncate text-[11px] text-[var(--color-text-hint)]">
                                    <span className="mr-1 font-semibold text-[var(--color-text-secondary)]">{opt.key}.</span>{opt.text}
                                  </p>
                                ))}
                              </div>
                            ) : null}

                            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-text-hint)]">
                              <span>答案 <strong className="font-semibold text-[var(--color-text-secondary)]">{renderAnswer(q.answer)}</strong></span>
                              {q.analysis ? <span className="min-w-0 max-w-[46ch] truncate" title={q.analysis}>解析 {q.analysis}</span> : null}
                              {q.warnings.length > 0 ? <span className="text-[var(--color-text-primary)]">{q.warnings.length} 条警告</span> : null}
                              {q.errors.length > 0 ? <span className="text-[var(--color-danger)]">{q.errors.length} 个错误</span> : null}
                            </div>
                          </div>

                          <div className="flex shrink-0 gap-1">
                            <Button variant="ghost" className="h-11 w-11 p-0 import-interactive" aria-label={`编辑题目 ${index + 1}`} title="编辑题目" onClick={() => startEdit(index)}>
                              <Edit3 className="h-4 w-4" aria-hidden="true" />
                            </Button>
                            <Button variant="ghost" className="h-11 w-11 p-0 import-interactive" aria-label={`删除题目 ${index + 1}`} title="删除题目" onClick={() => handleDelete(index)}>
                              <Trash2 className="h-4 w-4 text-[var(--color-danger)]" aria-hidden="true" />
                            </Button>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>

                  {editingIndex !== null && editForm ? (
                    <section className="mt-4 overflow-hidden rounded-xl border border-[rgba(74,111,138,0.32)] bg-white import-panel-swap">
                      <ImportPanelHeader
                        title={`编辑题目 ${editingIndex + 1}`}
                        description="保存后会重新标记为有效，并清空当前错误与警告。"
                        trailing={
                          <div className="flex gap-2">
                            <Button variant="ghost" className="h-11 import-interactive" onClick={() => { setEditingIndex(null); setEditForm(null); }}>取消</Button>
                            <Button className="h-11 import-interactive" onClick={saveEdit}><CheckCircle2 className="h-4 w-4" aria-hidden="true" />保存</Button>
                          </div>
                        }
                      />
                      <div className="grid gap-4 p-4 sm:grid-cols-2 sm:p-5">
                        <label className="space-y-1.5">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">科目</span>
                          <select className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]" value={editForm.subject_id ?? ""} onChange={(e) => setEditForm({ ...editForm, subject_id: e.target.value ? Number(e.target.value) : null })}>
                            <option value="">未指定</option>
                            {subjectOptions.map((s) => <option key={s.id} value={String(s.id)}>{s.name}</option>)}
                          </select>
                        </label>
                        <div className="space-y-1.5">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">题型</span>
                          <CustomSelect
                            value={editForm.question_type ?? ""}
                            onChange={(v) => setEditForm({ ...editForm, question_type: v || null })}
                            options={canonicalizeQuestionType(editForm.question_type) || !editForm.question_type
                              ? QUESTION_TYPE_OPTIONS
                              : [...QUESTION_TYPE_OPTIONS, { value: editForm.question_type!, label: formatUnknownType(editForm.question_type!), disabled: true }]}
                            placeholder="选择题型"
                            clearable={false}
                          />
                        </div>
                        <label className="space-y-1.5 sm:col-span-2">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">题干</span>
                          <textarea className="min-h-24 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2.5 text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]" value={editForm.stem} onChange={(e) => setEditForm({ ...editForm, stem: e.target.value })} />
                        </label>
                        <label className="space-y-1.5 sm:col-span-2">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">选项 <span className="font-normal text-[var(--color-text-hint)]">每行一个，例如 A. 选项内容</span></span>
                          <textarea className="min-h-24 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2.5 font-mono text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]" value={editForm.options.map((o) => `${o.key}. ${o.text}`).join("\n")} onChange={(e) => {
                            const lines = e.target.value.split("\n");
                            const opts: ParsedOption[] = [];
                            for (const line of lines) {
                              const m = line.match(/^([A-Da-d])\s*[.．、:：)）]?\s*(.+)/);
                              if (m) opts.push({ key: m[1].toUpperCase(), text: m[2].trim() });
                            }
                            setEditForm({ ...editForm, options: opts });
                          }} />
                        </label>
                        <label className="space-y-1.5">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">答案</span>
                          <input className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]" value={typeof editForm.answer === "boolean" ? (editForm.answer ? "正确" : "错误") : Array.isArray(editForm.answer) ? editForm.answer.join(",") : String(editForm.answer ?? "")} onChange={(e) => setEditForm({ ...editForm, answer: e.target.value })} />
                        </label>
                        <label className="space-y-1.5 sm:col-span-2">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">解析</span>
                          <textarea className="min-h-24 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2.5 text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]" value={editForm.analysis ?? ""} onChange={(e) => setEditForm({ ...editForm, analysis: e.target.value })} />
                        </label>
                      </div>
                    </section>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="flex min-h-[620px] flex-col import-panel-swap">
                <ImportPanelHeader title="解析结果" description="结果将在这里按有效性、题型与异常信息分组呈现。" />
                <div className="flex flex-1 items-center justify-center px-6 py-14">
                  <div className="max-w-sm text-center import-panel-swap">
                    <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] text-[var(--color-primary-dark)] import-soft-pop">
                      <FileText className="h-6 w-6" strokeWidth={1.6} aria-hidden="true" />
                    </div>
                    <p className="mt-4 text-sm font-semibold text-[var(--ink)]">等待解析内容</p>
                    <p className="mt-1.5 text-xs leading-5 text-[var(--color-text-hint)]">粘贴题目后执行解析。解析完成后可逐题编辑、删除，并仅导入有效题目。</p>
                    <div className="mt-5 grid grid-cols-3 divide-x divide-[var(--color-border-light)] border-y border-[var(--color-border-light)] py-2.5 text-[11px] text-[var(--color-text-secondary)]">
                      <span>识别</span><span>校验</span><span>入库</span>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
