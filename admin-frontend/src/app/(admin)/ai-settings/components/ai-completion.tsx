"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { WandSparkles, ArrowRight, FileQuestion, ListChecks, MessageSquareText } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiRequest } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import { Toggle } from "@/components/ui/toggle";
import type { AdminAiConfigsResponse, AdminAiConfigsPatchRequest } from "@/lib/api/types";

type PreviewType = "question" | "answer" | "explanation";

const previewData: Record<PreviewType, { label: string; icon: React.ElementType; color: string; content: string }> = {
  question: {
    label: "题目补全",
    icon: FileQuestion,
    color: "#5b7b9a",
    content: `设函数 f(x) 在区间 [0,1] 上连续，在 (0,1) 内可导，且 f(0)=0，f(1)=1。证明：存在 ξ∈(0,1)，使得 f'(ξ) = 2ξ。`,
  },
  answer: {
    label: "答案生成",
    icon: ListChecks,
    color: "#6b9b6b",
    content: `【答案】存在 ξ∈(0,1)，使得 f'(ξ) = 2ξ。

【提示】本题考察微分中值定理的应用。构造函数 F(x) = f(x) - x²，利用罗尔定理。`,
  },
  explanation: {
    label: "解析生成",
    icon: MessageSquareText,
    color: "#c49a6b",
    content: `【解析】令 F(x) = f(x) - x²，则 F(x) 在 [0,1] 上连续，在 (0,1) 内可导。

由 f(0)=0，f(1)=1 可得：
F(0) = f(0) - 0 = 0
F(1) = f(1) - 1 = 0

由罗尔定理，存在 ξ∈(0,1)，使得 F'(ξ) = 0。
而 F'(x) = f'(x) - 2x，因此 f'(ξ) = 2ξ。

证毕。`,
  },
};

export function AiCompletionPreview({
  configs,
  loading,
  modelName,
}: {
  configs?: Record<string, string | number | boolean> | null;
  loading?: boolean;
  modelName?: string | null;
}) {
  const queryClient = useQueryClient();
  const [activePreview, setActivePreview] = useState<PreviewType>("question");
  const [isGenerating, setIsGenerating] = useState(false);

  const data = configs ?? {};
  const savedPrompt = String(data["completion_prompt"] ?? "");
  const [prompt, setPrompt] = useState(savedPrompt);
  const prevSavedRef = useRef(savedPrompt);

  // Sync savedPrompt to prompt only when savedPrompt changes and prompt hasn't
  // been manually edited (still the initial empty/matching value).
  useEffect(() => {
    if (savedPrompt && !prompt && prevSavedRef.current !== savedPrompt) {
      setPrompt(savedPrompt);
    }
    prevSavedRef.current = savedPrompt;
  }, [savedPrompt, prompt]);

  const saveMutation = useMutation({
    mutationFn: (patch: AdminAiConfigsPatchRequest) =>
      apiRequest<AdminAiConfigsResponse>("/ai-configs", { method: "PATCH", body: JSON.stringify(patch) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-configs"] }),
  });

  const currentPreview = previewData[activePreview];
  const PreviewIcon = currentPreview.icon;

  const handleGenerate = () => {
    setIsGenerating(true);
    setTimeout(() => setIsGenerating(false), 1500);
  };

  const toggles = [
    { key: "completion_auto_stem", label: "自动补全题干" },
    { key: "completion_auto_options", label: "智能选项生成" },
    { key: "completion_auto_answer_reasoning", label: "答案推理链" },
    { key: "completion_auto_knowledge_tags", label: "知识点标签" },
  ];

  const toggleConfig = (key: string) => {
    saveMutation.mutate({ configs: { [key]: !data[key] } });
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--color-border)]/80 bg-white/80 shadow-[var(--shadow-card)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)]/60 px-5 py-4">
        <div>
          <h3 className="font-display text-xl font-bold text-[var(--ink)]">AI 补全配置</h3>
          <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">配置题目补全策略并实时预览生成效果</p>
        </div>
        {modelName && (
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border)]/60 bg-white/60 px-3 py-1.5 text-xs text-[var(--color-text-secondary)]">
            <WandSparkles className="h-3.5 w-3.5" />
            {modelName}
          </span>
        )}
      </div>

      {saveMutation.isError && (
        <div className="border-b border-[var(--color-border)]/40 px-5 py-2.5">
          <p className="text-xs text-[var(--color-danger)]">{getErrorMessage(saveMutation.error)}</p>
        </div>
      )}

      {/* Two-column body */}
      <div className="flex min-h-[420px]">
        {/* ── Left: Config ── */}
        <div className="flex-1 space-y-4 border-r border-[var(--color-border)]/60 p-5">
          {/* Prompt */}
          <div>
            <span className={cn("text-[11px] font-medium text-[var(--color-text-hint)]", "font-semibold uppercase tracking-wider")}>补全 Prompt</span>
            <div className="relative mt-1.5">
              <textarea
                value={loading ? "加载中..." : (prompt || savedPrompt)}
                onChange={(e) => setPrompt(e.target.value)}
                className="h-28 w-full resize-none rounded-xl border border-[var(--color-border)] bg-white p-3 pr-10 text-sm outline-none transition-colors focus:border-[var(--color-primary)] disabled:opacity-50"
                placeholder="输入补全提示词..."
                disabled={loading}
              />
              <WandSparkles className="absolute right-3 top-3 h-4 w-4 text-[var(--color-text-hint)]" />
            </div>
            {prompt !== savedPrompt && !loading && (
              <button
                onClick={() => saveMutation.mutate({ configs: { completion_prompt: prompt } })}
                disabled={saveMutation.isPending}
                className="mt-2 inline-flex items-center gap-1 rounded-lg border border-[var(--color-primary-dark)] bg-[var(--color-primary)] px-3 py-1.5 text-[11px] font-semibold text-white shadow-sm transition-all hover:bg-[var(--color-primary-dark)] disabled:opacity-50"
              >
                {saveMutation.isPending ? "保存中..." : "💾 保存 Prompt"}
              </button>
            )}
          </div>

          {/* Toggles */}
          <div>
            <span className={cn("text-[11px] font-medium text-[var(--color-text-hint)]", "font-semibold uppercase tracking-wider")}>补全维度</span>
            <div className="mt-2 space-y-1.5">
              {toggles.map((item) => (
                <label
                  key={item.key}
                  className={cn(
                    "flex items-center justify-between gap-2 rounded-lg border px-3 py-2 transition-colors",
                    Boolean(data[item.key])
                      ? "border-[var(--color-primary)]/20 bg-[var(--color-primary-light)]"
                      : "border-[var(--color-border)]/60 bg-white/60",
                  )}
                >
                  <span className="text-sm text-[var(--ink)]">{item.label}</span>
                  <Toggle
                    checked={Boolean(data[item.key])}
                    onChange={() => toggleConfig(item.key)}
                    disabled={saveMutation.isPending || loading}
                    size="sm"
                  />
                </label>
              ))}
            </div>

            {/* Repair structure */}
            <div className="mt-3 rounded-lg border border-[var(--color-warning)]/25 bg-[var(--color-warning-light)] px-3 py-2.5">
              <label className="flex items-center justify-between gap-2">
                <div>
                  <span className="text-sm font-semibold text-[var(--ink)]">修复题目结构</span>
                  <p className="text-[11px] text-[var(--color-text-hint)]">AI 重建完整题目结构，覆盖以上字段</p>
                </div>
                <Toggle
                  checked={Boolean(data["completion_repair_structure"])}
                  onChange={() => toggleConfig("completion_repair_structure")}
                  disabled={saveMutation.isPending || loading}
                  size="sm"
                  color="#c49a6b"
                />
              </label>
            </div>
          </div>

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={isGenerating || !(prompt || savedPrompt) || loading}
            className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-[var(--color-primary-dark)] bg-[var(--color-primary)] text-sm font-semibold text-white shadow-[var(--shadow-crisp)] transition-all hover:-translate-y-0.5 hover:bg-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-50"
          >
            {isGenerating ? (
              <>
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                生成中...
              </>
            ) : (
              <>
                <WandSparkles className="h-4 w-4" />
                生成预览
              </>
            )}
          </button>
        </div>

        {/* ── Right: Preview ── */}
        <div className="flex w-[340px] shrink-0 flex-col bg-[var(--color-bg-input)]/20 p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className={cn("text-[11px] font-medium text-[var(--color-text-hint)]", "font-semibold uppercase tracking-wider")}>效果预览</span>
            <span className="text-[10px] text-[var(--color-text-hint)]">实时</span>
          </div>

          {/* Preview type tabs */}
          <div className="mb-3 flex gap-1.5">
            {(Object.entries(previewData) as [PreviewType, typeof currentPreview][]).map(([key, item]) => {
              const isActive = activePreview === key;
              return (
                <button
                  key={key}
                  onClick={() => setActivePreview(key)}
                  className={cn(
                    "flex-1 rounded-md py-1.5 text-center text-[11px] font-semibold transition-all",
                    isActive
                      ? "text-white shadow-sm"
                      : "border border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]/40",
                  )}
                  style={{ backgroundColor: isActive ? item.color : undefined }}
                >
                  {item.label}
                </button>
              );
            })}
          </div>

          {/* Preview content */}
          <div
            className="relative flex-1 overflow-hidden rounded-xl border border-[var(--color-border)]/60"
            style={{
              background: "linear-gradient(180deg, rgba(247,245,240,0.3) 0%, rgba(255,255,255,0.8) 100%)",
            }}
          >
            {isGenerating ? (
              <div className="flex h-full items-center justify-center p-4">
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--color-primary)]" />
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--color-primary)] [animation-delay:200ms]" />
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--color-primary)] [animation-delay:400ms]" />
                    <span className="ml-2 text-sm text-[var(--color-text-hint)]">AI 正在生成...</span>
                  </div>
                  <div className="space-y-2">
                    {[80, 60, 90, 40, 70].map((w, i) => (
                      <div
                        key={i}
                        className="h-3 animate-pulse rounded-full bg-[var(--color-border)]"
                        style={{ width: `${w}%`, animationDelay: `${i * 100}ms` }}
                      />
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="animate-rise-in p-4">
                {/* Preview header */}
                <div className="mb-3 flex items-center gap-2">
                  <div
                    className="grid h-6 w-6 place-items-center rounded-md"
                    style={{ backgroundColor: `${currentPreview.color}14`, color: currentPreview.color }}
                  >
                    <PreviewIcon className="h-3.5 w-3.5" />
                  </div>
                  <span className="text-xs font-semibold" style={{ color: currentPreview.color }}>
                    {currentPreview.label}
                  </span>
                </div>

                {/* Prompt context */}
                <div className="mb-3 flex items-start gap-1.5 text-[11px] text-[var(--color-text-hint)]">
                  <ArrowRight className="mt-0.5 h-3 w-3 shrink-0" />
                  <span className="line-clamp-2">Prompt: {loading ? "加载中..." : (prompt || savedPrompt).slice(0, 60)}...</span>
                </div>

                {/* Content */}
                <div className="whitespace-pre-wrap rounded-lg border border-[var(--color-border)]/40 bg-white/60 p-3 font-mono text-xs leading-6 text-[var(--ink)]">
                  {currentPreview.content}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
