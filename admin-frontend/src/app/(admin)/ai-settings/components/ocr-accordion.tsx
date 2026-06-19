"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ChevronDown, FileText, Braces, Filter, Rows3, Save, Brain, WandSparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiRequest } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import { Toggle } from "@/components/ui/toggle";
import type { AdminAiConfigsPatchRequest, AdminAiConfigsResponse } from "@/lib/api/types";

interface AccordionItem {
  id: string;
  title: string;
  description: string;
  icon: React.ElementType;
  color: string;
  content: (configs: Record<string, string | number | boolean>) => React.ReactNode;
}

const items: AccordionItem[] = [
  {
    id: "prompt",
    title: "Prompt 配置",
    description: "定制 OCR 纠错和题目补全的提示词模板",
    icon: FileText,
    color: "#5b7b9a",
    content: (configs) => (
      <PromptPanel configs={configs} />
    ),
  },
  {
    id: "strategy",
    title: "OCR 纠错策略",
    description: "配置 OCR 文本的校对和修复规则",
    icon: Braces,
    color: "#6b9b6b",
    content: (configs) => (
      <StrategyPanel configs={configs} />
    ),
  },
  {
    id: "structure",
    title: "题目结构修复",
    description: "修复 OCR 识别后的题目结构错乱和格式问题",
    icon: Rows3,
    color: "#c49a6b",
    content: (configs) => (
      <StructurePanel configs={configs} />
    ),
  },
  {
    id: "filter",
    title: "长文本过滤",
    description: "配置文本长度限制和内容过滤规则",
    icon: Filter,
    color: "#9a7aba",
    content: (configs) => (
      <FilterPanel configs={configs} />
    ),
  },
];

function PromptPanel({ configs }: { configs: Record<string, string | number | boolean> }) {
  const queryClient = useQueryClient();
  const savedPrompt = String(configs["ocr_correction_prompt"] ?? "");
  const [prompt, setPrompt] = useState(savedPrompt);

  useEffect(() => {
    setPrompt(savedPrompt);
  }, [savedPrompt]);

  const mutation = useMutation({
    mutationFn: (data: AdminAiConfigsPatchRequest) =>
      apiRequest<AdminAiConfigsResponse>("/ai-configs", {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-configs"] }),
  });

  const hasChanges = prompt !== savedPrompt;

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-semibold text-[var(--ink)]">OCR 纠错 Prompt</label>
        <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">自定义 OCR 纠错提示词，修改后需要点击保存</p>
        <div className="relative mt-2">
          <textarea
            className="h-28 w-full resize-none rounded-xl border border-[var(--color-border)] bg-white p-3 pr-12 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <WandSparkles className="absolute right-4 top-3 h-5 w-5 text-[var(--color-text-hint)]" />
        </div>
      </div>
      {hasChanges && (
        <div className="flex items-center gap-3">
          <button
            onClick={() => mutation.mutate({ configs: { ocr_correction_prompt: prompt } })}
            disabled={mutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-primary-dark)] bg-[var(--color-primary)] px-4 py-2 text-xs font-semibold text-white transition-all hover:bg-[var(--color-primary-dark)] disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {mutation.isPending ? "保存中..." : "保存 Prompt"}
          </button>
          <button
            onClick={() => setPrompt(savedPrompt)}
            className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-xs font-semibold text-[var(--color-text-secondary)]"
          >
            取消
          </button>
        </div>
      )}
      {mutation.isError && (
        <p className="text-xs text-[var(--color-danger)]">{getErrorMessage(mutation.error)}</p>
      )}
    </div>
  );
}

function StrategyPanel({ configs }: { configs: Record<string, string | number | boolean> }) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (data: AdminAiConfigsPatchRequest) =>
      apiRequest<AdminAiConfigsResponse>("/ai-configs", {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-configs"] }),
  });

  const toggle = (key: string) => {
    mutation.mutate({ configs: { [key]: !configs[key] } });
  };

  const toggles = [
    { key: "ocr_strategy_math_formula", label: "数学公式修复", desc: "识别并修正 LaTeX 公式中的 OCR 错误" },
    { key: "ocr_strategy_punctuation", label: "标点符号校正", desc: "统一中英文标点符号格式" },
    { key: "ocr_strategy_digit_letter", label: "数字与字母混淆修复", desc: "区分易混淆字符如 O/0、l/1" },
    { key: "ocr_strategy_space_newline", label: "空格与换行处理", desc: "智能合并错误断行和多余空格" },
  ];

  return (
    <div className="space-y-4">
      {/* 纠错策略开关 */}
      <div className="border-t border-[var(--color-border)]/40 pt-3">
        <p className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">纠错策略开关</p>
        {toggles.map((item) => (
          <label
            key={item.key}
            className="flex items-center justify-between gap-3 rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)] px-4 py-3"
          >
            <div>
              <span className="text-sm font-medium text-[var(--ink)]">{item.label}</span>
              <p className="text-xs text-[var(--color-text-hint)]">{item.desc}</p>
            </div>
            <Toggle checked={Boolean(configs[item.key])} onChange={() => toggle(item.key)} disabled={mutation.isPending} />
          </label>
        ))}
      </div>

      {mutation.isError && (
        <p className="text-xs text-[var(--color-danger)]">{getErrorMessage(mutation.error)}</p>
      )}
    </div>
  );
}

function FilterPanel({ configs }: { configs: Record<string, string | number | boolean> }) {
  const queryClient = useQueryClient();
  const [local, setLocal] = useState<Record<string, string | number | boolean>>({});
  const [dirty, setDirty] = useState(false);

  const mutation = useMutation({
    mutationFn: (data: AdminAiConfigsPatchRequest) =>
      apiRequest<AdminAiConfigsResponse>("/ai-configs", {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ai-configs"] });
      setDirty(false);
    },
  });

  const fields = [
    { key: "ocr_filter_max_chars", label: "单题最大字符数", desc: "超过此长度的题目将被截断", type: "number" as const },
    { key: "ocr_filter_max_tokens", label: "单次最大 Token 数", desc: "单次 AI 调用的 Token 上限", type: "number" as const },
  ];

  const updateField = (key: string, value: string) => {
    setLocal((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  };

  const saveFilter = () => {
    mutation.mutate({ configs: { ...local } });
  };

  const getValue = (key: string) => {
    if (dirty && key in local) return local[key];
    return configs[key] ?? "";
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map((f) => (
          <label key={f.key} className="block rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)] p-4">
            <span className="text-sm font-semibold text-[var(--ink)]">{f.label}</span>
            <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">{f.desc}</p>
            <input
              type={f.type}
              value={String(getValue(f.key))}
              onChange={(e) => updateField(f.key, e.target.value)}
              disabled={mutation.isPending}
              className="mt-2 h-10 w-full rounded-lg border border-[var(--color-border)] bg-white px-3 text-sm outline-none focus:border-[var(--color-primary)] disabled:opacity-50"
            />
          </label>
        ))}
      </div>
      <label className="flex items-center justify-between gap-3 rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)] px-4 py-3">
        <div>
          <span className="text-sm font-medium text-[var(--ink)]">启用敏感内容过滤</span>
          <p className="text-xs text-[var(--color-text-hint)]">自动过滤 OCR 结果中的敏感内容</p>
        </div>
        <Toggle
          checked={Boolean(configs["ocr_filter_sensitive"])}
          onChange={() => mutation.mutate({ configs: { ocr_filter_sensitive: !configs["ocr_filter_sensitive"] } })}
          disabled={mutation.isPending}
        />
      </label>
      {dirty && (
        <div className="flex items-center gap-3">
          <button
            onClick={saveFilter}
            disabled={mutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-primary-dark)] bg-[var(--color-primary)] px-4 py-2 text-xs font-semibold text-white transition-all hover:bg-[var(--color-primary-dark)] disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            保存过滤设置
          </button>
          <button
            onClick={() => { setLocal({}); setDirty(false); }}
            className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-xs font-semibold text-[var(--color-text-secondary)]"
          >
            取消
          </button>
        </div>
      )}
      {mutation.isError && (
        <p className="text-xs text-[var(--color-danger)]">{getErrorMessage(mutation.error)}</p>
      )}
    </div>
  );
}

function StructurePanel({ configs }: { configs: Record<string, string | number | boolean> }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (data: AdminAiConfigsPatchRequest) =>
      apiRequest<AdminAiConfigsResponse>("/ai-configs", {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-configs"] }),
  });

  const items = [
    { key: "ocr_structure_question_type", label: "题型识别", value: "单选题 / 多选题 / 判断题 / 填空题", color: "#5b7b9a" },
    { key: "ocr_structure_options", label: "选项提取", value: "A. B. C. D. 格式识别", color: "#6b9b6b" },
    { key: "ocr_structure_answer", label: "答案匹配", value: "答案关键字定位", color: "#c49a6b" },
    { key: "ocr_structure_analysis", label: "解析分离", value: "解析文本与题干分离", color: "#9a7aba" },
  ];

  return (
    <div className="space-y-4">
      <p className="text-sm text-[var(--color-text-secondary)]">
        当 OCR 识别结果出现结构错乱时，以下规则将被应用来自动修复题目格式。
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item) => (
          <label
            key={item.key}
            className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)] p-3 transition hover:border-[var(--color-primary)]/40"
          >
            <div>
              <p className="text-xs font-semibold" style={{ color: item.color }}>{item.label}</p>
              <p className="mt-0.5 text-sm text-[var(--ink)]">{item.value}</p>
            </div>
            <Toggle
              checked={Boolean(configs[item.key])}
              onChange={() => mutation.mutate({ configs: { [item.key]: !configs[item.key] } })}
              disabled={mutation.isPending}
              size="sm"
            />
          </label>
        ))}
      </div>
      {mutation.isError && (
        <p className="text-xs text-[var(--color-danger)]">保存失败，请稍后重试。</p>
      )}
    </div>
  );
}

export function OcrAccordion({ configs, loading, modelName }: {
  configs?: Record<string, string | number | boolean> | null;
  loading?: boolean;
  modelName?: string | null;
}) {
  const [openId, setOpenId] = useState<string | null>("prompt");

  const toggle = (id: string) => {
    setOpenId((prev) => (prev === id ? null : id));
  };

  const data = configs ?? {};

  return (
    <div className="rounded-2xl border border-[var(--color-border)]/80 bg-white/80 p-5 shadow-sm">
      <div className="mb-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-display text-xl font-bold text-[var(--ink)]">OCR 纠错配置</h3>
            <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">管理 OCR 识别结果的纠错策略和处理规则</p>
          </div>
          {modelName && (
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border)]/60 bg-white/60 px-3 py-1.5 text-xs text-[var(--color-text-secondary)]">
              <Brain className="h-3.5 w-3.5" />
              模型: {modelName}
            </span>
          )}
        </div>
      </div>
      <div className="space-y-2">
        {items.map((item) => {
          const Icon = item.icon;
          const isOpen = openId === item.id;
          return (
            <div
              key={item.id}
              className={cn(
                "overflow-hidden rounded-xl border transition-all duration-300",
                isOpen
                  ? "border-[var(--color-border)] shadow-sm"
                  : "border-[var(--color-border)]/60",
              )}
            >
              <button
                onClick={() => toggle(item.id)}
                className="flex w-full items-center gap-3 px-5 py-4 text-left transition-colors hover:bg-[var(--color-bg-input)]/50"
              >
                <div
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-lg"
                  style={{ backgroundColor: `${item.color}14`, color: item.color }}
                >
                  <Icon className="h-4 w-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-[var(--ink)]">{item.title}</p>
                  <p className="truncate text-xs text-[var(--color-text-hint)]">{item.description}</p>
                </div>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 shrink-0 text-[var(--color-text-hint)] transition-transform duration-300",
                    isOpen && "rotate-180",
                  )}
                />
              </button>
              <div
                className={cn(
                  "overflow-hidden transition-all duration-300",
                  isOpen ? "max-h-[800px] opacity-100" : "max-h-0 opacity-0",
                )}
              >
                <div className="border-t border-[var(--color-border)]/60 px-5 py-4">
                  {loading ? (
                    <div className="space-y-3 animate-pulse">
                      <div className="h-20 w-full rounded bg-[var(--color-border)]" />
                      <div className="h-10 w-2/3 rounded bg-[var(--color-border)]" />
                    </div>
                  ) : (
                    item.content(data)
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
