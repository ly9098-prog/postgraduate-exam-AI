"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  AlertTriangle,
  Braces,
  Check,
  CheckCircle2,
  ChevronDown,
  Code2,
  Edit3,
  Eye,
  FileText,
  Info,
  Loader2,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import { CustomSelect } from "@/components/ui/custom-select";
import { MathFormula } from "@/components/ui/math-formula";
import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { apiRequest } from "@/lib/api/client";
import { ImportMetric, ImportPanelHeader, ImportWorkspaceHeader } from "../components/import-workspace";
import { ImportToast } from "../components/import-toast";
import { getQuestionTypeLabel, QUESTION_TYPE_OPTIONS, canonicalizeQuestionType, formatUnknownType } from "@/lib/question-types";
import { inspectLatexImportText, normalizeLatexImportDelimiters } from "@/lib/latex-import";

type ParsedOption = { key: string; text: string };

type ParsedQuestion = {
  subject?: string | null;
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

const PARSE_ISSUE_LABELS: Record<string, string> = {
  stem_empty: "题干为空",
  answer_empty: "答案为空",
  options_empty: "未识别到选项",
  options_too_few: "选项数量偏少",
  subject_empty: "科目未指定",
  subject_unspecified: "科目未指定，可在审核阶段补充",
};

function formatParseIssue(message: string) {
  if (PARSE_ISSUE_LABELS[message]) return PARSE_ISSUE_LABELS[message];
  const missingOption = message.match(/^missing_option_([A-H])$/i);
  if (missingOption) return `缺少 ${missingOption[1].toUpperCase()} 选项`;
  return message;
}

function parseEditableOptions(value: string): ParsedOption[] {
  const lines = value.replace(/\r\n?/g, "\n").split("\n");
  const options = new Map<string, string[]>();
  let currentKey: string | null = null;

  const start = (key: string, text = "") => {
    currentKey = key.toUpperCase();
    if (!options.has(currentKey)) options.set(currentKey, []);
    if (text.trim()) options.get(currentKey)?.push(text.trim());
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const inline = trimmed.match(/^([A-Da-d])\s*[.．、:：)）]\s*(.+)$/);
    if (inline) {
      start(inline[1], inline[2]);
      continue;
    }
    const bare = trimmed.match(/^([A-Da-d])$/);
    if (bare) {
      start(bare[1]);
      continue;
    }
    if (currentKey) options.get(currentKey)?.push(trimmed);
  }

  return [...options.entries()]
    .map(([key, parts]) => ({ key, text: parts.join(" ").trim() }))
    .filter((option) => option.text)
    .sort((a, b) => a.key.localeCompare(b.key));
}

const TEXT_IMPORT_SAMPLE = `【题目】
若 $f(x)=x^2$，则 $f'(x)$ 等于（）。

【选项】
A. $x$
B. $2x$
C. $x^2$
D. $2$

【答案】
B

【解析】
由幂函数求导公式，
$$
f'(x)=2x
$$`;

function RenderedAnswer({ answer }: { answer: string | string[] | boolean | null }) {
  const value = renderAnswer(answer);
  if (value === "—") return <>—</>;
  return <MathFormula text={value} />;
}

function ImportTextPreview({ text }: { text: string }) {
  if (!text.trim()) {
    return (
      <div className="grid min-h-[430px] place-items-center rounded-xl border border-dashed border-[var(--color-border)] bg-white/40 px-6 text-center">
        <div>
          <Eye className="mx-auto h-5 w-5 text-[var(--color-text-hint)]" aria-hidden="true" />
          <p className="mt-2 text-sm font-semibold text-[var(--ink)]">暂无可预览内容</p>
          <p className="mt-1 text-xs leading-5 text-[var(--color-text-hint)]">输入题目后，这里会按 KaTeX 与代码保护规则预览最终阅读效果。</p>
        </div>
      </div>
    );
  }

  const parts = text.replace(/\r\n?/g, "\n").split("```");
  return (
    <div className="min-h-[430px] overflow-auto rounded-xl border border-[var(--color-border)] bg-white/80 p-4 text-sm leading-7 text-[var(--color-text-secondary)] shadow-[inset_0_1px_0_rgba(255,255,255,0.72)]">
      {parts.map((part, index) => {
        if (index % 2 === 1) {
          const newline = part.indexOf("\n");
          const maybeLanguage = newline >= 0 ? part.slice(0, newline).trim() : "";
          const code = newline >= 0 && /^[a-zA-Z0-9_+.#-]{1,20}$/.test(maybeLanguage)
            ? part.slice(newline + 1)
            : part;
          const language = code === part ? "" : maybeLanguage;
          return (
            <figure key={`code-${index}`} className="my-3 overflow-hidden rounded-xl border border-slate-200 bg-slate-50/80 first:mt-0 last:mb-0">
              {language ? (
                <figcaption className="border-b border-slate-200 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-slate-400">{language}</figcaption>
              ) : null}
              <pre className="max-w-full overflow-x-auto px-3 py-3 font-mono text-[12px] leading-6 text-slate-800 [tab-size:2]"><code>{code}</code></pre>
            </figure>
          );
        }
        if (!part) return null;
        return (
          <div key={`text-${index}`} className="whitespace-pre-wrap break-words">
            <MathFormula text={part} />
          </div>
        );
      })}
    </div>
  );
}

function LatexRulesPanel({ onClose }: { onClose: () => void }) {
  const rules = [
    {
      title: "行内公式",
      source: "$f(x)=x^2$",
      detail: "短公式放在正文内，统一使用单个 $ 包裹。",
      preview: "$f(x)=x^2$",
    },
    {
      title: "块级公式",
      source: "$$\\int_0^1 x\\,dx$$",
      detail: "积分、矩阵、长分式等独立成行，统一使用 $$ 包裹。",
      preview: "$$\\int_0^1 x\\,dx$$",
    },
    {
      title: "标准命令",
      source: "$x^2, \\sqrt{x}, \\sum, \\pi$",
      detail: "避免 x²、√x、∑、π 等 Unicode 数学符号，减少 OCR / LLM 差异。",
      preview: "$x^2, \\sqrt{x}, \\sum, \\pi$",
    },
    {
      title: "代码保护",
      source: "```c\nif (p != NULL) return;\n```",
      detail: "程序代码放进 ``` 围栏；->、!=、[]、{} 等不会进入公式规范化。",
      preview: null,
    },
  ];

  return (
    <section id="latex-import-rules" className="mb-3 overflow-hidden rounded-xl border border-[rgba(74,111,138,0.22)] bg-[rgba(237,243,246,0.54)] import-details-body">
      <div className="flex items-start justify-between gap-4 border-b border-[rgba(74,111,138,0.14)] px-4 py-3">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold text-[var(--ink)]">
            <Braces className="h-4 w-4 text-[var(--color-primary-dark)]" aria-hidden="true" />
            LaTeX 导入规则
          </div>
          <p className="mt-1 max-w-[62ch] text-[11px] leading-5 text-[var(--color-text-hint)]">
            导入标准为行内 <code className="font-mono text-[var(--color-text-secondary)]">$...$</code>、块级 <code className="font-mono text-[var(--color-text-secondary)]">$$...$$</code>；兼容 <code className="font-mono">\(...\)</code> / <code className="font-mono">\[...\]</code>，解析时会机械标准化，不改写公式内容。
          </p>
        </div>
        <button type="button" onClick={onClose} className="h-11 shrink-0 rounded-lg px-3 text-xs font-medium text-[var(--color-text-secondary)] import-interactive hover:bg-white/75" aria-label="收起 LaTeX 规则">
          收起
        </button>
      </div>
      <div className="grid gap-px bg-[rgba(74,111,138,0.12)] sm:grid-cols-2">
        {rules.map((rule) => (
          <div key={rule.title} className="bg-[rgba(254,252,249,0.94)] p-3.5">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] font-semibold text-[var(--ink)]">{rule.title}</p>
              {rule.preview ? <span className="max-w-[55%] truncate text-[11px] text-[var(--color-primary-dark)]"><MathFormula text={rule.preview} /></span> : <Code2 className="h-3.5 w-3.5 text-[var(--color-text-hint)]" aria-hidden="true" />}
            </div>
            <code className="mt-2 block overflow-x-auto whitespace-pre rounded-lg bg-[rgba(239,235,229,0.64)] px-2.5 py-2 font-mono text-[10px] leading-5 text-[var(--color-text-secondary)]">{rule.source}</code>
            <p className="mt-2 text-[11px] leading-5 text-[var(--color-text-hint)]">{rule.detail}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function LatexInspectionPanel({
  inspection,
  expanded,
  onToggle,
  onIssueClick,
}: {
  inspection: ReturnType<typeof inspectLatexImportText>;
  expanded: boolean;
  onToggle: () => void;
  onIssueClick: (line: number | null) => void;
}) {
  const hasErrors = inspection.errorCount > 0;
  const hasWarnings = inspection.warningCount > 0;
  const stateLabel = hasErrors ? `${inspection.errorCount} 个错误` : hasWarnings ? `${inspection.warningCount} 个建议` : "检查通过";
  const stateClass = hasErrors
    ? "border-[rgba(196,77,77,0.28)] bg-[var(--color-danger-light)] text-[var(--color-danger)]"
    : hasWarnings
      ? "border-[rgba(196,154,107,0.32)] bg-[var(--color-warning-light)] text-[var(--color-text-primary)]"
      : "border-[rgba(91,140,91,0.26)] bg-[var(--color-success-light)] text-[var(--color-success)]";
  const StateIcon = hasErrors ? AlertTriangle : hasWarnings ? Info : Check;

  return (
    <div className={`mt-3 overflow-hidden rounded-xl border ${stateClass}`}>
      <button
        type="button"
        onClick={onToggle}
        className="flex min-h-11 w-full items-center gap-3 px-3.5 py-2 text-left import-interactive hover:bg-white/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-primary)]"
        aria-expanded={expanded}
        aria-controls="latex-import-inspection"
      >
        <StateIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]">
            <span className="font-semibold">LaTeX 预检 · {stateLabel}</span>
            <span className="text-[var(--color-text-hint)]">
              行内 {inspection.inlineCount} · 块级 {inspection.blockCount} · 代码块 {inspection.codeFenceCount}
            </span>
          </div>
        </div>
        <ChevronDown className={`h-4 w-4 shrink-0 import-chevron ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>

      {expanded ? (
        <div id="latex-import-inspection" className="border-t border-[rgba(74,111,138,0.12)] bg-white/40 px-3.5 py-3 import-details-body">
          {inspection.issues.length === 0 ? (
            <div className="flex items-start gap-2 text-[11px] leading-5">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <p>定界符、花括号与代码围栏未发现结构问题。解析仍会执行服务端题目结构校验。</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {inspection.issues.map((issue) => {
                const Icon = issue.severity === "error" ? AlertTriangle : issue.severity === "warning" ? Info : CheckCircle2;
                const content = (
                  <>
                    <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="font-semibold">{issue.title}</span>
                      {issue.line ? <span className="ml-1.5 font-mono text-[10px] opacity-70">L{issue.line}</span> : null}
                      <span className="mt-0.5 block leading-5 opacity-80">{issue.detail}</span>
                    </span>
                  </>
                );

                return issue.line ? (
                  <button
                    key={issue.id}
                    type="button"
                    onClick={() => onIssueClick(issue.line)}
                    className="flex min-h-11 w-full items-start gap-2 rounded-lg px-2 py-2 text-left text-[11px] import-interactive hover:bg-white/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
                    title={`跳转到第 ${issue.line} 行`}
                  >
                    {content}
                  </button>
                ) : (
                  <div key={issue.id} className="flex min-h-11 items-start gap-2 rounded-lg px-2 py-2 text-[11px]">{content}</div>
                );
              })}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

export default function TextImportPage() {
  const queryClient = useQueryClient();
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  const editSectionRef = useRef<HTMLElement>(null);
  const [text, setText] = useState("");
  const [inputMode, setInputMode] = useState<"source" | "preview">("source");
  const [rulesOpen, setRulesOpen] = useState(false);
  const [issuesOpen, setIssuesOpen] = useState(false);
  const [subjectOptions, setSubjectOptions] = useState<Array<{id: number; code: string; name: string}>>([]);
  useEffect(() => {
    apiRequest<Array<{id: number; code: string; name: string; path: string; level: number}>>("/imports/subject-options")
      .then(setSubjectOptions)
      .catch(() => {});
  }, []);
  const [parseResult, setParseResult] = useState<ParseResponse | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<ParsedQuestion | null>(null);
  const [optionDraft, setOptionDraft] = useState("");
  const [importStatus, setImportStatus] = useState<ImportResponse | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const charCount = text.length;
  const latexInspection = useMemo(() => inspectLatexImportText(text), [text]);
  const editLatexInspection = useMemo(() => {
    if (!editForm) return inspectLatexImportText("");
    return inspectLatexImportText([
      editForm.stem,
      ...editForm.options.map((option) => option.text),
      typeof editForm.answer === "string" ? editForm.answer : "",
      editForm.analysis ?? "",
    ].filter(Boolean).join("\n"));
  }, [editForm]);

  const editStructureIssues = useMemo(() => {
    if (!editForm) return [] as string[];
    const issues: string[] = [];
    if (!editForm.stem.trim()) issues.push("题干不能为空");
    const answerEmpty = editForm.answer === null || editForm.answer === undefined || editForm.answer === "" || (Array.isArray(editForm.answer) && editForm.answer.length === 0);
    if (answerEmpty) issues.push("答案不能为空");
    if (editForm.question_type === "single_choice" || editForm.question_type === "multiple_choice") {
      const optionKeys = new Set(editForm.options.map((option) => option.key.toUpperCase()));
      const missing = ["A", "B", "C", "D"].filter((key) => !optionKeys.has(key));
      if (missing.length > 0) issues.push(`选择题缺少 ${missing.join(" / ")} 选项`);
    }
    return issues;
  }, [editForm]);

  const resetParsedState = () => {
    setParseResult(null);
    setImportStatus(null);
    setEditingIndex(null);
    setEditForm(null);
    setOptionDraft("");
    setGlobalError(null);
  };

  const updateSourceText = (next: string) => {
    setText(next);
    resetParsedState();
  };

  const wrapSelection = (kind: "inline" | "block" | "code") => {
    const textarea = textAreaRef.current;
    if (!textarea) {
      setInputMode("source");
      return;
    }

    const start = textarea.selectionStart ?? text.length;
    const end = textarea.selectionEnd ?? start;
    const selected = text.slice(start, end);
    const fallback = kind === "inline" ? "x^2" : kind === "block" ? "\\frac{a}{b}" : "int value = 0;";
    const body = selected || fallback;
    const wrapped = kind === "inline"
      ? `$${body}$`
      : kind === "block"
        ? `$$\n${body}\n$$`
        : `\`\`\`\n${body}\n\`\`\``;
    const next = `${text.slice(0, start)}${wrapped}${text.slice(end)}`;
    updateSourceText(next);
    setInputMode("source");

    requestAnimationFrame(() => {
      const current = textAreaRef.current;
      if (!current) return;
      current.focus();
      const prefixLength = kind === "inline" ? 1 : kind === "block" ? 3 : 4;
      const selectionStart = start + prefixLength;
      current.setSelectionRange(selectionStart, selectionStart + body.length);
    });
  };

  const handleNormalizeDelimiters = () => {
    const normalized = normalizeLatexImportDelimiters(text);
    if (normalized !== text) updateSourceText(normalized);
    setInputMode("source");
    setIssuesOpen(true);
  };

  const focusSourceLine = (line: number | null) => {
    if (!line) return;
    setInputMode("source");
    requestAnimationFrame(() => {
      const textarea = textAreaRef.current;
      if (!textarea) return;
      const lines = text.replace(/\r\n?/g, "\n").split("\n");
      const safeLine = Math.max(1, Math.min(line, lines.length));
      const start = lines.slice(0, safeLine - 1).reduce((sum, current) => sum + current.length + 1, 0);
      const end = start + (lines[safeLine - 1]?.length ?? 0);
      textarea.focus();
      textarea.setSelectionRange(start, end);
      const lineHeight = Number.parseFloat(window.getComputedStyle(textarea).lineHeight) || 24;
      textarea.scrollTop = Math.max(0, (safeLine - 3) * lineHeight);
    });
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setRulesOpen(false);
      setIssuesOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (editingIndex === null) return;
    const frame = requestAnimationFrame(() => {
      const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
      editSectionRef.current?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "nearest" });
    });
    return () => cancelAnimationFrame(frame);
  }, [editingIndex]);

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
    if (editingIndex === index) {
      setEditingIndex(null);
      setEditForm(null);
      setOptionDraft("");
    } else if (editingIndex !== null && editingIndex > index) {
      setEditingIndex(editingIndex - 1);
    }
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
    setOptionDraft(q.options.map((option) => `${option.key}. ${option.text}`).join("\n"));
  };

  const saveEdit = () => {
    if (!parseResult || editingIndex === null || !editForm || editStructureIssues.length > 0) return;
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
    setOptionDraft("");
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
        description="粘贴结构化或自然语言题目，先解析结构与 LaTeX，再送入审核队列。科目可留空，选项支持常见网页复制格式。"
        meta={
          <div className="inline-flex h-9 items-center gap-2 rounded-full border border-[var(--color-border)] bg-white/70 px-3 text-xs text-[var(--color-text-secondary)]">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]" aria-hidden="true" />
            科目可后补
          </div>
        }
      />

      <ImportToast
        message={globalError ? `操作未完成：${globalError}` : null}
        tone="error"
        onDismiss={() => setGlobalError(null)}
      />

      <section className="overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.82)] shadow-[var(--shadow-card)] import-enter" style={{ animationDelay: "55ms" }}>
        <div className="grid min-h-[620px] xl:grid-cols-[minmax(0,0.88fr)_minmax(0,1.12fr)]">
          <div className="min-w-0 border-b border-[var(--color-border-light)] xl:border-b-0 xl:border-r">
            <ImportPanelHeader
              title="原始文本"
              description="先预检 LaTeX / 代码，再识别题干、选项与答案；支持 A. 内容，也支持 A 与内容分两行。"
              trailing={
                <div className="text-right font-mono text-[10px] tabular-nums text-[var(--color-text-hint)]">
                  <div>{charCount.toLocaleString()} 字</div>
                  <div className="mt-0.5">公式 {latexInspection.formulaCount}</div>
                </div>
              }
            />
            <div className="flex h-[calc(100%-4rem)] min-h-[555px] flex-col p-4 sm:p-5">
              <div className="mb-3 flex flex-col gap-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="inline-flex items-center rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-1" role="tablist" aria-label="文本输入模式">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={inputMode === "source"}
                      onClick={() => setInputMode("source")}
                      className={`h-11 rounded-lg px-3 text-xs font-medium import-interactive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] ${inputMode === "source" ? "bg-white text-[var(--ink)] shadow-[0_1px_4px_rgba(37,52,65,0.09)]" : "text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]"}`}
                    >
                      输入
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={inputMode === "preview"}
                      onClick={() => setInputMode("preview")}
                      className={`flex h-11 items-center gap-1.5 rounded-lg px-3 text-xs font-medium import-interactive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] ${inputMode === "preview" ? "bg-white text-[var(--ink)] shadow-[0_1px_4px_rgba(37,52,65,0.09)]" : "text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]"}`}
                    >
                      <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                      预览
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={() => setRulesOpen((open) => !open)}
                    className={`flex h-11 items-center gap-1.5 rounded-xl border px-3 text-xs font-medium import-interactive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] ${rulesOpen ? "border-[rgba(74,111,138,0.32)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]" : "border-[var(--color-border)] bg-white/60 text-[var(--color-text-secondary)] hover:bg-white"}`}
                    aria-expanded={rulesOpen}
                    aria-controls="latex-import-rules"
                  >
                    <Braces className="h-3.5 w-3.5" aria-hidden="true" />
                    LaTeX 规则
                  </button>
                </div>

                {inputMode === "source" ? (
                  <div className="flex flex-wrap items-center gap-1.5" aria-label="文本快速格式化工具">
                    <button type="button" onClick={() => wrapSelection("inline")} className="h-11 rounded-lg border border-[var(--color-border-light)] bg-white/60 px-3 font-mono text-[11px] font-semibold text-[var(--color-text-secondary)] import-interactive hover:border-[var(--color-border)] hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]" title="将选中文本包裹为行内公式">
                      $ · $ <span className="ml-1 font-sans font-normal text-[var(--color-text-hint)]">行内</span>
                    </button>
                    <button type="button" onClick={() => wrapSelection("block")} className="h-11 rounded-lg border border-[var(--color-border-light)] bg-white/60 px-3 font-mono text-[11px] font-semibold text-[var(--color-text-secondary)] import-interactive hover:border-[var(--color-border)] hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]" title="将选中文本包裹为块级公式">
                      $$ · $$ <span className="ml-1 font-sans font-normal text-[var(--color-text-hint)]">块级</span>
                    </button>
                    <button type="button" onClick={() => wrapSelection("code")} className="flex h-11 items-center gap-1.5 rounded-lg border border-[var(--color-border-light)] bg-white/60 px-3 text-[11px] font-medium text-[var(--color-text-secondary)] import-interactive hover:border-[var(--color-border)] hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]" title="将选中文本放入代码围栏">
                      <Code2 className="h-3.5 w-3.5" aria-hidden="true" />
                      代码块
                    </button>
                    {latexInspection.alternateDelimiterCount > 0 ? (
                      <button type="button" onClick={handleNormalizeDelimiters} className="ml-auto flex h-11 items-center gap-1.5 rounded-lg border border-[rgba(74,111,138,0.24)] bg-[var(--color-primary-light)] px-3 text-[11px] font-medium text-[var(--color-primary-dark)] import-interactive hover:border-[rgba(74,111,138,0.38)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]">
                        <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                        标准化 {latexInspection.alternateDelimiterCount} 处定界符
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>

              {rulesOpen ? <LatexRulesPanel onClose={() => setRulesOpen(false)} /> : null}

              {inputMode === "source" ? (
                <>
                  <label htmlFor="question-import-text" className="sr-only">题目文本</label>
                  <textarea
                    ref={textAreaRef}
                    id="question-import-text"
                    className="min-h-[430px] flex-1 resize-y rounded-xl border border-[var(--color-border)] bg-[rgba(239,235,229,0.62)] px-4 py-3.5 font-mono text-[13px] leading-6 text-[var(--ink)] outline-none transition-[border-color,background-color,box-shadow] duration-150 placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]"
                    placeholder={TEXT_IMPORT_SAMPLE}
                    value={text}
                    spellCheck={false}
                    onKeyDown={(event) => {
                      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                        event.preventDefault();
                        handleParse();
                      }
                    }}
                    onChange={(e) => updateSourceText(e.target.value)}
                  />
                </>
              ) : (
                <div className="flex-1 import-panel-swap" role="tabpanel" aria-label="题目渲染预览">
                  <ImportTextPreview text={text} />
                </div>
              )}

              <LatexInspectionPanel
                inspection={latexInspection}
                expanded={issuesOpen}
                onToggle={() => setIssuesOpen((open) => !open)}
                onIssueClick={focusSourceLine}
              />

              <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-xs leading-5 text-[var(--color-text-hint)]">
                  <p>支持带/不带括号的结构标签；选项可写 “A. 内容”，也可写成 “A” 后换行输入内容。</p>
                  <p className="mt-0.5 font-mono text-[10px]">⌘ / Ctrl + Enter · 解析文本</p>
                </div>
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
                  description="先处理结构错误再确认导入；科目未指定只提示，不阻塞进入审核队列。"
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
                              {q.subject_id || q.subject ? (
                                <span className="rounded-full border border-[rgba(74,111,138,0.18)] bg-[var(--color-primary-light)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-primary-dark)]" title={q.subject_id ? "已指定科目" : "自动识别的科目，可在审核时调整"}>
                                  {q.subject_id
                                    ? (subjectOptions.find((s) => s.id === q.subject_id)?.name || `#${q.subject_id}`)
                                    : (subjectOptions.find((s) => s.code === q.subject)?.name || q.subject)}
                                </span>
                              ) : (
                                <span className="rounded-full border border-dashed border-[var(--color-border)] bg-white/55 px-2 py-0.5 text-[10px] font-medium text-[var(--color-text-hint)]" title="科目可在审核阶段补充">科目待补</span>
                              )}
                            </div>
                            <div className="mt-2 max-h-28 overflow-hidden text-sm leading-6 text-[var(--color-text-secondary)]">
                              <QuestionContentRenderer content={q.stem} fallbackText={q.stem} preserveCodeText />
                            </div>

                            {q.options.length > 0 ? (
                              <div className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-2">
                                {q.options.slice(0, 4).map((opt) => (
                                  <div key={opt.key} className="flex min-w-0 items-baseline gap-1 text-[11px] text-[var(--color-text-hint)]">
                                    <span className="shrink-0 font-semibold text-[var(--color-text-secondary)]">{opt.key}.</span>
                                    <span className="min-w-0 truncate"><MathFormula text={opt.text} /></span>
                                  </div>
                                ))}
                              </div>
                            ) : q.question_type === "single_choice" || q.question_type === "multiple_choice" ? (
                              <button type="button" onClick={() => startEdit(index)} className="mt-2 flex min-h-11 w-full items-center gap-2 rounded-lg border border-dashed border-[rgba(196,154,107,0.42)] bg-[var(--color-warning-light)] px-3 py-2 text-left text-[11px] text-[var(--color-text-primary)] import-interactive hover:border-[rgba(196,154,107,0.62)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]">
                                <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                                <span><strong className="font-semibold">未识别到选项</strong> · 点击编辑补充或检查选项分隔格式</span>
                              </button>
                            ) : null}

                            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-text-hint)]">
                              <span className="inline-flex items-baseline gap-1">答案 <strong className="font-semibold text-[var(--color-text-secondary)]"><RenderedAnswer answer={q.answer} /></strong></span>
                              {q.analysis ? <span>含解析</span> : null}
                              {q.warnings.length > 0 ? <span className="text-[var(--color-text-primary)]">{q.warnings.length} 条警告</span> : null}
                              {q.errors.length > 0 ? <span className="text-[var(--color-danger)]">{q.errors.length} 个错误</span> : null}
                            </div>

                            {q.errors.length > 0 || q.warnings.length > 0 ? (
                              <details className="mt-2 rounded-lg border border-[var(--color-border-light)] bg-white/40 px-2.5 py-1.5 text-[11px] text-[var(--color-text-secondary)] open:pb-2.5">
                                <summary className="flex min-h-11 cursor-pointer select-none items-center py-1.5 font-medium text-[var(--color-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]">
                                  查看解析异常
                                </summary>
                                <div className="space-y-1.5 border-t border-[var(--color-border-light)] pt-2 import-details-body">
                                  {q.errors.map((message, issueIndex) => (
                                    <p key={`e-${issueIndex}`} className="flex gap-1.5 leading-5 text-[var(--color-danger)]"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{formatParseIssue(message)}</p>
                                  ))}
                                  {q.warnings.map((message, issueIndex) => (
                                    <p key={`w-${issueIndex}`} className="flex gap-1.5 leading-5"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{formatParseIssue(message)}</p>
                                  ))}
                                </div>
                              </details>
                            ) : null}
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
                    <section ref={editSectionRef} className="mt-4 scroll-mt-5 overflow-hidden rounded-xl border border-[rgba(74,111,138,0.32)] bg-white import-panel-swap">
                      <ImportPanelHeader
                        title={`编辑题目 ${editingIndex + 1}`}
                        description="按最终渲染效果检查题干、选项、公式与代码；科目为可选项，不参与结构有效性判断。"
                        trailing={
                          <div className="flex flex-wrap items-center justify-end gap-2">
                            <span className={`hidden rounded-full border px-2.5 py-1 text-[10px] font-medium sm:inline-flex ${editLatexInspection.errorCount > 0 ? "border-[rgba(196,77,77,0.26)] bg-[var(--color-danger-light)] text-[var(--color-danger)]" : editLatexInspection.warningCount > 0 ? "border-[rgba(196,154,107,0.3)] bg-[var(--color-warning-light)] text-[var(--color-text-primary)]" : "border-[rgba(91,140,91,0.24)] bg-[var(--color-success-light)] text-[var(--color-success)]"}`}>
                              公式 {editLatexInspection.formulaCount} · {editLatexInspection.errorCount + editLatexInspection.warningCount > 0 ? `风险 ${editLatexInspection.errorCount + editLatexInspection.warningCount}` : "通过"}
                            </span>
                            <Button variant="ghost" className="h-11 import-interactive" onClick={() => { setEditingIndex(null); setEditForm(null); setOptionDraft(""); }}>取消</Button>
                            <Button className="h-11 import-interactive" onClick={saveEdit} disabled={editStructureIssues.length > 0} title={editStructureIssues.length > 0 ? editStructureIssues.join("；") : "保存修改"}><CheckCircle2 className="h-4 w-4" aria-hidden="true" />保存</Button>
                          </div>
                        }
                      />
                      <div className="grid gap-4 p-4 sm:grid-cols-2 sm:p-5">
                        <label className="space-y-1.5">
                          <span className="flex items-center justify-between gap-2 text-xs font-semibold text-[var(--color-text-secondary)]">
                            <span>科目 <span className="font-normal text-[var(--color-text-hint)]">（可选）</span></span>
                            {!editForm.subject_id ? <span className="text-[10px] font-normal text-[var(--color-text-hint)]">审核时可补</span> : null}
                          </span>
                          <select className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]" value={editForm.subject_id ?? ""} onChange={(e) => setEditForm({ ...editForm, subject_id: e.target.value ? Number(e.target.value) : null })}>
                            <option value="">未指定 · 不阻塞导入</option>
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
                          <span className="flex flex-wrap items-center justify-between gap-1 text-xs font-semibold text-[var(--color-text-secondary)]">
                            <span>选项 <span className="font-normal text-[var(--color-text-hint)]">支持 “A. 内容” 或 “A ↵ 内容”</span></span>
                            <span className={`text-[10px] font-normal ${editForm.options.length >= 4 ? "text-[var(--color-success)]" : "text-[var(--color-text-hint)]"}`}>已识别 {editForm.options.length} 项</span>
                          </span>
                          <textarea className="min-h-28 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2.5 font-mono text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]" value={optionDraft} onChange={(e) => { const nextDraft = e.target.value; setOptionDraft(nextDraft); setEditForm({ ...editForm, options: parseEditableOptions(nextDraft) }); }} />
                        </label>
                        <label className="space-y-1.5">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">答案</span>
                          <input className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]" value={typeof editForm.answer === "boolean" ? (editForm.answer ? "正确" : "错误") : Array.isArray(editForm.answer) ? editForm.answer.join(",") : String(editForm.answer ?? "")} onChange={(e) => setEditForm({ ...editForm, answer: e.target.value })} />
                        </label>
                        <label className="space-y-1.5 sm:col-span-2">
                          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">解析</span>
                          <textarea className="min-h-24 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2.5 text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)]" value={editForm.analysis ?? ""} onChange={(e) => setEditForm({ ...editForm, analysis: e.target.value })} />
                        </label>

                        {editStructureIssues.length > 0 ? (
                          <div role="status" className="sm:col-span-2 flex items-start gap-2.5 rounded-xl border border-[rgba(196,154,107,0.34)] bg-[var(--color-warning-light)] px-3.5 py-3 text-[11px] leading-5 text-[var(--color-text-primary)] import-feedback-in">
                            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                            <div>
                              <p className="font-semibold">保存前还需处理 {editStructureIssues.length} 项结构问题</p>
                              <p className="mt-0.5 text-[var(--color-text-hint)]">{editStructureIssues.join(" · ")}</p>
                            </div>
                          </div>
                        ) : null}

                        <section className="sm:col-span-2 overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-[rgba(239,235,229,0.34)]">
                          <div className="flex min-h-11 items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-3.5 py-2">
                            <div className="flex items-center gap-2 text-xs font-semibold text-[var(--ink)]">
                              <Eye className="h-3.5 w-3.5 text-[var(--color-primary-dark)]" aria-hidden="true" />
                              最终渲染预览
                            </div>
                            <span className="text-[10px] text-[var(--color-text-hint)]">与题库阅读侧使用同一渲染规则</span>
                          </div>
                          <div className="space-y-4 p-3.5 text-sm leading-7 text-[var(--color-text-secondary)] import-panel-swap">
                            <div>
                              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-hint)]">题干</p>
                              <QuestionContentRenderer content={editForm.stem} fallbackText={editForm.stem} preserveCodeText />
                            </div>
                            {editForm.options.length > 0 ? (
                              <div className="grid gap-2 sm:grid-cols-2">
                                {editForm.options.map((option) => (
                                  <div key={option.key} className="flex min-w-0 gap-2 rounded-lg border border-[var(--color-border-light)] bg-white/60 px-2.5 py-2 text-xs leading-6">
                                    <span className="font-semibold text-[var(--color-primary-dark)]">{option.key}.</span>
                                    <span className="min-w-0"><MathFormula text={option.text} /></span>
                                  </div>
                                ))}
                              </div>
                            ) : null}
                            <div className="grid gap-3 border-t border-[var(--color-border-light)] pt-3 sm:grid-cols-[0.34fr_0.66fr]">
                              <div>
                                <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-hint)]">答案</p>
                                <div className="text-xs font-semibold text-[var(--color-text-secondary)]"><RenderedAnswer answer={editForm.answer} /></div>
                              </div>
                              <div>
                                <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-hint)]">解析</p>
                                <div className="whitespace-pre-wrap text-xs leading-6">{editForm.analysis ? <MathFormula text={editForm.analysis} /> : <span className="italic text-[var(--color-text-hint)]">无解析</span>}</div>
                              </div>
                            </div>
                            {editLatexInspection.issues.length > 0 ? (
                              <div className="rounded-lg border border-[rgba(196,154,107,0.28)] bg-[var(--color-warning-light)] px-3 py-2 text-[11px] leading-5 text-[var(--color-text-primary)]">
                                <span className="font-semibold">LaTeX 预检：</span>
                                {editLatexInspection.errorCount > 0 ? `${editLatexInspection.errorCount} 个结构错误` : `${editLatexInspection.warningCount} 个格式建议`}
                                <span className="ml-1 text-[var(--color-text-hint)]">· 保存前建议核对公式定界符与括号。</span>
                              </div>
                            ) : null}
                          </div>
                        </section>
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
                    <p className="mt-1.5 text-xs leading-5 text-[var(--color-text-hint)]">粘贴题目后先用左侧预览与 LaTeX 预检确认格式，再执行解析。完成后可逐题编辑、删除；科目可留空，结构通过即可进入审核。</p>
                    <div className="mt-5 grid grid-cols-3 divide-x divide-[var(--color-border-light)] border-y border-[var(--color-border-light)] py-2.5 text-[11px] text-[var(--color-text-secondary)]">
                      <span>预检</span><span>解析</span><span>入库</span>
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
