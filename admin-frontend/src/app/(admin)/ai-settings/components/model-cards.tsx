"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain, Cpu, Globe, Key, ToggleLeft, ToggleRight,
  CheckCircle2, Info, X, Trash2, Plus, Tag, ScanEye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiRequest } from "@/lib/api/client";
import type {
  AdminAiModelConfig,
  AdminAiModelConfigCreateRequest,
  AdminAiModelConfigPatchRequest,
} from "@/lib/api/types";
import { getErrorMessage } from "@/lib/api/errors";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";

const PROVIDER_ICONS: Record<string, React.ElementType> = {
  deepseek: Brain,
  openai: Globe,
  anthropic: Cpu,
  "qwen-vl": ScanEye,
  qwen: ScanEye,
};

const PROVIDER_COLORS: Record<string, string> = {
  deepseek: "#5b7b9a",
  openai: "#6b9b6b",
  anthropic: "#c49a6b",
  "qwen-vl": "#7c5ce7",
  qwen: "#7c5ce7",
};

const FEATURE_LABELS: Record<string, { label: string; color: string }> = {
  ocr: { label: "OCR 纠错", color: "#5b7b9a" },
  completion: { label: "AI 补全", color: "#6b9b6b" },
  analysis: { label: "AI 解析", color: "#c49a6b" },
};

const FEATURE_OPTIONS = [
  { value: "", label: "通用（所有功能）" },
  { value: "ocr", label: "OCR 纠错" },
  { value: "completion", label: "AI 补全" },
  { value: "analysis", label: "AI 解析" },
];

function getProviderIcon(provider: string) {
  return PROVIDER_ICONS[provider] || Brain;
}

function getProviderColor(provider: string) {
  return PROVIDER_COLORS[provider] || "#5b7b9a";
}

function resolveFeatureModel(
  models: AdminAiModelConfig[], feature: string,
): AdminAiModelConfig | null {
  const featured = models.find((m) => m.is_enabled && m.feature === feature);
  if (featured) return featured;
  const untagged = models.find((m) => m.is_enabled && !m.feature);
  if (untagged) return untagged;
  return models.find((m) => m.is_enabled) ?? null;
}

// ---------------------------------------------------------------------------
// Add Model Dialog
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
  const [apiBaseUrl, setApiBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [feature, setFeature] = useState("");

  if (!open) return null;

  const reset = () => {
    setName(""); setDisplayName(""); setProvider("openai");
    setApiBaseUrl(""); setApiKey(""); setFeature("");
  };

  const handleSave = () => {
    if (!name.trim() || !displayName.trim() || !provider.trim()) return;
    onSave({
      name: name.trim(),
      display_name: displayName.trim(),
      provider: provider.trim(),
      api_base_url: apiBaseUrl.trim() || undefined,
      api_key: apiKey.trim() || undefined,
      feature: feature || null,
    });
  };

  const handleClose = () => { reset(); onClose(); };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(16,24,40,0.42)] px-4">
      <div className="w-full max-w-md rounded-3xl border border-[var(--color-border)] bg-white p-6 shadow-[var(--shadow-floating)]">
        <div className="mb-5 flex items-center justify-between">
          <h3 className="font-display text-2xl font-bold text-[var(--ink)]">添加模型</h3>
          <button onClick={handleClose} className="text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-semibold text-[var(--color-text-secondary)]">
              模型标识 <span className="text-[var(--color-danger)]">*</span>
            </label>
            <input value={name} onChange={(e) => setName(e.target.value)}
              className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none focus:border-[var(--color-primary)]"
              placeholder="gpt-4o" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold text-[var(--color-text-secondary)]">
              显示名称 <span className="text-[var(--color-danger)]">*</span>
            </label>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)}
              className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none focus:border-[var(--color-primary)]"
              placeholder="GPT-4o" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold text-[var(--color-text-secondary)]">
              提供商 <span className="text-[var(--color-danger)]">*</span>
            </label>
            <input value={provider} onChange={(e) => setProvider(e.target.value)}
              className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none focus:border-[var(--color-primary)]"
              placeholder="openai" />
            <p className="mt-1 text-xs text-[var(--color-text-hint)]">常用值: deepseek / openai / anthropic / qwen-vl / google</p>
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold text-[var(--color-text-secondary)]">API Base URL <span className="text-[var(--color-text-hint)]">（可选）</span></label>
            <input value={apiBaseUrl} onChange={(e) => setApiBaseUrl(e.target.value)}
              className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none focus:border-[var(--color-primary)]"
              placeholder="https://api.openai.com/v1" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold text-[var(--color-text-secondary)]">API Key <span className="text-[var(--color-text-hint)]">（可选）</span></label>
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
              className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none focus:border-[var(--color-primary)]"
              placeholder="sk-..." />
          </div>
            <div>
            <label className="mb-1 block text-xs font-semibold text-[var(--color-text-secondary)]">用途 <span className="text-[var(--color-text-hint)]">（可选）</span></label>
            <Select
              value={feature}
              onChange={setFeature}
              placeholder="选择用途"
              className="h-10 text-sm w-full"
              options={FEATURE_OPTIONS.map((opt) => ({
                value: opt.value,
                label: opt.label,
              }))}
            />
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={loading}>取消</Button>
          <Button onClick={handleSave} disabled={loading || !name.trim() || !displayName.trim() || !provider.trim()}>
            {loading ? "添加中..." : "添加"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Model Card
// ---------------------------------------------------------------------------

function ModelCard({
  model, onToggle, onSetDefault, onSaveApiConfig, onDelete, disabled,
}: {
  model: AdminAiModelConfig;
  onToggle: () => void;
  onSetDefault: () => void;
  onSaveApiConfig: (id: number, data: AdminAiModelConfigPatchRequest) => void;
  onDelete: () => void;
  disabled: boolean;
}) {
  const [isEditingApi, setIsEditingApi] = useState(false);
  const [nameInput, setNameInput] = useState("");
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [apiBaseUrlInput, setApiBaseUrlInput] = useState("");
  const [featureInput, setFeatureInput] = useState("");

  const openApiEdit = () => {
    setNameInput(model.name);
    setApiKeyInput(model.api_configured ? (model.api_key_masked ?? "****") : "");
    setApiBaseUrlInput(model.api_base_url ?? "");
    setFeatureInput(model.feature ?? "");
    setIsEditingApi(true);
  };

  const saveApiConfig = () => {
    const payload: AdminAiModelConfigPatchRequest = {};
    if (nameInput.trim() && nameInput.trim() !== model.name) payload.name = nameInput.trim();
    if (apiKeyInput && apiKeyInput !== model.api_key_masked) payload.api_key = apiKeyInput;
    if (apiBaseUrlInput !== model.api_base_url) payload.api_base_url = apiBaseUrlInput;
    if (featureInput !== (model.feature ?? "")) payload.feature = featureInput || null;
    onSaveApiConfig(model.id, payload);
    setIsEditingApi(false);
  };

  const Icon = getProviderIcon(model.provider);
  const color = getProviderColor(model.provider);
  const featureInfo = model.feature ? FEATURE_LABELS[model.feature] : null;

  return (
    <div
      className={cn(
        "group relative rounded-xl border p-5 transition-all duration-300",
        model.is_enabled
          ? "border-[var(--color-border)]/80 hover:border-[var(--color-border)] hover:shadow-md"
          : "border-dashed border-[var(--color-border)] opacity-60 hover:opacity-80",
      )}
      style={{
        background: model.is_enabled
          ? "linear-gradient(135deg, rgba(255,255,255,0.95), rgba(255,255,255,0.7))"
          : "rgba(247,245,240,0.5)",
      }}
    >
      <div
        className="absolute left-0 right-0 top-0 h-0.5 rounded-t-xl transition-opacity"
        style={{ backgroundColor: color, opacity: model.is_enabled ? 1 : 0.3 }}
      />

      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div
            className="grid h-10 w-10 place-items-center rounded-xl border border-[var(--color-border)]/60 bg-white/60 shadow-sm"
            style={{ color }}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div>
            <p className="font-semibold text-[var(--ink)]">{model.display_name}</p>
            <p className="text-xs text-[var(--color-text-hint)] capitalize">{model.provider}</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={onDelete} disabled={disabled}
            className="rounded-lg p-1.5 text-[var(--color-text-hint)] opacity-0 transition-all hover:bg-[var(--color-danger-light)] hover:text-[var(--color-danger)] group-hover:opacity-100 disabled:opacity-30"
            title="删除模型">
            <Trash2 className="h-4 w-4" />
          </button>
          <button onClick={onToggle} disabled={disabled}
            className="transition-transform hover:scale-110 disabled:opacity-50"
            title={model.is_enabled ? "禁用" : "启用"}>
            {model.is_enabled
              ? <ToggleRight className="h-6 w-6" style={{ color }} />
              : <ToggleLeft className="h-6 w-6 text-[var(--color-text-hint)]" />}
          </button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {model.api_configured ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-success-light)] px-2.5 py-0.5 text-xs font-medium text-[var(--color-success)]">
            <CheckCircle2 className="h-3 w-3" />
            API 已配置
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-warning-light)] px-2.5 py-0.5 text-xs font-medium text-[var(--color-warning)]">
            未配置 API
          </span>
        )}
        {model.is_default && (
          <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium text-white"
            style={{ backgroundColor: color }}>
            默认模型
          </span>
        )}
        {featureInfo ? (
          <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium text-white"
            style={{ backgroundColor: featureInfo.color }}>
            <Tag className="h-3 w-3" />
            {featureInfo.label}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-bg-input)] px-2.5 py-0.5 text-xs font-medium text-[var(--color-text-hint)]">
            通用
          </span>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 rounded-xl bg-[var(--color-bg-input)] p-3">
        <div className="flex items-center gap-2 text-xs text-[var(--color-text-hint)]">
          <Info className="h-3 w-3 shrink-0" />
          <span>当前版本实际使用模型为 DeepSeek V4 Flash，此处配置仅作为管理记录</span>
        </div>
      </div>

      {isEditingApi ? (
        <div className="mt-4 space-y-3 rounded-xl border border-[var(--color-border)]/60 bg-white p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-semibold text-[var(--color-text-secondary)]">
              <Key className="h-3 w-3" />
              API 配置
            </div>
            <button onClick={() => setIsEditingApi(false)}
              className="text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">模型标识</label>
            <input type="text" value={nameInput} onChange={(e) => setNameInput(e.target.value)}
              className="h-9 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
              placeholder="deepseek-v4-flash" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">API Key</label>
            <input type="password" value={apiKeyInput} onChange={(e) => setApiKeyInput(e.target.value)}
              className="h-9 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
              placeholder={model.api_configured ? "输入新 API Key 以替换" : "sk-..."} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">API Base URL <span className="text-[var(--color-text-hint)]">（可选）</span></label>
            <input type="text" value={apiBaseUrlInput} onChange={(e) => setApiBaseUrlInput(e.target.value)}
              className="h-9 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
              placeholder="https://api.deepseek.com" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">用途</label>
            <Select
              value={featureInput}
              onChange={setFeatureInput}
              placeholder="选择用途"
              className="h-9 text-sm w-full"
              options={FEATURE_OPTIONS.map((opt) => ({
                value: opt.value,
                label: opt.label,
              }))}
            />
          </div>
          <div className="flex gap-2">
            <button onClick={saveApiConfig} disabled={disabled}
              className="flex-1 rounded-lg bg-[var(--color-primary)] py-2 text-xs font-semibold text-white transition-colors hover:bg-[var(--color-primary-dark)] disabled:opacity-50">
              保存
            </button>
            <button onClick={() => setIsEditingApi(false)}
              className="flex-1 rounded-lg border border-[var(--color-border)] py-2 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-input)]">
              取消
            </button>
          </div>
        </div>
      ) : (
        <button onClick={openApiEdit}
          className="mt-3 w-full rounded-lg border border-dashed border-[var(--color-border)] py-2 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:border-solid hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]">
          <Key className="mr-1 inline-block h-3 w-3" />
          {model.api_configured ? "编辑 API 配置" : "配置 API Key"}
        </button>
      )}

      {model.is_enabled && !model.is_default && (
        <button onClick={onSetDefault} disabled={disabled}
          className="mt-3 w-full rounded-lg border border-[var(--color-border)] py-2 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:opacity-50">
          设为默认模型
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feature Mapping Section
// ---------------------------------------------------------------------------

function FeatureMapping({
  models, onAssign, disabled,
}: {
  models: AdminAiModelConfig[];
  onAssign: (modelId: number, feature: string | null) => void;
  disabled: boolean;
}) {
  const features = [
    { key: "ocr", label: "OCR 纠错", desc: "OCR 识别结果纠错与结构化", color: "#5b7b9a" },
    { key: "completion", label: "AI 补全", desc: "导入题目字段补全与生成", color: "#6b9b6b" },
    { key: "analysis", label: "AI 解析", desc: "错题分析与学习建议生成", color: "#c49a6b" },
  ];

  const enabledModels = models.filter((m) => m.is_enabled);
  const untaggedModel = models.find((m) => m.is_enabled && !m.feature);

  return (
    <div className="mb-6 rounded-xl border border-[var(--color-border)]/60 bg-gradient-to-b from-[var(--color-bg-input)]/40 to-white/40 p-5">
      <div className="mb-4">
        <h4 className="font-display text-base font-bold text-[var(--ink)]">功能模型映射</h4>
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--color-text-hint)]">
          为每个 AI 功能指定专用模型。
          {untaggedModel ? (
            <>未指定的功能将使用 <span className="font-medium text-[var(--color-text-secondary)]">{untaggedModel.display_name}</span> 兜底。</>
          ) : enabledModels.length > 0 ? (
            <>当前没有通用模型，需为各功能单独指定。</>
          ) : (
            <>请先添加并启用至少一个模型。</>
          )}
        </p>
      </div>
      <div className="space-y-2.5">
        {features.map((feat) => {
          const assigned = resolveFeatureModel(models, feat.key);
          const hasDedicated = assigned?.feature === feat.key;
          return (
            <div
              key={feat.key}
              className="group relative rounded-xl border bg-white transition-all duration-200 hover:shadow-sm"
              style={{
                borderColor: hasDedicated
                  ? `${feat.color}30`
                  : "var(--color-border)",
              }}
            >
              {/* Left accent bar */}
              <div
                className="absolute left-0 top-0 w-1 rounded-l-xl transition-all duration-300"
                style={{
                  height: hasDedicated ? "100%" : "0%",
                  backgroundColor: feat.color,
                  opacity: hasDedicated ? 1 : 0,
                }}
              />

              <div className="flex flex-wrap items-center gap-2 pl-5 pr-4 py-3">
                {/* Feature info */}
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  <div
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ring-1 ring-inset"
                    style={{
                      backgroundColor: `${feat.color}0d`,
                      "--tw-ring-color": `${feat.color}20`,
                    } as React.CSSProperties}
                  >
                    <div className="h-2 w-2 rounded-full" style={{ backgroundColor: feat.color }} />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-[var(--ink)]">{feat.label}</span>
                      {hasDedicated && (
                        <span
                          className="inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white shadow-sm"
                          style={{ backgroundColor: feat.color }}
                        >
                          专用
                        </span>
                      )}
                      {assigned && !hasDedicated && assigned.is_enabled && (
                        <span className="inline-flex items-center rounded-md border border-[var(--color-border)]/60 bg-white/80 px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-text-hint)]">
                          兜底
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[var(--color-text-hint)]">{feat.desc}</p>
                  </div>
                </div>

                {/* Model selector */}
                <div className="flex items-center gap-2.5 shrink-0">
                  {assigned ? (
                    <span className={cn(
                      "text-xs font-medium transition-colors",
                      hasDedicated ? "text-[var(--ink)]" : "text-[var(--color-text-hint)]",
                    )}>
                      <span className="hidden sm:inline">{assigned.display_name}</span>
                      <span className="sm:hidden">
                        {assigned.display_name.length > 12
                          ? assigned.display_name.slice(0, 10) + "…"
                          : assigned.display_name}
                      </span>
                    </span>
                  ) : (
                    <span className="text-xs italic text-[var(--color-text-hint)]">未配置</span>
                  )}
                  {enabledModels.length > 0 && (
                    <Select
                      value={assigned?.id ? String(assigned.id) : ""}
                      onChange={(val) => {
                        if (!val) {
                          const current = models.find((m) => m.feature === feat.key);
                          if (current) onAssign(current.id, null);
                          return;
                        }
                        onAssign(Number(val), feat.key);
                      }}
                      disabled={disabled}
                      color={hasDedicated ? feat.color : undefined}
                      placeholder="取消指定"
                      options={[
                        { value: "", label: "取消指定" },
                        ...enabledModels.map((m) => ({
                          value: String(m.id),
                          label: m.display_name,
                          suffix: m.feature === feat.key ? "已分配" : undefined,
                        })),
                      ]}
                    />
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

// ---------------------------------------------------------------------------
// Main Export
// ---------------------------------------------------------------------------

export function ModelCards() {
  const queryClient = useQueryClient();
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AdminAiModelConfig | null>(null);

  const models = useQuery({
    queryKey: ["ai-models"],
    queryFn: () => apiRequest<AdminAiModelConfig[]>("/ai-models"),
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: AdminAiModelConfigPatchRequest }) =>
      apiRequest<AdminAiModelConfig>(`/ai-models/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-models"] }),
  });

  const createMutation = useMutation({
    mutationFn: (data: AdminAiModelConfigCreateRequest) =>
      apiRequest<AdminAiModelConfig>("/ai-models", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-models"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      apiRequest<void>(`/ai-models/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-models"] }),
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

  const handleAssignFeature = (modelId: number, feature: string | null) => {
    patchMutation.mutate({ id: modelId, data: { feature } });
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate(deleteTarget.id);
    setDeleteTarget(null);
  };

  const modelList = models.data ?? [];

  return (
    <div className="rounded-2xl border border-[var(--color-border)]/80 bg-white/80 p-5 shadow-sm">
      <div className="mb-5">
        <h3 className="font-display text-xl font-bold text-[var(--ink)]">模型配置</h3>
        <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">管理接入的 AI 模型及其功能映射</p>
      </div>

      {patchMutation.isError && (
        <p className="mb-4 rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {getErrorMessage(patchMutation.error)}
        </p>
      )}
      {createMutation.isError && (
        <p className="mb-4 rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {getErrorMessage(createMutation.error)}
        </p>
      )}
      {deleteMutation.isError && (
        <p className="mb-4 rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {getErrorMessage(deleteMutation.error)}
        </p>
      )}
      {models.isError && (
        <p className="mb-4 rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {getErrorMessage(models.error)}
        </p>
      )}

      {/* Feature Mapping */}
      {!models.isLoading && modelList.length > 0 && (
        <FeatureMapping
          models={modelList}
          onAssign={handleAssignFeature}
          disabled={patchMutation.isPending}
        />
      )}

      {/* Model Grid */}
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">
        {models.isLoading
          ? Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="animate-pulse rounded-xl border border-[var(--color-border)]/80 p-5">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-xl bg-[var(--color-border)]" />
                  <div className="space-y-2">
                    <div className="h-4 w-24 rounded bg-[var(--color-border)]" />
                    <div className="h-3 w-16 rounded bg-[var(--color-border)]" />
                  </div>
                </div>
              </div>
            ))
          : modelList.map((model) => (
              <ModelCard
                key={model.id}
                model={model}
                onToggle={() => toggleModel(model)}
                onSetDefault={() => setDefault(model)}
                onSaveApiConfig={handleSaveApiConfig}
                onDelete={() => setDeleteTarget(model)}
                disabled={patchMutation.isPending || deleteMutation.isPending}
              />
            ))}
      </div>

      <button onClick={() => setShowAddDialog(true)}
        className="mt-4 w-full rounded-xl border-2 border-dashed border-[var(--color-border)] py-4 text-sm font-semibold text-[var(--color-text-secondary)] transition-colors hover:border-solid hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]">
        <Plus className="mr-1.5 inline-block h-4 w-4" />
        添加模型
      </button>

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
