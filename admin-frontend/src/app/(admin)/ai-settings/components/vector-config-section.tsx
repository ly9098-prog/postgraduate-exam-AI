"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Loader2,
  Save,
  SlidersHorizontal,
  Wifi,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { Toggle } from "@/components/ui/toggle";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import type {
  AdminAiModelConfig,
  EmbeddingTestResponse,
  VectorConfig,
  VectorConfigPatchRequest,
} from "@/lib/api/types";

type Tab = "search" | "embedding";

const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
  { key: "search", label: "检索配置", icon: SlidersHorizontal },
  { key: "embedding", label: "Embedding 模型", icon: Brain },
];

const inputCls =
  "mt-1 h-9 w-full rounded-lg border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]";
const labelCls = "text-[11px] font-medium text-[var(--color-text-hint)]";

function hasEmbeddingCapability(model: AdminAiModelConfig) {
  return (model.features ?? []).includes("embedding") || model.feature === "embedding";
}

export function VectorConfigSection() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<VectorConfigPatchRequest>({});
  const [testResult, setTestResult] = useState<EmbeddingTestResponse | null>(null);
  const [tab, setTab] = useState<Tab>("search");

  function showToast(msg: string, isError = false) {
    const el = document.createElement("div");
    el.className =
      "fixed left-1/2 top-4 z-[200] -translate-x-1/2 rounded-xl border bg-white px-5 py-3 text-sm font-semibold shadow-[var(--shadow-card)] animate-rise-in" +
      (isError
        ? " border-[var(--color-danger)]/30 text-[var(--color-danger)]"
        : " border-[var(--color-success)]/30 text-[var(--color-success)]");
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2500);
  }

  const config = useQuery({
    queryKey: ["vector-config"],
    queryFn: () => apiRequest<VectorConfig>("/vector-config"),
    staleTime: 30_000,
  });

  const models = useQuery({
    queryKey: ["ai-models"],
    queryFn: () => apiRequest<AdminAiModelConfig[]>("/ai-models"),
    staleTime: 30_000,
  });

  const saveMutation = useMutation({
    mutationFn: (data: VectorConfigPatchRequest) =>
      apiRequest<VectorConfig>("/vector-config", {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["vector-config"], data);
      setForm({});
      setTestResult(null);
      showToast("向量配置已保存");
    },
    onError: (err) => showToast(getErrorMessage(err), true),
  });

  const set = useCallback(
    <K extends keyof VectorConfigPatchRequest>(key: K, value: VectorConfigPatchRequest[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const c = config.data;
  const selectedModelId =
    form.embedding_model_config_id !== undefined
      ? form.embedding_model_config_id
      : c?.embedding_model_config_id ?? null;

  const embeddingModels = useMemo(
    () => (models.data ?? []).filter((model) => model.is_enabled && hasEmbeddingCapability(model)),
    [models.data],
  );

  const selectedModel = useMemo(
    () => (models.data ?? []).find((model) => model.id === selectedModelId) ?? null,
    [models.data, selectedModelId],
  );

  const testMutation = useMutation({
    mutationFn: () => {
      if (!selectedModelId) throw new Error("请先选择 Embedding 模型");
      return apiRequest<EmbeddingTestResponse>("/vector-config/test-embedding", {
        method: "POST",
        body: JSON.stringify({
          model_config_id: selectedModelId,
          dim: form.embedding_dim ?? c?.embedding_dim ?? 1024,
          timeout: form.embedding_timeout ?? c?.embedding_timeout ?? 30,
        }),
      });
    },
    onSuccess: (data) => setTestResult(data),
    onError: (err) =>
      setTestResult({
        success: false,
        status: "network_error",
        message: getErrorMessage(err),
        latency_ms: 0,
        returned_dim: null,
      }),
  });

  if (config.isLoading || models.isLoading) {
    return (
      <div className="rounded-2xl border border-[var(--color-border)]/80 bg-white/80 p-8 text-center shadow-sm">
        <Loader2 className="mx-auto h-5 w-5 animate-spin text-[var(--color-primary)]" />
        <p className="mt-2 text-sm text-[var(--color-text-hint)]">加载向量配置…</p>
      </div>
    );
  }

  if (config.isError || !c) {
    return (
      <p className="rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
        {getErrorMessage(config.error)}
      </p>
    );
  }

  const dirty = Object.keys(form).length > 0;
  const isEnabled = form.vector_enabled ?? c.vector_enabled;
  const selectedInvalid = Boolean(selectedModel && (!selectedModel.is_enabled || !hasEmbeddingCapability(selectedModel)));

  return (
    <section className="overflow-hidden rounded-2xl border border-[var(--color-border)]/80 bg-white/80 shadow-[var(--shadow-card)] animate-rise-in">
      <div className="flex items-center justify-between border-b border-[var(--color-border)]/60 px-5 py-4">
        <div>
          <h3 className="font-display text-xl font-bold text-[var(--ink)]">向量检索 & Embedding</h3>
          <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">
            选择模型配置中已注册的 Embedding 模型，并管理 pgvector 检索参数
          </p>
        </div>
        <Button disabled={!dirty || saveMutation.isPending} onClick={() => saveMutation.mutate(form)}>
          {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          保存
        </Button>
      </div>

      <div className="flex min-h-[360px]">
        <nav className="flex w-[160px] shrink-0 flex-col gap-1 border-r border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/50 p-2.5">
          <div
            className={cn(
              "mb-2 flex items-center justify-between rounded-lg border px-3 py-2.5 transition-colors",
              isEnabled
                ? "border-[var(--color-success)]/30 bg-[var(--color-success-light)]"
                : "border-[var(--color-border)] bg-white/60",
            )}
          >
            <span className={cn("text-xs font-semibold", isEnabled ? "text-[var(--color-success)]" : "text-[var(--color-text-hint)]")}>
              {isEnabled ? "已启用" : "已禁用"}
            </span>
            <Toggle checked={isEnabled} size="sm" onChange={() => set("vector_enabled", !isEnabled)} />
          </div>

          {TABS.map((item) => {
            const Icon = item.icon;
            const active = tab === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setTab(item.key)}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] transition-all",
                  active
                    ? "bg-white font-semibold text-[var(--ink)] shadow-[0_2px_8px_rgba(0,0,0,.06)]"
                    : "text-[var(--color-text-secondary)] hover:bg-white/60",
                )}
              >
                <Icon className={cn("h-3.5 w-3.5", active ? "text-[var(--color-primary)]" : "text-[var(--color-text-hint)]")} />
                {item.label}
              </button>
            );
          })}
        </nav>

        <div className="flex-1 p-5">
          {tab === "search" && (
            <div className="space-y-5 animate-rise-in">
              <div className="grid grid-cols-3 gap-3">
                <label className="block">
                  <span className={labelCls}>Top K</span>
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    className={inputCls}
                    value={form.vector_top_k ?? c.vector_top_k}
                    onChange={(e) => set("vector_top_k", Number(e.target.value))}
                  />
                </label>
                <label className="block">
                  <span className={labelCls}>相似度阈值</span>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    className={inputCls}
                    value={form.vector_similarity_threshold ?? c.vector_similarity_threshold}
                    onChange={(e) => set("vector_similarity_threshold", Number(e.target.value))}
                  />
                </label>
                <label className="block">
                  <span className={labelCls}>缓存 TTL (秒)</span>
                  <input
                    type="number"
                    min={0}
                    max={86400}
                    className={inputCls}
                    value={form.vector_cache_ttl_sec ?? c.vector_cache_ttl_sec}
                    onChange={(e) => set("vector_cache_ttl_sec", Number(e.target.value))}
                  />
                </label>
              </div>

              <div className="rounded-lg border border-[var(--color-border)]/50 bg-[var(--color-bg-input)]/35 px-4 py-3 text-xs leading-relaxed text-[var(--color-text-secondary)]">
                Provider、API Key、Base URL 与 Model ID 统一在「模型配置」维护；本页不再保存第二套 Embedding 凭据。
              </div>
            </div>
          )}

          {tab === "embedding" && (
            <div className="space-y-4 animate-rise-in">
              {models.isError && (
                <div className="rounded-lg border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-3 py-2 text-xs text-[var(--color-danger)]">
                  {getErrorMessage(models.error)}
                </div>
              )}

              {embeddingModels.length === 0 ? (
                <div className="rounded-xl border border-[var(--color-warning)]/40 bg-[var(--color-warning-light)] px-4 py-4">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-warning)]" />
                    <div>
                      <p className="text-sm font-semibold text-[var(--ink)]">尚未注册 Embedding 模型</p>
                      <p className="mt-1 text-xs leading-relaxed text-[var(--color-text-secondary)]">
                        请先到「模型」标签添加模型，并将模型类型设置为 Embedding。API Key、Base URL 和模型标识只需配置一次。
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <label className="block">
                  <span className={labelCls}>当前 Embedding 模型</span>
                  <select
                    className={inputCls}
                    value={selectedModelId ?? ""}
                    onChange={(e) => {
                      set("embedding_model_config_id", e.target.value ? Number(e.target.value) : null);
                      setTestResult(null);
                    }}
                  >
                    <option value="">请选择模型</option>
                    {embeddingModels.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.display_name} · {model.name} · {model.provider}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {selectedModel && (
                <div className="grid grid-cols-2 gap-3 rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/30 p-4">
                  <div>
                    <p className={labelCls}>Provider</p>
                    <p className="mt-1 text-sm font-semibold text-[var(--ink)]">{selectedModel.provider}</p>
                  </div>
                  <div>
                    <p className={labelCls}>模型标识</p>
                    <p className="mt-1 break-all font-mono text-xs font-semibold text-[var(--ink)]">{selectedModel.name}</p>
                  </div>
                  <div className="col-span-2">
                    <p className={labelCls}>API Base URL</p>
                    <p className="mt-1 break-all font-mono text-xs text-[var(--color-text-secondary)]">
                      {selectedModel.api_base_url || "未配置"}
                    </p>
                  </div>
                  <div>
                    <p className={labelCls}>API Key</p>
                    <p className={cn("mt-1 text-xs font-semibold", selectedModel.api_configured ? "text-[var(--color-success)]" : "text-[var(--color-warning)]")}>
                      {selectedModel.api_configured ? "● 已配置" : "● 未配置"}
                    </p>
                  </div>
                  <div>
                    <p className={labelCls}>状态</p>
                    <p className={cn("mt-1 text-xs font-semibold", selectedModel.is_enabled ? "text-[var(--color-success)]" : "text-[var(--color-danger)]")}>
                      {selectedModel.is_enabled ? "● 可用" : "● 已禁用"}
                    </p>
                  </div>
                </div>
              )}

              {selectedInvalid && (
                <div className="rounded-lg border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-3 py-2 text-xs text-[var(--color-danger)]">
                  当前选择的模型已禁用或不再具备 Embedding 能力，请重新选择。
                </div>
              )}

              <div className="grid grid-cols-3 gap-3">
                <label className="block">
                  <span className={labelCls}>向量维度</span>
                  <input
                    type="number"
                    min={1}
                    max={8192}
                    className={inputCls}
                    value={form.embedding_dim ?? c.embedding_dim}
                    onChange={(e) => set("embedding_dim", Number(e.target.value))}
                  />
                </label>
                <label className="block">
                  <span className={labelCls}>请求超时 (秒)</span>
                  <input
                    type="number"
                    min={1}
                    max={300}
                    className={inputCls}
                    value={form.embedding_timeout ?? c.embedding_timeout}
                    onChange={(e) => set("embedding_timeout", Number(e.target.value))}
                  />
                </label>
                <label className="block">
                  <span className={labelCls}>批量大小</span>
                  <input
                    type="number"
                    min={1}
                    max={256}
                    className={inputCls}
                    value={form.embedding_batch_size ?? c.embedding_batch_size}
                    onChange={(e) => set("embedding_batch_size", Number(e.target.value))}
                  />
                </label>
              </div>

              <div className="border-t border-[var(--color-border)]/40 pt-4">
                <Button
                  variant="secondary"
                  disabled={testMutation.isPending || !selectedModelId || !selectedModel?.api_configured || selectedInvalid}
                  onClick={() => {
                    setTestResult(null);
                    testMutation.mutate();
                  }}
                >
                  {testMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wifi className="h-4 w-4" />}
                  测试 Embedding
                </Button>

                {testResult && (
                  <div
                    className={cn(
                      "mt-3 rounded-lg px-3 py-2.5 text-xs",
                      testResult.success
                        ? "border border-[var(--color-success)] bg-[var(--color-success-light)] text-[var(--color-success)]"
                        : "border border-[var(--color-danger)] bg-[var(--color-danger-light)] text-[var(--color-danger)]",
                    )}
                  >
                    <div className="flex items-start gap-2">
                      {testResult.success ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                      ) : (
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      )}
                      <div>
                        <p className="font-semibold">{testResult.success ? "连接成功" : "连接失败"}</p>
                        <p className="mt-0.5 break-words leading-relaxed">{testResult.message}</p>
                        {(testResult.latency_ms > 0 || testResult.returned_dim != null) && (
                          <p className="mt-1 opacity-70">
                            {testResult.latency_ms > 0 && `耗时 ${testResult.latency_ms}ms`}
                            {testResult.latency_ms > 0 && testResult.returned_dim != null && " · "}
                            {testResult.returned_dim != null && `维度 ${testResult.returned_dim}`}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
