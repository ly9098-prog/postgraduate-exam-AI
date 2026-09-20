"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  ChevronRight,
  Circle,
  Copy,
  Eye,
  FileText,
  History,
  ImageIcon,
  Layers3,
  ListChecks,
  Plus,
  Save,
  Search,
  Settings2,
  Sparkles,
  Tags,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatChinaDateTime } from "@/lib/time";
import { Input } from "@/components/ui/input";
import { LatexRenderer } from "@/components/ui/latex-renderer";
import { MixedLatexRenderer } from "@/components/ui/mixed-latex-renderer";
import {
  FormulaCategoryPicker,
  type FormulaCategoryNode,
} from "@/components/formulas/formula-category-picker";
import { FormulaGraphAssetPanel } from "@/components/formulas/formula-graph-asset-panel";
import { apiRequest } from "@/lib/api/client";
import { normalizeFormulaText } from "@/lib/formula-normalize";
import { normalizeLatexExpression } from "@/lib/math-text";

const BLOCKS_MAX = 8;
const EXAMPLES_MAX = 3;

const STATUS_BADGE: Record<string, string> = {
  draft: "border-slate-200 bg-slate-50 text-slate-600",
  pending_review: "border-amber-200 bg-amber-50 text-amber-700",
  rejected: "border-red-200 bg-red-50 text-red-700",
  published: "border-emerald-200 bg-emerald-50 text-emerald-700",
  offline: "border-slate-200 bg-slate-50 text-slate-600",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  pending_review: "待审核",
  rejected: "已驳回",
  published: "已发布",
  offline: "已下架",
};

const CARD_TYPE_LABEL: Record<string, string> = {
  auto: "自动识别",
  pure_formula: "纯公式",
  function_graph: "函数图像",
};

const STUDY_CARD_TYPE_LABEL: Record<string, string> = {
  formula: "公式",
  definition: "定义",
  complexity: "算法复杂度",
  protocol_rule: "协议字段 / 规则",
  key_conclusion: "高频结论",
  confusable: "易混概念",
  trap: "典型陷阱",
  comparison: "对比卡",
};

const DEFAULT_TEMPLATE_BY_STUDY_TYPE: Record<string, string> = {
  formula: "standard", definition: "memory", complexity: "rule", protocol_rule: "rule",
  key_conclusion: "memory", confusable: "contrast", trap: "trap", comparison: "contrast",
};

const VERSION_ACTION_LABEL: Record<string, string> = {
  create: "创建",
  update: "更新",
  approve: "审核通过",
  reject: "驳回",
  publish: "发布",
  offline: "下架",
  restore: "恢复",
  submit: "提交审核",
};

type FormulaBlock = {
  label?: string | null;
  latex: string;
  note?: string | null;
};

type FormulaExample = {
  question: string;
  short_solution: string;
  answer: string;
  error_tip?: string | null;
};

type TagOption = {
  id: number;
  code: string;
  name: string;
};

type VersionItem = {
  id: number;
  version: number;
  action: string;
  edited_by: number | null;
  edit_reason?: string | null;
  created_at: string;
};

export type FormulaEditWorkbenchData = {
  categoryId: number;
  title: string;
  aliases: string[] | null;
  summary: string | null;
  conditions: string | null;
  symbolNotes: string | null;
  secondaryConclusions: string | null;
  errorTips: string | null;
  tags: TagOption[];
  blocks: FormulaBlock[];
  examples: FormulaExample[] | null;
  sortOrder: number;
  cardType: string;
  studyCardType: string;
  templateType: string;
  functionProperties: Record<string, unknown> | null;
  status: string;
  version: number;
  publishedAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  updatedBy: number | null;
};

type Props = {
  cardId: number;
  initialData: FormulaEditWorkbenchData;
  onClose: () => void;
  onSaved?: () => void;
};

type WorkspaceTab = "block" | "supplement" | "examples" | "graph";
type RailTab = "properties" | "preview";

function formatDateTime(value: string | null | undefined) {
  return formatChinaDateTime(value);
}

function editableText(value: unknown) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function flattenCategories(nodes: FormulaCategoryNode[]): FormulaCategoryNode[] {
  return nodes.flatMap((node) => [node, ...flattenCategories(node.children || [])]);
}

function findCategoryPath(nodes: FormulaCategoryNode[], targetId: number): FormulaCategoryNode[] | null {
  for (const node of nodes) {
    if (node.id === targetId) return [node];
    const childPath = findCategoryPath(node.children || [], targetId);
    if (childPath) return [node, ...childPath];
  }
  return null;
}

function SectionLabel({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="mb-3 flex items-center gap-2 text-xs font-semibold tracking-wide text-[var(--color-text-secondary)]">
      <span className="text-[var(--color-primary)]">{icon}</span>
      {children}
    </div>
  );
}

function CompactTextarea({
  value,
  onChange,
  placeholder,
  rows = 3,
  mono = false,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  rows?: number;
  mono?: boolean;
}) {
  return (
    <textarea
      rows={rows}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      spellCheck={!mono}
      className={`w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2.5 text-sm leading-6 outline-none transition-all duration-200 placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.12)] ${mono ? "font-mono" : ""}`}
    />
  );
}

export function FormulaEditWorkbench({ cardId, initialData, onClose, onSaved }: Props) {
  const [title, setTitle] = useState(initialData.title);
  const [aliases, setAliases] = useState(initialData.aliases?.join(", ") || "");
  const [summary, setSummary] = useState(initialData.summary || "");
  const [categoryId, setCategoryId] = useState<number | null>(initialData.categoryId);
  const [cardType, setCardType] = useState(initialData.cardType || "auto");
  const [studyCardType, setStudyCardType] = useState(initialData.studyCardType || "formula");
  const [templateType, setTemplateType] = useState(initialData.templateType || DEFAULT_TEMPLATE_BY_STUDY_TYPE[initialData.studyCardType || "formula"] || "standard");
  const [sortOrder, setSortOrder] = useState(initialData.sortOrder || 0);
  const [conditions, setConditions] = useState(initialData.conditions || "");
  const [symbolNotes, setSymbolNotes] = useState(initialData.symbolNotes || "");
  const [secondaryConclusions, setSecondaryConclusions] = useState(initialData.secondaryConclusions || "");
  const [errorTips, setErrorTips] = useState(initialData.errorTips || "");
  const [selectedTags, setSelectedTags] = useState<string[]>(initialData.tags.map((tag) => tag.code));
  const [blocks, setBlocks] = useState<FormulaBlock[]>(initialData.blocks.length ? initialData.blocks : [{ latex: "" }]);
  const [examples, setExamples] = useState<FormulaExample[]>(initialData.examples || []);

  const [funcExpression, setFuncExpression] = useState(editableText(initialData.functionProperties?.function_expression));
  const [funcTemplate, setFuncTemplate] = useState(editableText(initialData.functionProperties?.graph_template_type));
  const [funcDomain, setFuncDomain] = useState(editableText(initialData.functionProperties?.domain));
  const [funcRange, setFuncRange] = useState(editableText(initialData.functionProperties?.range));
  const [funcParity, setFuncParity] = useState(editableText(initialData.functionProperties?.parity));
  const [funcPeriod, setFuncPeriod] = useState(editableText(initialData.functionProperties?.period));
  const [funcDerivative, setFuncDerivative] = useState(editableText(initialData.functionProperties?.derivative_summary));
  const [funcFeature, setFuncFeature] = useState(editableText(initialData.functionProperties?.one_line_feature));

  const [selectedBlockIndex, setSelectedBlockIndex] = useState(0);
  const [blockSearch, setBlockSearch] = useState("");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("block");
  const [railTab, setRailTab] = useState<RailTab>("properties");
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [savedVersion, setSavedVersion] = useState(initialData.version);
  const [savedUpdatedAt, setSavedUpdatedAt] = useState(initialData.updatedAt);
  const [savedUpdatedBy, setSavedUpdatedBy] = useState(initialData.updatedBy);
  const [savedSnapshot, setSavedSnapshot] = useState("");
  const submittedSnapshotRef = useRef("");
  const blockEditorRef = useRef<HTMLElement>(null);
  const previewRailRef = useRef<HTMLElement>(null);

  const tagsQuery = useQuery({
    queryKey: ["admin-formula-tags"],
    queryFn: () => apiRequest<{ items: TagOption[] }>("/formulas/tags"),
    staleTime: 60000,
  });

  const categoriesQuery = useQuery({
    queryKey: ["admin-formula-categories"],
    queryFn: () => apiRequest<{ items: FormulaCategoryNode[] }>("/formulas/categories"),
    staleTime: 60000,
  });

  const versionsQuery = useQuery({
    queryKey: ["admin-formulas", cardId, "versions"],
    queryFn: () => apiRequest<{ items: VersionItem[] }>(`/formulas/${cardId}/versions`),
    staleTime: 15000,
  });

  const allTags = useMemo(() => {
    const merged = new Map<string, TagOption>();
    initialData.tags.forEach((tag) => merged.set(tag.code, tag));
    tagsQuery.data?.items?.forEach((tag) => merged.set(tag.code, tag));
    return Array.from(merged.values()).sort((a, b) => a.id - b.id);
  }, [initialData.tags, tagsQuery.data]);

  const tagIdMap = useMemo(() => {
    const map: Record<string, number> = {};
    allTags.forEach((tag) => { map[tag.code] = tag.id; });
    return map;
  }, [allTags]);

  const categoryPath = useMemo(() => {
    if (!categoryId || !categoriesQuery.data?.items) return [];
    return findCategoryPath(categoriesQuery.data.items, categoryId) || [];
  }, [categoryId, categoriesQuery.data]);

  const categoryLabel = categoryPath.length
    ? categoryPath.map((node) => node.name).join(" / ")
    : categoriesQuery.isLoading
      ? "正在读取分类…"
      : categoryId
        ? `分类 #${categoryId}`
        : "未选择分类";

  const buildFunctionProperties = useCallback(() => {
    if (cardType === "pure_formula") return null;
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
    return Object.keys(properties).length ? properties : null;
  }, [
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

  const serializeForm = useCallback(() => JSON.stringify({
    title,
    aliases,
    summary,
    categoryId,
    cardType,
    studyCardType,
    templateType,
    sortOrder,
    conditions,
    symbolNotes,
    secondaryConclusions,
    errorTips,
    selectedTags,
    blocks,
    examples,
    functionProperties: buildFunctionProperties(),
  }), [
    title,
    aliases,
    summary,
    categoryId,
    cardType,
    studyCardType,
    templateType,
    sortOrder,
    conditions,
    symbolNotes,
    secondaryConclusions,
    errorTips,
    selectedTags,
    blocks,
    examples,
    buildFunctionProperties,
  ]);

  useEffect(() => {
    if (!savedSnapshot) setSavedSnapshot(serializeForm());
  }, [savedSnapshot, serializeForm]);

  const currentSnapshot = serializeForm();
  const isDirty = Boolean(savedSnapshot && currentSnapshot !== savedSnapshot);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!isDirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [isDirty]);

  const selectedBlock = blocks[selectedBlockIndex] || blocks[0];

  const filteredBlockIndexes = useMemo(() => {
    const keyword = blockSearch.trim().toLowerCase();
    return blocks
      .map((block, index) => ({ block, index }))
      .filter(({ block, index }) => {
        if (!keyword) return true;
        return `${index + 1} ${block.label || ""} ${block.note || ""}`.toLowerCase().includes(keyword);
      })
      .map(({ index }) => index);
  }, [blocks, blockSearch]);

  const scrollToBlockEditor = useCallback(() => {
    window.requestAnimationFrame(() => {
      blockEditorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, []);

  const selectBlock = useCallback((index: number, shouldScroll = true) => {
    setSelectedBlockIndex(index);
    setWorkspaceTab("block");
    if (shouldScroll) scrollToBlockEditor();
  }, [scrollToBlockEditor]);

  const openPreview = useCallback(() => {
    setRailTab("preview");
    if (typeof window !== "undefined" && window.matchMedia("(max-width: 1279px)").matches) {
      window.requestAnimationFrame(() => {
        previewRailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }, []);

  const updateBlock = useCallback((index: number, patch: Partial<FormulaBlock>) => {
    setBlocks((previous) => previous.map((block, itemIndex) => (
      itemIndex === index ? { ...block, ...patch } : block
    )));
  }, []);

  const addBlockAfter = useCallback((index?: number) => {
    setBlocks((previous) => {
      if (previous.length >= BLOCKS_MAX) return previous;
      const insertAt = typeof index === "number" ? Math.min(index + 1, previous.length) : previous.length;
      const next = [...previous];
      next.splice(insertAt, 0, { label: "", latex: "", note: "" });
      window.setTimeout(() => {
        setSelectedBlockIndex(insertAt);
        scrollToBlockEditor();
      }, 0);
      return next;
    });
    setWorkspaceTab("block");
  }, [scrollToBlockEditor]);

  const duplicateSelectedBlock = useCallback(() => {
    setBlocks((previous) => {
      if (previous.length >= BLOCKS_MAX || !previous[selectedBlockIndex]) return previous;
      const next = [...previous];
      next.splice(selectedBlockIndex + 1, 0, { ...previous[selectedBlockIndex] });
      window.setTimeout(() => {
        setSelectedBlockIndex(selectedBlockIndex + 1);
        scrollToBlockEditor();
      }, 0);
      return next;
    });
    setWorkspaceTab("block");
  }, [scrollToBlockEditor, selectedBlockIndex]);

  const removeSelectedBlock = useCallback(() => {
    if (blocks.length <= 1) return;
    const blockName = selectedBlock?.label?.trim() || `公式块 ${selectedBlockIndex + 1}`;
    if (!window.confirm(`确认删除“${blockName}”？`)) return;
    setBlocks((previous) => previous.filter((_, index) => index !== selectedBlockIndex));
    setSelectedBlockIndex((current) => Math.max(0, Math.min(current, blocks.length - 2)));
  }, [blocks.length, selectedBlock, selectedBlockIndex]);

  const moveSelectedBlock = useCallback((direction: -1 | 1) => {
    setBlocks((previous) => {
      const target = selectedBlockIndex + direction;
      if (target < 0 || target >= previous.length) return previous;
      const next = [...previous];
      [next[selectedBlockIndex], next[target]] = [next[target], next[selectedBlockIndex]];
      window.setTimeout(() => setSelectedBlockIndex(target), 0);
      return next;
    });
  }, [selectedBlockIndex]);

  const toggleTag = useCallback((code: string) => {
    setSelectedTags((previous) => previous.includes(code)
      ? previous.filter((item) => item !== code)
      : [...previous, code]);
  }, []);

  const updateExample = useCallback((index: number, patch: Partial<FormulaExample>) => {
    setExamples((previous) => previous.map((example, itemIndex) => (
      itemIndex === index ? { ...example, ...patch } : example
    )));
  }, []);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!categoryId) throw new Error("请选择公式分类");
      if (!title.trim()) throw new Error("请填写公式标题");
      const validBlocks = blocks.filter((block) => block.latex.trim());
      if (studyCardType === "formula" && validBlocks.length < 1) {
        throw new Error("公式卡至少需要一个公式块");
      }
      if (studyCardType !== "formula" && !summary.trim() && validBlocks.length < 1 && !secondaryConclusions.trim() && !errorTips.trim()) {
        throw new Error("非公式速记卡至少填写摘要、核心内容、常见结论或易错提醒之一");
      }
      if (examples.some((example) => !example.question.trim() || !example.short_solution.trim() || !example.answer.trim())) {
        throw new Error("例题的题目、核心解法和答案需要填写完整");
      }

      const aliasesList = aliases.split(/[,，、\s]+/).map((item) => item.trim()).filter(Boolean);
      const tagIds = selectedTags.map((code) => tagIdMap[code]).filter((id): id is number => Boolean(id));

      return apiRequest<{ version?: number; updated_at?: string; updated_by?: number | null }>(`/formulas/${cardId}`, {
        method: "PUT",
        body: JSON.stringify({
          category_id: categoryId,
          title: title.trim(),
          aliases: aliasesList.length ? aliasesList : null,
          search_text: [title.trim(), ...aliasesList].join(" "),
          card_type: cardType,
          study_card_type: studyCardType,
          template_type: templateType,
          summary: summary.trim() || null,
          formula_blocks: validBlocks.map((block) => ({
            label: block.label?.trim() || null,
            latex: block.latex.trim(),
            note: block.note?.trim() || null,
          })),
          conditions: normalizeFormulaText(conditions.trim()) || null,
          symbol_notes: normalizeFormulaText(symbolNotes.trim()) || null,
          secondary_conclusions: normalizeFormulaText(secondaryConclusions.trim()) || null,
          error_tips: normalizeFormulaText(errorTips.trim()) || null,
          examples: examples.length ? examples.map((example) => ({
            question: example.question.trim(),
            short_solution: example.short_solution.trim(),
            answer: example.answer.trim(),
            error_tip: example.error_tip?.trim() || null,
          })) : null,
          function_properties: buildFunctionProperties(),
          sort_order: sortOrder,
          tag_ids: tagIds,
        }),
      });
    },
    onSuccess: (result) => {
      setSavedSnapshot(submittedSnapshotRef.current || serializeForm());
      if (result?.version) setSavedVersion(result.version);
      if (result?.updated_at) setSavedUpdatedAt(result.updated_at);
      if (result && "updated_by" in result) setSavedUpdatedBy(result.updated_by ?? null);
      setMessage({ type: "success", text: "修改已保存" });
      versionsQuery.refetch();
      onSaved?.();
    },
    onError: (error) => {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "保存失败，请稍后重试",
      });
    },
  });

  useEffect(() => {
    if (message?.type !== "success") return;
    const timer = window.setTimeout(() => setMessage(null), 2200);
    return () => window.clearTimeout(timer);
  }, [message]);

  const handleSave = useCallback(() => {
    if (saveMutation.isPending) return;
    submittedSnapshotRef.current = serializeForm();
    saveMutation.mutate();
  }, [saveMutation, serializeForm]);

  const handleClose = useCallback(() => {
    if (isDirty && !window.confirm("当前有未保存修改，确定退出编辑吗？")) return;
    onClose();
  }, [isDirty, onClose]);

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        handleSave();
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [handleSave]);

  const requiredChecks = useMemo(() => [
    { label: "已选择分类", done: Boolean(categoryId) },
    { label: "已填写标题", done: Boolean(title.trim()) },
    { label: studyCardType === "formula" ? "已录入核心公式" : "已录入速记内容", done: studyCardType === "formula" ? blocks.some((block) => Boolean(block.latex.trim())) : Boolean(summary.trim() || blocks.some((block) => Boolean(block.latex.trim())) || secondaryConclusions.trim() || errorTips.trim()) },
    { label: "例题字段完整", done: examples.length === 0 || examples.every((example) => Boolean(example.question.trim() && example.short_solution.trim() && example.answer.trim())) },
  ], [categoryId, title, blocks, examples, studyCardType, summary, secondaryConclusions, errorTips]);

  const topWorkspaceTabs: Array<{ key: WorkspaceTab; label: string; icon: ReactNode; visible: boolean }> = [
    { key: "block", label: "内容编辑", icon: <FileText className="h-3.5 w-3.5" />, visible: true },
    { key: "supplement", label: "补充说明", icon: <ListChecks className="h-3.5 w-3.5" />, visible: true },
    { key: "examples", label: `例题 ${examples.length ? `(${examples.length})` : ""}`, icon: <Sparkles className="h-3.5 w-3.5" />, visible: true },
    { key: "graph", label: "函数图像", icon: <ImageIcon className="h-3.5 w-3.5" />, visible: cardType === "function_graph" },
  ];

  return (
    <div className="mx-auto h-full max-w-[1760px] px-3 pb-24 pt-2 lg:px-5 xl:flex xl:min-h-0 xl:flex-col xl:pb-3">
      <header className="sticky top-2 z-50 isolate shrink-0 rounded-2xl border border-[var(--color-border)] bg-[rgba(254,252,249,0.96)] px-3 py-1.5 shadow-[0_10px_30px_rgba(27,39,51,0.10)] backdrop-blur-xl xl:static">
        <div className="flex min-h-12 items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={handleClose}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--color-text-secondary)] transition-all duration-200 hover:-translate-x-0.5 hover:bg-white hover:text-[var(--ink)] hover:shadow-sm"
              aria-label="退出编辑"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div className="min-w-0">
              <div className="hidden items-center gap-1 text-[9px] font-medium text-[var(--color-text-hint)] sm:flex">
                <span>408 速记卡</span><ChevronRight className="h-2.5 w-2.5" /><span>编辑</span><ChevronRight className="h-2.5 w-2.5" /><span>#{cardId}</span>
              </div>
              <div className="flex min-w-0 items-center gap-2 sm:mt-0.5">
                <h1 className="truncate font-display text-base font-bold text-[var(--ink)] lg:text-lg">{title || "未命名速记卡"}</h1>
                <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${STATUS_BADGE[initialData.status] || STATUS_BADGE.draft}`}>
                  {STATUS_LABEL[initialData.status] || initialData.status}
                </span>
                {isDirty && (
                  <span className="hidden shrink-0 items-center gap-1 text-[10px] font-medium text-amber-700 sm:inline-flex">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500 motion-reduce:animate-none" />
                    有未保存修改
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <Button variant="secondary" size="sm" className="hidden h-8 md:inline-flex" onClick={openPreview}>
              <Eye className="h-3.5 w-3.5" /> 预览
            </Button>
            {isDirty || saveMutation.isPending ? (
              <Button size="sm" className="h-8" onClick={handleSave} disabled={saveMutation.isPending}>
                <Save className="h-3.5 w-3.5" />
                {saveMutation.isPending ? "保存中…" : "保存修改"}
              </Button>
            ) : (
              <div className="hidden h-8 items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 text-xs font-semibold text-emerald-700 sm:flex">
                <CheckCircle2 className="h-3.5 w-3.5" /> 已保存
              </div>
            )}
            <Button variant="ghost" size="sm" className="h-8 px-2.5" onClick={handleClose}>完成</Button>
          </div>
        </div>
      </header>

      {message && (
        <div
          role="status"
          aria-live="polite"
          className={`fixed right-5 top-20 z-[70] flex max-w-[min(420px,calc(100vw-2.5rem))] items-center justify-between gap-4 rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_14px_36px_rgba(27,39,51,0.16)] animate-drop-in ${message.type === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800"}`}
        >
          <div className="flex items-center gap-2">
            {message.type === "success" ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <Circle className="h-4 w-4 shrink-0 fill-current" />}
            <span>{message.text}</span>
          </div>
          <button type="button" onClick={() => setMessage(null)} className="rounded-lg p-1 transition hover:bg-white/70" aria-label="关闭提示"><X className="h-3.5 w-3.5" /></button>
        </div>
      )}

      <div className="mt-3 grid items-start gap-3 xl:min-h-0 xl:flex-1 xl:overflow-hidden xl:grid-cols-[214px_minmax(0,1fr)_292px] 2xl:grid-cols-[226px_minmax(0,1fr)_306px]">
        {/* Left: block navigation */}
        <aside className="min-h-0 xl:flex xl:h-full xl:flex-col">
          <div className="overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[rgba(254,252,249,0.92)] shadow-[var(--shadow-card)] xl:flex xl:min-h-0 xl:flex-1 xl:flex-col">
            <div className="shrink-0 border-b border-[var(--color-border-light)] px-3.5 py-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-[var(--ink)]">块导航</p>
                  <p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">{blocks.length} / {BLOCKS_MAX} 个公式块</p>
                </div>
                <Layers3 className="h-4 w-4 text-[var(--color-primary)]" />
              </div>
              <div className="relative mt-3">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-hint)]" />
                <Input value={blockSearch} onChange={(event) => setBlockSearch(event.target.value)} placeholder="搜索公式块" className="h-9 pl-8 pr-8 text-xs" />
                {blockSearch ? (
                  <button
                    type="button"
                    onClick={() => setBlockSearch("")}
                    className="absolute right-2 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-md text-[var(--color-text-hint)] transition hover:bg-white hover:text-[var(--ink)]"
                    aria-label="清除公式块搜索"
                  >
                    <X className="h-3 w-3" />
                  </button>
                ) : null}
              </div>
            </div>

            <div className="formula-editor-rail-scroll max-h-[46vh] space-y-1 overflow-y-auto p-2 xl:min-h-0 xl:max-h-none xl:flex-1">
              {filteredBlockIndexes.map((index) => {
                const block = blocks[index];
                const active = selectedBlockIndex === index;
                const valid = Boolean(block.latex.trim());
                return (
                  <button
                    key={`${index}-${block.label || "block"}`}
                    type="button"
                    onClick={() => selectBlock(index)}
                    aria-current={active ? "true" : undefined}
                    className={`group flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left transition-all duration-200 motion-safe:hover:-translate-y-px ${active ? "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] shadow-sm" : "text-[var(--color-text-secondary)] hover:bg-white hover:text-[var(--ink)] hover:shadow-sm"}`}
                  >
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border text-[10px] font-bold transition ${active ? "border-[var(--color-primary)] bg-white" : "border-[var(--color-border-light)] bg-white/70"}`}>{index + 1}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-semibold">{block.label?.trim() || `公式块 ${index + 1}`}</span>
                      <span className="mt-0.5 block truncate text-[10px] text-[var(--color-text-hint)]">{block.note?.trim() || (valid ? "已录入公式" : "待补充内容")}</span>
                    </span>
                    <span className={`h-2 w-2 shrink-0 rounded-full ${valid ? "bg-emerald-500" : "bg-amber-400"}`} />
                  </button>
                );
              })}
              {!filteredBlockIndexes.length && (
                <div className="px-2 py-8 text-center text-xs text-[var(--color-text-hint)]">没有匹配的公式块</div>
              )}
            </div>

            <div className="shrink-0 border-t border-[var(--color-border-light)] p-2.5">
              <Button variant="secondary" className="w-full" size="sm" onClick={() => addBlockAfter(selectedBlockIndex)} disabled={blocks.length >= BLOCKS_MAX}>
                <Plus className="h-3.5 w-3.5" /> 新增公式块
              </Button>
            </div>
          </div>

          <div className="mt-3 shrink-0 rounded-2xl border border-[var(--color-border-light)] bg-white/80 p-2.5 shadow-sm">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[var(--color-text-secondary)]">
                <Settings2 className="h-3.5 w-3.5 text-[var(--color-primary)]" />快捷操作
              </div>
              <span className="text-[9px] text-[var(--color-text-hint)]">当前 #{selectedBlockIndex + 1}</span>
            </div>
            <div className="grid grid-cols-4 gap-1.5 xl:grid-cols-2">
              <button type="button" title="复制当前块" aria-label="复制当前块" onClick={duplicateSelectedBlock} disabled={blocks.length >= BLOCKS_MAX} className="flex h-8 items-center justify-center gap-1.5 rounded-lg border border-transparent px-2 text-[11px] font-medium text-[var(--color-text-secondary)] transition-all hover:border-[var(--color-border-light)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:opacity-35"><Copy className="h-3.5 w-3.5" /><span className="hidden 2xl:inline">复制</span></button>
              <button type="button" title="新增同级块" aria-label="新增同级块" onClick={() => addBlockAfter(selectedBlockIndex)} disabled={blocks.length >= BLOCKS_MAX} className="flex h-8 items-center justify-center gap-1.5 rounded-lg border border-transparent px-2 text-[11px] font-medium text-[var(--color-text-secondary)] transition-all hover:border-[var(--color-border-light)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:opacity-35"><Plus className="h-3.5 w-3.5" /><span className="hidden 2xl:inline">新增</span></button>
              <button type="button" title="上移" aria-label="上移当前块" onClick={() => moveSelectedBlock(-1)} disabled={selectedBlockIndex === 0} className="flex h-8 items-center justify-center gap-1.5 rounded-lg border border-transparent px-2 text-[11px] font-medium text-[var(--color-text-secondary)] transition-all hover:border-[var(--color-border-light)] hover:bg-white disabled:opacity-30"><ArrowUp className="h-3.5 w-3.5" /><span className="hidden 2xl:inline">上移</span></button>
              <button type="button" title="下移" aria-label="下移当前块" onClick={() => moveSelectedBlock(1)} disabled={selectedBlockIndex >= blocks.length - 1} className="flex h-8 items-center justify-center gap-1.5 rounded-lg border border-transparent px-2 text-[11px] font-medium text-[var(--color-text-secondary)] transition-all hover:border-[var(--color-border-light)] hover:bg-white disabled:opacity-30"><ArrowDown className="h-3.5 w-3.5" /><span className="hidden 2xl:inline">下移</span></button>
              <button type="button" onClick={removeSelectedBlock} disabled={blocks.length <= 1} className="col-span-4 flex h-8 items-center justify-center gap-1.5 rounded-lg px-2 text-[11px] font-medium text-red-600 transition-all hover:bg-red-50 disabled:opacity-30 xl:col-span-2"><Trash2 className="h-3.5 w-3.5" />删除当前块</button>
            </div>
          </div>
        </aside>

        {/* Center: editing canvas */}
        <main className="min-w-0 space-y-3 xl:h-full xl:min-h-0 xl:overflow-y-auto xl:overscroll-contain xl:pb-1 xl:pr-1">
          <section className="overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[rgba(254,252,249,0.94)] shadow-[var(--shadow-card)]">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-[var(--ink)]">基础信息</p>
                <p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">保持核心字段同屏，减少上下滚动。</p>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-[var(--color-text-hint)]">
                <span>#{cardId}</span><span>·</span><span>v{savedVersion}</span><span>·</span><span>{STUDY_CARD_TYPE_LABEL[studyCardType] || studyCardType}</span><span>·</span><span>{CARD_TYPE_LABEL[cardType] || cardType}</span>
              </div>
            </div>
            <div className="grid gap-3 p-3.5 lg:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">标题 <span className="text-red-500">*</span></label>
                <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="公式标题" className="h-10" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">别名</label>
                <Input value={aliases} onChange={(event) => setAliases(event.target.value)} placeholder="多个别名使用逗号分隔" className="h-10" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">分类 <span className="text-red-500">*</span></label>
                <FormulaCategoryPicker mode="form" value={categoryId} onChange={setCategoryId} placeholder="选择速记卡分类" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">408 内容类型</label>
                <select value={studyCardType} onChange={(event) => { const next = event.target.value; setStudyCardType(next); setTemplateType(DEFAULT_TEMPLATE_BY_STUDY_TYPE[next] || "standard"); }} className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:bg-white">
                  {Object.entries(STUDY_CARD_TYPE_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">展示模板</label>
                <select value={templateType} onChange={(event) => setTemplateType(event.target.value)} className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:bg-white">
                  <option value="standard">标准卡</option>
                  <option value="memory">记忆卡</option>
                  <option value="rule">规则卡</option>
                  <option value="contrast">对比卡</option>
                  <option value="trap">陷阱卡</option>
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">渲染类型</label>
                <select value={cardType} onChange={(event) => setCardType(event.target.value)} className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:bg-white">
                  <option value="auto">自动识别</option>
                  <option value="pure_formula">纯公式</option>
                  <option value="function_graph">函数图像</option>
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">排序</label>
                <Input type="number" value={sortOrder} onChange={(event) => setSortOrder(Number(event.target.value))} className="h-11" />
              </div>
              <div className="lg:col-span-2">
                <div className="mb-1.5 flex items-center justify-between">
                  <label className="text-xs font-semibold text-[var(--color-text-secondary)]">摘要</label>
                  <span className="text-[10px] text-[var(--color-text-hint)]">{summary.length} 字</span>
                </div>
                <CompactTextarea value={summary} onChange={setSummary} placeholder="用一两句话概括这张 408 速记卡的核心内容" rows={2} />
              </div>
              <div className="lg:col-span-2 border-t border-[var(--color-border-light)] pt-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-secondary)]"><Tags className="h-3.5 w-3.5 text-[var(--color-primary)]" />关联标签</label>
                  <span className="text-[10px] text-[var(--color-text-hint)]">已选 {selectedTags.length}</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {allTags.length ? allTags.map((tag) => {
                    const active = selectedTags.includes(tag.code);
                    return (
                      <button
                        key={tag.code}
                        type="button"
                        aria-pressed={active}
                        onClick={() => toggleTag(tag.code)}
                        className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-all duration-200 motion-safe:hover:-translate-y-px ${active ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] shadow-sm" : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]/50 hover:text-[var(--ink)]"}`}
                      >
                        {tag.name}
                      </button>
                    );
                  }) : <span className="text-xs text-[var(--color-text-hint)]">{tagsQuery.isLoading ? "标签加载中…" : "暂无可用标签"}</span>}
                </div>
              </div>
            </div>
          </section>

          <section ref={blockEditorRef} className="scroll-mt-20 overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white/90 shadow-[var(--shadow-card)]">
            <div className="flex flex-wrap items-center gap-1 border-b border-[var(--color-border-light)] bg-[var(--porcelain)]/55 px-3 py-2">
              {topWorkspaceTabs.filter((tab) => tab.visible).map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  aria-pressed={workspaceTab === tab.key}
                  onClick={() => setWorkspaceTab(tab.key)}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-all duration-200 ${workspaceTab === tab.key ? "bg-white text-[var(--color-primary-dark)] shadow-sm" : "text-[var(--color-text-secondary)] hover:bg-white/60 hover:text-[var(--ink)]"}`}
                >
                  {tab.icon}{tab.label}
                </button>
              ))}
            </div>

            {workspaceTab === "block" && selectedBlock && (
              <div key={`block-${selectedBlockIndex}`} className="animate-fade-in p-3.5 lg:p-4">
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium text-[var(--color-text-hint)]">编辑当前块</p>
                    <h2 className="mt-0.5 font-display text-lg font-bold text-[var(--ink)]">{selectedBlock.label?.trim() || `公式块 ${selectedBlockIndex + 1}`}</h2>
                  </div>
                  <span className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${selectedBlock.latex.trim() ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                    {selectedBlock.latex.trim() ? "内容完整" : "待补充公式"}
                  </span>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">块标题</label>
                    <Input value={selectedBlock.label || ""} onChange={(event) => updateBlock(selectedBlockIndex, { label: event.target.value })} placeholder="例如：指数与对数" className="h-10" />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">说明</label>
                    <Input value={selectedBlock.note || ""} onChange={(event) => updateBlock(selectedBlockIndex, { note: event.target.value })} placeholder="补充适用范围或文字说明" className="h-10" />
                  </div>
                </div>

                <div className="mt-4 grid gap-4 2xl:grid-cols-[minmax(0,1.1fr)_minmax(300px,0.9fr)]">
                  <div>
                    <div className="mb-1.5 flex items-center justify-between">
                      <label className="text-xs font-semibold text-[var(--color-text-secondary)]">内容编辑（LaTeX / 文本） <span className="text-red-500">*</span></label>
                      <button type="button" onClick={() => updateBlock(selectedBlockIndex, { latex: normalizeFormulaText(selectedBlock.latex) || selectedBlock.latex })} className="inline-flex items-center gap-1 text-[10px] font-semibold text-[var(--color-primary)] hover:underline"><Sparkles className="h-3 w-3" />规范格式</button>
                    </div>
                    <CompactTextarea value={selectedBlock.latex} onChange={(value) => updateBlock(selectedBlockIndex, { latex: value })} placeholder="输入 LaTeX，例如：P(x) \\text{ 在 } \\mathbb{R} \\text{ 上连续}" rows={6} mono />
                    <p className="mt-1.5 text-[10px] text-[var(--color-text-hint)]">中文说明建议使用 \\text&#123;...&#125; 包裹；预览区会实时渲染。</p>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">实时预览</label>
                    <div className="flex min-h-[178px] items-center justify-center overflow-x-auto rounded-xl border border-dashed border-[var(--color-border)] bg-gradient-to-br from-[var(--porcelain)] to-white px-4 py-5 text-center transition-all duration-200">
                      {selectedBlock.latex.trim() ? (
                        <div className="w-full overflow-x-auto">
                          <LatexRenderer latex={normalizeLatexExpression(selectedBlock.latex)} displayMode={true} />
                          {selectedBlock.note?.trim() && (
                            <div className="mt-4 border-t border-[var(--color-border-light)] pt-3 text-left text-xs leading-5 text-[var(--color-text-secondary)]"><MixedLatexRenderer text={selectedBlock.note} /></div>
                          )}
                        </div>
                      ) : (
                        <div className="text-[var(--color-text-hint)]"><Eye className="mx-auto mb-2 h-6 w-6 opacity-40" /><p className="text-xs">输入公式后在此实时预览</p></div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {workspaceTab === "supplement" && (
              <div className="animate-fade-in grid gap-4 p-3.5 lg:grid-cols-2 lg:p-4">
                {[
                  ["适用条件", conditions, setConditions, "输入适用条件，可混排文字与 LaTeX"],
                  ["符号说明", symbolNotes, setSymbolNotes, "说明变量、符号和参数含义"],
                  ["二级结论", secondaryConclusions, setSecondaryConclusions, "补充由主公式推出的常用结论"],
                  ["易错提醒", errorTips, setErrorTips, "记录高频误区或边界条件"],
                ].map(([label, value, setter, placeholder]) => (
                  <div key={label as string}>
                    <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">{label as string}</label>
                    <CompactTextarea value={value as string} onChange={setter as (value: string) => void} placeholder={placeholder as string} rows={5} />
                    {(value as string).trim() && (
                      <div className="mt-2 rounded-xl border border-[var(--color-border-light)] bg-[var(--porcelain)]/65 px-3 py-2 text-xs leading-5 text-[var(--color-text-secondary)]"><MixedLatexRenderer text={normalizeFormulaText(value as string) || (value as string)} /></div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {workspaceTab === "examples" && (
              <div className="animate-fade-in p-3.5 lg:p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div><p className="text-sm font-semibold text-[var(--ink)]">例题与用法</p><p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">最多 {EXAMPLES_MAX} 个，保持内容精炼。</p></div>
                  <Button variant="secondary" size="sm" onClick={() => setExamples((previous) => previous.length < EXAMPLES_MAX ? [...previous, { question: "", short_solution: "", answer: "" }] : previous)} disabled={examples.length >= EXAMPLES_MAX}><Plus className="h-3.5 w-3.5" />添加例题</Button>
                </div>
                <div className="space-y-3">
                  {examples.map((example, index) => (
                    <div key={index} className="rounded-xl border border-[var(--color-border-light)] bg-[var(--porcelain)]/45 p-3.5">
                      <div className="mb-3 flex items-center justify-between"><span className="text-xs font-semibold text-[var(--ink)]">例题 {index + 1}</span><button type="button" onClick={() => setExamples((previous) => previous.filter((_, itemIndex) => itemIndex !== index))} className="rounded-lg p-1.5 text-[var(--color-text-hint)] transition hover:bg-red-50 hover:text-red-600"><Trash2 className="h-3.5 w-3.5" /></button></div>
                      <div className="grid gap-3 lg:grid-cols-2">
                        <div className="lg:col-span-2"><label className="mb-1 block text-[11px] font-semibold text-[var(--color-text-secondary)]">题目</label><CompactTextarea value={example.question} onChange={(value) => updateExample(index, { question: value })} placeholder="输入题目" rows={2} /></div>
                        <div><label className="mb-1 block text-[11px] font-semibold text-[var(--color-text-secondary)]">核心解法</label><CompactTextarea value={example.short_solution} onChange={(value) => updateExample(index, { short_solution: value })} placeholder="核心步骤" rows={3} /></div>
                        <div><label className="mb-1 block text-[11px] font-semibold text-[var(--color-text-secondary)]">答案</label><CompactTextarea value={example.answer} onChange={(value) => updateExample(index, { answer: value })} placeholder="最终答案" rows={3} /></div>
                        <div className="lg:col-span-2"><label className="mb-1 block text-[11px] font-semibold text-[var(--color-text-secondary)]">易错点</label><Input value={example.error_tip || ""} onChange={(event) => updateExample(index, { error_tip: event.target.value })} placeholder="可选" /></div>
                      </div>
                    </div>
                  ))}
                  {!examples.length && <div className="rounded-xl border border-dashed border-[var(--color-border)] px-4 py-12 text-center text-xs text-[var(--color-text-hint)]">暂无例题，可按需补充。</div>}
                </div>
              </div>
            )}

            {workspaceTab === "graph" && cardType === "function_graph" && (
              <div className="animate-fade-in p-3.5 lg:p-4">
                <div className="mb-4 flex flex-col gap-2 border-b border-[var(--color-border-light)] pb-3 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <p className="text-xs font-semibold text-[var(--color-text-secondary)]">函数图像配置</p>
                    <p className="mt-1 max-w-2xl text-[11px] leading-5 text-[var(--color-text-hint)]">
                      左侧维护函数属性，右侧直接管理小程序展示图片。图片上传采用独立保存，不必先提交整张公式卡。
                    </p>
                  </div>
                  <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-[var(--color-border-light)] bg-[var(--porcelain)] px-2.5 py-1 text-[10px] font-medium text-[var(--color-text-hint)]">
                    <ImageIcon className="h-3 w-3 text-[var(--color-primary)]" /> 图片操作即时保存
                  </span>
                </div>

                <div className="grid items-start gap-4 xl:grid-cols-[minmax(280px,0.82fr)_minmax(0,1.18fr)]">
                  <section className="min-w-0 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)]/35">
                    <div className="border-b border-[var(--color-border-light)] px-3.5 py-3">
                      <SectionLabel icon={<Settings2 className="h-3.5 w-3.5" />}>函数参数</SectionLabel>
                      <p className="-mt-1 text-[10px] leading-4 text-[var(--color-text-hint)]">用于公式卡描述、检索与图像语义，不影响右侧图片的独立保存。</p>
                    </div>
                    <div className="grid gap-3 p-3.5 md:grid-cols-2 xl:grid-cols-1">
                      <div><label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">函数表达式</label><Input value={funcExpression} onChange={(event) => setFuncExpression(event.target.value)} placeholder="f(x) = x^2" /></div>
                      <div><label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">模板类型</label><Input value={funcTemplate} onChange={(event) => setFuncTemplate(event.target.value)} placeholder="quadratic / sine / logarithmic" /></div>
                      <div><label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">定义域</label><Input value={funcDomain} onChange={(event) => setFuncDomain(event.target.value)} placeholder="(-\\infty,+\\infty)" /></div>
                      <div><label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">值域</label><Input value={funcRange} onChange={(event) => setFuncRange(event.target.value)} placeholder="[0,+\\infty)" /></div>
                      <div><label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">奇偶性</label><Input value={funcParity} onChange={(event) => setFuncParity(event.target.value)} placeholder="偶函数 / 奇函数" /></div>
                      <div><label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">周期</label><Input value={funcPeriod} onChange={(event) => setFuncPeriod(event.target.value)} placeholder="T = 2\\pi" /></div>
                      <div className="md:col-span-2 xl:col-span-1"><label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">导数与临界点</label><CompactTextarea value={funcDerivative} onChange={setFuncDerivative} placeholder="导数、临界点和单调性摘要" rows={3} /></div>
                      <div className="md:col-span-2 xl:col-span-1"><label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">一行特征</label><CompactTextarea value={funcFeature} onChange={setFuncFeature} placeholder="用于卡片快速说明图像特征" rows={2} /></div>
                    </div>
                  </section>

                  <div className="min-w-0 xl:sticky xl:top-0">
                    <FormulaGraphAssetPanel cardId={cardId} canUpdate={true} />
                  </div>
                </div>
              </div>
            )}
          </section>

        </main>

        {/* Right: properties / preview */}
        <aside ref={previewRailRef} className="min-h-0 scroll-mt-20 xl:h-full">
          <div className="overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[rgba(254,252,249,0.94)] shadow-[var(--shadow-floating)] xl:flex xl:h-full xl:min-h-0 xl:flex-col">
            <div className="shrink-0 grid grid-cols-2 gap-1 border-b border-[var(--color-border-light)] bg-[var(--porcelain)]/55 p-1.5">
              <button type="button" aria-pressed={railTab === "properties"} onClick={() => setRailTab("properties")} className={`rounded-lg px-3 py-2 text-xs font-semibold transition-all ${railTab === "properties" ? "bg-white text-[var(--color-primary-dark)] shadow-sm" : "text-[var(--color-text-secondary)] hover:bg-white/60"}`}>属性</button>
              <button type="button" aria-pressed={railTab === "preview"} onClick={() => setRailTab("preview")} className={`rounded-lg px-3 py-2 text-xs font-semibold transition-all ${railTab === "preview" ? "bg-white text-[var(--color-primary-dark)] shadow-sm" : "text-[var(--color-text-secondary)] hover:bg-white/60"}`}>预览</button>
            </div>

            {railTab === "properties" ? (
              <div className="formula-editor-rail-scroll space-y-0 overflow-y-auto animate-fade-in xl:min-h-0 xl:flex-1">
                <div className="border-b border-[var(--color-border-light)] p-4">
                  <SectionLabel icon={<Settings2 className="h-3.5 w-3.5" />}>发布状态</SectionLabel>
                  <div className="space-y-2 text-xs">
                    <div className="flex items-center justify-between gap-3"><span className="text-[var(--color-text-hint)]">状态</span><span className={`rounded-full border px-2 py-0.5 font-semibold ${STATUS_BADGE[initialData.status] || STATUS_BADGE.draft}`}>{STATUS_LABEL[initialData.status] || initialData.status}</span></div>
                    <div className="flex items-start justify-between gap-3"><span className="shrink-0 text-[var(--color-text-hint)]">分类</span><span className="text-right font-medium leading-5 text-[var(--ink)]">{categoryLabel}</span></div>
                    <div className="flex items-center justify-between gap-3"><span className="text-[var(--color-text-hint)]">内容类型</span><span className="font-medium text-[var(--ink)]">{STUDY_CARD_TYPE_LABEL[studyCardType] || studyCardType}</span></div>
                    <div className="flex items-center justify-between gap-3"><span className="text-[var(--color-text-hint)]">模板</span><span className="font-medium text-[var(--ink)]">{templateType}</span></div>
                  </div>
                </div>

                <div className="border-b border-[var(--color-border-light)] p-4">
                  <SectionLabel icon={<FileText className="h-3.5 w-3.5" />}>元数据</SectionLabel>
                  <div className="space-y-2 text-xs">
                    <div className="flex items-center justify-between"><span className="text-[var(--color-text-hint)]">公式 ID</span><span className="font-mono text-[var(--ink)]">#{cardId}</span></div>
                    <div className="flex items-center justify-between"><span className="text-[var(--color-text-hint)]">版本</span><span className="font-medium text-[var(--ink)]">v{savedVersion}</span></div>
                    <div className="flex items-start justify-between gap-3"><span className="text-[var(--color-text-hint)]">更新时间</span><span className="text-right font-medium text-[var(--ink)]">{formatDateTime(savedUpdatedAt)}</span></div>
                    <div className="flex items-start justify-between gap-3"><span className="text-[var(--color-text-hint)]">发布时间</span><span className="text-right font-medium text-[var(--ink)]">{formatDateTime(initialData.publishedAt)}</span></div>
                    <div className="flex items-start justify-between gap-3"><span className="text-[var(--color-text-hint)]">创建时间</span><span className="text-right font-medium text-[var(--ink)]">{formatDateTime(initialData.createdAt)}</span></div>
                    <div className="flex items-center justify-between"><span className="text-[var(--color-text-hint)]">最后编辑者</span><span className="font-medium text-[var(--ink)]">{savedUpdatedBy ? `管理员 #${savedUpdatedBy}` : "—"}</span></div>
                  </div>
                </div>

                <div className="border-b border-[var(--color-border-light)] p-4">
                  <SectionLabel icon={<History className="h-3.5 w-3.5" />}>版本记录</SectionLabel>
                  <div className="space-y-2.5">
                    {versionsQuery.data?.items?.slice(0, 4).map((version, index) => (
                      <div key={version.id} className="flex items-start gap-2.5 text-xs">
                        <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${index === 0 ? "bg-emerald-500" : "bg-[var(--color-border)]"}`} />
                        <div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-2"><span className="font-semibold text-[var(--ink)]">v{version.version}</span><span className="text-[10px] text-[var(--color-text-hint)]">{VERSION_ACTION_LABEL[version.action] || version.action}</span></div><p className="mt-0.5 truncate text-[10px] text-[var(--color-text-hint)]">{formatDateTime(version.created_at)}</p></div>
                      </div>
                    ))}
                    {!versionsQuery.data?.items?.length && <p className="text-xs text-[var(--color-text-hint)]">暂无版本记录</p>}
                  </div>
                </div>

                <div className="p-4">
                  <SectionLabel icon={<ListChecks className="h-3.5 w-3.5" />}>保存前检查</SectionLabel>
                  <div className="space-y-2">
                    {requiredChecks.map((item) => (
                      <div key={item.label} className="flex items-center gap-2 text-xs">
                        {item.done ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Circle className="h-4 w-4 text-amber-500" />}
                        <span className={item.done ? "text-[var(--color-text-secondary)]" : "font-medium text-[var(--ink)]"}>{item.label}</span>
                      </div>
                    ))}
                  </div>
                  <div className={`mt-4 rounded-xl border px-3 py-2.5 text-xs ${isDirty ? "border-amber-200 bg-amber-50 text-amber-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
                    <p className="font-semibold">{isDirty ? "存在未保存修改" : "当前修改已保存"}</p>
                    <p className="mt-1 opacity-80">可使用 Ctrl / ⌘ + S 快速保存。</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="formula-editor-rail-scroll overflow-y-auto p-4 animate-fade-in xl:min-h-0 xl:flex-1">
                <div className="mb-4">
                  <p className="font-display text-lg font-bold leading-7 text-[var(--ink)]"><MixedLatexRenderer text={title || "公式标题"} /></p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${STATUS_BADGE[initialData.status] || STATUS_BADGE.draft}`}>{STATUS_LABEL[initialData.status] || initialData.status}</span>
                    {selectedTags.map((code) => {
                      const tag = allTags.find((item) => item.code === code);
                      return <span key={code} className="rounded-full bg-[var(--color-primary-light)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-primary-dark)]">{tag?.name || code}</span>;
                    })}
                  </div>
                </div>

                {summary.trim() && <div className="mb-4 rounded-xl bg-[var(--porcelain)] px-3 py-2.5 text-xs leading-5 text-[var(--color-text-secondary)]"><MixedLatexRenderer text={summary} /></div>}

                <div className="space-y-2.5">
                  {blocks.map((block, index) => ({ block, index })).filter(({ block }) => block.latex.trim()).map(({ block, index }) => (
                    <div
                      key={index}
                      role="button"
                      tabIndex={0}
                      onClick={() => selectBlock(index)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          selectBlock(index);
                        }
                      }}
                      className={`w-full cursor-pointer rounded-xl border bg-white px-3 py-3 text-left transition-all duration-200 motion-safe:hover:-translate-y-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]/35 ${index === selectedBlockIndex ? "border-[var(--color-primary)] shadow-sm" : "border-[var(--color-border-light)] hover:border-[var(--color-primary)]/45 hover:shadow-sm"}`}
                    >
                      {block.label?.trim() && <p className="mb-2 text-[10px] font-semibold text-[var(--color-text-hint)]">{block.label}</p>}
                      <div className="overflow-x-auto text-center"><LatexRenderer latex={normalizeLatexExpression(block.latex)} displayMode={true} /></div>
                      {block.note?.trim() && <div className="mt-2 border-t border-[var(--color-border-light)] pt-2 text-[10px] leading-5 text-[var(--color-text-secondary)]"><MixedLatexRenderer text={block.note} /></div>}
                    </div>
                  ))}
                  {!blocks.some((block) => block.latex.trim()) && <div className="rounded-xl border border-dashed border-[var(--color-border)] px-3 py-10 text-center text-xs text-[var(--color-text-hint)]">公式预览将在这里显示</div>}
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--color-border)] bg-[rgba(254,252,249,0.95)] px-4 py-3 shadow-[0_-8px_28px_rgba(27,39,51,0.08)] backdrop-blur-xl xl:hidden">
        <div className="mx-auto flex max-w-[1720px] items-center gap-2">
          <Button variant="secondary" className="flex-1" onClick={openPreview}><Eye className="h-4 w-4" />预览</Button>
          <Button className="flex-[1.4]" onClick={handleSave} disabled={saveMutation.isPending || !isDirty}><Save className="h-4 w-4" />{saveMutation.isPending ? "保存中…" : isDirty ? "保存修改" : "已保存"}</Button>
        </div>
      </div>
    </div>
  );
}
