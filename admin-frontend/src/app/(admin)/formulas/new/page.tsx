"use client";

import { useState, useMemo } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Plus, Save, X, Trash2, ArrowLeft } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { apiRequest, toQuery } from "@/lib/api/client";
import Link from "next/link";

type FormulaCategory = {
  id: number;
  parent_id: number | null;
  code: string;
  name: string;
  node_type: string;
  children: FormulaCategory[];
};

type TagOption = { id: number; code: string; name: string };

type FormulaBlock = { label: string; latex: string; note: string };
type FormulaExample = { question: string; short_solution: string; answer: string; error_tip: string };

const TAG_CODES = ["basic", "high_frequency", "error_prone", "must_memorize"];
const TAG_NAMES: Record<string, string> = {
  basic: "基础",
  high_frequency: "高频",
  error_prone: "易错",
  must_memorize: "必背",
};

function flattenCats(cats: FormulaCategory[], depth = 0): Array<{ id: number; label: string; depth: number }> {
  const result: Array<{ id: number; label: string; depth: number }> = [];
  for (const cat of cats) {
    result.push({ id: cat.id, label: "  ".repeat(depth) + cat.name, depth });
    if (cat.children?.length) result.push(...flattenCats(cat.children, depth + 1));
  }
  return result;
}

export default function NewFormulaPage() {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Form state
  const [categoryId, setCategoryId] = useState("");
  const [title, setTitle] = useState("");
  const [aliases, setAliases] = useState("");
  const [summary, setSummary] = useState("");
  const [conditions, setConditions] = useState("");
  const [symbolNotes, setSymbolNotes] = useState("");
  const [errorTips, setErrorTips] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  // Formula blocks
  const [blocks, setBlocks] = useState<FormulaBlock[]>([
    { label: "", latex: "", note: "" },
  ]);

  // Examples
  const [examples, setExamples] = useState<FormulaExample[]>([]);

  // Load categories
  const categories = useQuery({
    queryKey: ["admin-formula-categories"],
    queryFn: () => apiRequest<{ items: FormulaCategory[] }>("/formulas/categories"),
    staleTime: 60000,
  });
  const flatCats = useMemo(() => flattenCats(categories.data?.items ?? []), [categories.data]);

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

  const toggleTag = (code: string) => {
    setSelectedTags((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
    );
  };

  const updateBlock = (i: number, field: keyof FormulaBlock, value: string) => {
    setBlocks((prev) => prev.map((b, idx) => (idx === i ? { ...b, [field]: value } : b)));
  };

  const addBlock = () => setBlocks((prev) => [...prev, { label: "", latex: "", note: "" }]);
  const removeBlock = (i: number) => {
    if (blocks.length <= 1) return;
    setBlocks((prev) => prev.filter((_, idx) => idx !== i));
  };

  const addExample = () => {
    if (examples.length >= 3) return;
    setExamples((prev) => [...prev, { question: "", short_solution: "", answer: "", error_tip: "" }]);
  };
  const updateExample = (i: number, field: keyof FormulaExample, value: string) => {
    setExamples((prev) => prev.map((ex, idx) => (idx === i ? { ...ex, [field]: value } : ex)));
  };
  const removeExample = (i: number) => setExamples((prev) => prev.filter((_, idx) => idx !== i));

  // Save
  const createMutation = useMutation({
    mutationFn: async () => {
      const catId = parseInt(categoryId, 10);
      if (!catId || !title.trim()) throw new Error("请填写分类和标题");

      const validBlocks = blocks.filter((b) => b.latex.trim());
      if (validBlocks.length < 1) throw new Error("至少需要一个公式块（需填写 LaTeX）");

      const tagIds = selectedTags.map((code) => tagMap[code]).filter(Boolean);
      const aliasesList = aliases.split(/[,，、\s]+/).filter(Boolean);

      return apiRequest("/formulas", {
        method: "POST",
        body: JSON.stringify({
          category_id: catId,
          title: title.trim(),
          aliases: aliasesList.length > 0 ? aliasesList : null,
          search_text: aliasesList.length > 0 ? aliasesList.join(" ") : null,
          summary: summary.trim() || null,
          formula_blocks: validBlocks.map((b) => ({
            label: b.label || null,
            latex: b.latex.trim(),
            note: b.note || null,
          })),
          conditions: conditions.trim() || null,
          symbol_notes: symbolNotes.trim() || null,
          error_tips: errorTips.trim() || null,
          examples: examples.length > 0 ? examples.map((ex) => ({
            question: ex.question,
            short_solution: ex.short_solution,
            answer: ex.answer,
            error_tip: ex.error_tip || null,
          })) : null,
          tag_ids: tagIds,
          source_type: "manual",
        }),
      });
    },
    onSuccess: (result: unknown) => {
      const card = result as { id?: number };
      setMessage("创建成功！");
      setTimeout(() => router.push(`/formulas`), 1000);
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "创建失败"),
  });

  return (
    <div className="space-y-6 pb-24">
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link href="/formulas">
                <Button variant="ghost" size="sm">
                  <ArrowLeft className="h-4 w-4" />
                </Button>
              </Link>
              <div>
                <h3 className="font-display text-2xl font-bold text-[var(--ink)]">新建公式</h3>
                <p className="mt-1 text-sm text-[var(--color-text-secondary)]">填写以下信息创建公式卡片</p>
              </div>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {message ? (
            <div className="rounded-2xl border border-[var(--color-success)] bg-[var(--color-success-light)] px-4 py-3 text-sm font-medium">
              {message}
            </div>
          ) : null}

          {/* Category */}
          <section className="space-y-2">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">分类 *</label>
            <select
              className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
            >
              <option value="">选择分类</option>
              {flatCats.filter((c) => c.depth === 2).map((c) => (
                <option key={c.id} value={c.id}>{c.label}</option>
              ))}
            </select>
          </section>

          {/* Title */}
          <section className="space-y-2">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">标题 *</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：两个重要极限" />
          </section>

          {/* Aliases */}
          <section className="space-y-2">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">别名 / 关键词</label>
            <Input value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="逗号分隔，例如：重要极限, sinx/x极限" />
          </section>

          {/* Summary */}
          <section className="space-y-2">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">摘要</label>
            <textarea
              className="min-h-16 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="公式的简要说明..."
            />
          </section>

          {/* Tags */}
          <section className="space-y-2">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">标签</label>
            <div className="flex flex-wrap gap-2">
              {TAG_CODES.map((code) => (
                <button
                  key={code}
                  type="button"
                  onClick={() => toggleTag(code)}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition ${
                    selectedTags.includes(code)
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                      : "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]"
                  }`}
                >
                  {selectedTags.includes(code) && <Check className="h-3 w-3" />}
                  {TAG_NAMES[code]}
                </button>
              ))}
            </div>
          </section>

          {/* Formula Blocks */}
          <section className="space-y-3 rounded-xl border border-[var(--color-border)] bg-white/60 p-4">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">公式块 *（1～8）</label>
              {blocks.length < 8 && (
                <Button variant="secondary" size="sm" onClick={addBlock}>
                  <Plus className="h-3 w-3" /> 添加公式块
                </Button>
              )}
            </div>
            {blocks.map((block, i) => (
              <div key={i} className="rounded-xl border border-[var(--color-border)] bg-white p-3 shadow-sm">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-[var(--color-text-hint)]">公式块 #{i + 1}</span>
                  {blocks.length > 1 && (
                    <button onClick={() => removeBlock(i)} className="text-red-500 hover:text-red-700">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <div className="grid gap-2">
                  <Input
                    value={block.label}
                    onChange={(e) => updateBlock(i, "label", e.target.value)}
                    placeholder="标题（可选）例如：第一个重要极限"
                  />
                  <textarea
                    className="min-h-16 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 font-mono text-sm"
                    value={block.latex}
                    onChange={(e) => updateBlock(i, "latex", e.target.value)}
                    placeholder="LaTeX 公式..."
                  />
                  <Input
                    value={block.note}
                    onChange={(e) => updateBlock(i, "note", e.target.value)}
                    placeholder="注释说明（可选）"
                  />
                </div>
              </div>
            ))}
          </section>

          {/* Conditions */}
          <section className="space-y-2">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">适用条件</label>
            <textarea
              className="min-h-16 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm"
              value={conditions}
              onChange={(e) => setConditions(e.target.value)}
              placeholder="公式的适用条件..."
            />
          </section>

          {/* Symbol Notes */}
          <section className="space-y-2">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">符号说明</label>
            <textarea
              className="min-h-16 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm"
              value={symbolNotes}
              onChange={(e) => setSymbolNotes(e.target.value)}
              placeholder="符号的含义..."
            />
          </section>

          {/* Error Tips */}
          <section className="space-y-2">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">易错提醒</label>
            <textarea
              className="min-h-16 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm"
              value={errorTips}
              onChange={(e) => setErrorTips(e.target.value)}
              placeholder="常见的易错点..."
            />
          </section>

          {/* Examples */}
          <section className="space-y-3 rounded-xl border border-[var(--color-border)] bg-white/60 p-4">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">例题（最多 3 个）</label>
              {examples.length < 3 && (
                <Button variant="secondary" size="sm" onClick={addExample}>
                  <Plus className="h-3 w-3" /> 添加例题
                </Button>
              )}
            </div>
            {examples.map((ex, i) => (
              <div key={i} className="rounded-xl border border-[var(--color-border)] bg-white p-3 shadow-sm">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-[var(--color-text-hint)]">例题 #{i + 1}</span>
                  <button onClick={() => removeExample(i)} className="text-red-500 hover:text-red-700">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="grid gap-2">
                  <Input value={ex.question} onChange={(e) => updateExample(i, "question", e.target.value)} placeholder="题目" />
                  <Input value={ex.short_solution} onChange={(e) => updateExample(i, "short_solution", e.target.value)} placeholder="简短解法" />
                  <Input value={ex.answer} onChange={(e) => updateExample(i, "answer", e.target.value)} placeholder="答案" />
                  <Input value={ex.error_tip} onChange={(e) => updateExample(i, "error_tip", e.target.value)} placeholder="易错点（可选）" />
                </div>
              </div>
            ))}
            {examples.length === 0 && (
              <p className="text-xs text-[var(--color-text-hint)]">暂无例题，点击上方按钮添加</p>
            )}
          </section>

          {/* Submit */}
          <div className="flex justify-end gap-3 pt-4 border-t border-[var(--color-border)]">
            <Link href="/formulas">
              <Button variant="secondary" type="button">
                <X className="h-4 w-4" /> 取消
              </Button>
            </Link>
            <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
              <Save className="h-4 w-4" />
              {createMutation.isPending ? "保存中..." : "保存草稿"}
            </Button>
          </div>
        </CardContent>
      </Card>
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
