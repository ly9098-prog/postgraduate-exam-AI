"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Database,
  Loader2,
  Network,
  Play,
  Save,
  XCircle,
  Zap,
} from "lucide-react";
import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import type {
  EmbeddingTestResponse,
  VectorConfig,
  VectorConfigPatchRequest,
} from "@/lib/api/types";

const VECTOR_MODES = [
  { value: "off", label: "关闭", desc: "完全禁用向量检索" },
  { value: "shadow", label: "影子模式", desc: "执行检索但不使用结果" },
  { value: "allowlist", label: "白名单", desc: "仅对指定科目/用户启用" },
  { value: "all", label: "全部开启", desc: "对所有请求启用向量检索" },
] as const;

export function VectorConfigSection() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<VectorConfigPatchRequest>({});
  const [testResult, setTestResult] = useState<EmbeddingTestResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const config = useQuery({
    queryKey: ["vector-config"],
    queryFn: () => apiRequest<VectorConfig>("/vector-config"),
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
      setMessage("配置已保存");
      setTimeout(() => setMessage(null), 3000);
    },
    onError: (err) => {
      setMessage(getErrorMessage(err));
    },
  });

  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<EmbeddingTestResponse>("/vector-config/test-embedding", {
        method: "POST",
        body: JSON.stringify({
          api_base_url: form.embedding_base_url ?? config.data?.embedding_base_url ?? "",
          api_key: form.embedding_api_key ?? "",
          model: form.embedding_model ?? config.data?.embedding_model ?? "",
          dim: form.embedding_dim ?? config.data?.embedding_dim ?? 1024,
          timeout: form.embedding_timeout ?? config.data?.embedding_timeout ?? 30,
        }),
      }),
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

  const set = useCallback(
    <K extends keyof VectorConfigPatchRequest>(key: K, value: VectorConfigPatchRequest[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const dirty = Object.keys(form).length > 0;
  const c = config.data;

  if (config.isLoading) {
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

  return (
    <section className="rounded-2xl border border-[var(--color-border)]/80 bg-white/80 shadow-sm animate-rise-in">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)]/60 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl border border-[var(--color-border)]/60 bg-white/60 shadow-sm">
            <Database className="h-5 w-5 text-[var(--color-primary)]" />
          </div>
          <div>
            <h3 className="font-display text-xl font-bold text-[var(--ink)]">
              向量检索 & Embedding
            </h3>
            <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">
              pgvector 检索配置与 Embedding API 管理
            </p>
          </div>
        </div>
        <Button disabled={!dirty || saveMutation.isPending} onClick={() => saveMutation.mutate(form)}>
          {saveMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          保存
        </Button>
      </div>

      <div className="space-y-5 p-5">
        {/* Messages */}
        {message && (
          <p className="rounded-xl border border-[var(--color-border)] bg-white/70 px-4 py-2.5 text-sm text-[var(--color-text-secondary)]">
            {message}
          </p>
        )}

        {/* ── Vector Search Mode ── */}
        <fieldset className="space-y-3">
          <legend className="flex items-center gap-2 text-sm font-semibold text-[var(--ink)]">
            <Zap className="h-4 w-4 text-[var(--color-primary)]" />
            向量检索模式
          </legend>

          <div className="flex items-center justify-between rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)] px-4 py-3">
            <div>
              <span className="text-sm font-medium text-[var(--ink)]">启用向量检索</span>
              <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">
                全局开关，关闭后所有向量功能停止
              </p>
            </div>
            <button
              type="button"
              onClick={() => set("vector_enabled", !(form.vector_enabled ?? c.vector_enabled))}
              className="relative h-6 w-11 rounded-full border border-[var(--color-border)] transition-colors"
              style={{
                backgroundColor: (form.vector_enabled ?? c.vector_enabled)
                  ? "var(--color-success)"
                  : "var(--color-bg-input)",
              }}
            >
              <span
                className="absolute left-0.5 top-0.5 h-[calc(100%-4px)] w-[calc(50%-2px)] rounded-full bg-white shadow-sm transition-transform"
                style={{
                  transform: (form.vector_enabled ?? c.vector_enabled)
                    ? "translateX(100%)"
                    : "translateX(0)",
                }}
              />
            </button>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {VECTOR_MODES.map((m) => {
              const active = (form.vector_mode ?? c.vector_mode) === m.value;
              return (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => set("vector_mode", m.value)}
                  className={`rounded-xl border px-3 py-2.5 text-left transition-all ${
                    active
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] shadow-sm"
                      : "border-[var(--color-border)]/60 bg-white/50 hover:border-[var(--color-primary)]/40"
                  }`}
                >
                  <span
                    className={`text-sm font-semibold ${
                      active ? "text-[var(--color-primary)]" : "text-[var(--ink)]"
                    }`}
                  >
                    {m.label}
                  </span>
                  <p className="mt-0.5 text-[11px] leading-tight text-[var(--color-text-hint)]">
                    {m.desc}
                  </p>
                </button>
              );
            })}
          </div>
        </fieldset>

        {/* ── Search Parameters ── */}
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">
              Top K
            </span>
            <input
              type="number"
              min={1}
              max={10000}
              className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
              value={form.vector_top_k ?? c.vector_top_k}
              onChange={(e) => set("vector_top_k", Number(e.target.value))}
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">
              相似度阈值
            </span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
              value={form.vector_similarity_threshold ?? c.vector_similarity_threshold}
              onChange={(e) => set("vector_similarity_threshold", Number(e.target.value))}
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">
              缓存 TTL (秒)
            </span>
            <input
              type="number"
              min={0}
              max={86400}
              className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
              value={form.vector_cache_ttl_sec ?? c.vector_cache_ttl_sec}
              onChange={(e) => set("vector_cache_ttl_sec", Number(e.target.value))}
            />
          </label>
        </div>

        {/* Allowlist */}
        {(form.vector_mode ?? c.vector_mode) === "allowlist" && (
          <label className="block">
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">
              白名单 (JSON 数组)
            </span>
            <input
              type="text"
              placeholder='["exam408-ds","exam408-os"] 或 [1,2,3]'
              className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 font-mono text-xs outline-none transition-colors focus:border-[var(--color-primary)]"
              value={form.vector_allowlist ?? c.vector_allowlist}
              onChange={(e) => set("vector_allowlist", e.target.value)}
            />
          </label>
        )}

        {/* ── Embedding API ── */}
        <fieldset className="space-y-3">
          <legend className="flex items-center gap-2 text-sm font-semibold text-[var(--ink)]">
            <Network className="h-4 w-4 text-[var(--color-primary)]" />
            Embedding API
          </legend>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">
                API Base URL
              </span>
              <input
                type="url"
                placeholder="https://api.openai.com/v1"
                className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
                value={form.embedding_base_url ?? c.embedding_base_url}
                onChange={(e) => set("embedding_base_url", e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">
                API Key
              </span>
              <div className="relative mt-1">
                <input
                  type="password"
                  placeholder={c.embedding_api_key_configured ? c.embedding_api_key_masked : "输入 API Key"}
                  className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 pr-16 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
                  value={form.embedding_api_key ?? ""}
                  onChange={(e) => set("embedding_api_key", e.target.value)}
                />
                {c.embedding_api_key_configured && !form.embedding_api_key && (
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-semibold uppercase text-[var(--color-success)]">
                    已配置
                  </span>
                )}
              </div>
            </label>
          </div>

          <div className="grid gap-3 sm:grid-cols-4">
            <label className="block">
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">模型</span>
              <input
                type="text"
                placeholder="BAAI/bge-m3"
                className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 font-mono text-xs outline-none transition-colors focus:border-[var(--color-primary)]"
                value={form.embedding_model ?? c.embedding_model}
                onChange={(e) => set("embedding_model", e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">维度</span>
              <input
                type="number"
                min={1}
                max={8192}
                className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
                value={form.embedding_dim ?? c.embedding_dim}
                onChange={(e) => set("embedding_dim", Number(e.target.value))}
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">超时 (秒)</span>
              <input
                type="number"
                min={1}
                max={300}
                className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
                value={form.embedding_timeout ?? c.embedding_timeout}
                onChange={(e) => set("embedding_timeout", Number(e.target.value))}
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">批量大小</span>
              <input
                type="number"
                min={1}
                max={256}
                className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
                value={form.embedding_batch_size ?? c.embedding_batch_size}
                onChange={(e) => set("embedding_batch_size", Number(e.target.value))}
              />
            </label>
          </div>

          <label className="block">
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">
              Provider
            </span>
            <input
              type="text"
              placeholder="openai_compatible"
              className="mt-1 h-10 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
              value={form.embedding_provider ?? c.embedding_provider}
              onChange={(e) => set("embedding_provider", e.target.value)}
            />
          </label>

          {/* Test Connection */}
          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              disabled={testMutation.isPending}
              onClick={() => {
                setTestResult(null);
                testMutation.mutate();
              }}
            >
              {testMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              测试连接
            </Button>
            {testResult && (
              <div className="flex items-center gap-2">
                {testResult.success ? (
                  <CheckCircle2 className="h-4 w-4 text-[var(--color-success)]" />
                ) : (
                  <XCircle className="h-4 w-4 text-[var(--color-danger)]" />
                )}
                <span
                  className={`text-xs ${
                    testResult.success
                      ? "text-[var(--color-success)]"
                      : "text-[var(--color-danger)]"
                  }`}
                >
                  {testResult.message}
                  {testResult.latency_ms > 0 && ` (${testResult.latency_ms}ms)`}
                  {testResult.returned_dim != null && ` dim=${testResult.returned_dim}`}
                </span>
              </div>
            )}
          </div>
        </fieldset>

        {/* ── Metadata ── */}
        {c.updated_at && (
          <p className="text-[11px] text-[var(--color-text-hint)]">
            上次更新: {new Date(c.updated_at).toLocaleString("zh-CN")}
          </p>
        )}
      </div>
    </section>
  );
}
