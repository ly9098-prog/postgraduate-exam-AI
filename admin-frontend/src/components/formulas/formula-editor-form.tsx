"use client";

import { useState, useMemo, useCallback, useRef } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Plus, Save, X, Trash2, ArrowLeft, ChevronDown, ChevronRight } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { LatexRenderer } from "@/components/ui/latex-renderer";
import { MixedLatexRenderer } from "@/components/ui/mixed-latex-renderer";
import { FormulaCategoryPicker } from "@/components/formulas/formula-category-picker";
import { apiRequest } from "@/lib/api/client";
import { normalizeFormulaText } from "@/lib/formula-normalize";

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

/* ── FormulaBlockEditor ── */

function FormulaBlockEditor({
  block,
  index,
  onChange,
  onRemove,
  canRemove,
}: {
  block: FormulaBlock;
  index: number;
  onChange: (field: keyof FormulaBlock, value: string) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-[var(--color-text-hint)]">
          公式块 #{index + 1}
        </span>
        {canRemove && (
          <button onClick={onRemove} className="text-red-400 hover:text-red-600 transition-colors" aria-label="删除公式块">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <div className="grid gap-3">
        <Input
          value={block.label || ""}
          onChange={(e) => onChange("label", e.target.value)}
          placeholder="标题（可选）例如：第一个重要极限"
        />
        <div className="grid gap-2">
          <textarea
            className="min-h-20 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 font-mono text-sm outline-none focus:border-[var(--color-primary)]"
            value={block.latex}
            onChange={(e) => onChange("latex", e.target.value)}
            placeholder="LaTeX 公式..."
          />
          {block.latex.trim() && (
            <div className="rounded-lg border border-[var(--color-border)]/60 bg-[var(--porcelain)] p-3">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">
                预览
              </p>
              <LatexRenderer latex={block.latex} displayMode={true} />
            </div>
          )}
        </div>
        <Input
          value={block.note || ""}
          onChange={(e) => onChange("note", e.target.value)}
          placeholder="注释说明（可选）"
        />
      </div>
    </div>
  );
}

/* ── FormulaEditorForm ── */

export function FormulaEditorForm({ mode, cardId, initialData, onSaveSuccess }: Props) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [messageType, setMessageType] = useState<"success" | "error">("success");

  // Collapsible sections
  const [showSupplement, setShowSupplement] = useState(false);
  const [showExamples, setShowExamples] = useState(false);

  // Form state
  const [categoryId, setCategoryId] = useState<number | null>(initialData?.categoryId ?? null);
  const [categoryError, setCategoryError] = useState("");
  const [title, setTitle] = useState(initialData?.title ?? "");
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
  const [functionProperties, setFunctionProperties] = useState<Record<string, unknown> | null>(
    initialData?.functionProperties ?? null,
  );

  // Refs for post-save LaTeX verification
  const sentConditionsRef = useRef<string | null>(null);
  const sentErrorTipsRef = useRef<string | null>(null);

  // Load tags
  const tags = useQuery({
    queryKey: ["admin-formula-tags"],
    queryFn: () => apiRequest<{ items: TagOption[] }>("/formulas/tags"),
    staleTime: 60000,
  });
  const tagMap = useMemo(() => {
    const m: Record<string, number> = {};
    tags.data?.items?.forEach((t) => { m[t.code] = t.id; });
    return m;
  }, [tags.data]);

  // Block handlers
  const updateBlock = useCallback((i: number, field: keyof FormulaBlock, value: string) => {
    setBlocks((prev) => prev.map((b, idx) => (idx === i ? { ...b, [field]: value } : b)));
  }, []);
  const addBlock = useCallback(() => {
    if (blocks.length < BLOCKS_MAX) setBlocks((prev) => [...prev, { latex: "" }]);
  }, [blocks.length]);
  const removeBlock = useCallback((i: number) => {
    if (blocks.length > 1) setBlocks((prev) => prev.filter((_, idx) => idx !== i));
  }, [blocks.length]);

  // Example handlers
  const addExample = useCallback(() => {
    if (examples.length < EXAMPLES_MAX) {
      setExamples((prev) => [...prev, { question: "", short_solution: "", answer: "" }]);
      setShowExamples(true);
    }
  }, [examples.length]);
  const updateExample = useCallback((i: number, field: keyof FormulaExample, value: string) => {
    setExamples((prev) => prev.map((ex, idx) => (idx === i ? { ...ex, [field]: value } : ex)));
  }, []);
  const removeExample = useCallback((i: number) => {
    setExamples((prev) => prev.filter((_, idx) => idx !== i));
  }, []);

  // Tag toggle
  const toggleTag = useCallback((code: string) => {
    setSelectedTags((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
    );
  }, []);

  // Save / Create
  const createMutation = useMutation({
    mutationFn: async () => {
      if (!categoryId) { setCategoryError("请选择分类"); throw new Error("请选择分类"); }
      if (!title.trim()) throw new Error("请填写标题");
      const validBlocks = blocks.filter((b) => b.latex.trim());
      if (validBlocks.length < 1) throw new Error("至少需要一个公式块（需填写 LaTeX）");

      const tagIds = selectedTags.map((code) => tagMap[code]).filter(Boolean);
      const aliasesList = aliases.split(/[,，、\s]+/).filter(Boolean);

      // Normalise conditions and errorTips before sending
      const normalizedConditions = normalizeFormulaText(conditions.trim()) || null;
      const normalizedErrorTips = normalizeFormulaText(errorTips.trim()) || null;
      sentConditionsRef.current = normalizedConditions;
      sentErrorTipsRef.current = normalizedErrorTips;

      const body: Record<string, unknown> = {
        category_id: categoryId,
        title: title.trim(),
        aliases: aliasesList.length > 0 ? aliasesList : null,
        search_text: aliasesList.length > 0 ? aliasesList.join(" ") : null,
        card_type: cardType,
        function_properties: cardType === "function_graph" ? (functionProperties ?? {}) : null,
        summary: summary.trim() || null,
        formula_blocks: validBlocks.map((b) => ({
          label: b.label || null,
          latex: b.latex.trim(),
          note: b.note || null,
        })),
        conditions: normalizedConditions,
        symbol_notes: symbolNotes.trim() || null,
        error_tips: normalizedErrorTips,
        examples: examples.length > 0 ? examples.map((ex) => ({
          question: ex.question,
          short_solution: ex.short_solution,
          answer: ex.answer,
          error_tip: ex.error_tip || null,
        })) : null,
        tag_ids: tagIds,
        source_type: "manual",
      };
      if (mode === "edit" && cardId) {
        body.sort_order = sortOrder;
        return apiRequest(`/formulas/${cardId}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
      }
      return apiRequest("/formulas", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: async () => {
      setMessageType("success");
      setMessage(mode === "create" ? "创建成功！" : "保存成功！");

      if (onSaveSuccess) onSaveSuccess();

      // Post-save verification: re-read and check LaTeX integrity
      if (mode === "edit" && cardId) {
        try {
          const detail = await apiRequest<{ conditions?: string; error_tips?: string }>(`/formulas/${cardId}`);
          const rc = detail.conditions ?? null;
          const re = detail.error_tips ?? null;
          if (rc !== sentConditionsRef.current || re !== sentErrorTipsRef.current) {
            console.warn("[formula-normalize] Save verification mismatch:", {
              sent: { conditions: sentConditionsRef.current, errorTips: sentErrorTipsRef.current },
              received: { conditions: rc, errorTips: re },
            });
            setMessageType("error");
            setMessage("保存成功，但接口返回的 LaTeX 内容不一致。请检查反斜杠是否丢失或重复转义。");
          }
        } catch (err) {
          console.warn("[formula-normalize] Post-save verification fetch failed", err);
        }
      }

      if (!onSaveSuccess) setTimeout(() => router.push("/formulas"), 1000);
    },
    onError: (e) => {
      setMessageType("error");
      setMessage(e instanceof Error ? e.message : (mode === "create" ? "创建失败" : "保存失败"));
    },
  });

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
            className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition ${
              active
                ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                : "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]"
            }`}
          >
            {active && <Check className="h-3 w-3" />}
            {TAG_NAMES[code]}
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="space-y-6 pb-24">
      {/* Sticky Top Bar */}
      <div className="sticky top-0 z-30 -mx-6 -mt-6 bg-white/90 backdrop-blur-md border-b border-[var(--color-border)] px-6 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="sm" onClick={() => router.push("/formulas")}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <h3 className="font-display text-xl font-bold text-[var(--ink)]">
                {mode === "create" ? "新建公式" : "编辑公式"}
              </h3>
              {mode === "edit" && cardId && (
                <p className="text-xs text-[var(--color-text-hint)]">#{cardId}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => router.push("/formulas")}>
              <X className="h-4 w-4" /> 取消
            </Button>
            <Button onClick={() => createMutation.mutate()} disabled={isPending}>
              <Save className="h-4 w-4" />
              {isPending ? "保存中..." : mode === "create" ? "保存草稿" : "保存"}
            </Button>
          </div>
        </div>
      </div>

      {/* Message */}
      {message ? (
        <div className={`rounded-2xl border px-4 py-3 text-sm font-medium ${
          messageType === "success"
            ? "border-[var(--color-success)] bg-[var(--color-success-light)]"
            : "border-red-200 bg-red-50"
        }`}>
          {message}
          <button className="ml-3" onClick={() => setMessage(null)}>✕</button>
        </div>
      ) : null}

      {/* Two-Column Layout */}
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">

        {/* ── Left Column: Main Content ── */}
        <div className="space-y-6 min-w-0">

          {/* Formula Blocks */}
          <section className="rounded-xl border border-[var(--color-border)] bg-white/60 p-4 lg:p-5">
            <div className="flex items-center justify-between mb-4">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">
                公式块 *（{blocks.length}/{BLOCKS_MAX}）
              </label>
              {blocks.length < BLOCKS_MAX && (
                <Button variant="secondary" size="sm" onClick={addBlock}>
                  <Plus className="h-3 w-3" /> 添加公式块
                </Button>
              )}
            </div>
            <div className="space-y-4">
              {blocks.map((block, i) => (
                <FormulaBlockEditor
                  key={i}
                  block={block}
                  index={i}
                  onChange={(field, value) => updateBlock(i, field, value)}
                  onRemove={() => removeBlock(i)}
                  canRemove={blocks.length > 1}
                />
              ))}
            </div>
          </section>

          {/* Collapsible: Supplement (conditions, symbols, tips) */}
          <section className="rounded-xl border border-[var(--color-border)] bg-white/60 overflow-hidden">
            <button
              type="button"
              onClick={() => setShowSupplement(!showSupplement)}
              className="flex w-full items-center justify-between px-4 py-3 lg:px-5 text-sm font-semibold text-[var(--ink)] hover:bg-white/50 transition-colors"
            >
              <span>补充说明</span>
              {showSupplement ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
            {showSupplement && (
              <div className="space-y-4 px-4 pb-4 lg:px-5">
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-[var(--color-text-secondary)]">适用条件</label>
                    <button
                      type="button"
                      onClick={() => setConditions(normalizeFormulaText(conditions) ?? '')}
                      className="text-xs text-[var(--color-primary)] hover:underline"
                    >Σ LaTeX</button>
                  </div>
                  <textarea
                    className="min-h-16 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm outline-none focus:border-[var(--color-primary)]"
                    value={conditions}
                    onChange={(e) => setConditions(e.target.value)}
                    placeholder="公式的适用条件..."
                  />
                  {conditions.trim() && (
                    <div className="rounded-lg border border-[var(--color-border)]/60 bg-[var(--porcelain)] p-3 text-sm whitespace-pre-wrap break-words max-w-full overflow-x-auto">
                      <MixedLatexRenderer text={conditions} />
                    </div>
                  )}
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-[var(--color-text-secondary)]">符号说明</label>
                    <button
                      type="button"
                      onClick={() => setSymbolNotes(normalizeFormulaText(symbolNotes) ?? '')}
                      className="text-xs text-[var(--color-primary)] hover:underline"
                    >Σ LaTeX</button>
                  </div>
                  <textarea
                    className="min-h-16 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm outline-none focus:border-[var(--color-primary)]"
                    value={symbolNotes}
                    onChange={(e) => setSymbolNotes(e.target.value)}
                    placeholder="符号的含义..."
                  />
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-[var(--color-text-secondary)]">易错提醒</label>
                    <button
                      type="button"
                      onClick={() => setErrorTips(normalizeFormulaText(errorTips) ?? '')}
                      className="text-xs text-[var(--color-primary)] hover:underline"
                    >Σ LaTeX</button>
                  </div>
                  <textarea
                    className="min-h-16 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm outline-none focus:border-[var(--color-primary)]"
                    value={errorTips}
                    onChange={(e) => setErrorTips(e.target.value)}
                    placeholder="常见的易错点..."
                  />
                  {errorTips.trim() && (
                    <div className="rounded-lg border border-[var(--color-border)]/60 bg-[var(--porcelain)] p-3 text-sm whitespace-pre-wrap break-words max-w-full overflow-x-auto">
                      <MixedLatexRenderer text={errorTips} />
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>

          {/* Collapsible: Examples */}
          <section className="rounded-xl border border-[var(--color-border)] bg-white/60 overflow-hidden">
            <button
              type="button"
              onClick={() => setShowExamples(!showExamples)}
              className="flex w-full items-center justify-between px-4 py-3 lg:px-5 text-sm font-semibold text-[var(--ink)] hover:bg-white/50 transition-colors"
            >
              <span>典型例题（{examples.length}/{EXAMPLES_MAX}）</span>
              <div className="flex items-center gap-2">
                {examples.length < EXAMPLES_MAX && (
                  <span
                    onClick={(e) => { e.stopPropagation(); addExample(); }}
                    className="flex h-6 w-6 items-center justify-center rounded hover:bg-[var(--color-bg-input)]"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </span>
                )}
                {showExamples ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              </div>
            </button>
            {showExamples && (
              <div className="space-y-3 px-4 pb-4 lg:px-5">
                {examples.length === 0 ? (
                  <p className="text-xs text-[var(--color-text-hint)] py-2">暂无例题，点击上方 + 添加</p>
                ) : (
                  examples.map((ex, i) => (
                    <div key={i} className="rounded-xl border border-[var(--color-border)] bg-white p-3 shadow-sm">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-semibold text-[var(--color-text-hint)]">例题 #{i + 1}</span>
                        <button onClick={() => removeExample(i)} className="text-red-400 hover:text-red-600" aria-label="删除例题">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="grid gap-2">
                        <Input value={ex.question} onChange={(e) => updateExample(i, "question", e.target.value)} placeholder="题目" />
                        <Input value={ex.short_solution} onChange={(e) => updateExample(i, "short_solution", e.target.value)} placeholder="解法" />
                        <Input value={ex.answer} onChange={(e) => updateExample(i, "answer", e.target.value)} placeholder="答案" />
                        <Input value={ex.error_tip || ""} onChange={(e) => updateExample(i, "error_tip", e.target.value)} placeholder="易错点（可选）" />
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </section>
        </div>

        {/* ── Right Column: Sidebar Info ── */}
        <div className="space-y-5 lg:sticky lg:top-24 lg:self-start">
          <div className="rounded-xl border border-[var(--color-border)] bg-white/70 p-4 space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">分类 *</label>
              <FormulaCategoryPicker
                mode="form"
                value={categoryId}
                onChange={(v) => { setCategoryId(v); setCategoryError(""); }}
                placeholder="选择公式分组"
                error={categoryError}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">卡片类型</label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setCardType("pure_formula")}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition ${
                    cardType === "pure_formula"
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                      : "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]"
                  }`}
                >
                  纯公式
                </button>
                <button
                  type="button"
                  onClick={() => setCardType("function_graph")}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition ${
                    cardType === "function_graph"
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                      : "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]"
                  }`}
                >
                  函数图像
                </button>
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">标题 *</label>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：两个重要极限" />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">别名 / 关键词</label>
              <Input value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="逗号分隔" />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">标签</label>
              {tagButtons}
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">摘要</label>
              <textarea
                className="min-h-[4rem] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm outline-none focus:border-[var(--color-primary)]"
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                placeholder="公式的简要说明..."
              />
            </div>

            {cardType === "function_graph" && (
              <div className="space-y-3 rounded-lg border border-[var(--color-primary-light)] bg-[var(--porcelain)] p-3">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">函数图像配置</label>
                {functionProperties ? (
                  <div className="space-y-2 text-xs text-[var(--color-text-secondary)]">
                    {!!functionProperties.function_expression && (
                      <p><span className="font-semibold">表达式：</span>{String(functionProperties.function_expression)}</p>
                    )}
                    {!!functionProperties.graph_template_type && (
                      <p><span className="font-semibold">模板类型：</span>{String(functionProperties.graph_template_type)}</p>
                    )}
                    {!!functionProperties.graph_render_mode && (
                      <p><span className="font-semibold">渲染模式：</span>{String(functionProperties.graph_render_mode)}</p>
                    )}
                    {!!functionProperties.domain && (
                      <p><span className="font-semibold">定义域：</span>{JSON.stringify(functionProperties.domain)}</p>
                    )}
                    {!!functionProperties.range && (
                      <p><span className="font-semibold">值域：</span>{JSON.stringify(functionProperties.range)}</p>
                    )}
                    {!!functionProperties.parity && (
                      <p><span className="font-semibold">奇偶性：</span>{String(functionProperties.parity)}</p>
                    )}
                    {!!functionProperties.period && (
                      <p><span className="font-semibold">周期：</span>{String(functionProperties.period)}</p>
                    )}
                    {!!functionProperties.derivative_summary && (
                      <p><span className="font-semibold">导数：</span>{String(functionProperties.derivative_summary)}</p>
                    )}
                    {!!functionProperties.one_line_feature && (
                      <p><span className="font-semibold">特征：</span>{String(functionProperties.one_line_feature)}</p>
                    )}
                    <details className="mt-2">
                      <summary className="cursor-pointer text-[11px] text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]">原始配置 JSON</summary>
                      <pre className="mt-1 max-h-40 overflow-auto rounded bg-white/80 p-2 font-mono text-[10px]">
                        {JSON.stringify(functionProperties, null, 2)}
                      </pre>
                    </details>
                  </div>
                ) : (
                  <p className="text-xs text-[var(--color-text-hint)]">尚未设置函数属性</p>
                )}
              </div>
            )}

            {mode === "edit" && (
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-[var(--color-text-secondary)]">排序</label>
                <Input type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Check({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}
