"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Save,
  SlidersHorizontal,
  Wifi,
  Zap,
  Settings2,
  Network,
  Brain,
} from "lucide-react";
import { useCallback, useState } from "react";
import { cn } from "@/lib/utils";
import { Toggle } from "@/components/ui/toggle";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import type {
  EmbeddingTestResponse,
  VectorConfig,
  VectorConfigPatchRequest,
} from "@/lib/api/types";

const VECTOR_MODES = [
  { value: "off", label: "关闭", desc: "禁用向量检索" },
  { value: "shadow", label: "影子", desc: "检索但不使用" },
  { value: "allowlist", label: "白名单", desc: "仅指定科目" },
  { value: "all", label: "全部", desc: "全局启用" },
] as const;

type Tab = "search" | "api" | "model";

const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
  { key: "search", label: "检索配置", icon: SlidersHorizontal },
  { key: "api", label: "Embedding API", icon: Network },
  { key: "model", label: "模型参数", icon: Brain },
];

const inputCls =
  "mt-1 h-9 w-full rounded-lg border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)]";
const monoCls =
  "mt-1 h-9 w-full rounded-lg border border-[var(--color-border)] bg-white px-3 font-mono text-xs outline-none transition-colors focus:border-[var(--color-primary)]";
const labelCls = "text-[11px] font-medium text-[var(--color-text-hint)]";

export function VectorConfigSection() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<VectorConfigPatchRequest>({});
  const [testResult, setTestResult] = useState<EmbeddingTestResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("search");
  const [keyEditing, setKeyEditing] = useState(false);

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
      setKeyEditing(false);
      setMessage("配置已保存");
      setTimeout(() => setMessage(null), 3000);
    },
    onError: (err) => setMessage(getErrorMessage(err)),
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

  // ── Loading ──
  if (config.isLoading) {
    return (
      <div className="rounded-2xl border border-[var(--color-border)]/80 bg-white/80 p-8 text-center shadow-sm">
        <Loader2 className="mx-auto h-5 w-5 animate-spin text-[var(--color-primary)]" />
        <p className="mt-2 text-sm text-[var(--color-text-hint)]">加载向量配置…</p>
      </div>
    );
  }

  // ── Error ──
  if (config.isError || !c) {
    return (
      <p className="rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
        {getErrorMessage(config.error)}
      </p>
    );
  }

  const isEnabled = form.vector_enabled ?? c.vector_enabled;
  const currentMode = form.vector_mode ?? c.vector_mode;

  return (
    <section className="overflow-hidden rounded-2xl border border-[var(--color-border)]/80 bg-white/80 shadow-[var(--shadow-card)] animate-rise-in">
      {/* ── Header ── */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)]/60 px-5 py-4">
        <div>
          <h3 className="font-display text-xl font-bold text-[var(--ink)]">
            向量检索 & Embedding
          </h3>
          <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">
            pgvector 检索配置与 Embedding API 管理
          </p>
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

      {/* ── Message ── */}
      {message && (
        <div className="border-b border-[var(--color-border)]/40 px-5 py-2.5">
          <p className="text-sm text-[var(--color-text-secondary)]">{message}</p>
        </div>
      )}

      {/* ── Body: Sidebar + Content ── */}
      <div className="flex min-h-[380px]">
        {/* ── Sidebar ── */}
        <nav className="flex w-[152px] shrink-0 flex-col gap-1 border-r border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/50 p-2.5">
          {/* Enable toggle */}
          <div
            className={cn(
              "mb-2 flex items-center justify-between rounded-lg border px-3 py-2.5 transition-colors",
              isEnabled
                ? "border-[var(--color-success)]/30 bg-[var(--color-success-light)]"
                : "border-[var(--color-border)] bg-white/60",
            )}
          >
            <span
              className={cn(
                "text-xs font-semibold",
                isEnabled ? "text-[var(--color-success)]" : "text-[var(--color-text-hint)]",
              )}
            >
              {isEnabled ? "已启用" : "已禁用"}
            </span>
            <Toggle
              checked={isEnabled}
              size="sm"
              onChange={() => set("vector_enabled", !isEnabled)}
            />
          </div>

          {/* Tab buttons */}
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] transition-all",
                  active
                    ? "bg-white font-semibold text-[var(--ink)] shadow-[0_2px_8px_rgba(0,0,0,.06)]"
                    : "font-normal text-[var(--color-text-secondary)] hover:bg-white/60",
                )}
              >
                <Icon
                  className={cn(
                    "h-3.5 w-3.5",
                    active ? "text-[var(--color-primary)]" : "text-[var(--color-text-hint)]",
                  )}
                />
                {t.label}
              </button>
            );
          })}

          {/* Footer in sidebar */}
          <div className="mt-auto">
            {c.updated_at && (
              <p className="px-3 text-[10px] leading-tight text-[var(--color-text-hint)]">
                更新于
                <br />
                {new Date(c.updated_at).toLocaleString("zh-CN")}
              </p>
            )}
          </div>
        </nav>

        {/* ── Content ── */}
        <div className="flex-1 p-5">
          {/* ═══ Tab: 检索配置 ═══ */}
          {tab === "search" && (
            <div className="space-y-5 animate-rise-in">
              {/* Mode selector */}
              <fieldset>
                <legend className="mb-2.5 text-xs font-semibold text-[var(--color-text-secondary)]">
                  检索模式
                </legend>
                <div className="grid grid-cols-2 gap-2">
                  {VECTOR_MODES.map((m) => {
                    const active = currentMode === m.value;
                    return (
                      <button
                        key={m.value}
                        type="button"
                        onClick={() => set("vector_mode", m.value)}
                        className={cn(
                          "rounded-lg border px-3 py-2.5 text-left transition-all",
                          active
                            ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] shadow-sm"
                            : "border-[var(--color-border)]/60 bg-white/60 hover:border-[var(--color-primary)]/40",
                        )}
                      >
                        <span
                          className={cn(
                            "text-xs font-semibold",
                            active ? "text-[var(--color-primary)]" : "text-[var(--ink)]",
                          )}
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

              {/* Search parameters */}
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

              {currentMode === "allowlist" && (
                <label className="block">
                  <span className={labelCls}>白名单 (JSON 数组)</span>
                  <input
                    type="text"
                    placeholder='["exam408-ds","exam408-os"]'
                    className={monoCls}
                    value={form.vector_allowlist ?? c.vector_allowlist}
                    onChange={(e) => set("vector_allowlist", e.target.value)}
                  />
                </label>
              )}
            </div>
          )}

          {/* ═══ Tab: Embedding API ═══ */}
          {tab === "api" && (
            <div className="space-y-4 animate-rise-in">
              {/* Key status badge */}
              <div className="flex items-center gap-2">
                {c.embedding_api_key_configured ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-success-light)] px-2.5 py-1 text-[11px] font-semibold text-[var(--color-success)]">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Key 已配置
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-warning-light)] px-2.5 py-1 text-[11px] font-semibold text-[var(--color-warning)]">
                    <Zap className="h-3.5 w-3.5" />
                    Key 未配置
                  </span>
                )}
              </div>

              <div className="space-y-3">
                <label className="block">
                  <span className={labelCls}>API Base URL</span>
                  <input
                    type="url"
                    placeholder="https://api.openai.com/v1"
                    className={inputCls}
                    value={form.embedding_base_url ?? c.embedding_base_url}
                    onChange={(e) => set("embedding_base_url", e.target.value)}
                  />
                </label>

                <label className="block">
                  <span className={labelCls}>API Key</span>
                  <input
                    type="password"
                    placeholder="sk-..."
                    className={inputCls}
                    value={
                      form.embedding_api_key ??
                      (keyEditing ? "" : c.embedding_api_key_configured ? "••••••••••" : "")
                    }
                    onChange={(e) => {
                      if (!keyEditing) setKeyEditing(true);
                      set("embedding_api_key", e.target.value);
                    }}
                    onFocus={() => {
                      if (!keyEditing && c.embedding_api_key_configured) {
                        setKeyEditing(true);
                        setForm((prev) => {
                          const next = { ...prev };
                          delete next.embedding_api_key;
                          return next;
                        });
                      }
                    }}
                    onBlur={() => {
                      if (keyEditing && !form.embedding_api_key) {
                        setKeyEditing(false);
                      }
                    }}
                  />
                </label>

                <label className="block">
                  <span className={labelCls}>Provider</span>
                  <input
                    type="text"
                    placeholder="openai_compatible"
                    className={inputCls}
                    value={form.embedding_provider ?? c.embedding_provider}
                    onChange={(e) => set("embedding_provider", e.target.value)}
                  />
                </label>
              </div>

              {/* Test connection */}
              <div className="border-t border-[var(--color-border)]/40 pt-4">
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
                    <Wifi className="h-4 w-4" />
                  )}
                  测试 Embedding 连接
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
                      <div className="min-w-0">
                        <p className="font-semibold">
                          {testResult.success ? "连接成功" : "连接失败"}
                        </p>
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

          {/* ═══ Tab: 模型参数 ═══ */}
          {tab === "model" && (
            <div className="animate-rise-in">
              <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                <label className="block">
                  <span className={labelCls}>模型</span>
                  <input
                    type="text"
                    placeholder="BAAI/bge-m3"
                    className={monoCls}
                    value={form.embedding_model ?? c.embedding_model}
                    onChange={(e) => set("embedding_model", e.target.value)}
                  />
                </label>
                <label className="block">
                  <span className={labelCls}>维度</span>
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
                  <span className={labelCls}>超时 (秒)</span>
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

              {/* Info */}
              <div className="mt-5 rounded-lg border border-[var(--color-border)]/40 bg-[var(--color-bg-input)]/40 px-4 py-3">
                <div className="flex items-start gap-2">
                  <Settings2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-text-hint)]" />
                  <div className="text-xs leading-relaxed text-[var(--color-text-secondary)]">
                    <p>
                      模型名称和维度决定了向量检索时调用的 Embedding API 参数。
                      修改模型或维度后，已有的向量数据可能需要重新生成。
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
