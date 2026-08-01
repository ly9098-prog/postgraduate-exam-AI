"use client";

import React, { useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain, Cpu, Globe, Key,
  CheckCircle2, X, Trash2, Plus, Tag, ScanEye,
  Loader2, AlertTriangle, Wifi, ChevronDown,
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
  "qwen-vl": ScanEye, qwen: ScanEye,
};

const PROVIDER_COLORS: Record<string, string> = {
  deepseek: "#5b7b9a", openai: "#6b9b6b", anthropic: "#c49a6b",
  "qwen-vl": "#7c5ce7", qwen: "#7c5ce7",
  paddleocr: "#e67e22", paddleocr_vl: "#e67e22", "paddleocr-vl": "#e67e22",
};

const FEATURE_LABELS: Record<string, { label: string; color: string }> = {
  ocr: { label: "OCR", color: "#5b7b9a" },
  completion: { label: "补全", color: "#6b9b6b" },
  analysis: { label: "解析", color: "#c49a6b" },
  vision: { label: "视觉", color: "#e67e22" },
};

const FEATURE_OPTIONS = [
  { value: "", label: "通用（所有功能）" },
  { value: "ocr", label: "OCR 纠错" },
  { value: "completion", label: "AI 补全" },
  { value: "analysis", label: "AI 解析" },
  { value: "vision", label: "视觉层" },
];

function getProviderIcon(p: string) { return PROVIDER_ICONS[p] || Brain; }
function getProviderColor(p: string) { return PROVIDER_COLORS[p] || "#5b7b9a"; }

const inputCls =
  "h-9 w-full rounded-lg border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]";

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
  const [apiBaseUrl, setApiBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [features, setFeatures] = useState<string[]>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestConnectionResponse | null>(null);

  if (!open) return null;

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
          features,
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
    setName(""); setDisplayName(""); setProvider("openai");
    setApiBaseUrl(""); setApiKey(""); setFeatures([]); setTestResult(null);
  };

  const handleSave = () => {
    if (!name.trim() || !displayName.trim() || !provider.trim()) return;
    onSave({
      name: name.trim(), display_name: displayName.trim(), provider: provider.trim(),
      api_base_url: apiBaseUrl.trim() || undefined,
      api_key: apiKey.trim() || undefined,
      features: features.length > 0 ? features : null,
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
          <label className="block">
            <span className="text-[11px] font-medium text-[var(--color-text-hint)]">提供商 *</span>
            <input value={provider} onChange={(e) => setProvider(e.target.value)} className={cn(inputCls, "mt-1")} placeholder="openai" />
          </label>
          <label className="block">
            <span className="text-[11px] font-medium text-[var(--color-text-hint)]">API Base URL</span>
            <input value={apiBaseUrl} onChange={(e) => setApiBaseUrl(e.target.value)} className={cn(inputCls, "mt-1")} placeholder="https://api.openai.com/v1" />
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
          <div>
            <span className="text-[11px] font-medium text-[var(--color-text-hint)]">用途（可多选）</span>
            <div className="mt-1.5 flex flex-wrap gap-2">
              {FEATURE_OPTIONS.filter((o) => o.value).map((opt) => {
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
                    {opt.label}
                  </label>
                );
              })}
            </div>
          </div>
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
          <Button onClick={handleSave} disabled={loading || !name.trim() || !displayName.trim() || !provider.trim()}>
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
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [apiBaseUrlInput, setApiBaseUrlInput] = useState(model.api_base_url ?? "");
  const [featuresInput, setFeaturesInput] = useState<string[]>(model.features ?? []);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestConnectionResponse | null>(null);
  const [keyEditing, setKeyEditing] = useState(false);

  const handleTestConnection = async () => {
    if (!apiBaseUrlInput.trim() || !nameInput.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiRequest<ModelTestConnectionResponse>("/ai-models/test-connection", {
        method: "POST",
        body: JSON.stringify({
          api_base_url: apiBaseUrlInput.trim(),
          api_key: apiKeyInput.trim(),
          model_name: nameInput.trim(),
          model_id: model.id,
          provider: model.provider,
          features: featuresInput,
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
    if (apiKeyInput) payload.api_key = apiKeyInput;
    if (apiBaseUrlInput !== model.api_base_url) payload.api_base_url = apiBaseUrlInput;
    if (JSON.stringify(featuresInput) !== JSON.stringify(model.features ?? [])) {
      payload.features = featuresInput.length > 0 ? featuresInput : null;
    }
    onSaveApiConfig(model.id, payload);
    setApiKeyInput("");
    setKeyEditing(false);
    showToast("API 配置已保存");
  };

  return (
    <tr>
      <td colSpan={5} className="relative border-b border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/30 px-5 py-4">

        <div className="flex gap-6">
          {/* Left: API config */}
          <div className="flex-1 space-y-3">
            <h4 className="flex items-center gap-2 text-xs font-semibold text-[var(--color-text-secondary)]">
              <Key className="h-3.5 w-3.5" />
              API 配置
            </h4>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-[11px] font-medium text-[var(--color-text-hint)]">模型标识</span>
                <input type="text" value={nameInput} onChange={(e) => setNameInput(e.target.value)}
                  className={cn(inputCls, "mt-1")} />
              </label>
              <label className="block">
                <span className="text-[11px] font-medium text-[var(--color-text-hint)]">API Base URL</span>
                <input type="text" value={apiBaseUrlInput} onChange={(e) => setApiBaseUrlInput(e.target.value)}
                  className={cn(inputCls, "mt-1")} placeholder="https://api.openai.com/v1" />
              </label>
            </div>
            <label className="block">
              <span className="text-[11px] font-medium text-[var(--color-text-hint)]">API Key</span>
              <div className="mt-1 flex gap-2">
                <input type="password"
                  value={
                    apiKeyInput ||
                    (keyEditing ? "" : model.api_configured ? "••••••••••••••••••••••••••••••" : "")
                  }
                  onChange={(e) => {
                    if (!keyEditing) setKeyEditing(true);
                    setApiKeyInput(e.target.value);
                  }}
                  onFocus={() => {
                    if (!keyEditing && model.api_configured) {
                      setKeyEditing(true);
                      setApiKeyInput("");
                    }
                  }}
                  onBlur={() => {
                    if (keyEditing && !apiKeyInput) {
                      setKeyEditing(false);
                    }
                  }}
                  className={cn(inputCls, "flex-1")}
                  placeholder="sk-..." />
                <button type="button" onClick={handleTestConnection}
                  disabled={testing || !apiBaseUrlInput.trim() || !nameInput.trim()}
                  className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)] bg-white px-3 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-primary)] disabled:opacity-40">
                  {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                  测试
                </button>
              </div>
            </label>

            {/* Feature multi-select */}
            <div>
              <span className="text-[11px] font-medium text-[var(--color-text-hint)]">用途（可多选）</span>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {FEATURE_OPTIONS.filter((o) => o.value).map((opt) => {
                  const selected = featuresInput.includes(opt.value);
                  return (
                    <label key={opt.value}
                      className={cn(
                        "flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors",
                        selected ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                          : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]/40",
                      )}>
                      <input type="checkbox" className="sr-only" checked={selected}
                        onChange={() => setFeaturesInput((prev) => prev.includes(opt.value) ? prev.filter((f) => f !== opt.value) : [...prev, opt.value])} />
                      <div className={cn("flex h-3 w-3 items-center justify-center rounded-sm border transition-colors",
                        selected ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white" : "border-[var(--color-border)]")}>
                        {selected && <CheckCircle2 className="h-2 w-2" />}
                      </div>
                      {opt.label}
                    </label>
                  );
                })}
              </div>
            </div>

            {testResult && (
              <div className={cn("rounded-lg px-3 py-2 text-xs",
                testResult.success ? "border border-[var(--color-success)] bg-[var(--color-success-light)] text-[var(--color-success)]"
                  : "border border-[var(--color-danger)] bg-[var(--color-danger-light)] text-[var(--color-danger)]")}>
                <div className="flex items-start gap-1.5">
                  {testResult.success ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                  <div className="min-w-0">
                    <p className="font-semibold">{testResult.success ? "连接成功" : "连接失败"}</p>
                    <p className="mt-0.5 break-words">{testResult.message}</p>
                    {testResult.latency_ms != null && <p className="mt-0.5 opacity-70">耗时 {testResult.latency_ms}ms</p>}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Right: Actions */}
          <div className="flex w-32 shrink-0 flex-col gap-2 pt-6">
            <Button onClick={save} disabled={disabled}>保存</Button>
            {model.is_enabled && !model.is_default && (
              <button onClick={onSetDefault} disabled={disabled}
                className="h-9 rounded-xl border border-[var(--color-border)] bg-white text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:opacity-50">
                设为默认
              </button>
            )}
            <button onClick={onDelete} disabled={disabled}
              className="h-9 rounded-xl border border-[var(--color-danger)]/30 bg-white text-xs font-semibold text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger-light)] disabled:opacity-50">
              <Trash2 className="mr-1 inline-block h-3 w-3" />
              删除
            </button>
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
                        <td className="px-4 py-3 text-xs capitalize text-[var(--color-text-secondary)]">
                          {model.provider}
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
