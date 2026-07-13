"use client";

import { useState, useMemo, useCallback, useRef, useEffect, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  Plus,
  Save,
  X,
  Trash2,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Check,
  CheckCircle2,
  Circle,
  Copy,
  Eye,
  FileText,
  LayoutTemplate,
  Lightbulb,
  ListChecks,
  RotateCcw,
  Sparkles,
  Tags,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { LatexRenderer } from "@/components/ui/latex-renderer";
import { MixedLatexRenderer } from "@/components/ui/mixed-latex-renderer";
import { FormulaCategoryPicker } from "@/components/formulas/formula-category-picker";
import { FormulaGraphAssetPanel } from "@/components/formulas/formula-graph-asset-panel";
import { apiRequest } from "@/lib/api/client";
import { normalizeFormulaText } from "@/lib/formula-normalize";
import { normalizeLatexExpression } from "@/lib/math-text";

/* ── Types ── */

type TagOption = { id: number; code: string; name: string };
type FormulaBlock = { label?: string | null; latex: string; note?: string | null };
type FormulaExample = { question: string; short_solution: string; answer: string; error_tip?: string | null };

type EditorFormData = {
  categoryId: number | null;
  title: string;
  aliases: string;
  summary: string;
  conditions: string;
  symbolNotes: string;
  secondaryConclusions: string;
  errorTips: string;
  selectedTags: string[];
  blocks: FormulaBlock[];
  examples: FormulaExample[];
  sortOrder: number;
  cardType: string;
  functionProperties: Record<string, unknown> | null;
};

type EditorMode = "create" | "edit";

type Props = {
  mode: EditorMode;
  cardId?: number;
  initialData?: Partial<EditorFormData>;
  onSaveSuccess?: () => void;
};

type LocalDraft = {
  savedAt: string;
  categoryId: number | null;
  title: string;
  aliases: string;
  summary: string;
  conditions: string;
  symbolNotes: string;
  secondaryConclusions: string;
  errorTips: string;
  selectedTags: string[];
  blocks: FormulaBlock[];
  examples: FormulaExample[];
  cardType: string;
  funcExpression: string;
  funcTemplate: string;
  funcDomain: string;
  funcRange: string;
  funcParity: string;
  funcPeriod: string;
  funcDerivative: string;
  funcFeature: string;
};

/* ── Constants ── */

const TAG_CODES = ["basic", "high_frequency", "error_prone", "must_memorize"];
const TAG_NAMES: Record<string, string> = {
  basic: "基础",
  high_frequency: "高频",
  error_prone: "易错",
  must_memorize: "必背",
};
const EXAMPLES_MAX = 3;
const BLOCKS_MAX = 8;
const CREATE_DRAFT_KEY = "admin-formulas-create-draft-v2";

/* ── Shared UI ── */

function SectionCard({
  step,
  title,
  description,
  optional = false,
  children,
  action,
}: {
  step: string;
  title: string;
  description: string;
  optional?: boolean;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.88)] shadow-[var(--shadow-card)] backdrop-blur-sm">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--color-border-light)] px-5 py-4 lg:px-6">
        <div className="flex min-w-0 items-start gap-3.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--color-primary)] text-xs font-bold text-white shadow-sm">
            {step}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-display text-lg font-bold text-[var(--ink)]">{title}</h2>
              {optional && (
                <span className="rounded-full bg-[var(--color-bg-input)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-text-hint)]">
                  可选
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs leading-5 text-[var(--color-text-secondary)]">{description}</p>
          </div>
        </div>
        {action}
      </div>
      <div className="p-5 lg:p-6">{children}</div>
    </section>
  );
}

function FieldLabel({
  children,
  required = false,
  hint,
}: {
  children: ReactNode;
  required?: boolean;
  hint?: string;
}) {
  return (
    <div className="mb-1.5 flex items-center justify-between gap-3">
      <label className="text-sm font-semibold text-[var(--color-text-primary)]">
        {children}
        {required && <span className="ml-1 text-[var(--color-danger)]">*</span>}
      </label>
      {hint && <span className="text-[11px] text-[var(--color-text-hint)]">{hint}</span>}
    </div>
  );
}

function MathTextAreaField({
  label,
  value,
  onChange,
  placeholder,
  helper,
  minHeight = "min-h-24",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  helper?: string;
  minHeight?: string;
}) {
  const normalized = value.trim() ? normalizeFormulaText(value) ?? value : "";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <label className="text-sm font-semibold text-[var(--color-text-primary)]">{label}</label>
          {helper && <p className="mt-0.5 text-[11px] text-[var(--color-text-hint)]">{helper}</p>}
        </div>
        {value.trim() && (
          <button
            type="button"
            onClick={() => onChange(normalizeFormulaText(value) ?? "")}
            className="inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-[var(--color-primary)] transition hover:bg-[var(--color-primary-light)]"
          >
            <Sparkles className="h-3.5 w-3.5" />
            规范格式
          </button>
        )}
      </div>
      <textarea
        className={`${minHeight} w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm leading-6 outline-none transition placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
      {value.trim() && (
        <div className="rounded-xl border border-[var(--color-border-light)] bg-white/70 px-3 py-2.5 text-sm leading-6 text-[var(--color-text-secondary)]">
          <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">
            <Eye className="h-3 w-3" /> 预览
          </div>
          <div className="max-w-full overflow-x-auto whitespace-pre-wrap break-words">
            <MixedLatexRenderer text={normalized} />
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Formula block editor ── */

function FormulaBlockEditor({
  block,
  index,
  onChange,
  onRemove,
  onDuplicate,
  canRemove,
  canDuplicate,
}: {
  block: FormulaBlock;
  index: number;
  onChange: (field: keyof FormulaBlock, value: string) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  canRemove: boolean;
  canDuplicate: boolean;
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white shadow-sm transition focus-within:border-[var(--color-primary)] focus-within:shadow-[0_8px_28px_rgba(27,39,51,0.08)]">
      <div className="flex items-center justify-between border-b border-[var(--color-border-light)] bg-[rgba(239,235,229,0.45)] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--color-primary-light)] bg-white text-xs font-bold text-[var(--color-primary-dark)]">
            {index + 1}
          </span>
          <div>
            <p className="text-sm font-semibold text-[var(--ink)]">公式块</p>
            <p className="text-[10px] text-[var(--color-text-hint)]">支持标准 LaTeX，如 \\frac、\\sqrt、上下标</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {canDuplicate && (
            <button
              type="button"
              onClick={onDuplicate}
              className="rounded-lg p-2 text-[var(--color-text-hint)] transition hover:bg-white hover:text-[var(--color-primary)]"
              aria-label="复制公式块"
              title="复制公式块"
            >
              <Copy className="h-4 w-4" />
            </button>
          )}
          {canRemove && (
            <button
              type="button"
              onClick={onRemove}
              className="rounded-lg p-2 text-[var(--color-text-hint)] transition hover:bg-red-50 hover:text-red-600"
              aria-label="删除公式块"
              title="删除公式块"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      <div className="space-y-4 p-4 lg:p-5">
        <div>
          <FieldLabel hint="可选">小标题</FieldLabel>
          <Input
            value={block.label || ""}
            onChange={(event) => onChange("label", event.target.value)}
            placeholder="例如：顶点坐标、判别式、求根公式"
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.08fr)_minmax(260px,0.92fr)]">
          <div>
            <FieldLabel required>LaTeX 公式</FieldLabel>
            <textarea
              className="min-h-36 w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3.5 font-mono text-sm leading-6 outline-none transition placeholder:font-sans placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
              value={block.latex}
              onChange={(event) => onChange("latex", event.target.value)}
              placeholder="例如：y = ax^2 + bx + c"
              spellCheck={false}
            />
          </div>

          <div>
            <FieldLabel>公式预览</FieldLabel>
            <div className="flex min-h-36 items-center justify-center overflow-x-auto rounded-xl border border-dashed border-[var(--color-border)] bg-[var(--porcelain)] px-4 py-5 text-center">
              {block.latex.trim() ? (
                <LatexRenderer latex={normalizeLatexExpression(block.latex)} displayMode={true} />
              ) : (
                <div className="text-[var(--color-text-hint)]">
                  <Eye className="mx-auto mb-2 h-5 w-5 opacity-60" />
                  <p className="text-xs">输入公式后将在这里实时渲染</p>
                </div>
              )}
            </div>
          </div>
        </div>

        <div>
          <FieldLabel hint="可输入文字与行内公式">说明</FieldLabel>
          <textarea
            className="min-h-20 w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm leading-6 outline-none transition placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
            value={block.note || ""}
            onChange={(event) => onChange("note", event.target.value)}
            placeholder="解释该公式的用途、变量关系或使用方法（可选）"
          />
          {!!block.note?.trim() && (
            <div className="mt-2 rounded-lg bg-[var(--color-primary-light)]/55 px-3 py-2 text-sm leading-6 text-[var(--color-text-secondary)]">
              <MixedLatexRenderer text={block.note} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Formula editor ── */

export function FormulaEditorForm({ mode, cardId, initialData, onSaveSuccess }: Props) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [messageType, setMessageType] = useState<"success" | "error">("success");

  const [showSupplement, setShowSupplement] = useState(
    mode === "edit" && Boolean(
      initialData?.conditions || initialData?.symbolNotes || initialData?.secondaryConclusions || initialData?.errorTips,
    ),
  );
  const [showExamples, setShowExamples] = useState(
    mode === "edit" && Boolean(initialData?.examples?.length),
  );

  const [categoryId, setCategoryId] = useState<number | null>(initialData?.categoryId ?? null);
  const [categoryError, setCategoryError] = useState("");
  const [title, setTitle] = useState(initialData?.title ?? "");
  const [titleError, setTitleError] = useState("");
  const [blocksError, setBlocksError] = useState("");
  const [aliases, setAliases] = useState(initialData?.aliases ?? "");
  const [summary, setSummary] = useState(initialData?.summary ?? "");
  const [conditions, setConditions] = useState(initialData?.conditions ?? "");
  const [symbolNotes, setSymbolNotes] = useState(initialData?.symbolNotes ?? "");
  const [secondaryConclusions, setSecondaryConclusions] = useState(initialData?.secondaryConclusions ?? "");
  const [errorTips, setErrorTips] = useState(initialData?.errorTips ?? "");
  const [selectedTags, setSelectedTags] = useState<string[]>(initialData?.selectedTags ?? []);
  const [blocks, setBlocks] = useState<FormulaBlock[]>(
    initialData?.blocks?.length ? initialData.blocks : [{ latex: "" }],
  );
  const [examples, setExamples] = useState<FormulaExample[]>(initialData?.examples ?? []);
  const [sortOrder, setSortOrder] = useState(initialData?.sortOrder ?? 0);
  const [cardType, setCardType] = useState(initialData?.cardType ?? "pure_formula");

  const [funcExpression, setFuncExpression] = useState(
    (initialData?.functionProperties?.function_expression as string) ?? "",
  );
  const [funcTemplate, setFuncTemplate] = useState(
    (initialData?.functionProperties?.graph_template_type as string) ?? "",
  );
  const [funcDomain, setFuncDomain] = useState(
    (initialData?.functionProperties?.domain as string) ?? "",
  );
  const [funcRange, setFuncRange] = useState(
    (initialData?.functionProperties?.range as string) ?? "",
  );
  const [funcParity, setFuncParity] = useState(
    (initialData?.functionProperties?.parity as string) ?? "",
  );
  const [funcPeriod, setFuncPeriod] = useState(
    (initialData?.functionProperties?.period as string) ?? "",
  );
  const [funcDerivative, setFuncDerivative] = useState(
    (initialData?.functionProperties?.derivative_summary as string) ?? "",
  );
  const [funcFeature, setFuncFeature] = useState(
    (initialData?.functionProperties?.one_line_feature as string) ?? "",
  );

  const [recoverableDraft, setRecoverableDraft] = useState<LocalDraft | null>(null);
  const [draftStorageReady, setDraftStorageReady] = useState(false);
  const [lastAutoSavedAt, setLastAutoSavedAt] = useState<Date | null>(null);

  const basicSectionRef = useRef<HTMLDivElement>(null);
  const formulaSectionRef = useRef<HTMLDivElement>(null);
  const sentConditionsRef = useRef<string | null>(null);
  const sentErrorTipsRef = useRef<string | null>(null);

  const tags = useQuery({
    queryKey: ["admin-formula-tags"],
    queryFn: () => apiRequest<{ items: TagOption[] }>("/formulas/tags"),
    staleTime: 60000,
  });
  const tagMap = useMemo(() => {
    const map: Record<string, number> = {};
    tags.data?.items?.forEach((tag) => { map[tag.code] = tag.id; });
    return map;
  }, [tags.data]);

  const updateBlock = useCallback((index: number, field: keyof FormulaBlock, value: string) => {
    setBlocks((previous) => previous.map((block, itemIndex) => (
      itemIndex === index ? { ...block, [field]: value } : block
    )));
    if (field === "latex" && value.trim()) setBlocksError("");
  }, []);

  const addBlock = useCallback(() => {
    setBlocks((previous) => (
      previous.length < BLOCKS_MAX ? [...previous, { latex: "" }] : previous
    ));
  }, []);

  const duplicateBlock = useCallback((index: number) => {
    setBlocks((previous) => {
      if (previous.length >= BLOCKS_MAX) return previous;
      const source = previous[index];
      const next = [...previous];
      next.splice(index + 1, 0, { ...source });
      return next;
    });
  }, []);

  const removeBlock = useCallback((index: number) => {
    setBlocks((previous) => (
      previous.length > 1 ? previous.filter((_, itemIndex) => itemIndex !== index) : previous
    ));
  }, []);

  const addExample = useCallback(() => {
    setExamples((previous) => (
      previous.length < EXAMPLES_MAX
        ? [...previous, { question: "", short_solution: "", answer: "" }]
        : previous
    ));
    setShowExamples(true);
  }, []);

  const updateExample = useCallback((index: number, field: keyof FormulaExample, value: string) => {
    setExamples((previous) => previous.map((example, itemIndex) => (
      itemIndex === index ? { ...example, [field]: value } : example
    )));
  }, []);

  const removeExample = useCallback((index: number) => {
    setExamples((previous) => previous.filter((_, itemIndex) => itemIndex !== index));
  }, []);

  const toggleTag = useCallback((code: string) => {
    setSelectedTags((previous) => (
      previous.includes(code)
        ? previous.filter((item) => item !== code)
        : [...previous, code]
    ));
  }, []);

  const buildFunctionProperties = useCallback(() => {
    const properties: Record<string, unknown> = {};
    if (funcExpression.trim()) properties.function_expression = funcExpression.trim();
    if (funcTemplate.trim()) properties.graph_template_type = funcTemplate.trim();
    if (funcDomain.trim()) {
      try { properties.domain = JSON.parse(funcDomain); }
      catch { properties.domain = funcDomain.trim(); }
    }
    if (funcRange.trim()) {
      try { properties.range = JSON.parse(funcRange); }
      catch { properties.range = funcRange.trim(); }
    }
    if (funcParity.trim()) properties.parity = funcParity.trim();
    if (funcPeriod.trim()) properties.period = funcPeriod.trim();
    if (funcDerivative.trim()) properties.derivative_summary = funcDerivative.trim();
    if (funcFeature.trim()) properties.one_line_feature = funcFeature.trim();
    return Object.keys(properties).length > 0 ? properties : null;
  }, [funcExpression, funcTemplate, funcDomain, funcRange, funcParity, funcPeriod, funcDerivative, funcFeature]);

  const hasAnyInput = useMemo(() => (
    Boolean(
      categoryId
      || title.trim()
      || aliases.trim()
      || summary.trim()
      || conditions.trim()
      || symbolNotes.trim()
      || secondaryConclusions.trim()
      || errorTips.trim()
      || selectedTags.length
      || blocks.some((block) => block.latex.trim() || block.label?.trim() || block.note?.trim())
      || examples.some((example) => example.question.trim() || example.short_solution.trim() || example.answer.trim() || example.error_tip?.trim())
      || cardType !== "pure_formula"
      || funcExpression.trim()
      || funcTemplate.trim()
      || funcDomain.trim()
      || funcRange.trim()
      || funcParity.trim()
      || funcPeriod.trim()
      || funcDerivative.trim()
      || funcFeature.trim()
    )
  ), [
    categoryId,
    title,
    aliases,
    summary,
    conditions,
    symbolNotes,
    secondaryConclusions,
    errorTips,
    selectedTags,
    blocks,
    examples,
    cardType,
    funcExpression,
    funcTemplate,
    funcDomain,
    funcRange,
    funcParity,
    funcPeriod,
    funcDerivative,
    funcFeature,
  ]);

  const localDraft = useMemo<LocalDraft>(() => ({
    savedAt: new Date().toISOString(),
    categoryId,
    title,
    aliases,
    summary,
    conditions,
    symbolNotes,
    secondaryConclusions,
    errorTips,
    selectedTags,
    blocks,
    examples,
    cardType,
    funcExpression,
    funcTemplate,
    funcDomain,
    funcRange,
    funcParity,
    funcPeriod,
    funcDerivative,
    funcFeature,
  }), [
    categoryId,
    title,
    aliases,
    summary,
    conditions,
    symbolNotes,
    secondaryConclusions,
    errorTips,
    selectedTags,
    blocks,
    examples,
    cardType,
    funcExpression,
    funcTemplate,
    funcDomain,
    funcRange,
    funcParity,
    funcPeriod,
    funcDerivative,
    funcFeature,
  ]);

  useEffect(() => {
    if (mode !== "create") return;
    try {
      const raw = window.localStorage.getItem(CREATE_DRAFT_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as LocalDraft;
        const meaningful = Boolean(
          parsed.title?.trim()
          || parsed.categoryId
          || parsed.blocks?.some((block) => block.latex?.trim())
          || parsed.summary?.trim(),
        );
        if (meaningful) setRecoverableDraft(parsed);
      }
    } catch (error) {
      console.warn("[formula-create] Failed to read local draft", error);
    } finally {
      setDraftStorageReady(true);
    }
  }, [mode]);

  useEffect(() => {
    if (mode !== "create" || !draftStorageReady || recoverableDraft) return;
    const timer = window.setTimeout(() => {
      try {
        if (hasAnyInput) {
          window.localStorage.setItem(CREATE_DRAFT_KEY, JSON.stringify(localDraft));
          setLastAutoSavedAt(new Date());
        } else {
          window.localStorage.removeItem(CREATE_DRAFT_KEY);
          setLastAutoSavedAt(null);
        }
      } catch (error) {
        console.warn("[formula-create] Failed to save local draft", error);
      }
    }, 700);
    return () => window.clearTimeout(timer);
  }, [mode, draftStorageReady, recoverableDraft, hasAnyInput, localDraft]);

  useEffect(() => {
    if (mode !== "create") return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasAnyInput) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [mode, hasAnyInput]);

  const restoreDraft = useCallback(() => {
    if (!recoverableDraft) return;
    setCategoryId(recoverableDraft.categoryId ?? null);
    setTitle(recoverableDraft.title ?? "");
    setAliases(recoverableDraft.aliases ?? "");
    setSummary(recoverableDraft.summary ?? "");
    setConditions(recoverableDraft.conditions ?? "");
    setSymbolNotes(recoverableDraft.symbolNotes ?? "");
    setSecondaryConclusions(recoverableDraft.secondaryConclusions ?? "");
    setErrorTips(recoverableDraft.errorTips ?? "");
    setSelectedTags(recoverableDraft.selectedTags ?? []);
    setBlocks(recoverableDraft.blocks?.length ? recoverableDraft.blocks : [{ latex: "" }]);
    setExamples(recoverableDraft.examples ?? []);
    setCardType(recoverableDraft.cardType ?? "pure_formula");
    setFuncExpression(recoverableDraft.funcExpression ?? "");
    setFuncTemplate(recoverableDraft.funcTemplate ?? "");
    setFuncDomain(recoverableDraft.funcDomain ?? "");
    setFuncRange(recoverableDraft.funcRange ?? "");
    setFuncParity(recoverableDraft.funcParity ?? "");
    setFuncPeriod(recoverableDraft.funcPeriod ?? "");
    setFuncDerivative(recoverableDraft.funcDerivative ?? "");
    setFuncFeature(recoverableDraft.funcFeature ?? "");
    setRecoverableDraft(null);
    setLastAutoSavedAt(recoverableDraft.savedAt ? new Date(recoverableDraft.savedAt) : new Date());
    setMessageType("success");
    setMessage("已恢复上次未完成的本地草稿");
  }, [recoverableDraft]);

  const discardDraft = useCallback(() => {
    try { window.localStorage.removeItem(CREATE_DRAFT_KEY); }
    catch { /* ignore storage failures */ }
    setRecoverableDraft(null);
  }, []);

  const validateRequired = useCallback(() => {
    const missingCategory = !categoryId;
    const missingTitle = !title.trim();
    const missingBlocks = !blocks.some((block) => block.latex.trim());

    setCategoryError(missingCategory ? "请选择公式分类" : "");
    setTitleError(missingTitle ? "请填写公式标题" : "");
    setBlocksError(missingBlocks ? "至少填写一个 LaTeX 公式" : "");

    if (missingCategory || missingTitle) {
      basicSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (missingBlocks) {
      formulaSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    if (missingCategory || missingTitle || missingBlocks) {
      setMessageType("error");
      setMessage("请先完善标记为必填的内容");
      return false;
    }
    return true;
  }, [categoryId, title, blocks]);

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!categoryId) throw new Error("请选择分类");
      if (!title.trim()) throw new Error("请填写标题");
      const validBlocks = blocks.filter((block) => block.latex.trim());
      if (validBlocks.length < 1) throw new Error("至少需要一个公式块（需填写 LaTeX）");

      const tagIds = selectedTags.map((code) => tagMap[code]).filter(Boolean);
      const aliasesList = aliases.split(/[,，、\s]+/).filter(Boolean);
      const normalizedConditions = normalizeFormulaText(conditions.trim()) || null;
      const normalizedSymbolNotes = normalizeFormulaText(symbolNotes.trim()) || null;
      const normalizedSecondaryConclusions = normalizeFormulaText(secondaryConclusions.trim()) || null;
      const normalizedErrorTips = normalizeFormulaText(errorTips.trim()) || null;
      sentConditionsRef.current = normalizedConditions;
      sentErrorTipsRef.current = normalizedErrorTips;

      const body: Record<string, unknown> = {
        category_id: categoryId,
        title: title.trim(),
        aliases: aliasesList.length > 0 ? aliasesList : null,
        search_text: [title.trim(), ...aliasesList].join(" "),
        card_type: cardType,
        function_properties: cardType === "function_graph" ? buildFunctionProperties() : null,
        summary: summary.trim() || null,
        formula_blocks: validBlocks.map((block) => ({
          label: block.label?.trim() || null,
          latex: block.latex.trim(),
          note: block.note?.trim() || null,
        })),
        conditions: normalizedConditions,
        symbol_notes: normalizedSymbolNotes,
        secondary_conclusions: normalizedSecondaryConclusions,
        error_tips: normalizedErrorTips,
        examples: examples.length > 0 ? examples.map((example) => ({
          question: example.question.trim(),
          short_solution: example.short_solution.trim(),
          answer: example.answer.trim(),
          error_tip: example.error_tip?.trim() || null,
        })) : null,
        tag_ids: tagIds,
        source_type: "manual",
      };

      if (mode === "edit" && cardId) {
        body.sort_order = sortOrder;
        return apiRequest<Record<string, unknown>>(`/formulas/${cardId}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
      }
      return apiRequest<Record<string, unknown>>("/formulas", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: async (result: Record<string, unknown> | undefined) => {
      setMessageType("success");
      setMessage(mode === "create" ? "公式草稿创建成功" : "保存成功");
      const newId = result?.id as number | undefined;

      if (mode === "create") {
        try { window.localStorage.removeItem(CREATE_DRAFT_KEY); }
        catch { /* ignore storage failures */ }
      }

      if (onSaveSuccess) onSaveSuccess();

      if (mode === "edit" && cardId) {
        try {
          const detail = await apiRequest<{ conditions?: string; error_tips?: string }>(`/formulas/${cardId}`);
          const returnedConditions = detail.conditions ?? null;
          const returnedErrorTips = detail.error_tips ?? null;
          if (returnedConditions !== sentConditionsRef.current || returnedErrorTips !== sentErrorTipsRef.current) {
            console.warn("[formula-normalize] Save verification mismatch:", {
              sent: { conditions: sentConditionsRef.current, errorTips: sentErrorTipsRef.current },
              received: { conditions: returnedConditions, errorTips: returnedErrorTips },
            });
            setMessageType("error");
            setMessage("保存成功，但接口返回的 LaTeX 内容不一致。请检查反斜杠是否丢失或重复转义。");
          }
        } catch (error) {
          console.warn("[formula-normalize] Post-save verification fetch failed", error);
        }
      }

      if (!onSaveSuccess) {
        if (mode === "create" && newId) {
          window.setTimeout(() => router.push(`/formulas/${newId}`), 700);
        } else {
          window.setTimeout(() => router.push("/formulas"), 700);
        }
      }
    },
    onError: (error) => {
      setMessageType("error");
      setMessage(error instanceof Error ? error.message : (mode === "create" ? "创建失败" : "保存失败"));
    },
  });

  const handleSave = useCallback(() => {
    if (!validateRequired()) return;
    createMutation.mutate();
  }, [validateRequired, createMutation]);

  const handleCancel = useCallback(() => {
    if (mode === "create" && hasAnyInput) {
      const confirmed = window.confirm("当前内容尚未提交。离开后仍可从本地草稿恢复，确定返回吗？");
      if (!confirmed) return;
    }
    router.push("/formulas");
  }, [mode, hasAnyInput, router]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (!createMutation.isPending) handleSave();
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [handleSave, createMutation.isPending]);

  const requiredItems = useMemo(() => [
    { label: "选择分类", done: Boolean(categoryId) },
    { label: "填写标题", done: Boolean(title.trim()) },
    { label: "录入公式", done: blocks.some((block) => Boolean(block.latex.trim())) },
  ], [categoryId, title, blocks]);
  const completedRequired = requiredItems.filter((item) => item.done).length;
  const completionPercent = Math.round((completedRequired / requiredItems.length) * 100);
  const isPending = createMutation.isPending;

  const tagButtons = (
    <div className="flex flex-wrap gap-2">
      {TAG_CODES.map((code) => {
        const active = selectedTags.includes(code);
        return (
          <button
            key={code}
            type="button"
            onClick={() => toggleTag(code)}
            className={`inline-flex h-9 items-center gap-1.5 rounded-xl border px-3 text-sm font-medium transition ${
              active
                ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] shadow-sm"
                : "border-[var(--color-border)] bg-white/75 text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:bg-white"
            }`}
          >
            {active && <Check className="h-3.5 w-3.5" />}
            {TAG_NAMES[code]}
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="mx-auto max-w-[1500px] space-y-5 px-4 pb-28 lg:px-8">
      {/*
        The focused editor route removes padding from the scroll container.
        Keeping the header at top:0 inside that container prevents the 24px
        gap that previously exposed scrolled form fields above the action bar.
      */}
      <div className="sticky top-0 z-50 isolate -mx-4 border-b border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-2.5 shadow-[0_10px_28px_rgba(27,39,51,0.10)] lg:-mx-8 lg:px-8">
        <div className="mx-auto flex min-h-16 max-w-[1500px] items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={handleCancel}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-transparent text-[var(--color-text-secondary)] transition hover:border-[var(--color-border)] hover:bg-white hover:text-[var(--ink)]"
              aria-label="返回公式列表"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[11px] font-medium text-[var(--color-text-hint)]">
                <span>公式库</span>
                <ChevronRight className="h-3 w-3" />
                <span>{mode === "create" ? "新建" : `编辑 #${cardId}`}</span>
              </div>
              <h1 className="truncate font-display text-xl font-bold text-[var(--ink)] lg:text-2xl">
                {mode === "create" ? "创建公式卡片" : "编辑公式卡片"}
              </h1>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <div className="hidden min-w-36 rounded-xl border border-[var(--color-border-light)] bg-white px-3 py-2 shadow-sm lg:block">
              <div className="flex items-center justify-between text-[10px] font-semibold text-[var(--color-text-hint)]">
                <span>必填进度</span>
                <span>{completedRequired}/{requiredItems.length}</span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--color-bg-input)]">
                <div
                  className="h-full rounded-full bg-[var(--color-primary)] transition-all duration-300"
                  style={{ width: `${completionPercent}%` }}
                />
              </div>
            </div>
            <Button variant="secondary" className="hidden sm:inline-flex" onClick={handleCancel}>
              <X className="h-4 w-4" /> 取消
            </Button>
            <Button className="hidden sm:inline-flex" onClick={handleSave} disabled={isPending}>
              <Save className="h-4 w-4" />
              {isPending ? "保存中..." : mode === "create" ? "保存草稿" : "保存修改"}
            </Button>
          </div>
        </div>
      </div>

      {/* Recover local draft */}
      {mode === "create" && recoverableDraft && (
        <div className="flex flex-col gap-3 rounded-2xl border border-amber-200 bg-amber-50/85 px-4 py-3 shadow-sm sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <RotateCcw className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
            <div>
              <p className="text-sm font-semibold text-amber-900">发现未完成的本地草稿</p>
              <p className="mt-0.5 text-xs text-amber-700">
                保存于 {new Date(recoverableDraft.savedAt).toLocaleString()}，可恢复后继续编辑。
              </p>
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="ghost" size="sm" onClick={discardDraft}>忽略</Button>
            <Button size="sm" onClick={restoreDraft}>恢复草稿</Button>
          </div>
        </div>
      )}

      {/* Feedback */}
      {message && (
        <div className={`flex items-start justify-between gap-3 rounded-2xl border px-4 py-3 text-sm font-medium shadow-sm ${
          messageType === "success"
            ? "border-green-200 bg-[var(--color-success-light)] text-green-900"
            : "border-red-200 bg-red-50 text-red-800"
        }`}>
          <div className="flex items-center gap-2">
            {messageType === "success" ? <CheckCircle2 className="h-4 w-4" /> : <Circle className="h-4 w-4 fill-current" />}
            <span>{message}</span>
          </div>
          <button type="button" onClick={() => setMessage(null)} className="rounded p-0.5 opacity-60 transition hover:opacity-100" aria-label="关闭提示">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-6">
          {/* Step 1 */}
          <div ref={basicSectionRef} className="scroll-mt-28">
            <SectionCard
              step="01"
              title="基础信息"
              description="先确定公式卡片的归属、名称和用途，让后续内容更容易检索与维护。"
            >
              <div className="space-y-5">
                <div>
                  <FieldLabel required hint={`${title.length}/80`}>标题</FieldLabel>
                  <Input
                    className={`h-12 text-base ${titleError ? "border-red-400 bg-red-50/50 focus:border-red-500 focus:ring-red-100" : ""}`}
                    value={title}
                    maxLength={80}
                    onChange={(event) => {
                      setTitle(event.target.value);
                      if (event.target.value.trim()) setTitleError("");
                    }}
                    placeholder="例如：二次函数 y=ax^2+bx+c"
                  />
                  {titleError && <p className="mt-1.5 text-xs font-medium text-red-600">{titleError}</p>}
                  {title.trim() && (
                    <div className="mt-2 rounded-xl border border-[var(--color-border-light)] bg-white/65 px-3 py-2.5 text-base font-semibold text-[var(--ink)]">
                      <MixedLatexRenderer text={title} />
                    </div>
                  )}
                </div>

                <div className="grid gap-5 md:grid-cols-2">
                  <div>
                    <FieldLabel required>分类</FieldLabel>
                    <FormulaCategoryPicker
                      mode="form"
                      value={categoryId}
                      onChange={(value) => {
                        setCategoryId(value);
                        setCategoryError("");
                      }}
                      placeholder="选择公式分组"
                      error={categoryError}
                    />
                  </div>

                  <div>
                    <FieldLabel required>卡片类型</FieldLabel>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() => setCardType("pure_formula")}
                        className={`flex min-h-12 items-center gap-2 rounded-xl border px-3 text-left transition ${
                          cardType === "pure_formula"
                            ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] shadow-sm"
                            : "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:bg-white"
                        }`}
                      >
                        <FileText className="h-4 w-4 shrink-0" />
                        <span>
                          <span className="block text-sm font-semibold">纯公式</span>
                          <span className="block text-[10px] opacity-70">定义、定理与公式</span>
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setCardType("function_graph")}
                        className={`flex min-h-12 items-center gap-2 rounded-xl border px-3 text-left transition ${
                          cardType === "function_graph"
                            ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] shadow-sm"
                            : "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:bg-white"
                        }`}
                      >
                        <LayoutTemplate className="h-4 w-4 shrink-0" />
                        <span>
                          <span className="block text-sm font-semibold">函数图像</span>
                          <span className="block text-[10px] opacity-70">含图像与函数属性</span>
                        </span>
                      </button>
                    </div>
                  </div>
                </div>

                <div className="grid gap-5 md:grid-cols-2">
                  <div>
                    <FieldLabel hint="逗号、空格均可分隔">别名 / 检索词</FieldLabel>
                    <Input
                      value={aliases}
                      onChange={(event) => setAliases(event.target.value)}
                      placeholder="抛物线, quadratic function, parabola"
                    />
                  </div>
                  <div>
                    <FieldLabel>标签</FieldLabel>
                    {tags.isLoading ? (
                      <div className="flex h-9 items-center text-xs text-[var(--color-text-hint)]">正在加载标签...</div>
                    ) : tagButtons}
                  </div>
                </div>

                <div>
                  <FieldLabel hint={`${summary.length}/300`}>摘要</FieldLabel>
                  <textarea
                    className="min-h-24 w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm leading-6 outline-none transition placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
                    value={summary}
                    maxLength={300}
                    onChange={(event) => setSummary(event.target.value)}
                    placeholder="用一两句话说明该公式解决什么问题、关键变量或使用场景。"
                  />
                  {summary.trim() && (
                    <div className="mt-2 rounded-xl border border-[var(--color-border-light)] bg-white/65 px-3 py-2.5 text-sm leading-6 text-[var(--color-text-secondary)]">
                      <MixedLatexRenderer text={summary} />
                    </div>
                  )}
                </div>
              </div>
            </SectionCard>
          </div>

          {/* Step 2 */}
          <div ref={formulaSectionRef} className="scroll-mt-28">
            <SectionCard
              step="02"
              title="公式内容"
              description="每个公式块可以独立设置标题、公式和说明，建议按知识点拆分。"
              action={blocks.length < BLOCKS_MAX ? (
                <Button variant="secondary" size="sm" onClick={addBlock}>
                  <Plus className="h-3.5 w-3.5" /> 添加公式块
                </Button>
              ) : undefined}
            >
              <div className="space-y-4">
                {blocksError && (
                  <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
                    {blocksError}
                  </div>
                )}
                {blocks.map((block, index) => (
                  <FormulaBlockEditor
                    key={index}
                    block={block}
                    index={index}
                    onChange={(field, value) => updateBlock(index, field, value)}
                    onRemove={() => removeBlock(index)}
                    onDuplicate={() => duplicateBlock(index)}
                    canRemove={blocks.length > 1}
                    canDuplicate={blocks.length < BLOCKS_MAX}
                  />
                ))}
                {blocks.length < BLOCKS_MAX && (
                  <button
                    type="button"
                    onClick={addBlock}
                    className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--color-border)] bg-white/45 px-4 py-3 text-sm font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]"
                  >
                    <Plus className="h-4 w-4" />
                    再添加一个公式块
                  </button>
                )}
              </div>
            </SectionCard>
          </div>

          {/* Step 3: function properties */}
          {cardType === "function_graph" && (
            <SectionCard
              step="03"
              title="函数属性"
              description="填写图像生成与知识卡展示所需的关键属性；暂不确定的字段可以留空。"
              optional
            >
              <div className="space-y-5">
                {mode === "create" && (
                  <div className="flex items-start gap-2.5 rounded-xl border border-blue-200 bg-blue-50/70 px-3.5 py-3 text-xs leading-5 text-blue-800">
                    <Lightbulb className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>先保存公式卡片，随后可在详情页上传或生成函数图像。</span>
                  </div>
                )}

                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <FieldLabel>函数表达式</FieldLabel>
                    <Input value={funcExpression} onChange={(event) => setFuncExpression(event.target.value)} placeholder="f(x) = x^2" />
                    {funcExpression.trim() && (
                      <div className="mt-2 overflow-x-auto rounded-lg bg-[var(--porcelain)] px-3 py-2 text-center">
                        <LatexRenderer latex={normalizeLatexExpression(funcExpression)} displayMode={false} />
                      </div>
                    )}
                  </div>
                  <div>
                    <FieldLabel hint="可直接输入或选择建议">模板类型</FieldLabel>
                    <Input
                      list="formula-graph-template-options"
                      value={funcTemplate}
                      onChange={(event) => setFuncTemplate(event.target.value)}
                      placeholder="quadratic"
                    />
                    <datalist id="formula-graph-template-options">
                      <option value="quadratic" />
                      <option value="linear" />
                      <option value="sine" />
                      <option value="cosine" />
                      <option value="exponential" />
                      <option value="logarithmic" />
                      <option value="rational" />
                    </datalist>
                  </div>
                  <div>
                    <FieldLabel>定义域</FieldLabel>
                    <Input value={funcDomain} onChange={(event) => setFuncDomain(event.target.value)} placeholder="(-\\infty, +\\infty)" />
                  </div>
                  <div>
                    <FieldLabel>值域</FieldLabel>
                    <Input value={funcRange} onChange={(event) => setFuncRange(event.target.value)} placeholder="[0, +\\infty)" />
                  </div>
                  <div>
                    <FieldLabel>奇偶性</FieldLabel>
                    <Input value={funcParity} onChange={(event) => setFuncParity(event.target.value)} placeholder="偶函数 / 奇函数 / 非奇非偶" />
                  </div>
                  <div>
                    <FieldLabel>周期</FieldLabel>
                    <Input value={funcPeriod} onChange={(event) => setFuncPeriod(event.target.value)} placeholder="T = 2\\pi 或 无" />
                  </div>
                  <div className="md:col-span-2">
                    <FieldLabel>导数与临界点</FieldLabel>
                    <textarea
                      className="min-h-20 w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
                      value={funcDerivative}
                      onChange={(event) => setFuncDerivative(event.target.value)}
                      placeholder="例如：y' = 2ax+b，临界点 x=-b/(2a)"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <FieldLabel>一行特征描述</FieldLabel>
                    <textarea
                      className="min-h-20 w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
                      value={funcFeature}
                      onChange={(event) => setFuncFeature(event.target.value)}
                      placeholder="例如：抛物线关于 x=-b/(2a) 对称，顶点由系数 a、b、c 决定。"
                    />
                  </div>
                </div>
              </div>
            </SectionCard>
          )}

          {/* ── Function graph asset management (edit mode only) ── */}
          {cardType === "function_graph" && mode === "edit" && cardId && (
            <FormulaGraphAssetPanel cardId={cardId} canUpdate={true} />
          )}

          {/* Supplement */}
          <section className="overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.78)] shadow-[var(--shadow-card)]">
            <button
              type="button"
              onClick={() => setShowSupplement((value) => !value)}
              className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition hover:bg-white/60 lg:px-6"
            >
              <div className="flex items-center gap-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-bg-input)] text-[var(--color-primary-dark)]">
                  <ListChecks className="h-4 w-4" />
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="font-display text-lg font-bold text-[var(--ink)]">补充说明</h2>
                    <span className="rounded-full bg-[var(--color-bg-input)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-text-hint)]">可选</span>
                  </div>
                  <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">适用条件、符号说明、二级结论与易错提醒。</p>
                </div>
              </div>
              {showSupplement ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
            {showSupplement && (
              <div className="grid gap-5 border-t border-[var(--color-border-light)] p-5 lg:grid-cols-2 lg:p-6">
                <MathTextAreaField
                  label="适用条件"
                  value={conditions}
                  onChange={setConditions}
                  placeholder={'例如：[{"expression":"a\\ne 0","note":"二次项系数不为零"}]'}
                  helper="可输入普通文本、LaTeX 或 JSON 数组"
                />
                <MathTextAreaField
                  label="符号说明"
                  value={symbolNotes}
                  onChange={setSymbolNotes}
                  placeholder={'例如：[{"symbol":"\\Delta=b^2-4ac","note":"判别式"}]'}
                  helper="说明变量、符号和参数的含义"
                />
                <MathTextAreaField
                  label="二级结论"
                  value={secondaryConclusions}
                  onChange={setSecondaryConclusions}
                  placeholder={'例如：["对称轴为 x=-\\frac{b}{2a}", "顶点坐标为……"]'}
                  helper="补充可由主公式推出的常用结论"
                />
                <MathTextAreaField
                  label="易错提醒"
                  value={errorTips}
                  onChange={setErrorTips}
                  placeholder={'例如：["a=0 时不是二次函数", "注意判别式与极值的区别"]'}
                  helper="记录容易混淆、漏写或误用的内容"
                />
              </div>
            )}
          </section>

          {/* Examples */}
          <section className="overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.78)] shadow-[var(--shadow-card)]">
            <div className="flex items-center gap-2 px-5 py-4 transition hover:bg-white/60 lg:px-6">
              <button
                type="button"
                onClick={() => setShowExamples((value) => !value)}
                className="flex min-w-0 flex-1 items-center justify-between gap-4 text-left"
                aria-expanded={showExamples}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--color-bg-input)] text-[var(--color-primary-dark)]">
                    <Lightbulb className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h2 className="font-display text-lg font-bold text-[var(--ink)]">典型例题</h2>
                      <span className="rounded-full bg-[var(--color-bg-input)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-text-hint)]">{examples.length}/{EXAMPLES_MAX}</span>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-[var(--color-text-secondary)]">添加少量代表性例题，帮助理解公式的实际用法。</p>
                  </div>
                </div>
                {showExamples ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
              </button>
              {examples.length < EXAMPLES_MAX && (
                <button
                  type="button"
                  onClick={addExample}
                  className="flex h-8 shrink-0 items-center gap-1 rounded-lg border border-[var(--color-border)] bg-white px-2.5 text-xs font-semibold text-[var(--color-primary-dark)] transition hover:border-[var(--color-primary)]"
                >
                  <Plus className="h-3.5 w-3.5" /> 添加
                </button>
              )}
            </div>

            {showExamples && (
              <div className="space-y-4 border-t border-[var(--color-border-light)] p-5 lg:p-6">
                {examples.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-[var(--color-border)] bg-white/45 px-4 py-8 text-center">
                    <Lightbulb className="mx-auto mb-2 h-6 w-6 text-[var(--color-text-hint)]" />
                    <p className="text-sm font-medium text-[var(--color-text-secondary)]">暂未添加例题</p>
                    <p className="mt-1 text-xs text-[var(--color-text-hint)]">最多可添加 {EXAMPLES_MAX} 道典型例题</p>
                    <Button variant="secondary" size="sm" className="mt-3" onClick={addExample}>
                      <Plus className="h-3.5 w-3.5" /> 添加第一道例题
                    </Button>
                  </div>
                ) : (
                  examples.map((example, index) => (
                    <div key={index} className="overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white shadow-sm">
                      <div className="flex items-center justify-between border-b border-[var(--color-border-light)] bg-[rgba(239,235,229,0.4)] px-4 py-2.5">
                        <span className="text-sm font-semibold text-[var(--ink)]">例题 {index + 1}</span>
                        <button
                          type="button"
                          onClick={() => removeExample(index)}
                          className="rounded-lg p-1.5 text-[var(--color-text-hint)] transition hover:bg-red-50 hover:text-red-600"
                          aria-label="删除例题"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                      <div className="grid gap-4 p-4 md:grid-cols-2">
                        <div className="md:col-span-2">
                          <FieldLabel>题目</FieldLabel>
                          <textarea
                            className="min-h-20 w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
                            value={example.question}
                            onChange={(event) => updateExample(index, "question", event.target.value)}
                            placeholder="输入题目，可包含数学公式"
                          />
                        </div>
                        <div>
                          <FieldLabel>简要解法</FieldLabel>
                          <textarea
                            className="min-h-24 w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
                            value={example.short_solution}
                            onChange={(event) => updateExample(index, "short_solution", event.target.value)}
                            placeholder="写出核心步骤"
                          />
                        </div>
                        <div>
                          <FieldLabel>答案</FieldLabel>
                          <textarea
                            className="min-h-24 w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm leading-6 outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
                            value={example.answer}
                            onChange={(event) => updateExample(index, "answer", event.target.value)}
                            placeholder="输入最终答案"
                          />
                        </div>
                        <div className="md:col-span-2">
                          <FieldLabel hint="可选">例题易错点</FieldLabel>
                          <Input
                            value={example.error_tip || ""}
                            onChange={(event) => updateExample(index, "error_tip", event.target.value)}
                            placeholder="例如：不要漏掉 a≠0 的条件"
                          />
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </section>

          {mode === "edit" && (
            <SectionCard step="04" title="管理设置" description="仅管理员编辑时可调整的排序信息。" optional>
              <div className="max-w-xs">
                <FieldLabel>排序值</FieldLabel>
                <Input type="number" value={sortOrder} onChange={(event) => setSortOrder(Number(event.target.value))} />
              </div>
            </SectionCard>
          )}
        </div>

        {/* Live preview / status rail */}
        <aside className="hidden xl:sticky xl:top-[5.75rem] xl:block xl:min-h-0 xl:self-start">
          <div
            className="formula-editor-rail-scroll max-h-[calc(100dvh-7.25rem)] space-y-4 overflow-y-auto overscroll-contain pb-2 pr-1.5"
            tabIndex={0}
            aria-label="公式编辑辅助侧栏，可独立上下滚动"
          >
          <div className="overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--porcelain)] shadow-[var(--shadow-floating)]">
            <div className="flex items-center justify-between border-b border-[var(--color-border-light)] px-4 py-3">
              <div className="flex items-center gap-2">
                <Eye className="h-4 w-4 text-[var(--color-primary)]" />
                <span className="text-sm font-semibold text-[var(--ink)]">实时预览</span>
              </div>
              <span className="rounded-full bg-[var(--color-bg-input)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-text-hint)]">
                {cardType === "function_graph" ? "函数图像" : "纯公式"}
              </span>
            </div>

            <div className="space-y-4 p-4">
              <div>
                <h3 className="font-display text-xl font-bold leading-8 text-[var(--ink)]">
                  {title.trim() ? <MixedLatexRenderer text={title} /> : <span className="text-[var(--color-text-hint)]">公式标题</span>}
                </h3>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {categoryId ? (
                    <span className="rounded-md bg-[var(--color-primary-light)] px-2 py-1 text-[10px] font-semibold text-[var(--color-primary-dark)]">已选择分类</span>
                  ) : (
                    <span className="rounded-md border border-dashed border-[var(--color-border)] px-2 py-1 text-[10px] text-[var(--color-text-hint)]">未选择分类</span>
                  )}
                  {selectedTags.map((code) => (
                    <span key={code} className="rounded-md bg-[var(--color-bg-input)] px-2 py-1 text-[10px] font-semibold text-[var(--color-text-secondary)]">
                      {TAG_NAMES[code]}
                    </span>
                  ))}
                </div>
              </div>

              {summary.trim() && (
                <div className="rounded-xl bg-[var(--color-primary-light)]/55 px-3 py-2.5 text-xs leading-5 text-[var(--color-text-secondary)]">
                  <MixedLatexRenderer text={summary} />
                </div>
              )}

              <div className="space-y-3">
                {blocks.some((block) => block.latex.trim()) ? (
                  blocks.filter((block) => block.latex.trim()).map((block, index) => (
                    <div key={index} className="rounded-xl border border-[var(--color-border-light)] bg-white px-3 py-3">
                      {block.label?.trim() && <p className="mb-2 text-[10px] font-semibold text-[var(--color-text-hint)]">{block.label}</p>}
                      <div className="overflow-x-auto text-center">
                        <LatexRenderer latex={normalizeLatexExpression(block.latex)} displayMode={true} />
                      </div>
                      {block.note?.trim() && (
                        <div className="mt-2 border-t border-[var(--color-border-light)] pt-2 text-xs leading-5 text-[var(--color-text-secondary)]">
                          <MixedLatexRenderer text={block.note} />
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="rounded-xl border border-dashed border-[var(--color-border)] px-3 py-8 text-center text-xs text-[var(--color-text-hint)]">
                    公式内容将显示在这里
                  </div>
                )}
              </div>

              {cardType === "function_graph" && (funcExpression.trim() || funcDomain.trim() || funcRange.trim()) && (
                <div className="space-y-1.5 rounded-xl border border-[var(--color-primary-light)] bg-[var(--color-primary-light)]/35 px-3 py-2.5 text-xs text-[var(--color-text-secondary)]">
                  {funcExpression.trim() && (
                    <p><span className="font-semibold text-[var(--ink)]">表达式：</span><MixedLatexRenderer text={funcExpression} /></p>
                  )}
                  {funcDomain.trim() && (
                    <p><span className="font-semibold text-[var(--ink)]">定义域：</span><MixedLatexRenderer text={funcDomain} /></p>
                  )}
                  {funcRange.trim() && (
                    <p><span className="font-semibold text-[var(--ink)]">值域：</span><MixedLatexRenderer text={funcRange} /></p>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-[var(--color-border-light)] bg-white/75 p-4 shadow-sm">
            <div className="mb-3 flex items-center gap-2">
              <ListChecks className="h-4 w-4 text-[var(--color-primary)]" />
              <p className="text-sm font-semibold text-[var(--ink)]">提交前检查</p>
            </div>
            <div className="space-y-2.5">
              {requiredItems.map((item) => (
                <div key={item.label} className="flex items-center gap-2 text-xs">
                  {item.done ? (
                    <CheckCircle2 className="h-4 w-4 text-[var(--color-success)]" />
                  ) : (
                    <Circle className="h-4 w-4 text-[var(--color-border)]" />
                  )}
                  <span className={item.done ? "text-[var(--color-text-secondary)]" : "font-medium text-[var(--ink)]"}>{item.label}</span>
                </div>
              ))}
            </div>
            <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-[var(--color-bg-input)]">
              <div className="h-full rounded-full bg-[var(--color-primary)] transition-all duration-300" style={{ width: `${completionPercent}%` }} />
            </div>
            <p className="mt-2 text-[10px] text-[var(--color-text-hint)]">完成必填项后即可保存为草稿。</p>
          </div>

          <div className="rounded-2xl border border-[var(--color-border-light)] bg-white/65 p-4 text-xs leading-5 text-[var(--color-text-secondary)]">
            <div className="flex items-start gap-2.5">
              <Tags className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-primary)]" />
              <div>
                <p className="font-semibold text-[var(--ink)]">编辑提示</p>
                <p className="mt-1">使用 <kbd className="rounded border bg-white px-1.5 py-0.5 font-mono text-[10px]">Ctrl / ⌘ + S</kbd> 可快速保存。</p>
                {mode === "create" && (
                  <p className="mt-1">
                    {lastAutoSavedAt
                      ? `本地草稿已自动保存于 ${lastAutoSavedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                      : "填写后会自动保存到当前浏览器。"}
                  </p>
                )}
              </div>
            </div>
          </div>
          </div>
        </aside>
      </div>

      {/* Mobile save bar */}
      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--color-border)] bg-[rgba(254,252,249,0.94)] px-4 py-3 shadow-[0_-8px_28px_rgba(27,39,51,0.08)] backdrop-blur-xl sm:hidden">
        <div className="flex items-center gap-2">
          <Button variant="secondary" className="flex-1" onClick={handleCancel}>
            取消
          </Button>
          <Button className="flex-[1.4]" onClick={handleSave} disabled={isPending}>
            <Save className="h-4 w-4" />
            {isPending ? "保存中..." : mode === "create" ? "保存草稿" : "保存修改"}
          </Button>
        </div>
      </div>
    </div>
  );
}
