"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Filter, RefreshCw, Search, X } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { AuditLogDetail, AuditLogListItem, PaginatedResponse, QuestionAuditDetail } from "@/lib/api/types";

// ── Constants ──

const SEVERITY_OPTIONS = ["", "critical", "important", "normal", "low"] as const;
const STATUS_OPTIONS = ["", "success", "failed"] as const;
const DEBOUNCE_MS = 300;
const KEYWORD_MAX_LENGTH = 200;

// ── Label mappings ──

const ACTION_LABELS: Record<string, string> = {
  "question.update": "编辑题目",
  "question.delete": "删除题目",
  "question.batch_delete": "批量删除题目",
  "question.toggle_active": "修改题目启用状态",
  "question.backfill_embeddings": "题目向量回填",
  "subject.create": "新增科目",
  "subject.update": "编辑科目",
  "subject.delete": "删除科目",
  "admin_user.create": "新增管理员",
  "admin_user.update": "编辑管理员",
  "admin_user.delete": "删除管理员",
  "admin_user.force_logout": "强制登出",
  "admin_user.reset_password": "重置密码",
  "admin_user.change_password": "修改密码",
  "app_user.update": "编辑用户",
  "app_user.ban": "封禁用户",
  "app_user.unban": "解封用户",
  "app_user.bind_admin": "绑定管理员",
  "app_user.unbind_admin": "解绑管理员",
  "ai_model_config.create": "新增AI模型",
  "ai_model_config.update": "编辑AI模型",
  "ai_model_config.delete": "删除AI模型",
  "ai_config.update": "更新AI配置",
  "ai_setting.update": "更新AI设置",
  "ai_setting.disable": "关闭AI解析",
  "ai_parse.blocked": "AI解析被拒绝",
  "ai_quota.exhausted": "AI额度耗尽",
  "role.update_permissions": "修改角色权限",
  "import.complete": "AI补全导入题",
  "import.batch_complete": "AI批量补全",
  "import.enrich": "AI富化导入题",
  "watermark_rule.create": "新增水印规则",
  "watermark_rule.update": "编辑水印规则",
  "watermark_rule.delete": "删除水印规则",
  "vector_config.update": "更新向量配置",
  "knowledge.backfill": "知识点回填",
  "knowledge.create_edge": "创建知识图谱边",
  "knowledge.infer_edges": "推断知识图谱边",
};

const SEVERITY_LABELS: Record<string, string> = {
  critical: "严重",
  important: "重要",
  normal: "普通",
  low: "低",
};

const STATUS_LABELS: Record<string, string> = {
  success: "成功",
  failed: "失败",
};

function actionLabel(action: string): string {
  return ACTION_LABELS[action] || action;
}

// ── Date / Time helpers ──

function formatLocalDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return "时间格式异常";
    const fmt = new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    return fmt.format(d);
  } catch {
    return "时间格式异常";
  }
}

/** Convert a local date string (YYYY-MM-DD) to a UTC ISO string at local midnight. */
function localDateToUtcIso(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  const local = new Date(y, m - 1, d);
  return local.toISOString();
}

/** Convert a local date string (YYYY-MM-DD) to the NEXT local midnight in UTC ISO (exclusive end). */
function localDateToUtcIsoNext(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  const local = new Date(y, m - 1, d + 1); // next local midnight
  return local.toISOString();
}

// ── Tone map ──

const TONE_MAP: Record<string, "danger" | "warning" | "primary" | "neutral"> = {
  critical: "danger",
  important: "warning",
  normal: "primary",
  low: "neutral",
};

// ── Detail value renderer ──

function renderValue(value: unknown, indent = 0): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "[序列化异常]";
  }
}

// ── Options renderer ──

function renderOptions(options: unknown): string {
  if (!options) return "—";
  if (typeof options === "string") return options;
  if (Array.isArray(options)) {
    return options.map((opt, i) => {
      if (typeof opt === "string") return `${String.fromCharCode(65 + i)}. ${opt}`;
      if (typeof opt === "object" && opt !== null) {
        const key = opt.key || String.fromCharCode(65 + i);
        const text = opt.text || opt.value || opt.label || JSON.stringify(opt);
        return `${key}. ${text}`;
      }
      return `${String.fromCharCode(65 + i)}. ${String(opt)}`;
    }).join("\n");
  }
  if (typeof options === "object" && options !== null) {
    const obj = options as Record<string, unknown>;
    return Object.entries(obj)
      .map(([key, val]) => `${key}. ${typeof val === "string" ? val : JSON.stringify(val)}`)
      .join("\n");
  }
  return JSON.stringify(options);
}

// ── Question detail resolver ──

const DATA_SOURCE_LABELS: Record<string, string> = {
  audit_snapshot: "操作时快照",
  audit_before: "操作前快照",
  audit_after: "操作后快照",
  audit_summary: "日志摘要",
  current_database: "当前数据库内容，仅用于兼容历史日志",
};

function renderQuestionDetail(qd: QuestionAuditDetail) {
  const isCurrentDb = qd.data_source === "current_database";
  const fields: Array<{ label: string; value: unknown }> = [
    { label: "题目 ID", value: qd.id },
    { label: "数据来源", value: DATA_SOURCE_LABELS[qd.data_source ?? ""] ?? qd.data_source },
    { label: "科目", value: qd.subject_name ?? qd.subject_code },
    { label: "题型", value: qd.question_type },
    { label: "题干", value: qd.content_text ?? qd.content_preview ?? renderValue(qd.content) },
    { label: "选项", value: renderOptions(qd.options) },
    { label: "答案", value: qd.answer },
    { label: "解析", value: qd.analysis },
    { label: "知识点", value: qd.knowledge_points },
    { label: "难度", value: qd.difficulty },
    { label: "年份", value: qd.year },
    { label: "审核状态", value: qd.review_status },
    { label: "启用状态", value: qd.is_active === null ? "—" : qd.is_active ? "启用" : "停用" },
  ];

  return (
    <div className="space-y-2">
      <h4 className="font-semibold text-[var(--ink)]">题目详情</h4>
      {isCurrentDb && (
        <p className="rounded-2xl bg-[var(--color-warning-light)] px-3 py-2 text-xs text-[var(--color-warning)]">
          该内容是当前题目数据，可能与日志发生时的内容不同。
        </p>
      )}
      {fields.map(({ label, value }) => (
        <section key={label} className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3">
          <p className="text-xs font-medium text-[var(--color-text-hint)]">{label}</p>
          <pre className="mt-1 whitespace-pre-wrap font-sans text-sm text-[var(--color-text-secondary)]">{renderValue(value)}</pre>
        </section>
      ))}
    </div>
  );
}

// ============================================================================
// Component
// ============================================================================

export default function AuditLogsPage() {
  // ── Filters ──
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [detailId, setDetailId] = useState<number | null>(null);

  // Debounce keyword
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    if (keyword === "") {
      setDebouncedKeyword("");
      return;
    }
    debounceTimer.current = setTimeout(() => {
      setDebouncedKeyword(keyword);
      setPage(1);
    }, DEBOUNCE_MS);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [keyword]);

  // Convert local dates to UTC for the API
  const queryParams = useMemo(() => {
    const params: Record<string, string | number | boolean | undefined | null> = {
      page,
      pageSize: 20,
      severity,
      status,
      resourceType: resourceType,
      keyword: debouncedKeyword,
    };
    if (dateFrom) {
      params["from"] = localDateToUtcIso(dateFrom);
    }
    if (dateTo) {
      params["to"] = localDateToUtcIsoNext(dateTo);
    }
    return params;
  }, [page, severity, status, resourceType, debouncedKeyword, dateFrom, dateTo]);

  // ── Queries ──
  const logs = useQuery({
    queryKey: ["audit-logs", "list", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<AuditLogListItem>>(`/audit-logs${toQuery(queryParams)}`),
    retry: 1,
    staleTime: 10_000,
    refetchOnMount: "always",
  });

  const detail = useQuery({
    queryKey: ["audit-logs", "detail", detailId],
    queryFn: () => apiRequest<AuditLogDetail>(`/audit-logs/${detailId}`),
    enabled: detailId !== null,
    retry: 1,
    staleTime: 30_000,
  });

  // ── Handlers ──

  const handleRefresh = useCallback(() => {
    logs.refetch();
  }, [logs]);

  const handleReset = useCallback(() => {
    setSeverity("");
    setStatus("");
    setKeyword("");
    setDebouncedKeyword("");
    setResourceType("");
    setDateFrom("");
    setDateTo("");
    setPage(1);
  }, []);

  const openDetail = useCallback((id: number) => {
    setDetailId(id);
  }, []);

  const closeDetail = useCallback(() => {
    setDetailId(null);
  }, []);

  // Detail drawer: Escape key
  useEffect(() => {
    if (detailId === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDetail();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [detailId, closeDetail]);

  // Prevent background scroll when drawer open
  useEffect(() => {
    if (detailId !== null) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [detailId]);

  // ── Helpers ──

  const renderQuestionSummary = useCallback((log: AuditLogListItem) => {
    const summary = log.detail_summary;
    if (!summary) return null;
    const parts: string[] = [];
    if (summary.subject_name) parts.push(summary.subject_name);
    if (summary.question_type) parts.push(summary.question_type);
    if (summary.content_preview) {
      const preview = summary.content_preview.length > 80 ? summary.content_preview.slice(0, 80) + "…" : summary.content_preview;
      parts.push(preview);
    }
    if (parts.length === 0) return null;
    return (
      <p className="mt-1 text-xs text-[var(--color-text-hint)] line-clamp-2">
        {parts.join(" · ")}
      </p>
    );
  }, []);

  // ── Detail drawer structured sections ──

  const renderDetailSections = useCallback((data: AuditLogDetail) => {
    const sections: Array<{ label: string; value: unknown }> = [
      { label: "操作", value: actionLabel(data.action) },
      { label: "原始动作", value: data.action },
      { label: "资源类型", value: data.resource_type },
      { label: "资源ID", value: data.resource_id },
      { label: "级别", value: SEVERITY_LABELS[data.severity] ?? data.severity },
      { label: "状态", value: STATUS_LABELS[data.status] ?? data.status },
      { label: "操作人", value: data.operator_name ?? data.operator_id ?? "system" },
      { label: "IP", value: data.ip },
      { label: "User-Agent", value: data.user_agent },
      { label: "操作时间（本地）", value: formatLocalDateTime(data.created_at) },
      { label: "操作时间（UTC）", value: data.created_at },
      { label: "错误信息", value: data.error_message },
    ];

    return (
      <>
        {sections.map(({ label, value }) => (
          <section key={label} className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
            <p className="font-semibold text-[var(--ink)]">{label}</p>
            <pre className="mt-2 whitespace-pre-wrap font-sans text-[var(--color-text-secondary)]">{renderValue(value)}</pre>
          </section>
        ))}

        {/* Question detail section (from enriched API data) */}
        {data.question_detail && renderQuestionDetail(data.question_detail)}
        {/* Fallback when no question data and this is a question log */}
        {!data.question_detail && (data.resource_type === "question" || data.action.startsWith("question.")) && (
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
            <p className="font-semibold text-[var(--ink)]">题目详情</p>
            <p className="mt-2 text-sm text-[var(--color-text-hint)]">
              该历史日志未保存题目快照，当前数据库中也未找到对应题目。
            </p>
          </section>
        )}

        {/* Structured detail fields (before/after/changed_fields etc.) */}
        {data.detail && renderStructuredDetail(data)}

        {/* Raw JSON detail (collapsible, for debugging) */}
        <details className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3">
          <summary className="cursor-pointer text-xs font-medium text-[var(--color-text-hint)]">原始 JSON</summary>
          <pre className="mt-2 whitespace-pre-wrap font-sans text-xs text-[var(--color-text-secondary)]">{renderValue(data.detail)}</pre>
        </details>
      </>
    );
  }, []);

  const renderStructuredDetail = useCallback((data: AuditLogDetail) => {
    const detail = data.detail;
    if (!detail || typeof detail !== "object") return null;

    const items: Array<{ label: string; value: unknown }> = [];

    if ("changed_fields" in detail && Array.isArray(detail.changed_fields)) {
      items.push({ label: "修改字段", value: (detail.changed_fields as string[]).join(", ") });
    }
    if ("before" in detail) items.push({ label: "修改前", value: detail.before });
    if ("after" in detail) items.push({ label: "修改后", value: detail.after });
    if ("edit_reason" in detail) items.push({ label: "编辑原因", value: detail.edit_reason });
    if ("delete_mode" in detail) items.push({ label: "删除方式", value: detail.delete_mode });
    if ("requested_ids" in detail && Array.isArray(detail.requested_ids)) {
      const rids = detail.requested_ids as number[];
      items.push({ label: "请求删除的 ID", value: `共 ${rids.length} 个: [${rids.join(", ")}]` });
    }
    if ("success_ids" in detail && Array.isArray(detail.success_ids)) {
      const sids = detail.success_ids as number[];
      items.push({ label: "成功删除的 ID", value: `共 ${sids.length} 个: [${sids.join(", ")}]` });
    }
    if ("failed_items" in detail && Array.isArray(detail.failed_items)) {
      const fails = detail.failed_items as Array<{ id: number; error: string }>;
      items.push({ label: "失败项", value: fails.length ? fails.map((f) => `#${f.id}: ${f.error}`).join("\n") : "无" });
    }

    if (items.length === 0) return null;

    return (
      <div className="space-y-2">
        <h4 className="font-semibold text-[var(--ink)]">变更详情</h4>
        {items.map(({ label, value }) => (
          <section key={label} className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3">
            <p className="text-xs font-medium text-[var(--color-text-hint)]">{label}</p>
            <pre className="mt-1 whitespace-pre-wrap font-sans text-sm text-[var(--color-text-secondary)]">{renderValue(value)}</pre>
          </section>
        ))}
      </div>
    );
  }, []);

  // ── Pagination info ──

  const paginationInfo = useMemo(() => {
    if (!logs.data) return null;
    const { total, page: cp, total_pages: tp } = logs.data;
    if (total === 0) return "共 0 条";
    return `共 ${total} 条 · 第 ${Math.min(cp, tp)}/${tp} 页`;
  }, [logs.data]);

  // ── Render ──

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">Audit Logs</p>
          <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">审计日志</h2>
        </div>
      </div>

      <Card className="overflow-hidden">
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">日志列表</h3>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">支持多维过滤、刷新、单条详情查看。</p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={handleRefresh} disabled={logs.isFetching}>
              <RefreshCw className={`h-4 w-4 ${logs.isFetching ? "animate-spin" : ""}`} />
              刷新
            </Button>
            <Button variant="secondary" onClick={handleReset}>
              <Filter className="h-4 w-4" />
              重置
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* ── Filters ── */}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <label className="relative xl:col-span-2">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input
                className="pl-9"
                placeholder="搜索动作 / 资源 / 操作人（自动防抖）"
                value={keyword}
                maxLength={KEYWORD_MAX_LENGTH}
                onChange={(e) => { setKeyword(e.target.value); }}
              />
              {keyword && (
                <button
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-hint)] hover:text-[var(--ink)]"
                  onClick={() => { setKeyword(""); setDebouncedKeyword(""); setPage(1); }}
                  aria-label="清除搜索"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </label>
            <select
              className="h-11 w-full min-w-0 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
              value={severity}
              onChange={(e) => { setSeverity(e.target.value); setPage(1); }}
              aria-label="严重程度筛选"
            >
              {SEVERITY_OPTIONS.map((s) => (
                <option key={s || "all"} value={s}>{s ? SEVERITY_LABELS[s] ?? s : "全部级别"}</option>
              ))}
            </select>
            <select
              className="h-11 w-full min-w-0 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
              value={status}
              onChange={(e) => { setStatus(e.target.value); setPage(1); }}
              aria-label="状态筛选"
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s || "all"} value={s}>{s ? STATUS_LABELS[s] ?? s : "全部状态"}</option>
              ))}
            </select>
            <Input
              placeholder="资源类型"
              value={resourceType}
              onChange={(e) => { setResourceType(e.target.value); setPage(1); }}
              maxLength={64}
            />
          </div>

          {/* ── Date range ── */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">日期范围（本地日期）</span>
            <Input
              className="min-w-0 flex-1 sm:flex-none sm:w-44"
              type="date"
              value={dateFrom}
              onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
              aria-label="开始日期"
            />
            <span className="text-[var(--color-text-hint)]">—</span>
            <Input
              className="min-w-0 flex-1 sm:flex-none sm:w-44"
              type="date"
              value={dateTo}
              onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
              aria-label="结束日期"
            />
            {(dateFrom || dateTo) && (
              <span className="text-xs text-[var(--color-text-hint)]">默认查询近 183 天</span>
            )}
          </div>

          {/* ── Error: 422 date validation ── */}
          {logs.isError && !logs.isFetching && (
            <div className="flex flex-col items-center gap-4 rounded-2xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] p-6">
              <p className="text-sm text-[var(--color-danger)]">
                {logs.error instanceof Error
                  ? logs.error.message.includes("不能超过") || logs.error.message.includes("不能晚于")
                    ? logs.error.message
                    : logs.error.message.includes("403") || logs.error.message.includes("Forbidden")
                      ? "权限不足，需要 audit:read 权限"
                      : logs.error.message.includes("401") || logs.error.message.includes("Unauthorized")
                        ? "登录已过期，请重新登录"
                        : logs.error.message.slice(0, 200)
                  : "请求失败，请稍后重试"}
              </p>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => logs.refetch()}>重试</Button>
                <Button variant="secondary" onClick={handleReset}>重置筛选</Button>
              </div>
            </div>
          )}

          {/* ── Loading skeleton ── */}
          {logs.isLoading && (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="animate-pulse rounded-2xl border border-[var(--color-border)] bg-white/70 p-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="h-5 w-16 rounded-full bg-[var(--color-border)]" />
                    <div className="h-5 w-14 rounded-full bg-[var(--color-border)]" />
                    <div className="h-4 w-32 rounded bg-[var(--color-border)]" />
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-4">
                    <div className="h-3 w-24 rounded bg-[var(--color-border)]" />
                    <div className="h-3 w-36 rounded bg-[var(--color-border)]" />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ── Empty state (only when loaded and truly empty) ── */}
          {!logs.isLoading && !logs.isError && (logs.data?.items?.length ?? 0) === 0 && (
            <p className="py-10 text-center text-sm text-[var(--color-text-hint)]">暂无审计日志</p>
          )}

          {/* ── List ── */}
          {!logs.isLoading && !logs.isError && (logs.data?.items?.length ?? 0) > 0 && (
            <div className="space-y-3">
              {logs.data!.items.map((log) => (
                <button
                  key={log.id}
                  className="w-full rounded-2xl border border-[var(--color-border)] bg-white/70 p-4 text-left transition hover:border-[var(--color-primary)] hover:bg-white hover:shadow-sm"
                  onClick={() => openDetail(log.id)}
                >
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <StatusBadge tone={TONE_MAP[log.severity] ?? "neutral"}>
                      {SEVERITY_LABELS[log.severity] ?? log.severity}
                    </StatusBadge>
                    <StatusBadge tone={log.status === "failed" ? "danger" : "success"}>
                      {STATUS_LABELS[log.status] ?? log.status}
                    </StatusBadge>
                    <span className="text-sm font-semibold text-[var(--ink)]">{actionLabel(log.action)}</span>
                    <span className="text-xs text-[var(--color-text-hint)]">
                      by {log.operator_name ?? log.operator_id ?? "system"}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-[var(--color-text-secondary)]">
                    {log.resource_type && (
                      <span title="资源类型">{log.resource_type}{log.resource_id ? ` #${log.resource_id}` : ""}</span>
                    )}
                    {log.ip && <span title="IP 地址">{log.ip}</span>}
                    <span title={log.created_at}>{formatLocalDateTime(log.created_at)}</span>
                  </div>
                  {renderQuestionSummary(log)}
                  {log.error_message ? (
                    <p className="mt-2 rounded-2xl bg-[var(--color-danger-light)] px-3 py-2 text-xs text-[var(--color-danger)]">
                      {log.error_message.length > 150 ? log.error_message.slice(0, 150) + "…" : log.error_message}
                    </p>
                  ) : null}
                </button>
              ))}
            </div>
          )}

          {/* ── Pagination ── */}
          {logs.data && logs.data.total > 0 && (
            <div className="mt-4 flex items-center justify-between text-sm text-[var(--color-text-secondary)]">
              <span>{paginationInfo}</span>
              <div className="flex gap-1">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page <= 1 || logs.isFetching}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  上一页
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page >= (logs.data?.total_pages ?? 1) || logs.isFetching}
                  onClick={() => setPage((p) => Math.min(logs.data?.total_pages ?? 1, p + 1))}
                >
                  下一页
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Detail Drawer ── */}
      {detailId !== null && (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.28)]"
          onClick={closeDetail}
          role="dialog"
          aria-modal="true"
          aria-label="审计日志详情"
        >
          <aside
            className="h-full w-full max-w-2xl overflow-y-auto bg-white p-6 shadow-[var(--shadow-floating)] outline-none"
            onClick={(e) => e.stopPropagation()}
            tabIndex={-1}
          >
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">审计日志详情</h3>
              <div className="flex gap-2">
                {detail.isError && (
                  <Button variant="secondary" size="sm" onClick={() => detail.refetch()}>重试</Button>
                )}
                <Button variant="ghost" onClick={closeDetail}>关闭</Button>
              </div>
            </div>

            {/* Detail loading */}
            {detail.isLoading && (
              <p className="mt-6 text-sm text-[var(--color-text-secondary)]">正在加载详情...</p>
            )}

            {/* Detail error */}
            {detail.isError && !detail.isLoading && (
              <div className="mt-6 flex flex-col items-center gap-4">
                <p className="text-sm text-[var(--color-danger)]">
                  {detail.error instanceof Error ? detail.error.message.slice(0, 200) : "加载详情失败"}
                </p>
              </div>
            )}

            {/* Detail data */}
            {detail.data && !detail.isLoading && (
              <div className="mt-6 space-y-4 text-sm">
                {renderDetailSections(detail.data)}
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
