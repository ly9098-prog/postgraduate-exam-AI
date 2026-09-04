"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain, Cpu, Globe, Key,
  CheckCircle2, X, Trash2, Plus, Tag, ScanEye,
  Loader2, AlertTriangle, Wifi, ChevronDown, Eye, EyeOff, Link2, MoreHorizontal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiRequest } from "@/lib/api/client";
import type {
  AdminAiModelConfig,
  AdminAiModelConfigCreateRequest,
  AdminAiModelConfigPatchRequest,
  ModelTestConnectionRequest,
  ModelTestConnectionResponse,
} from "@/lib/api/types";
import { ApiError, getErrorMessage } from "@/lib/api/errors";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";

const PROVIDER_ICONS: Record<string, React.ElementType> = {
  deepseek: Brain, openai: Globe, anthropic: Cpu,
  "qwen-vl": ScanEye, qwen: ScanEye, glm: Brain, minimax: Brain,
  moonshot: Brain, openrouter: Globe, relay: Globe, vllm: Cpu, custom: Cpu,
};

const PROVIDER_COLORS: Record<string, string> = {
  deepseek: "#5b7b9a", openai: "#6b9b6b", anthropic: "#c49a6b",
  "qwen-vl": "#7c5ce7", qwen: "#7c5ce7", glm: "#4f72b8",
  minimax: "#8b6bb1", moonshot: "#506c8f", openrouter: "#5d6b76", relay: "#52758f",
  paddleocr: "#e67e22", paddleocr_vl: "#e67e22", "paddleocr-vl": "#e67e22",
};

type ProviderPreset = {
  value: string;
  label: string;
  description: string;
};

const PROVIDER_PRESETS: ProviderPreset[] = [
  { value: "openai", label: "OpenAI", description: "OpenAI 官方或标准 OpenAI-compatible 服务" },
  { value: "deepseek", label: "DeepSeek", description: "DeepSeek OpenAI-compatible API" },
  { value: "qwen", label: "Qwen / 百炼", description: "阿里云百炼兼容模式、Qwen 文本模型" },
  { value: "qwen-vl", label: "Qwen-VL", description: "Qwen 视觉语言模型的 OpenAI-compatible 接口" },
  { value: "glm", label: "GLM / 智谱", description: "智谱 GLM OpenAI-compatible API" },
  { value: "minimax", label: "MiniMax", description: "MiniMax OpenAI-compatible API" },
  { value: "moonshot", label: "Moonshot / Kimi", description: "Moonshot OpenAI-compatible API" },
  { value: "openrouter", label: "OpenRouter", description: "OpenRouter 多模型聚合接口" },
  { value: "relay", label: "第三方 / Relay", description: "第三方 OpenAI-compatible API，支持 /v1 Base URL 或完整 chat/completions 地址" },
  { value: "vllm", label: "vLLM", description: "自部署 vLLM OpenAI-compatible Server" },
  { value: "custom", label: "Custom", description: "其他兼容 /v1/chat/completions 的服务" },
  { value: "paddleocr-vl", label: "PaddleOCR-VL", description: "PaddleOCR 专用视觉 OCR Job API" },
];

const FEATURE_LABELS: Record<string, { label: string; color: string }> = {
  analysis: { label: "学习/错题分析", color: "#c49a6b" },
  completion: { label: "题目补全", color: "#6b9b6b" },
  ai_repair: { label: "题目审核修复", color: "#8b6bb1" },
  text_structuring: { label: "文本导题结构化", color: "#4f72b8" },
  ocr_fix: { label: "OCR LLM纠错", color: "#5b7b9a" },
  text_correction: { label: "OCR文本纠错", color: "#6887a5" },
  ocr: { label: "OCR通用(兼容)", color: "#5b7b9a" },
  vision: { label: "视觉/OCR-VL", color: "#e67e22" },
  embedding: { label: "Embedding", color: "#65756b" },
};

const FEATURE_OPTIONS = [
  { value: "analysis", label: "学习/错题分析", desc: "小程序错题分析、学习建议、Dashboard AI 诊断" },
  { value: "completion", label: "题目补全", desc: "单题/批量补全、题目元数据补全（兼容旧配置）" },
  { value: "ai_repair", label: "题目审核修复", desc: "导题审核、低置信度题目修复、答案/解析辅助补全" },
  { value: "text_structuring", label: "文本导题结构化", desc: "文本导入和代码结构重建" },
  { value: "ocr_fix", label: "OCR LLM 纠错", desc: "OCR 后的文本纠错与修复，走 OpenAI-compatible chat/completions" },
  { value: "text_correction", label: "OCR 文本纠错", desc: "文本纠错细分能力，可与 ocr_fix 分开指定模型" },
  { value: "ocr", label: "OCR 通用（兼容）", desc: "旧 OCR LLM 纠错配置兼容标签" },
  { value: "vision", label: "PaddleOCR-VL 视觉 OCR", desc: "PaddleOCR 厂商专用 Job API，不走 OpenAI-compatible chat/completions" },
  { value: "embedding", label: "Embedding", desc: "向量模型（不走 chat/completions）" },
];

type ModelKind = "chat" | "embedding" | "ocr_job";

const CHAT_FEATURE_OPTIONS = FEATURE_OPTIONS.filter((opt) => !["embedding", "vision"].includes(opt.value));

function getModelKind(model: Pick<AdminAiModelConfig, "provider" | "features" | "feature">): ModelKind {
  const features = model.features ?? (model.feature ? [model.feature] : []);
  if (features.includes("embedding")) return "embedding";
  if (features.includes("vision") || isPaddleOcrProvider(model.provider)) return "ocr_job";
  return "chat";
}

function featuresForKind(kind: ModelKind, current: string[] = []): string[] {
  if (kind === "embedding") return ["embedding"];
  if (kind === "ocr_job") return ["vision"];
  return current.filter((feature) => feature !== "embedding" && feature !== "vision");
}

function rememberedChatFeatures(current: string[] = []): string[] {
  return current.filter((feature) => feature !== "embedding" && feature !== "vision");
}

function featureSignature(features: string[] = []): string {
  return [...new Set(features)].sort().join("|");
}

function configuredFeatures(model: Pick<AdminAiModelConfig, "features" | "feature">): string[] {
  if (model.features?.length) return model.features;
  return model.feature ? [model.feature] : [];
}

type FeatureConflict = {
  feature: string;
  model: AdminAiModelConfig;
};

function findEnabledFeatureConflicts(features: string[], models: AdminAiModelConfig[]): FeatureConflict[] {
  const selected = new Set(features.filter((feature) => feature !== "embedding"));
  if (selected.size === 0) return [];

  const conflicts: FeatureConflict[] = [];
  for (const model of models) {
    if (!model.is_enabled) continue;
    for (const feature of configuredFeatures(model)) {
      if (selected.has(feature)) conflicts.push({ feature, model });
    }
  }
  return conflicts;
}

const MODEL_KIND_META: Record<ModelKind, { label: string; desc: string }> = {
  chat: { label: "Chat / LLM", desc: "通过 chat/completions 承载分析、补全与 OCR 文本纠错" },
  embedding: { label: "Embedding", desc: "通过 embeddings 生成向量；具体使用模型在“向量”页选择" },
  ocr_job: { label: "OCR Job", desc: "PaddleOCR-VL 等厂商专用视觉 OCR 接口" },
};

function isPaddleOcrProvider(provider: string) {
  const normalized = provider.toLowerCase().replace(/_/g, "-");
  return normalized === "paddle" || normalized.startsWith("paddleocr");
}

function adapterLabel(provider: string) {
  if (isPaddleOcrProvider(provider)) return "PaddleOCR 专用";
  const normalized = provider.trim().toLowerCase();
  if (normalized === "relay" || normalized === "custom") return "OpenAI-compatible / 第三方";
  return "OpenAI 兼容";
}

type ParsedCompatibleExample = {
  apiBaseUrl?: string;
  modelName?: string;
};

function stripChatCompletionsSuffix(value: string): string {
  const normalized = value.trim().replace(/[\\,;]+$/, "").replace(/["'`]+$/, "").replace(/\/$/, "");
  return normalized.replace(/\/chat\/completions$/i, "");
}

function parseOpenAICompatibleExample(raw: string): ParsedCompatibleExample {
  const text = raw.trim();
  if (!text) return {};

  const baseUrlMatch = text.match(/base_url\s*=\s*["']([^"']+)["']/i);
  const urls = text.match(/https?:\/\/[^\s"'`\\]+/gi) ?? [];
  const endpointUrl = urls.find((url) => /\/chat\/completions(?:\/)?$/i.test(url.replace(/[),;]+$/, "")));
  const fallbackUrl = urls[0];
  const rawUrl = baseUrlMatch?.[1] ?? endpointUrl ?? fallbackUrl;

  const jsonModelMatch = text.match(/["']model["']\s*:\s*["']([^"']+)["']/i);
  const keywordModelMatch = text.match(/\bmodel\s*=\s*["']([^"']+)["']/i);
  const modelName = (jsonModelMatch?.[1] ?? keywordModelMatch?.[1] ?? "").trim();

  return {
    apiBaseUrl: rawUrl ? stripChatCompletionsSuffix(rawUrl.replace(/[),;]+$/, "")) : undefined,
    modelName: modelName || undefined,
  };
}

function buildOpenAICompatibleEndpoint(apiBaseUrl: string): string | null {
  const normalized = apiBaseUrl.trim().replace(/\/$/, "");
  if (!normalized) return null;
  try {
    const parsed = new URL(normalized);
    if (!['http:', 'https:'].includes(parsed.protocol)) return null;
    const path = parsed.pathname.replace(/\/$/, "");
    if (/\/chat\/completions$/i.test(path)) return normalized;
    if (!path) return `${normalized}/v1/chat/completions`;
    return `${normalized}/chat/completions`;
  } catch {
    return null;
  }
}

function CompatibleEndpointHint({ apiBaseUrl, kind }: { apiBaseUrl: string; kind: ModelKind }) {
  if (kind !== "chat" || !apiBaseUrl.trim()) return null;
  const endpoint = buildOpenAICompatibleEndpoint(apiBaseUrl);
  if (!endpoint) {
    return <span className="mt-1 block text-[10px] text-[var(--color-danger)]">请输入完整的 http(s) API 地址</span>;
  }
  return (
    <span className="mt-1 block break-all text-[10px] leading-4 text-[var(--color-text-hint)]">
      实际请求：<span className="font-mono text-[var(--color-text-secondary)]">POST {endpoint}</span>
    </span>
  );
}

const COMPATIBLE_EXAMPLE_PLACEHOLDER = `curl https://8stoken.com/v1/chat/completions \\
  -H "Authorization: Bearer $NEW_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-5.6-sol",
    "messages": [
      {
        "role": "user",
        "content": "Explain quantum entanglement in one paragraph."
      }
    ],
    "temperature": 0.7
  }'`;

type CompatibleExampleImporterProps = {
  disabled?: boolean;
  onApply: (parsed: ParsedCompatibleExample) => void;
};

function CompatibleExampleImporter({ disabled = false, onApply }: CompatibleExampleImporterProps) {
  const [expanded, setExpanded] = useState(false);
  const [example, setExample] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const apply = () => {
    const parsed = parseOpenAICompatibleExample(example);
    if (!parsed.apiBaseUrl && !parsed.modelName) {
      setMessage("未识别到 API 地址或 model，请检查示例内容");
      return;
    }
    onApply(parsed);
    const parts = [parsed.apiBaseUrl ? "API 地址" : null, parsed.modelName ? "模型标识" : null].filter(Boolean);
    setMessage(`已识别并填入${parts.join("、")}`);
  };

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border transition-[border-color,background-color,box-shadow] duration-200",
        expanded
          ? "border-[var(--color-primary)]/25 bg-white shadow-[0_2px_10px_rgba(15,23,42,0.035)]"
          : "border-slate-200 bg-slate-50/45 hover:border-[var(--color-primary)]/25 hover:bg-[var(--color-primary-light)]/25",
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((previous) => !previous)}
        disabled={disabled}
        aria-expanded={expanded}
        className="group flex w-full cursor-pointer items-center justify-between gap-4 px-3 py-2.5 text-left disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="flex min-w-0 items-center gap-2.5">
          <span className={cn(
            "grid h-7 w-7 shrink-0 place-items-center rounded-md border bg-white transition-[border-color,color] duration-150",
            expanded ? "border-[var(--color-primary)]/30 text-[var(--color-primary)]" : "border-slate-200 text-slate-400 group-hover:border-[var(--color-primary)]/25 group-hover:text-[var(--color-primary)]",
          )}>
            <Globe className="h-3.5 w-3.5" />
          </span>
          <span className="min-w-0">
            <span className="block text-[12px] font-semibold text-slate-700 transition-colors group-hover:text-slate-900">第三方API快速填入</span>
            <span className="mt-0.5 block text-[10px] leading-4 text-slate-400">粘贴 cURL / Python 调用示例，自动识别 Base URL 与模型标识。</span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <span className="hidden text-[10px] font-medium text-slate-400 sm:inline">cURL / Python</span>
          <span className="inline-flex h-7 items-center gap-1 rounded-md border border-slate-200 bg-white px-2 text-[10px] font-semibold text-slate-500 transition-[border-color,color,box-shadow] group-hover:border-[var(--color-primary)]/30 group-hover:text-[var(--color-primary)] group-hover:shadow-sm">
            {expanded ? "收起" : "展开"}
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform duration-200 ease-out", expanded && "rotate-180")} />
          </span>
        </span>
      </button>
      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] duration-200 ease-out",
          expanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-200/90 px-3 pb-3 pt-3">
            <textarea
              value={example}
              onChange={(event) => { setExample(event.target.value); setMessage(null); }}
              disabled={disabled}
              rows={11}
              spellCheck={false}
              aria-label="第三方 API 调用示例"
              placeholder={COMPATIBLE_EXAMPLE_PLACEHOLDER}
              className="min-h-[220px] w-full resize-y rounded-lg border border-slate-200 bg-slate-50/35 px-3.5 py-3 font-mono text-[11px] leading-[1.65] text-slate-700 outline-none transition-[border-color,background-color,box-shadow] duration-150 placeholder:whitespace-pre-wrap placeholder:text-slate-400 focus:border-[var(--color-primary)] focus:bg-white focus:ring-2 focus:ring-[var(--color-primary)]/10 disabled:opacity-50"
            />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <span className={cn("min-w-0 flex-1 text-[10px] leading-4", message?.startsWith("已识别") ? "text-[var(--color-success)]" : "text-slate-400")}>
                {message ?? "支持 Base URL、完整 /chat/completions 地址与 model 参数；示例中的 API Key 不会被读取。"}
              </span>
              <button
                type="button"
                onClick={apply}
                disabled={disabled || !example.trim()}
                className="h-8 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-[11px] font-semibold text-slate-600 transition-[border-color,background-color,color,transform,box-shadow] duration-150 hover:border-[var(--color-primary)]/35 hover:bg-[var(--color-primary-light)]/25 hover:text-[var(--color-primary)] hover:shadow-sm active:scale-[0.98] disabled:opacity-40"
              >
                识别并填入
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function getProviderIcon(p: string) { return PROVIDER_ICONS[p] || Brain; }
function getProviderColor(p: string) { return PROVIDER_COLORS[p] || "#5b7b9a"; }

const inputCls =
  "h-9 w-full rounded-lg border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]";


type ProviderSelectProps = {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
};

function ProviderSelect({
  value,
  onChange,
  disabled = false,
  placeholder = "选择或输入 Provider",
}: ProviderSelectProps) {
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number; width: number } | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const normalizedValue = value.trim().toLowerCase();
  const filtered = PROVIDER_PRESETS.filter((item) => {
    if (!normalizedValue) return true;
    return item.value.includes(normalizedValue)
      || item.label.toLowerCase().includes(normalizedValue)
      || item.description.toLowerCase().includes(normalizedValue);
  });
  const hasExactPreset = PROVIDER_PRESETS.some((item) => item.value === normalizedValue);

  const syncMenuPosition = useCallback(() => {
    const rect = rootRef.current?.getBoundingClientRect();
    if (!rect) return;
    setMenuPosition({ top: rect.bottom + 4, left: rect.left, width: rect.width });
  }, []);

  const openMenu = () => {
    if (disabled) return;
    syncMenuPosition();
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;

    const closeOnOutsideClick = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    const reposition = () => syncMenuPosition();

    document.addEventListener("pointerdown", closeOnOutsideClick);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open, syncMenuPosition]);

  const choose = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
  };

  const menu = open && menuPosition && typeof document !== "undefined" ? createPortal(
    <div
      ref={menuRef}
      role="listbox"
      style={{ top: menuPosition.top, left: menuPosition.left, width: menuPosition.width }}
      className="fixed z-[120] max-h-64 overflow-y-auto rounded-xl border border-[var(--color-border)] bg-white p-1.5 shadow-[var(--shadow-floating)]"
    >
      {filtered.length > 0 ? filtered.map((item) => {
        const selected = normalizedValue === item.value;
        const Icon = getProviderIcon(item.value);
        const color = getProviderColor(item.value);
        return (
          <button
            key={item.value}
            type="button"
            role="option"
            aria-selected={selected}
            onClick={() => choose(item.value)}
            className={cn(
              "flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors",
              selected
                ? "bg-[var(--color-primary-light)]"
                : "hover:bg-[var(--color-bg-input)]",
            )}
          >
            <span
              className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md border"
              style={{ background: `${color}08`, borderColor: `${color}25` }}
            >
              <Icon className="h-3.5 w-3.5" style={{ color }} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                <span className="text-xs font-semibold text-[var(--ink)]">{item.label}</span>
                <span className="font-mono text-[10px] text-[var(--color-text-hint)]">{item.value}</span>
              </span>
              <span className="mt-0.5 block text-[10px] leading-4 text-[var(--color-text-hint)]">{item.description}</span>
            </span>
            {selected ? <CheckCircle2 className="mt-1 h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" /> : null}
          </button>
        );
      }) : (
        <div className="px-3 py-2 text-xs text-[var(--color-text-hint)]">没有匹配的预设 Provider</div>
      )}

      {value.trim() && !hasExactPreset ? (
        <>
          <div className="my-1 border-t border-[var(--color-border)]/70" />
          <button
            type="button"
            onClick={() => choose(value.trim())}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-input)]"
          >
            <Cpu className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
            <span>使用自定义 Provider：</span>
            <span className="truncate font-mono font-semibold text-[var(--ink)]">{value.trim()}</span>
          </button>
        </>
      ) : null}
    </div>,
    document.body,
  ) : null;

  return (
    <>
      <div ref={rootRef} className="relative mt-1">
        <input
          type="text"
          value={value}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          aria-haspopup="listbox"
          aria-expanded={open}
          placeholder={placeholder}
          onFocus={openMenu}
          onChange={(event) => {
            onChange(event.target.value);
            openMenu();
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
            if (event.key === "ArrowDown") openMenu();
          }}
          className={cn(inputCls, "pr-9")}
        />
        <button
          type="button"
          tabIndex={-1}
          disabled={disabled}
          aria-label={open ? "收起 Provider 列表" : "展开 Provider 列表"}
          onClick={() => {
            if (open) setOpen(false);
            else openMenu();
          }}
          className="absolute inset-y-0 right-0 grid w-9 place-items-center text-[var(--color-text-hint)] transition-colors hover:text-[var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        </button>
      </div>
      {menu}
    </>
  );
}

// ---------------------------------------------------------------------------
// Add model inspector drawer
// ---------------------------------------------------------------------------

type AddDrawerTab = "basic" | "api" | "features";

type NewModelDraft = {
  version: 1;
  name: string;
  displayName: string;
  provider: string;
  modelKind: ModelKind;
  apiBaseUrl: string;
  features: string[];
  savedAt: number;
};

const NEW_MODEL_DRAFT_STORAGE_KEY = "ai-settings:new-model-draft";
const ADD_DRAWER_TABS: { key: AddDrawerTab; label: string }[] = [
  { key: "basic", label: "基础配置" },
  { key: "api", label: "API 配置" },
  { key: "features", label: "功能映射" },
];

function AddModelDrawer({
  onClose, onSave, loading, existingModels,
}: {
  onClose: () => void;
  onSave: (data: AdminAiModelConfigCreateRequest) => Promise<AdminAiModelConfig>;
  loading: boolean;
  existingModels: AdminAiModelConfig[];
}) {
  const [visible, setVisible] = useState(false);
  const [activeTab, setActiveTab] = useState<AddDrawerTab>("basic");
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [modelKind, setModelKind] = useState<ModelKind>("chat");
  const [apiBaseUrl, setApiBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [features, setFeatures] = useState<string[]>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestConnectionResponse | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [draftReady, setDraftReady] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const basicSectionRef = useRef<HTMLElement>(null);
  const apiSectionRef = useRef<HTMLElement>(null);
  const featuresSectionRef = useRef<HTMLElement>(null);

  const effectiveFeatures = featuresForKind(modelKind, features);
  const featureConflicts = findEnabledFeatureConflicts(effectiveFeatures, existingModels);
  const normalizedApiBaseUrl = apiBaseUrl.trim().replace(/\/$/, "");
  const valid = Boolean(name.trim() && displayName.trim() && provider.trim() && normalizedApiBaseUrl);
  const persistentDirty = Boolean(
    name.trim()
    || displayName.trim()
    || normalizedApiBaseUrl
    || features.length
    || provider !== "openai"
    || modelKind !== "chat",
  );
  const dirty = persistentDirty || Boolean(apiKey.trim());

  const requestClose = useCallback(() => {
    if (loading) return;
    setVisible(false);
    window.setTimeout(onClose, 220);
  }, [loading, onClose]);

  useEffect(() => {
    const enterFrame = window.requestAnimationFrame(() => setVisible(true));
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(enterFrame);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [requestClose]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(NEW_MODEL_DRAFT_STORAGE_KEY);
      if (raw) {
        const draft = JSON.parse(raw) as NewModelDraft;
        if (draft.version === 1) {
          setName(draft.name ?? "");
          setDisplayName(draft.displayName ?? "");
          setProvider(draft.provider ?? "openai");
          setModelKind(draft.modelKind ?? "chat");
          setApiBaseUrl(draft.apiBaseUrl ?? "");
          setFeatures(Array.isArray(draft.features) ? rememberedChatFeatures(draft.features) : []);
        } else {
          window.localStorage.removeItem(NEW_MODEL_DRAFT_STORAGE_KEY);
        }
      }
    } catch {
      // Local draft persistence is best-effort.
    } finally {
      setDraftReady(true);
    }
  }, []);

  useEffect(() => {
    if (!draftReady) return;
    try {
      if (!persistentDirty) {
        window.localStorage.removeItem(NEW_MODEL_DRAFT_STORAGE_KEY);
        return;
      }
      const draft: NewModelDraft = {
        version: 1,
        name,
        displayName,
        provider,
        modelKind,
        apiBaseUrl,
        features,
        savedAt: Date.now(),
      };
      window.localStorage.setItem(NEW_MODEL_DRAFT_STORAGE_KEY, JSON.stringify(draft));
    } catch {
      // The drawer remains usable even if localStorage is unavailable.
    }
  }, [apiBaseUrl, displayName, draftReady, features, modelKind, name, persistentDirty, provider]);

  const scrollToTab = useCallback((tab: AddDrawerTab) => {
    setActiveTab(tab);
    const container = bodyRef.current;
    const section = tab === "basic"
      ? basicSectionRef.current
      : tab === "features"
        ? featuresSectionRef.current
        : apiSectionRef.current;
    if (!container || !section) return;
    const top = section.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop - 8;
    container.scrollTo({ top: Math.max(top, 0), behavior: "smooth" });
  }, []);

  const handleTestConnection = async () => {
    if (!normalizedApiBaseUrl || !apiKey.trim() || !name.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiRequest<ModelTestConnectionResponse>("/ai-models/test-connection", {
        method: "POST",
        body: JSON.stringify({
          api_base_url: normalizedApiBaseUrl,
          api_key: apiKey.trim(),
          model_name: name.trim(),
          provider: provider.trim(),
          features: effectiveFeatures,
        } satisfies ModelTestConnectionRequest),
      });
      setTestResult(result);
    } catch (err) {
      setTestResult({ success: false, status: "network_error", message: getErrorMessage(err), latency_ms: null });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (!valid || loading || featureConflicts.length > 0) return;
    setSubmitError(null);
    try {
      await onSave({
        name: name.trim(),
        display_name: displayName.trim(),
        provider: provider.trim(),
        api_base_url: normalizedApiBaseUrl,
        api_key: apiKey.trim() || undefined,
        features: effectiveFeatures.length > 0 ? effectiveFeatures : null,
      });
      try {
        window.localStorage.removeItem(NEW_MODEL_DRAFT_STORAGE_KEY);
      } catch {
        // Creation succeeded; draft cleanup is best-effort.
      }
      setVisible(false);
      window.setTimeout(onClose, 220);
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setSubmitError(
          "模型配置未通过校验。若所选功能已由其他启用模型使用，请先禁用旧模型，并检查模型标识、Provider 与 API 地址。",
        );
      } else {
        setSubmitError(getErrorMessage(err));
      }
    }
  };

  return createPortal(
    <div
      className={cn(
        "fixed inset-0 z-40 flex justify-end backdrop-blur-[0.5px] transition-[background-color] duration-200",
        visible ? "bg-slate-950/[0.10]" : "bg-slate-950/0",
      )}
      onMouseDown={requestClose}
    >
      <aside
        aria-label="添加模型"
        onMouseDown={(event) => event.stopPropagation()}
        className={cn(
          "flex h-full w-[clamp(720px,46vw,820px)] max-w-[calc(100vw-24px)] flex-col border-l border-slate-200/80 bg-white shadow-[-18px_0_52px_rgba(15,23,42,0.12)] will-change-transform transition-transform duration-200 ease-out",
          visible ? "translate-x-0" : "translate-x-full",
        )}
      >
        <header className="shrink-0 border-b border-slate-200/80 bg-white/95 px-7 pt-3 backdrop-blur-xl">
          <div className="flex min-h-14 items-center justify-between gap-4 pb-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2.5">
                <h3 className="truncate text-[17px] font-semibold tracking-[-0.01em] text-slate-950">添加模型</h3>
                {dirty ? <span className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">草稿</span> : null}
              </div>
              <p className="mt-0.5 text-[11px] text-slate-400">新建模型配置，普通字段会自动保存为本地草稿。</p>
            </div>
            <button
              type="button"
              onClick={requestClose}
              disabled={loading}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-slate-400 transition-[background-color,color,transform] hover:bg-slate-100 hover:text-slate-900 active:scale-95 disabled:opacity-40"
              aria-label="关闭添加模型抽屉"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <nav className="flex gap-6" aria-label="添加模型配置分区">
            {ADD_DRAWER_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => scrollToTab(tab.key)}
                className={cn(
                  "relative pb-3 text-[13px] font-semibold transition-colors",
                  activeTab === tab.key ? "text-[var(--color-primary)]" : "text-slate-400 hover:text-slate-700",
                )}
              >
                {tab.label}
                <span
                  className={cn(
                    "absolute inset-x-0 -bottom-px h-0.5 origin-center rounded-full bg-[var(--color-primary)] transition-transform duration-200",
                    activeTab === tab.key ? "scale-x-100" : "scale-x-0",
                  )}
                />
              </button>
            ))}
          </nav>
        </header>

        <div ref={bodyRef} className="min-h-0 flex-1 overflow-y-auto scroll-smooth bg-white px-7 pb-24 pt-1">
          <section ref={basicSectionRef} className="scroll-mt-3 border-b border-slate-200 py-5">
            <div className="mb-4">
              <h4 className="text-[13px] font-semibold text-slate-950">模型信息</h4>
              <p className="mt-0.5 text-[11px] text-slate-400">用于识别模型并确定调用接口类型。</p>
            </div>

            <div className="grid gap-x-4 gap-y-4 md:grid-cols-2">
              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">模型标识 *</span>
                <input
                  value={name}
                  onChange={(event) => { setName(event.target.value); setTestResult(null); setSubmitError(null); }}
                  className={cn(inputCls, "mt-1.5 h-10 bg-slate-50/45 transition-[border-color,background-color,box-shadow] focus:bg-white focus:ring-2 focus:ring-[var(--color-primary)]/10")}
                  placeholder="deepseek-v4-flash"
                />
              </label>
              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">显示名称 *</span>
                <input
                  value={displayName}
                  onChange={(event) => { setDisplayName(event.target.value); setSubmitError(null); }}
                  className={cn(inputCls, "mt-1.5 h-10 bg-slate-50/45 transition-[border-color,background-color,box-shadow] focus:bg-white focus:ring-2 focus:ring-[var(--color-primary)]/10")}
                  placeholder="DeepSeek V4 Flash"
                />
              </label>
              <div className="md:col-span-2 grid gap-2 sm:grid-cols-[92px_minmax(0,1fr)] sm:items-start">
                <span className="pt-2.5 text-[11px] font-medium text-slate-500">模型类型 *</span>
                <div className="min-w-0">
                  <div className="grid w-full max-w-[560px] grid-cols-3 gap-2">
                    {(Object.keys(MODEL_KIND_META) as ModelKind[]).map((kind) => {
                      const selected = modelKind === kind;
                      return (
                        <button
                          key={kind}
                          type="button"
                          disabled={loading}
                          onClick={() => {
                            setModelKind(kind);
                            setTestResult(null);
                            setSubmitError(null);
                            if (kind === "ocr_job" && provider === "openai") setProvider("paddleocr-vl");
                          }}
                          className={cn(
                            "relative flex h-10 items-center justify-center rounded-md border-2 px-3 text-[12px] font-medium transition-[border-color,background-color,color,box-shadow,transform] duration-200 ease-out active:scale-[0.985] disabled:opacity-50",
                            selected
                              ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/25 text-slate-900 shadow-[0_1px_3px_rgba(15,23,42,0.035)]"
                              : "border-slate-200/90 bg-white text-slate-500 hover:border-slate-300 hover:bg-slate-50/70 hover:text-slate-700",
                          )}
                        >
                          {MODEL_KIND_META[kind].label}
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-1.5 max-w-[560px] text-[10px] leading-4 text-slate-400 transition-colors duration-200">{MODEL_KIND_META[modelKind].desc}</p>
                </div>
              </div>
            </div>
          </section>

          <section ref={apiSectionRef} className="scroll-mt-3 border-b border-slate-200 py-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h4 className="flex items-center gap-2 text-[13px] font-semibold text-slate-950"><Key className="h-3.5 w-3.5 text-[var(--color-primary)]" />API 接入</h4>
                <p className="mt-0.5 text-[11px] text-slate-400">配置 Provider、接口地址与访问凭证。</p>
              </div>
              <span className="rounded-md border border-slate-200/90 bg-slate-50/70 px-2 py-1 text-[10px] font-medium text-slate-500">{adapterLabel(provider)}</span>
            </div>

            <div className="max-w-[680px] space-y-4">
              {modelKind === "chat" ? (
                <CompatibleExampleImporter
                  disabled={loading}
                  onApply={(parsed) => {
                    if (parsed.apiBaseUrl) setApiBaseUrl(parsed.apiBaseUrl);
                    if (parsed.modelName) {
                      setName(parsed.modelName);
                      setDisplayName((current) => current.trim() ? current : parsed.modelName ?? current);
                    }
                    setProvider("relay");
                    setTestResult(null);
                    setSubmitError(null);
                  }}
                />
              ) : null}

              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">Provider / 接入方式 *</span>
                <ProviderSelect
                  value={provider}
                  onChange={(value) => { setProvider(value); setTestResult(null); setSubmitError(null); }}
                  disabled={loading}
                  placeholder="relay / openai / deepseek / custom"
                />
                <span className="mt-1 block text-[10px] leading-4 text-slate-400">接第三方 API 服务建议选择「第三方 / Relay」，模型标识仍填写服务商实际要求的 model。</span>
              </label>

              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">API 地址 *</span>
                <div className="relative mt-1.5">
                  <input
                    value={apiBaseUrl}
                    onChange={(event) => { setApiBaseUrl(event.target.value); setTestResult(null); setSubmitError(null); }}
                    className={cn(inputCls, "h-10 bg-slate-50/45 pr-9 transition-[border-color,background-color,box-shadow] focus:bg-white focus:ring-2 focus:ring-[var(--color-primary)]/10")}
                    placeholder="https://8stoken.com/v1"
                  />
                  <Link2 className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-300" />
                </div>
                <CompatibleEndpointHint apiBaseUrl={apiBaseUrl} kind={modelKind} />
              </label>

              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">API Key</span>
                <div className="relative mt-1.5">
                  <input
                    type={showApiKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(event) => { setApiKey(event.target.value); setTestResult(null); }}
                    className={cn(inputCls, "h-10 bg-slate-50/45 pr-10 transition-[border-color,background-color,box-shadow] focus:bg-white focus:ring-2 focus:ring-[var(--color-primary)]/10")}
                    placeholder="sk-... / 第三方 API 令牌"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey((previous) => !previous)}
                    disabled={!apiKey}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 transition-colors hover:text-[var(--color-primary)] disabled:cursor-default disabled:opacity-45"
                    aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"}
                  >
                    {showApiKey && apiKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </button>
                </div>
                <p className="mt-1 text-[10px] leading-4 text-slate-400">API Key 不写入浏览器本地草稿；关闭抽屉后需重新输入。</p>
              </label>

              <div className="flex flex-wrap items-center gap-3 pt-0.5">
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={testing || !apiKey.trim() || !normalizedApiBaseUrl || !name.trim()}
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 text-xs font-semibold text-slate-600 transition-[border-color,background-color,color,transform] duration-150 hover:border-[var(--color-primary)]/35 hover:bg-[var(--color-primary-light)]/35 hover:text-[var(--color-primary)] active:scale-[0.98] disabled:opacity-40"
                >
                  {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                  测试连接
                </button>
                <span className="text-[10px] text-slate-400">建议保存前先测试接口连通性与模型标识。</span>
              </div>

              {testResult ? (
                <div className="max-w-[680px] border-t border-slate-200 pt-2.5 text-[11px] leading-5">
                  <div className="flex min-w-0 items-start gap-2">
                    <span
                      className={cn(
                        "mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full",
                        testResult.success ? "bg-emerald-500" : "bg-rose-500",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      {testResult.success ? (
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span className="font-medium text-slate-700">连接成功</span>
                          {testResult.latency_ms != null ? <span className="text-slate-400">响应时间 {testResult.latency_ms}ms</span> : null}
                          <span className="text-slate-400">模型接口可正常使用</span>
                        </div>
                      ) : (
                        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span className="shrink-0 font-medium text-rose-700">连接失败</span>
                          <span className="min-w-0 break-words text-slate-500">{testResult.message}</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </section>

          <section ref={featuresSectionRef} className="scroll-mt-3 py-5">
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <h4 className="text-[13px] font-semibold text-slate-950">能力映射</h4>
                <p className="mt-0.5 text-[11px] text-slate-400">同一功能仅允许一个启用模型。</p>
              </div>
            </div>

            {modelKind === "chat" ? (
              <div className="max-w-[680px] divide-y divide-slate-200 border-y border-slate-200">
                {DRAWER_FEATURE_OPTIONS.map((option) => {
                  const selected = features.includes(option.value);
                  const owners = existingModels.filter(
                    (item) => item.is_enabled && configuredFeatures(item).includes(option.value),
                  );
                  const conflict = owners[0];
                  return (
                    <label
                      key={option.value}
                      className={cn(
                        "flex cursor-pointer items-start gap-3 px-2 py-3 transition-colors",
                        selected ? "bg-[var(--color-primary-light)]/32" : "hover:bg-slate-50/80",
                        conflict && selected && "bg-amber-50/65",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={selected}
                        onChange={() => {
                          setSubmitError(null);
                          setFeatures((previous) => previous.includes(option.value) ? previous.filter((feature) => feature !== option.value) : [...previous, option.value]);
                        }}
                      />
                      <span className={cn("mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors", selected ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white" : "border-slate-300 bg-white")}>
                        {selected ? <CheckCircle2 className="h-2.5 w-2.5" /> : null}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold text-slate-800">{option.label}</span>
                          {conflict ? <span className="text-[10px] font-medium text-amber-700">已由「{conflict.display_name}」占用</span> : null}
                        </span>
                        <span className="mt-0.5 block text-[11px] leading-4 text-slate-400">{option.desc}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <div className="max-w-[680px] border-y border-slate-200 py-3">
                <p className="text-xs font-semibold text-slate-800">{modelKind === "embedding" ? "Vector Embedding" : "视觉 OCR Job"}</p>
                <p className="mt-1 text-[11px] leading-5 text-slate-400">{MODEL_KIND_META[modelKind].desc}</p>
              </div>
            )}

            {featureConflicts.length > 0 ? (
              <div role="alert" className="mt-4 max-w-[680px] border-l-2 border-amber-400 bg-amber-50/60 px-3 py-2.5 text-xs text-amber-800">
                <p className="font-semibold">存在功能占用冲突，当前无法创建</p>
                <div className="mt-1 space-y-0.5 leading-5">
                  {featureConflicts.map(({ feature, model }) => (
                    <p key={`${feature}-${model.id}`}>「{FEATURE_LABELS[feature]?.label ?? feature}」已由启用模型「{model.display_name}」使用</p>
                  ))}
                </div>
              </div>
            ) : null}

            {submitError ? (
              <div role="alert" aria-live="polite" className="mt-4 max-w-[680px] border-l-2 border-red-400 bg-red-50/60 px-3 py-2.5 text-xs leading-5 text-red-700">
                创建失败：{submitError}
              </div>
            ) : null}
          </section>
        </div>

        <footer className="shrink-0 border-t border-slate-200 bg-white/96 px-7 py-4 shadow-[0_-12px_30px_rgba(15,23,42,0.04)] backdrop-blur-xl">
          <div className="flex items-center justify-between gap-5">
            <div className="min-w-0 text-[11px]">
              {dirty ? (
                <span className="inline-flex items-center gap-2 font-medium text-amber-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                  {apiKey.trim() ? "有未保存内容 · 普通字段草稿已自动保存，API Key 不落本地" : "有未保存内容 · 草稿已自动保存"}
                </span>
              ) : (
                <span className="inline-flex items-center gap-2 text-slate-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                  等待填写模型配置
                </span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2.5">
              <Button variant="secondary" onClick={requestClose} disabled={loading} className="border-slate-200 bg-white shadow-none">取消</Button>
              <Button
                onClick={handleSave}
                disabled={loading || !valid || featureConflicts.length > 0}
                className="min-w-[112px] shadow-none"
              >
                {loading ? "创建中..." : featureConflicts.length > 0 ? "映射冲突" : "创建模型"}
              </Button>
            </div>
          </div>
        </footer>
      </aside>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Model configuration inspector drawer
// ---------------------------------------------------------------------------

type DrawerTab = "basic" | "api" | "features";

type ModelDrawerDraft = {
  version: 3;
  sourceUpdatedAt: string | null;
  sourceFingerprint: string;
  name: string;
  displayName: string;
  provider: string;
  modelKind: ModelKind;
  apiBaseUrl: string;
  features: string[];
  savedAt: number;
};

type LegacyModelDrawerDraft = Omit<ModelDrawerDraft, "version" | "sourceFingerprint"> & {
  version: 2;
  sourceFeaturesSignature: string;
};

type StoredModelDrawerDraft = ModelDrawerDraft | LegacyModelDrawerDraft;

const DRAWER_TABS: { key: DrawerTab; label: string }[] = [
  { key: "basic", label: "基础配置" },
  { key: "api", label: "API 配置" },
  { key: "features", label: "功能映射" },
];

const DRAWER_FEATURE_OPTIONS = CHAT_FEATURE_OPTIONS.map((option) => {
  const label = FEATURE_LABELS[option.value]?.label ?? option.label;
  if (option.value === "analysis") return { ...option, label, desc: "用于题目解析与错题分析生成" };
  if (option.value === "completion") return { ...option, label, desc: "用于缺失题干或答案内容补全" };
  if (option.value === "ai_repair") return { ...option, label, desc: "用于内容审核和质量检查" };
  return { ...option, label };
});

function modelDraftStorageKey(modelId: number) {
  return `ai-settings:model-draft:${modelId}`;
}

function normalizedModelFeatures(model: AdminAiModelConfig) {
  return featuresForKind(getModelKind(model), configuredFeatures(model));
}

function modelServerFingerprint(model: AdminAiModelConfig): string {
  return JSON.stringify({
    name: model.name,
    displayName: model.display_name,
    provider: model.provider,
    modelKind: getModelKind(model),
    apiBaseUrl: (model.api_base_url ?? "").trim().replace(/\/$/, ""),
    features: [...normalizedModelFeatures(model)].sort(),
  });
}

function draftDiffersFromServer(draft: StoredModelDrawerDraft, model: AdminAiModelConfig): boolean {
  const draftFeatures = rememberedChatFeatures(Array.isArray(draft.features) ? draft.features : []);
  return (
    (draft.name ?? model.name).trim() !== model.name
    || (draft.displayName ?? model.display_name).trim() !== model.display_name
    || (draft.provider ?? model.provider).trim() !== model.provider
    || (draft.modelKind ?? getModelKind(model)) !== getModelKind(model)
    || (draft.apiBaseUrl ?? "").trim().replace(/\/$/, "") !== (model.api_base_url ?? "").trim().replace(/\/$/, "")
    || featureSignature(draftFeatures) !== featureSignature(rememberedChatFeatures(configuredFeatures(model)))
  );
}

function ModelConfigDrawer({
  model,
  models,
  onClose,
  onSave,
  onSetDefault,
  onToggle,
  onDelete,
  disabled,
}: {
  model: AdminAiModelConfig;
  models: AdminAiModelConfig[];
  onClose: () => void;
  onSave: (id: number, data: AdminAiModelConfigPatchRequest) => Promise<AdminAiModelConfig>;
  onSetDefault: () => void;
  onToggle: () => void;
  onDelete: () => void;
  disabled: boolean;
}) {
  const [visible, setVisible] = useState(false);
  const [activeTab, setActiveTab] = useState<DrawerTab>("api");
  const [nameInput, setNameInput] = useState(model.name);
  const [displayNameInput, setDisplayNameInput] = useState(model.display_name);
  const [providerInput, setProviderInput] = useState(model.provider);
  const [modelKind, setModelKind] = useState<ModelKind>(() => getModelKind(model));
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [apiBaseUrlInput, setApiBaseUrlInput] = useState(model.api_base_url ?? "");
  const [featuresInput, setFeaturesInput] = useState<string[]>(() => rememberedChatFeatures(configuredFeatures(model)));
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestConnectionResponse | null>(null);
  const [showApiKey, setShowApiKey] = useState(false);
  const [draftReady, setDraftReady] = useState(false);
  const [recoverableDraft, setRecoverableDraft] = useState<StoredModelDrawerDraft | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const basicSectionRef = useRef<HTMLElement>(null);
  const apiSectionRef = useRef<HTMLElement>(null);
  const featuresSectionRef = useRef<HTMLElement>(null);

  const effectiveFeaturesInput = featuresForKind(modelKind, featuresInput);
  const baselineFeatures = normalizedModelFeatures(model);
  const baselineRememberedFeatures = rememberedChatFeatures(configuredFeatures(model));
  const normalizedApiBaseUrl = apiBaseUrlInput.trim().replace(/\/$/, "");
  const baselineApiBaseUrl = (model.api_base_url ?? "").trim().replace(/\/$/, "");
  const persistentDirty =
    nameInput.trim() !== model.name ||
    displayNameInput.trim() !== model.display_name ||
    providerInput.trim() !== model.provider ||
    modelKind !== getModelKind(model) ||
    normalizedApiBaseUrl !== baselineApiBaseUrl ||
    JSON.stringify(effectiveFeaturesInput) !== JSON.stringify(baselineFeatures);
  const rememberedFeaturesDirty = JSON.stringify(featuresInput) !== JSON.stringify(baselineRememberedFeatures);
  const draftDirty = persistentDirty || rememberedFeaturesDirty;
  const dirty = persistentDirty || Boolean(apiKeyInput.trim());
  const featureConflicts = model.is_enabled
    ? findEnabledFeatureConflicts(effectiveFeaturesInput, models.filter((item) => item.id !== model.id))
    : [];
  const valid = Boolean(nameInput.trim() && displayNameInput.trim() && providerInput.trim() && normalizedApiBaseUrl);

  const requestClose = useCallback(() => {
    setVisible(false);
    window.setTimeout(onClose, 220);
  }, [onClose]);

  const resetToServer = useCallback(() => {
    setNameInput(model.name);
    setDisplayNameInput(model.display_name);
    setProviderInput(model.provider);
    setModelKind(getModelKind(model));
    setApiBaseUrlInput(model.api_base_url ?? "");
    setFeaturesInput(rememberedChatFeatures(configuredFeatures(model)));
    setApiKeyInput("");
    setShowApiKey(false);
    setTestResult(null);
    setSaveError(null);
    setRecoverableDraft(null);
    try {
      window.localStorage.removeItem(modelDraftStorageKey(model.id));
    } catch {
      // Ignore storage failures; the server-backed form remains usable.
    }
  }, [model]);

  useEffect(() => {
    const enterFrame = window.requestAnimationFrame(() => setVisible(true));
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(enterFrame);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [requestClose]);

  useEffect(() => {
    // 数据库始终是打开 Drawer 时的回显来源。本地草稿只作为“可恢复版本”保留，
    // 不再自动写回表单，避免旧草稿覆盖服务端最新能力映射或其他配置。
    setNameInput(model.name);
    setDisplayNameInput(model.display_name);
    setProviderInput(model.provider);
    setModelKind(getModelKind(model));
    setApiBaseUrlInput(model.api_base_url ?? "");
    setFeaturesInput(rememberedChatFeatures(configuredFeatures(model)));
    setApiKeyInput("");
    setShowApiKey(false);
    setTestResult(null);
    setSaveError(null);
    setRecoverableDraft(null);
    setDraftReady(false);

    try {
      const raw = window.localStorage.getItem(modelDraftStorageKey(model.id));
      if (raw) {
        const draft = JSON.parse(raw) as StoredModelDrawerDraft;
        const sourceUpdatedAtMatches =
          !draft.sourceUpdatedAt || !model.updated_at || draft.sourceUpdatedAt === model.updated_at;
        const sourceMatches = draft.version === 3
          ? draft.sourceFingerprint === modelServerFingerprint(model)
          : draft.version === 2
            && sourceUpdatedAtMatches
            && draft.sourceFeaturesSignature === featureSignature(configuredFeatures(model));

        if (sourceMatches && draftDiffersFromServer(draft, model)) {
          setRecoverableDraft(draft);
        } else {
          // 服务端配置已变化、草稿已与服务端一致，或草稿版本无效时直接清理。
          window.localStorage.removeItem(modelDraftStorageKey(model.id));
        }
      }
    } catch {
      try {
        window.localStorage.removeItem(modelDraftStorageKey(model.id));
      } catch {
        // Ignore storage failures; server-backed values remain authoritative.
      }
    } finally {
      setDraftReady(true);
    }
  }, [model]);

  const restoreDraft = useCallback(() => {
    if (!recoverableDraft) return;
    setNameInput(recoverableDraft.name ?? model.name);
    setDisplayNameInput(recoverableDraft.displayName ?? model.display_name);
    setProviderInput(recoverableDraft.provider ?? model.provider);
    setModelKind(recoverableDraft.modelKind ?? getModelKind(model));
    setApiBaseUrlInput(recoverableDraft.apiBaseUrl ?? (model.api_base_url ?? ""));
    setFeaturesInput(
      Array.isArray(recoverableDraft.features)
        ? rememberedChatFeatures(recoverableDraft.features)
        : rememberedChatFeatures(configuredFeatures(model)),
    );
    setRecoverableDraft(null);
    setTestResult(null);
    setSaveError(null);
  }, [model, recoverableDraft]);

  const discardRecoverableDraft = useCallback(() => {
    setRecoverableDraft(null);
    try {
      window.localStorage.removeItem(modelDraftStorageKey(model.id));
    } catch {
      // Ignore storage failures; the server-backed form remains usable.
    }
  }, [model.id]);

  useEffect(() => {
    if (!draftReady) return;

    // 如果用户在“恢复草稿”提示未处理时直接开始编辑，视为以数据库版本为基线新建草稿，
    // 自动替换旧草稿，而不是让旧草稿重新覆盖当前表单。
    if (recoverableDraft && !draftDirty) return;
    if (recoverableDraft && draftDirty) setRecoverableDraft(null);

    try {
      if (!draftDirty) {
        window.localStorage.removeItem(modelDraftStorageKey(model.id));
        return;
      }
      const draft: ModelDrawerDraft = {
        version: 3,
        sourceUpdatedAt: model.updated_at ?? null,
        sourceFingerprint: modelServerFingerprint(model),
        name: nameInput,
        displayName: displayNameInput,
        provider: providerInput,
        modelKind,
        apiBaseUrl: apiBaseUrlInput,
        features: featuresInput,
        savedAt: Date.now(),
      };
      window.localStorage.setItem(modelDraftStorageKey(model.id), JSON.stringify(draft));
    } catch {
      // Local draft persistence is best-effort and must not block editing.
    }
  }, [
    apiBaseUrlInput,
    displayNameInput,
    draftReady,
    featuresInput,
    model,
    modelKind,
    nameInput,
    draftDirty,
    providerInput,
    recoverableDraft,
  ]);

  const scrollToTab = useCallback((tab: DrawerTab, behavior: ScrollBehavior = "smooth") => {
    setActiveTab(tab);
    const container = bodyRef.current;
    const section = tab === "basic"
      ? basicSectionRef.current
      : tab === "features"
        ? featuresSectionRef.current
        : apiSectionRef.current;
    if (!container || !section) return;
    const top = section.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop - 12;
    container.scrollTo({ top: Math.max(top, 0), behavior });
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => scrollToTab("api", "auto"));
    return () => window.cancelAnimationFrame(frame);
  }, [scrollToTab]);

  const handleTestConnection = async () => {
    if (!normalizedApiBaseUrl || !nameInput.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiRequest<ModelTestConnectionResponse>("/ai-models/test-connection", {
        method: "POST",
        body: JSON.stringify({
          api_base_url: normalizedApiBaseUrl,
          api_key: apiKeyInput.trim() || undefined,
          model_name: nameInput.trim(),
          model_id: model.id,
          provider: providerInput.trim(),
          features: effectiveFeaturesInput,
        } satisfies ModelTestConnectionRequest),
      });
      setTestResult(result);
    } catch (err) {
      setTestResult({ success: false, status: "network_error", message: getErrorMessage(err), latency_ms: null });
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    if (!dirty || !valid || featureConflicts.length > 0 || disabled) return;
    const payload: AdminAiModelConfigPatchRequest = {};
    if (nameInput.trim() !== model.name) payload.name = nameInput.trim();
    if (displayNameInput.trim() !== model.display_name) payload.display_name = displayNameInput.trim();
    if (providerInput.trim() !== model.provider) payload.provider = providerInput.trim();
    if (apiKeyInput.trim()) payload.api_key = apiKeyInput.trim();
    if (normalizedApiBaseUrl !== baselineApiBaseUrl) payload.api_base_url = normalizedApiBaseUrl;
    if (JSON.stringify(effectiveFeaturesInput) !== JSON.stringify(baselineFeatures)) {
      payload.features = effectiveFeaturesInput.length > 0 ? effectiveFeaturesInput : null;
    }

    setSaveError(null);
    try {
      const result = await onSave(model.id, payload);
      setNameInput(result.name);
      setDisplayNameInput(result.display_name);
      setProviderInput(result.provider);
      setModelKind(getModelKind(result));
      setApiBaseUrlInput(result.api_base_url ?? "");
      setFeaturesInput(rememberedChatFeatures(configuredFeatures(result)));
      setApiKeyInput("");
      setShowApiKey(false);
      try {
        window.localStorage.removeItem(modelDraftStorageKey(model.id));
      } catch {
        // Saving to the server succeeded; local storage cleanup is best-effort.
      }
    } catch (error) {
      setSaveError(getErrorMessage(error));
    }
  };

  const statusText = model.is_enabled ? "运行中" : "已禁用";

  return createPortal(
    <div
      className={cn(
        "fixed inset-0 z-40 flex justify-end backdrop-blur-[0.5px] transition-[background-color] duration-200",
        visible ? "bg-slate-950/[0.10]" : "bg-slate-950/0",
      )}
      onMouseDown={requestClose}
    >
      <aside
        aria-label={`${model.display_name} 模型配置`}
        onMouseDown={(event) => event.stopPropagation()}
        className={cn(
          "flex h-full w-[clamp(720px,46vw,820px)] max-w-[calc(100vw-24px)] flex-col border-l border-slate-200/80 bg-white shadow-[-18px_0_52px_rgba(15,23,42,0.12)] will-change-transform transition-transform duration-200 ease-out",
          visible ? "translate-x-0" : "translate-x-full",
        )}
      >
        <header className="shrink-0 border-b border-slate-200/80 bg-white/95 px-7 pt-3 backdrop-blur-xl">
          <div className="flex min-h-14 items-center justify-between gap-4 pb-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2.5">
                <h3 className="truncate text-[17px] font-semibold tracking-[-0.01em] text-slate-950">{displayNameInput || model.display_name}</h3>
                {persistentDirty ? <span className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">草稿</span> : null}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
                <span className="font-mono text-slate-400">{nameInput || model.name}</span>
                <span className="inline-flex items-center gap-1.5 font-medium text-slate-500">
                  <span className={cn("h-1.5 w-1.5 rounded-full", model.is_enabled ? "bg-emerald-500" : "bg-slate-300")} />
                  {statusText}
                </span>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <details className="relative">
                <summary className="grid h-9 w-9 cursor-pointer list-none place-items-center rounded-lg text-slate-400 transition-[background-color,color,transform] hover:bg-slate-100 hover:text-slate-800 active:scale-95 [&::-webkit-details-marker]:hidden" aria-label="更多模型操作">
                  <MoreHorizontal className="h-4 w-4" />
                </summary>
                <div className="absolute right-0 top-10 z-20 min-w-[168px] overflow-hidden rounded-xl border border-slate-200 bg-white p-1.5 text-xs shadow-[0_12px_34px_rgba(15,23,42,0.14)]">
                  {model.is_enabled && !model.is_default ? (
                    <button type="button" onClick={onSetDefault} disabled={disabled} className="w-full rounded-lg px-3 py-2 text-left font-medium text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-950 disabled:opacity-50">设为默认模型</button>
                  ) : null}
                  <button type="button" onClick={onToggle} disabled={disabled} className="w-full rounded-lg px-3 py-2 text-left font-medium text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-950 disabled:opacity-50">
                    {model.is_enabled ? "禁用模型" : "启用模型"}
                  </button>
                  {persistentDirty || recoverableDraft ? (
                    <button type="button" onClick={resetToServer} disabled={disabled} className="w-full rounded-lg px-3 py-2 text-left font-medium text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-950 disabled:opacity-50">丢弃本地草稿</button>
                  ) : null}
                  <div className="my-1 h-px bg-slate-100" />
                  <button type="button" onClick={onDelete} disabled={disabled} className="w-full rounded-lg px-3 py-2 text-left font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50">删除配置</button>
                </div>
              </details>
              <button
                type="button"
                onClick={requestClose}
                className="grid h-9 w-9 place-items-center rounded-lg text-slate-400 transition-[background-color,color,transform] hover:bg-slate-100 hover:text-slate-900 active:scale-95"
                aria-label="关闭模型配置"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <nav className="flex gap-6" aria-label="模型配置分区">
            {DRAWER_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => scrollToTab(tab.key)}
                className={cn(
                  "relative pb-3 text-[13px] font-semibold transition-colors",
                  activeTab === tab.key ? "text-[var(--color-primary)]" : "text-slate-400 hover:text-slate-700",
                )}
              >
                {tab.label}
                <span
                  className={cn(
                    "absolute inset-x-0 -bottom-px h-0.5 origin-center rounded-full bg-[var(--color-primary)] transition-transform duration-200",
                    activeTab === tab.key ? "scale-x-100" : "scale-x-0",
                  )}
                />
              </button>
            ))}
          </nav>
        </header>

        <div ref={bodyRef} className="min-h-0 flex-1 overflow-y-auto scroll-smooth bg-white px-7 pb-24 pt-1">
          {recoverableDraft ? (
            <div className="mt-3 flex items-center justify-between gap-4 border-y border-amber-200/80 bg-amber-50/55 px-3 py-2.5 text-[11px]">
              <div className="flex min-w-0 items-start gap-2.5 text-amber-800">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <div className="min-w-0">
                  <p className="font-semibold">检测到未保存的本地草稿</p>
                  <p className="mt-0.5 text-amber-700/80">当前优先显示数据库配置；仅在你主动恢复后才会应用草稿。</p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <button
                  type="button"
                  onClick={discardRecoverableDraft}
                  className="rounded-md px-2.5 py-1.5 font-medium text-amber-700 transition-colors hover:bg-amber-100/70"
                >
                  丢弃
                </button>
                <button
                  type="button"
                  onClick={restoreDraft}
                  className="rounded-md border border-amber-300 bg-white px-2.5 py-1.5 font-semibold text-amber-800 transition-[border-color,background-color,transform] hover:border-amber-400 hover:bg-amber-50 active:scale-[0.98]"
                >
                  恢复草稿
                </button>
              </div>
            </div>
          ) : null}

          <section ref={basicSectionRef} className="scroll-mt-3 border-b border-slate-200 py-5">
            <div className="mb-4">
              <h4 className="text-[13px] font-semibold text-slate-950">模型信息</h4>
              <p className="mt-0.5 text-[11px] text-slate-400">用于识别模型并确定调用接口类型。</p>
            </div>

            <div className="grid gap-x-4 gap-y-4 md:grid-cols-2">
              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">模型标识</span>
                <input
                  value={nameInput}
                  onChange={(event) => { setNameInput(event.target.value); setTestResult(null); }}
                  disabled={disabled}
                  className={cn(inputCls, "mt-1.5 h-10 bg-slate-50/45 transition-[border-color,background-color,box-shadow] focus:bg-white focus:ring-2 focus:ring-[var(--color-primary)]/10 disabled:opacity-50")}
                />
              </label>
              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">显示名称</span>
                <input
                  value={displayNameInput}
                  onChange={(event) => setDisplayNameInput(event.target.value)}
                  disabled={disabled}
                  className={cn(inputCls, "mt-1.5 h-10 bg-slate-50/45 transition-[border-color,background-color,box-shadow] focus:bg-white focus:ring-2 focus:ring-[var(--color-primary)]/10 disabled:opacity-50")}
                />
              </label>
              <div className="md:col-span-2 grid gap-2 sm:grid-cols-[92px_minmax(0,1fr)] sm:items-start">
                <span className="pt-2.5 text-[11px] font-medium text-slate-500">模型类型</span>
                <div className="min-w-0">
                  <div className="grid w-full max-w-[560px] grid-cols-3 gap-2">
                    {(Object.keys(MODEL_KIND_META) as ModelKind[]).map((kind) => {
                      const selected = modelKind === kind;
                      return (
                        <button
                          key={kind}
                          type="button"
                          disabled={disabled}
                          onClick={() => {
                            setModelKind(kind);
                            setTestResult(null);
                            if (kind === "ocr_job" && providerInput === "openai") setProviderInput("paddleocr-vl");
                          }}
                          className={cn(
                            "relative flex h-10 items-center justify-center rounded-md border-2 px-3 text-[12px] font-medium transition-[border-color,background-color,color,box-shadow,transform] duration-200 ease-out active:scale-[0.985] disabled:opacity-50",
                            selected
                              ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/25 text-slate-900 shadow-[0_1px_3px_rgba(15,23,42,0.035)]"
                              : "border-slate-200/90 bg-white text-slate-500 hover:border-slate-300 hover:bg-slate-50/70 hover:text-slate-700",
                          )}
                        >
                          {MODEL_KIND_META[kind].label}
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-1.5 max-w-[560px] text-[10px] leading-4 text-slate-400 transition-colors duration-200">{MODEL_KIND_META[modelKind].desc}</p>
                </div>
              </div>
            </div>
          </section>

          <section ref={apiSectionRef} className="scroll-mt-3 border-b border-slate-200 py-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h4 className="flex items-center gap-2 text-[13px] font-semibold text-slate-950"><Key className="h-3.5 w-3.5 text-[var(--color-primary)]" />API 接入</h4>
                <p className="mt-0.5 text-[11px] text-slate-400">配置 Provider、接口地址与访问凭证。</p>
              </div>
              <span className="rounded-md border border-slate-200/90 bg-slate-50/70 px-2 py-1 text-[10px] font-medium text-slate-500">{adapterLabel(providerInput)}</span>
            </div>

            <div className="max-w-[680px] space-y-4">
              {modelKind === "chat" ? (
                <CompatibleExampleImporter
                  disabled={disabled}
                  onApply={(parsed) => {
                    if (parsed.apiBaseUrl) setApiBaseUrlInput(parsed.apiBaseUrl);
                    if (parsed.modelName) setNameInput(parsed.modelName);
                    setProviderInput("relay");
                    setTestResult(null);
                  }}
                />
              ) : null}

              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">Provider / 接入方式</span>
                <ProviderSelect
                  value={providerInput}
                  onChange={(value) => { setProviderInput(value); setTestResult(null); }}
                  disabled={disabled}
                  placeholder="relay / openai / deepseek / custom"
                />
                <span className="mt-1 block text-[10px] leading-4 text-slate-400">接第三方 API 服务建议选择「第三方 / Relay」，模型标识仍填写服务商实际要求的 model。</span>
              </label>

              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">API 地址</span>
                <div className="relative mt-1.5">
                  <input
                    value={apiBaseUrlInput}
                    onChange={(event) => { setApiBaseUrlInput(event.target.value); setTestResult(null); }}
                    disabled={disabled}
                    className={cn(inputCls, "h-10 bg-slate-50/45 pr-9 transition-[border-color,background-color,box-shadow] focus:bg-white focus:ring-2 focus:ring-[var(--color-primary)]/10 disabled:opacity-50")}
                    placeholder="https://8stoken.com/v1"
                  />
                  <Link2 className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-300" />
                </div>
                <CompatibleEndpointHint apiBaseUrl={apiBaseUrlInput} kind={modelKind} />
              </label>

              <label className="block">
                <span className="text-[11px] font-medium text-slate-500">API Key</span>
                <div className="relative mt-1.5">
                  <input
                    type={showApiKey ? "text" : "password"}
                    value={apiKeyInput}
                    onChange={(event) => { setApiKeyInput(event.target.value); setTestResult(null); }}
                    disabled={disabled}
                    className={cn(inputCls, "h-10 bg-slate-50/45 pr-10 transition-[border-color,background-color,box-shadow] focus:bg-white focus:ring-2 focus:ring-[var(--color-primary)]/10 disabled:opacity-50")}
                    placeholder={model.api_configured ? "" : "sk-..."}
                    autoComplete="new-password"
                    aria-label={model.api_configured ? "API Key（已保存，输入新值可替换）" : "API Key"}
                  />
                  {model.api_configured && !apiKeyInput ? (
                    <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-3 flex items-center select-none text-sm tracking-[0.16em] text-slate-500">••••••••••••••••••••••</span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setShowApiKey((previous) => !previous)}
                    disabled={!apiKeyInput}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 transition-colors hover:text-[var(--color-primary)] disabled:cursor-default disabled:opacity-45"
                    aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"}
                  >
                    {showApiKey && apiKeyInput ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </button>
                </div>
                <p className="mt-1 text-[10px] leading-4 text-slate-400">已保存的密钥不会回显；API Key 不写入浏览器本地草稿。</p>
              </label>

              <div className="flex flex-wrap items-center gap-3 pt-0.5">
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={testing || !normalizedApiBaseUrl || !nameInput.trim() || (!model.api_configured && !apiKeyInput.trim())}
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 text-xs font-semibold text-slate-600 transition-[border-color,background-color,color,transform] duration-150 hover:border-[var(--color-primary)]/35 hover:bg-[var(--color-primary-light)]/35 hover:text-[var(--color-primary)] active:scale-[0.98] disabled:opacity-40"
                >
                  {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                  测试连接
                </button>
                <span className="text-[10px] text-slate-400">修改接口或模型标识后建议重新测试。</span>
              </div>

              {testResult ? (
                <div className="max-w-[680px] border-t border-slate-200 pt-2.5 text-[11px] leading-5">
                  <div className="flex min-w-0 items-start gap-2">
                    <span
                      className={cn(
                        "mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full",
                        testResult.success ? "bg-emerald-500" : "bg-rose-500",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      {testResult.success ? (
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span className="font-medium text-slate-700">连接成功</span>
                          {testResult.latency_ms != null ? <span className="text-slate-400">响应时间 {testResult.latency_ms}ms</span> : null}
                          <span className="text-slate-400">模型接口可正常使用</span>
                        </div>
                      ) : (
                        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span className="shrink-0 font-medium text-rose-700">连接失败</span>
                          <span className="min-w-0 break-words text-slate-500">{testResult.message}</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </section>

          <section ref={featuresSectionRef} className="scroll-mt-3 py-5">
            <div className="mb-3">
              <h4 className="text-[13px] font-semibold text-slate-950">能力映射</h4>
              <p className="mt-0.5 text-[11px] text-slate-400">决定各 AI 功能优先使用的模型。</p>
            </div>

            {modelKind === "chat" ? (
              <div className="max-w-[680px] divide-y divide-slate-200 border-y border-slate-200">
                {DRAWER_FEATURE_OPTIONS.map((option) => {
                  const selected = featuresInput.includes(option.value);
                  const conflict = featureConflicts.find((item) => item.feature === option.value);
                  return (
                    <label
                      key={option.value}
                      className={cn(
                        "flex cursor-pointer items-start gap-3 px-2 py-3 transition-colors",
                        selected ? "bg-[var(--color-primary-light)]/32" : "hover:bg-slate-50/80",
                        conflict && "bg-amber-50/65",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={selected}
                        disabled={disabled}
                        onChange={() => setFeaturesInput((previous) => previous.includes(option.value) ? previous.filter((feature) => feature !== option.value) : [...previous, option.value])}
                      />
                      <span className={cn("mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors", selected ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white" : "border-slate-300 bg-white")}>
                        {selected ? <CheckCircle2 className="h-2.5 w-2.5" /> : null}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold text-slate-800">{option.label}</span>
                          {conflict ? <span className="text-[10px] font-medium text-amber-700">当前由「{conflict.model.display_name}」占用</span> : null}
                        </span>
                        <span className="mt-0.5 block text-[11px] leading-4 text-slate-400">{option.desc}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <div className="max-w-[680px] border-y border-slate-200 py-3">
                <p className="text-xs font-semibold text-slate-800">{modelKind === "embedding" ? "Vector Embedding" : "视觉 OCR Job"}</p>
                <p className="mt-1 text-[11px] leading-5 text-slate-400">{MODEL_KIND_META[modelKind].desc}</p>
              </div>
            )}

            {featureConflicts.length > 0 ? (
              <div className="mt-3 max-w-[680px] border-t border-slate-200 pt-3 text-[11px] leading-5">
                <div className="flex items-start gap-2">
                  <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
                  <p className="min-w-0 text-slate-500">
                    <span className="mr-2 font-medium text-slate-700">功能映射冲突</span>
                    请先禁用占用该功能的模型，或取消当前映射后再保存。
                  </p>
                </div>
              </div>
            ) : null}

            {saveError ? (
              <div role="alert" className="mt-3 max-w-[680px] border-t border-slate-200 pt-3 text-[11px] leading-5">
                <div className="flex items-start gap-2">
                  <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500" />
                  <p className="min-w-0 break-words text-slate-500">
                    <span className="mr-2 font-medium text-rose-700">保存失败</span>
                    {saveError}
                  </p>
                </div>
              </div>
            ) : null}
          </section>
        </div>

        <footer className="shrink-0 border-t border-slate-200 bg-white/96 px-7 py-4 shadow-[0_-12px_30px_rgba(15,23,42,0.04)] backdrop-blur-xl">
          <div className="flex items-center justify-between gap-5">
            <div className="min-w-0 text-[11px]">
              {dirty ? (
                <span className="inline-flex items-center gap-2 font-medium text-amber-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                  {apiKeyInput.trim() ? "有未保存的修改 · 普通字段草稿已自动保存，API Key 不落本地" : "有未保存的修改 · 草稿已自动保存"}
                </span>
              ) : recoverableDraft ? (
                <span className="inline-flex items-center gap-2 font-medium text-amber-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                  当前显示数据库配置 · 有本地草稿可恢复
                </span>
              ) : (
                <span className="inline-flex items-center gap-2 text-slate-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  配置已同步
                </span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2.5">
              <Button variant="secondary" onClick={requestClose} disabled={disabled} className="border-slate-200 bg-white shadow-none">取消</Button>
              <Button onClick={save} disabled={disabled || !dirty || !valid || featureConflicts.length > 0} className="min-w-[112px] shadow-none">
                {disabled ? "保存中..." : featureConflicts.length > 0 ? "映射冲突" : "保存配置"}
              </Button>
            </div>
          </div>
        </footer>
      </aside>
    </div>,
    document.body,
  );

}


// ---------------------------------------------------------------------------
// Main Export
// ---------------------------------------------------------------------------

function showToast(msg: string) {
  const el = document.createElement("div");
  el.className = "fixed left-1/2 top-4 z-[200] -translate-x-1/2 rounded-xl border border-[var(--color-success)]/30 bg-white px-5 py-3 text-sm font-semibold text-[var(--color-success)] shadow-[var(--shadow-card)] animate-rise-in";
  el.innerHTML = `<svg class="-mt-0.5 mr-1.5 inline-block h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>${msg}`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2500);
}

export function ModelCards() {
  const queryClient = useQueryClient();
  const [showAddDrawer, setShowAddDrawer] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AdminAiModelConfig | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const models = useQuery({
    queryKey: ["ai-models"],
    queryFn: () => apiRequest<AdminAiModelConfig[]>("/ai-models"),
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: AdminAiModelConfigPatchRequest }) =>
      apiRequest<AdminAiModelConfig>(`/ai-models/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: (result) => {
      queryClient.setQueryData<AdminAiModelConfig[]>(["ai-models"], (old) => {
        if (!old) return [result];
        return old.map((m) => (m.id === result.id ? { ...result } : m));
      });
      showToast("模型配置已保存");
    },
    onError: () => queryClient.invalidateQueries({ queryKey: ["ai-models"] }),
  });

  const createMutation = useMutation({
    mutationFn: (data: AdminAiModelConfigCreateRequest) =>
      apiRequest<AdminAiModelConfig>("/ai-models", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["ai-models"] }); showToast("模型已添加"); },
    onError: () => queryClient.invalidateQueries({ queryKey: ["ai-models"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiRequest<void>(`/ai-models/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ai-models"] });
      setSelectedId(null);
    },
  });

  const toggleModel = (model: AdminAiModelConfig) => {
    patchMutation.mutate({ id: model.id, data: { is_enabled: !model.is_enabled } });
  };

  const handleSaveApiConfig = (id: number, data: AdminAiModelConfigPatchRequest) =>
    patchMutation.mutateAsync({ id, data });

  const setDefault = (model: AdminAiModelConfig) => {
    patchMutation.mutate({ id: model.id, data: { is_default: true } });
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate(deleteTarget.id);
    setDeleteTarget(null);
  };

  const modelList = models.data ?? [];
  const selectedModel = modelList.find((model) => model.id === selectedId) ?? null;

  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--color-border)]/80 bg-white/80 shadow-[var(--shadow-card)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)]/60 px-5 py-4">
        <h3 className="font-display text-xl font-bold text-[var(--ink)]">模型配置</h3>
        <Button onClick={() => setShowAddDrawer(true)}>
          <Plus className="h-4 w-4" />
          添加模型
        </Button>
      </div>

      {/* Errors */}
      {[patchMutation, deleteMutation, models].map((q, i) =>
        q.isError ? (
          <p key={i} className="mx-5 mt-3 rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
            {getErrorMessage(q.error)}
          </p>
        ) : null,
      )}

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-[var(--color-border)]/60">
              <th className="px-5 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">模型</th>
              <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">提供商</th>
              <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">功能映射</th>
              <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">状态</th>
              <th className="px-4 py-2.5 text-right text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">操作</th>
            </tr>
          </thead>
          <tbody>
            {models.isLoading
              ? Array.from({ length: 3 }).map((_, i) => (
                  <tr key={i} className="border-b border-[var(--color-border)]/40">
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-3">
                        <div className="h-8 w-8 animate-pulse rounded-lg bg-[var(--color-border)]" />
                        <div className="space-y-1.5">
                          <div className="h-3.5 w-24 animate-pulse rounded bg-[var(--color-border)]" />
                          <div className="h-2.5 w-16 animate-pulse rounded bg-[var(--color-border)]" />
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-4"><div className="h-3 w-14 animate-pulse rounded bg-[var(--color-border)]" /></td>
                    <td className="px-4 py-4"><div className="h-5 w-20 animate-pulse rounded bg-[var(--color-border)]" /></td>
                    <td className="px-4 py-4"><div className="h-5 w-12 animate-pulse rounded bg-[var(--color-border)]" /></td>
                    <td className="px-4 py-4"><div className="ml-auto h-7 w-14 animate-pulse rounded bg-[var(--color-border)]" /></td>
                  </tr>
                ))
              : modelList.map((model) => {
                  const Icon = getProviderIcon(model.provider);
                  const color = getProviderColor(model.provider);
                  const featureList = configuredFeatures(model)
                    .map((feature) => FEATURE_LABELS[feature])
                    .filter(Boolean);
                  const isSelected = selectedId === model.id;

                  return (
                    <React.Fragment key={model.id}>
                      <tr
                        onClick={() => setSelectedId(model.id)}
                        className={cn(
                          "cursor-pointer border-b border-[var(--color-border)]/40 transition-colors",
                          isSelected
                            ? "bg-[var(--color-primary-light)]"
                            : "hover:bg-[var(--color-bg-input)]/40",
                          !model.is_enabled && "opacity-50",
                        )}
                      >
                        {/* Model name */}
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2.5">
                            <div
                              className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border"
                              style={{ background: `${color}08`, borderColor: `${color}25` }}
                            >
                              <Icon className="h-4 w-4" style={{ color }} />
                            </div>
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-[13px] font-semibold text-[var(--ink)]">{model.display_name}</span>
                                {model.is_default && (
                                  <span
                                    className="rounded-full px-1.5 py-0.5 text-[9px] font-bold text-white"
                                    style={{ backgroundColor: color }}
                                  >
                                    默认
                                  </span>
                                )}
                              </div>
                              <span className="text-[11px] text-[var(--color-text-hint)] font-mono">{model.name}</span>
                            </div>
                          </div>
                        </td>

                        {/* Provider */}
                        <td className="px-4 py-3 text-xs text-[var(--color-text-secondary)]">
                          <div className="font-medium">{model.provider}</div>
                          <div className="mt-0.5 text-[9px] text-[var(--color-text-hint)]">
                            {MODEL_KIND_META[getModelKind(model)].label} · {adapterLabel(model.provider)}
                          </div>
                        </td>

                        {/* Feature badges */}
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {featureList.length > 0
                              ? featureList.map((fi) => (
                                  <span
                                    key={fi.label}
                                    className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold"
                                    style={{ background: `${fi.color}15`, color: fi.color }}
                                  >
                                    <Tag className="h-2.5 w-2.5" />
                                    {fi.label}
                                  </span>
                                ))
                              : model.is_enabled && (
                                  <span className="rounded px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-text-hint)] bg-[var(--color-bg-input)]">
                                    通用
                                  </span>
                                )}
                          </div>
                        </td>

                        {/* Status */}
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1.5">
                            <span
                              className="inline-block h-1.5 w-1.5 rounded-full"
                              style={{ background: model.is_enabled ? "var(--color-success)" : "var(--color-border)" }}
                            />
                            <span
                              className={cn(
                                "text-[11px] font-semibold",
                                model.is_enabled ? "text-[var(--color-success)]" : "text-[var(--color-text-hint)]",
                              )}
                            >
                              {model.is_enabled ? "运行中" : "已禁用"}
                            </span>
                          </div>
                        </td>

                        {/* Actions */}
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              onClick={(e) => { e.stopPropagation(); toggleModel(model); }}
                              disabled={patchMutation.isPending}
                              className="rounded-md border border-[var(--color-border)] bg-white px-2.5 py-1 text-[11px] font-semibold text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-primary)] disabled:opacity-40"
                            >
                              {model.is_enabled ? "禁用" : "启用"}
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); setDeleteTarget(model); }}
                              disabled={deleteMutation.isPending}
                              className="rounded-md p-1 text-[var(--color-text-hint)] transition-colors hover:bg-[var(--color-danger-light)] hover:text-[var(--color-danger)] disabled:opacity-30"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                            <ChevronDown
                              className={cn(
                                "h-4 w-4 -rotate-90 text-[var(--color-text-hint)] transition-colors",
                                isSelected && "text-[var(--color-primary)]",
                              )}
                            />
                          </div>
                        </td>
                      </tr>

                    </React.Fragment>
                  );
                })}
          </tbody>
        </table>
      </div>


      {selectedModel ? (
        <ModelConfigDrawer
          key={selectedModel.id}
          model={selectedModel}
          models={modelList}
          onClose={() => setSelectedId((current) => current === selectedModel.id ? null : current)}
          onSave={handleSaveApiConfig}
          onSetDefault={() => setDefault(selectedModel)}
          onToggle={() => toggleModel(selectedModel)}
          onDelete={() => setDeleteTarget(selectedModel)}
          disabled={patchMutation.isPending}
        />
      ) : null}

      {showAddDrawer ? (
        <AddModelDrawer
          onClose={() => setShowAddDrawer(false)}
          onSave={(data) => createMutation.mutateAsync(data)}
          loading={createMutation.isPending}
          existingModels={modelList}
        />
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除模型"
        description={deleteTarget ? `确定删除「${deleteTarget.display_name}」？该操作不可撤销。` : ""}
        confirmText="删除"
        danger
        loading={deleteMutation.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </div>
  );
}
