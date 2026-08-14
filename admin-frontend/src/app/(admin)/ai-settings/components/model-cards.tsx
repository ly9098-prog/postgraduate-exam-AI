"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain, Cpu, Globe, Key,
  CheckCircle2, X, Trash2, Plus, Tag, ScanEye,
  Loader2, AlertTriangle, Wifi, ChevronDown, Eye, EyeOff, Link2,
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
import { getErrorMessage } from "@/lib/api/errors";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";

const PROVIDER_ICONS: Record<string, React.ElementType> = {
  deepseek: Brain, openai: Globe, anthropic: Cpu,
  "qwen-vl": ScanEye, qwen: ScanEye, glm: Brain, minimax: Brain,
  moonshot: Brain, openrouter: Globe, vllm: Cpu, custom: Cpu,
};

const PROVIDER_COLORS: Record<string, string> = {
  deepseek: "#5b7b9a", openai: "#6b9b6b", anthropic: "#c49a6b",
  "qwen-vl": "#7c5ce7", qwen: "#7c5ce7", glm: "#4f72b8",
  minimax: "#8b6bb1", moonshot: "#506c8f", openrouter: "#5d6b76",
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
  return isPaddleOcrProvider(provider) ? "PaddleOCR 专用" : "OpenAI 兼容";
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
// Add Model Dialog (unchanged logic, tightened UI)
// ---------------------------------------------------------------------------

function AddModelDialog({
  open, onClose, onSave, loading,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (data: AdminAiModelConfigCreateRequest) => void;
  loading: boolean;
}) {
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [modelKind, setModelKind] = useState<ModelKind>("chat");
  const [apiBaseUrl, setApiBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [features, setFeatures] = useState<string[]>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestConnectionResponse | null>(null);

  if (!open) return null;

  const effectiveFeatures = featuresForKind(modelKind, features);

  const handleTestConnection = async () => {
    if (!apiBaseUrl.trim() || !apiKey.trim() || !name.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiRequest<ModelTestConnectionResponse>("/ai-models/test-connection", {
        method: "POST",
        body: JSON.stringify({
          api_base_url: apiBaseUrl.trim(),
          api_key: apiKey.trim(),
          model_name: name.trim(),
          provider,
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

  const reset = () => {
    setName(""); setDisplayName(""); setProvider("openai"); setModelKind("chat");
    setApiBaseUrl(""); setApiKey(""); setFeatures([]); setTestResult(null);
  };

  const handleSave = () => {
    if (!name.trim() || !displayName.trim() || !provider.trim() || !apiBaseUrl.trim()) return;
    onSave({
      name: name.trim(), display_name: displayName.trim(), provider: provider.trim(),
      api_base_url: apiBaseUrl.trim(),
      api_key: apiKey.trim() || undefined,
      features: effectiveFeatures.length > 0 ? effectiveFeatures : null,
    });
  };

  const handleClose = () => { reset(); onClose(); };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(16,24,40,0.42)] px-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--color-border)] bg-white p-6 shadow-[var(--shadow-card)]">
        <div className="mb-5 flex items-center justify-between">
          <h3 className="font-display text-xl font-bold text-[var(--ink)]">添加模型</h3>
          <button onClick={handleClose} className="text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-[11px] font-medium text-[var(--color-text-hint)]">模型标识 *</span>
              <input value={name} onChange={(e) => setName(e.target.value)} className={cn(inputCls, "mt-1")} placeholder="gpt-4o" />
            </label>
            <label className="block">
              <span className="text-[11px] font-medium text-[var(--color-text-hint)]">显示名称 *</span>
              <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className={cn(inputCls, "mt-1")} placeholder="GPT-4o" />
            </label>
          </div>
          <div>
            <span className="text-[11px] font-medium text-[var(--color-text-hint)]">模型类型 *</span>
            <div className="mt-1.5 grid grid-cols-3 gap-2">
              {(Object.keys(MODEL_KIND_META) as ModelKind[]).map((kind) => {
                const selected = modelKind === kind;
                return (
                  <button
                    key={kind}
                    type="button"
                    onClick={() => {
                      setModelKind(kind);
                      setFeatures((prev) => featuresForKind(kind, prev));
                      if (kind === "ocr_job" && provider === "openai") setProvider("paddleocr-vl");
                    }}
                    className={cn(
                      "rounded-lg border px-2 py-2 text-left transition-colors",
                      selected
                        ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                        : "border-[var(--color-border)] bg-white hover:border-[var(--color-primary)]/40",
                    )}
                  >
                    <span className={cn("block text-xs font-semibold", selected ? "text-[var(--color-primary)]" : "text-[var(--ink)]")}>
                      {MODEL_KIND_META[kind].label}
                    </span>
                    <span className="mt-0.5 block text-[9px] leading-3 text-[var(--color-text-hint)]">{MODEL_KIND_META[kind].desc}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <label className="block">
            <span className="text-[11px] font-medium text-[var(--color-text-hint)]">提供商 *</span>
            <ProviderSelect value={provider} onChange={setProvider} placeholder="openai / qwen / glm / custom" />
            <span className="mt-1 block text-[10px] text-[var(--color-text-hint)]">{adapterLabel(provider)}；provider 仅用于路由标识与监控，不限制厂商名称。</span>
          </label>
          <label className="block">
            <span className="text-[11px] font-medium text-[var(--color-text-hint)]">API Base URL *</span>
            <input value={apiBaseUrl} onChange={(e) => setApiBaseUrl(e.target.value)} className={cn(inputCls, "mt-1")} placeholder="https://api.openai.com/v1" />
            <span className="mt-1 block text-[10px] leading-4 text-[var(--color-text-hint)]">
              {modelKind === "embedding"
                ? "填写 OpenAI-compatible SDK 的 base_url；阿里云百炼应以 /compatible-mode/v1 结尾，文本向量 Model ID 例如 text-embedding-v4；不要手动追加 /embeddings。"
                : modelKind === "ocr_job"
                  ? "填写厂商 OCR 服务根地址；PaddleOCR-VL 将按专用 Job API 调用。"
                  : "填写 OpenAI SDK 的 base_url，不要手动追加 /chat/completions。"}
            </span>
          </label>
          <label className="block">
            <span className="text-[11px] font-medium text-[var(--color-text-hint)]">API Key</span>
            <div className="mt-1 flex gap-2">
              <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} className={cn(inputCls, "flex-1")} placeholder="sk-..." />
              <button type="button" onClick={handleTestConnection}
                disabled={testing || !apiKey.trim() || !apiBaseUrl.trim() || !name.trim()}
                className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)] px-3 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-primary)] disabled:opacity-40">
                {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                测试
              </button>
            </div>
          </label>
          {modelKind === "chat" ? (
            <div>
              <span className="text-[11px] font-medium text-[var(--color-text-hint)]">功能映射（可多选）</span>
              <div className="mt-1.5 flex flex-wrap gap-2">
                {CHAT_FEATURE_OPTIONS.map((opt) => {
                  const selected = features.includes(opt.value);
                  return (
                    <label key={opt.value}
                      className={cn(
                        "flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors",
                        selected ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                          : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]/40",
                      )}>
                      <input type="checkbox" className="sr-only" checked={selected}
                        onChange={() => setFeatures((prev) => prev.includes(opt.value) ? prev.filter((f) => f !== opt.value) : [...prev, opt.value])} />
                      <div className={cn("flex h-3.5 w-3.5 items-center justify-center rounded border transition-colors",
                        selected ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white" : "border-[var(--color-border)]")}>
                        {selected && <CheckCircle2 className="h-2.5 w-2.5" />}
                      </div>
                      <span title={opt.desc}>{opt.label}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/40 px-3 py-2.5">
              <p className="text-xs font-semibold text-[var(--ink)]">能力：{modelKind === "embedding" ? "Vector Embedding" : "视觉 OCR Job"}</p>
              <p className="mt-0.5 text-[10px] leading-4 text-[var(--color-text-hint)]">
                {modelKind === "embedding"
                  ? "Embedding 模型只负责向量生成；在“向量”页选择当前检索使用的模型。"
                  : "OCR Job 模型用于 PaddleOCR-VL 等厂商专用视觉识别，不参与 Chat 功能映射。"}
              </p>
            </div>
          )}
        </div>

        {testResult && (
          <div className={cn("mt-3 rounded-lg px-3 py-2 text-xs",
            testResult.success ? "border border-[var(--color-success)] bg-[var(--color-success-light)] text-[var(--color-success)]"
              : "border border-[var(--color-danger)] bg-[var(--color-danger-light)] text-[var(--color-danger)]")}>
            <div className="flex items-start gap-1.5">
              {testResult.success ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
              <div className="min-w-0">
                <p className="font-semibold">{testResult.success ? "连接成功" : "连接失败"}</p>
                <p className="mt-0.5 break-words">{testResult.message}</p>
              </div>
            </div>
          </div>
        )}

        <div className="mt-4 flex justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={loading}>取消</Button>
          <Button onClick={handleSave} disabled={loading || !name.trim() || !displayName.trim() || !provider.trim() || !apiBaseUrl.trim()}>
            {loading ? "添加中..." : "添加"}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Detail Panel (expanded below table on row click)
// ---------------------------------------------------------------------------

function DetailPanel({
  model, onSaveApiConfig, onSetDefault, onDelete, disabled,
}: {
  model: AdminAiModelConfig;
  onSaveApiConfig: (id: number, data: AdminAiModelConfigPatchRequest) => void;
  onSetDefault: () => void;
  onDelete: () => void;
  disabled: boolean;
}) {
  const [nameInput, setNameInput] = useState(model.name);
  const [displayNameInput, setDisplayNameInput] = useState(model.display_name);
  const [providerInput, setProviderInput] = useState(model.provider);
  const [modelKind, setModelKind] = useState<ModelKind>(() => getModelKind(model));
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [apiBaseUrlInput, setApiBaseUrlInput] = useState(model.api_base_url ?? "");
  const [featuresInput, setFeaturesInput] = useState<string[]>(model.features ?? []);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestConnectionResponse | null>(null);
  const [showApiKey, setShowApiKey] = useState(false);
  const effectiveFeaturesInput = featuresForKind(modelKind, featuresInput);

  const handleTestConnection = async () => {
    if (!apiBaseUrlInput.trim() || !nameInput.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiRequest<ModelTestConnectionResponse>("/ai-models/test-connection", {
        method: "POST",
        body: JSON.stringify({
          api_base_url: apiBaseUrlInput.trim(),
          api_key: apiKeyInput.trim() || undefined,
          model_name: nameInput.trim(),
          model_id: model.id,
          provider: providerInput,
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

  const save = () => {
    const payload: AdminAiModelConfigPatchRequest = {};
    if (nameInput.trim() && nameInput.trim() !== model.name) payload.name = nameInput.trim();
    if (displayNameInput.trim() && displayNameInput.trim() !== model.display_name) payload.display_name = displayNameInput.trim();
    if (providerInput.trim() && providerInput.trim() !== model.provider) payload.provider = providerInput.trim();
    if (apiKeyInput) payload.api_key = apiKeyInput;
    if (apiBaseUrlInput !== model.api_base_url) payload.api_base_url = apiBaseUrlInput;
    if (JSON.stringify(effectiveFeaturesInput) !== JSON.stringify(model.features ?? [])) {
      payload.features = effectiveFeaturesInput.length > 0 ? effectiveFeaturesInput : null;
    }
    onSaveApiConfig(model.id, payload);
    setApiKeyInput("");
    showToast("API 配置已保存");
  };

  return (
    <tr>
      <td colSpan={5} className="border-b border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/20 p-0">
        <div className="px-5 pb-5 pt-4">
          <div className="overflow-hidden rounded-2xl border border-[var(--color-border)]/80 bg-white shadow-[0_8px_24px_rgba(40,57,73,0.06)]">
            <div className="px-5 pb-5 pt-4">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h4 className="flex items-center gap-2 text-sm font-semibold text-[var(--ink)]">
                  <Key className="h-4 w-4 text-[var(--color-primary)]" />
                  API 配置
                </h4>

                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-medium text-[var(--color-text-hint)]">模型类型</span>
                  <div className="inline-flex rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)]/45 p-0.5">
                    {(Object.keys(MODEL_KIND_META) as ModelKind[]).map((kind) => (
                      <button
                        key={kind}
                        type="button"
                        disabled={disabled}
                        onClick={() => {
                          setModelKind(kind);
                          setFeaturesInput((prev) => featuresForKind(kind, prev));
                        }}
                        className={cn(
                          "rounded-md px-2.5 py-1.5 text-[10px] font-semibold transition-all disabled:opacity-50",
                          modelKind === kind
                            ? "bg-white text-[var(--color-primary)] shadow-sm"
                            : "text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]",
                        )}
                      >
                        {MODEL_KIND_META[kind].label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-x-4 gap-y-4 md:grid-cols-2">
                <label className="block">
                  <span className="text-[11px] font-medium text-[var(--color-text-hint)]">模型标识</span>
                  <input
                    type="text"
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    className={cn(inputCls, "mt-1 h-10")}
                  />
                </label>

                <label className="block">
                  <span className="text-[11px] font-medium text-[var(--color-text-hint)]">显示名称</span>
                  <input
                    type="text"
                    value={displayNameInput}
                    onChange={(e) => setDisplayNameInput(e.target.value)}
                    className={cn(inputCls, "mt-1 h-10")}
                  />
                </label>

                <label className="block">
                  <span className="text-[11px] font-medium text-[var(--color-text-hint)]">Provider</span>
                  <ProviderSelect
                    value={providerInput}
                    onChange={setProviderInput}
                    disabled={disabled}
                    placeholder="qwen / glm / custom"
                  />
                  <span className="mt-1 block text-[10px] text-[var(--color-text-hint)]">{adapterLabel(providerInput)}</span>
                </label>

                <label className="block">
                  <span className="text-[11px] font-medium text-[var(--color-text-hint)]">API Base URL</span>
                  <div className="relative mt-1">
                    <input
                      type="text"
                      value={apiBaseUrlInput}
                      onChange={(e) => setApiBaseUrlInput(e.target.value)}
                      className={cn(inputCls, "h-10 pr-9")}
                      placeholder="https://api.openai.com/v1"
                    />
                    <Link2 className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-hint)]" />
                  </div>
                  <span className="mt-1 block text-[10px] leading-4 text-[var(--color-text-hint)]">
                    {modelKind === "embedding"
                      ? "按 SDK base_url 填写；阿里云百炼建议以 /compatible-mode/v1 结尾，不追加 /embeddings"
                      : modelKind === "ocr_job"
                        ? "填写厂商 OCR 服务根地址"
                        : "按 SDK base_url 填写，不追加 /chat/completions"}
                  </span>
                </label>
              </div>

              <label className="mt-4 block">
                <span className="text-[11px] font-medium text-[var(--color-text-hint)]">API Key</span>
                <div className="mt-1 flex gap-2">
                  <div className="relative min-w-0 flex-1">
                    <input
                      type={showApiKey ? "text" : "password"}
                      value={apiKeyInput}
                      onChange={(e) => setApiKeyInput(e.target.value)}
                      className={cn(inputCls, "h-10 pr-10")}
                      placeholder={model.api_configured ? "" : "sk-..."}
                      autoComplete="new-password"
                      aria-label={model.api_configured ? "API Key（已保存，输入新值可替换）" : "API Key"}
                    />
                    {model.api_configured && !apiKeyInput && (
                      <span
                        aria-hidden="true"
                        className="pointer-events-none absolute inset-y-0 left-3 flex items-center select-none text-sm tracking-[0.16em] text-[var(--color-text-secondary)]"
                      >
                        ••••••••••••••••••••
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => setShowApiKey((prev) => !prev)}
                      disabled={!apiKeyInput}
                      title={apiKeyInput ? (showApiKey ? "隐藏新输入的 API Key" : "显示新输入的 API Key") : "已保存的 API Key 不可回显"}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--color-text-hint)] transition-colors hover:text-[var(--color-primary)] disabled:cursor-default disabled:opacity-45"
                    >
                      {showApiKey && apiKeyInput ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={handleTestConnection}
                    disabled={testing || !apiBaseUrlInput.trim() || !nameInput.trim() || (!model.api_configured && !apiKeyInput.trim())}
                    className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-lg border border-[var(--color-primary)]/35 bg-white px-3.5 text-xs font-semibold text-[var(--color-primary)] transition-all hover:bg-[var(--color-primary-light)] disabled:opacity-40"
                  >
                    {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                    测试连接
                  </button>
                </div>
                {model.api_configured && (
                  <span className="mt-1 block text-[10px] leading-4 text-[var(--color-text-hint)]">
                    已保存 API Key；留空测试会自动使用已有密钥，输入新值时优先测试新密钥。
                  </span>
                )}
              </label>

              <div className="mt-5 border-t border-[var(--color-border)]/60 pt-4">
                {modelKind === "chat" ? (
                  <div>
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <span className="text-[11px] font-medium text-[var(--color-text-hint)]">用途（可多选）</span>
                      <span className="text-[10px] text-[var(--color-text-hint)]">决定各 AI 功能优先使用的模型</span>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
                      {CHAT_FEATURE_OPTIONS.map((opt) => {
                        const selected = featuresInput.includes(opt.value);
                        return (
                          <label
                            key={opt.value}
                            title={opt.desc}
                            className={cn(
                              "flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-[11px] font-medium transition-all",
                              selected
                                ? "border-[var(--color-primary)]/70 bg-[var(--color-primary-light)]/70 text-[var(--color-primary-dark)]"
                                : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]/35 hover:bg-[var(--color-bg-input)]/45",
                            )}
                          >
                            <input
                              type="checkbox"
                              className="sr-only"
                              checked={selected}
                              onChange={() => setFeaturesInput((prev) => prev.includes(opt.value) ? prev.filter((f) => f !== opt.value) : [...prev, opt.value])}
                            />
                            <span
                              className={cn(
                                "grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors",
                                selected
                                  ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                                  : "border-[var(--color-border)] bg-white",
                              )}
                            >
                              {selected && <CheckCircle2 className="h-2.5 w-2.5" />}
                            </span>
                            <span className="truncate">{opt.label}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-xl border border-[var(--color-border)]/70 bg-[var(--color-bg-input)]/35 px-4 py-3">
                    <p className="text-xs font-semibold text-[var(--ink)]">
                      能力：{modelKind === "embedding" ? "Vector Embedding" : "视觉 OCR Job"}
                    </p>
                    <p className="mt-1 text-[10px] leading-4 text-[var(--color-text-hint)]">{MODEL_KIND_META[modelKind].desc}</p>
                  </div>
                )}
              </div>

              {testResult && (
                <div
                  className={cn(
                    "mt-4 rounded-xl px-3.5 py-2.5 text-xs",
                    testResult.success
                      ? "border border-[var(--color-success)]/45 bg-[var(--color-success-light)] text-[var(--color-success)]"
                      : "border border-[var(--color-danger)]/45 bg-[var(--color-danger-light)] text-[var(--color-danger)]",
                  )}
                >
                  <div className="flex items-start gap-2">
                    {testResult.success
                      ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                    <div className="min-w-0">
                      <p className="font-semibold">{testResult.success ? "连接成功" : "连接失败"}</p>
                      <p className="mt-0.5 break-words">{testResult.message}</p>
                      {testResult.latency_ms != null && <p className="mt-0.5 opacity-70">耗时 {testResult.latency_ms}ms</p>}
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border)]/70 bg-[var(--color-bg-input)]/20 px-5 py-3.5">
              <button
                onClick={onDelete}
                disabled={disabled}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[var(--color-danger)]/35 bg-white px-3 text-xs font-semibold text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger-light)] disabled:opacity-50"
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除配置
              </button>

              <div className="ml-auto flex items-center gap-2">
                {model.is_enabled && !model.is_default && (
                  <button
                    onClick={onSetDefault}
                    disabled={disabled}
                    className="h-9 rounded-lg border border-[var(--color-border)] bg-white px-3 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-primary)]/45 hover:bg-[var(--color-primary-light)]/55 hover:text-[var(--color-primary-dark)] disabled:opacity-50"
                  >
                    设为默认
                  </button>
                )}
                <Button onClick={save} disabled={disabled} className="min-w-[112px]">
                  保存配置
                </Button>
              </div>
            </div>
          </div>
        </div>
      </td>
    </tr>
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
  const [showAddDialog, setShowAddDialog] = useState(false);
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

  const handleSaveApiConfig = (id: number, data: AdminAiModelConfigPatchRequest) => {
    patchMutation.mutate({ id, data });
  };

  const setDefault = (model: AdminAiModelConfig) => {
    patchMutation.mutate({ id: model.id, data: { is_default: true } });
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate(deleteTarget.id);
    setDeleteTarget(null);
  };

  const modelList = models.data ?? [];

  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--color-border)]/80 bg-white/80 shadow-[var(--shadow-card)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)]/60 px-5 py-4">
        <div>
          <h3 className="font-display text-xl font-bold text-[var(--ink)]">模型配置</h3>
          <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">管理接入的 AI 模型及其功能映射</p>
        </div>
        <Button onClick={() => setShowAddDialog(true)}>
          <Plus className="h-4 w-4" />
          添加模型
        </Button>
      </div>

      {/* Errors */}
      {[patchMutation, createMutation, deleteMutation, models].map((q, i) =>
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
                  const featureList = model.features?.length
                    ? model.features.map((f) => FEATURE_LABELS[f]).filter(Boolean)
                    : [];
                  const isSelected = selectedId === model.id;

                  return (
                    <React.Fragment key={model.id}>
                      <tr
                        onClick={() => setSelectedId(isSelected ? null : model.id)}
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
                                "h-4 w-4 text-[var(--color-text-hint)] transition-transform",
                                isSelected && "rotate-180",
                              )}
                            />
                          </div>
                        </td>
                      </tr>

                      {/* Detail panel */}
                      {isSelected && (
                        <DetailPanel
                          model={model}
                          onSaveApiConfig={handleSaveApiConfig}
                          onSetDefault={() => setDefault(model)}
                          onDelete={() => setDeleteTarget(model)}
                          disabled={patchMutation.isPending}
                        />
                      )}
                    </React.Fragment>
                  );
                })}
          </tbody>
        </table>
      </div>

      <AddModelDialog
        open={showAddDialog}
        onClose={() => setShowAddDialog(false)}
        onSave={(data) => { createMutation.mutate(data); setShowAddDialog(false); }}
        loading={createMutation.isPending}
      />

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
