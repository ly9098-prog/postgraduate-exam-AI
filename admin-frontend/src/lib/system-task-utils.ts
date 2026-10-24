/**
 * Pure helpers for system tasks page, extracted from system/tasks/page.tsx.
 * Covers status label mapping, async task naming, task status metadata,
 * run result metadata, status-group matching, and queue total computation.
 */

export const STATUS_LABELS_ZH: Record<string, string> = {
  pending: "待发布",
  leased: "发布中",
  published: "已发布",
  failed: "失败",
  cancelled: "已取消",
  ready: "待处理",
  processing: "处理中",
  retry: "等待重试",
  dead: "死信",
  corrupt: "损坏",
  completed: "已完成",
  success: "成功",
  skipped: "已跳过",
  running: "运行中",
  idle: "空闲",
  disabled: "已停用",
  unavailable: "不可用",
  unobservable: "不可观测",
  prerequisite_failed: "运行条件异常",
  database_unavailable: "数据库不可用",
  database_unobservable: "数据库不可观测",
  loop_unavailable: "执行循环未启动",
  stopped: "未启动",
  stale: "心跳过期",
  redis_unavailable: "Redis 不可用",
  cancel_requested: "取消中",
  review_required: "待人工处理",
  active: "运行中",
  inactive: "未运行",
  activating: "启动中",
  deactivating: "停止中",
  not_found: "未找到",
  "not-found": "未找到",
};

export const ASYNC_TASK_LABELS: Record<string, string> = {
  import_pipeline: "题目导入流水线",
  image_pipeline: "图片导入处理",
  excel_pipeline: "Excel 导入处理",
  resume_pipeline: "导入恢复任务",
  admin_resume: "管理端恢复任务",
  batch_image: "批量图片处理",
  formula_batch: "公式批处理",
  prewarm_analysis: "AI 预热分析",
  export_mistakes: "错题导出",
  answer_projection: "答题投影",
  ocr_pipeline: "OCR 处理",
};

export type StatusTone = "danger" | "success" | "warning" | "neutral";

/**
 * Map a status value to its Chinese display label.
 */
export function statusLabelZh(value?: string | null): string {
  if (!value) return "未知";
  const key = String(value).trim().toLowerCase();
  return STATUS_LABELS_ZH[key] || value;
}

/**
 * Map an async task type to its Chinese display label.
 */
export function asyncTaskName(taskType: string): string {
  return ASYNC_TASK_LABELS[taskType] || taskType;
}

/**
 * Derive the display metadata (label + tone) for a task's status/location.
 */
export function taskStatusMeta(status: string, location?: string | null): {
  label: string;
  tone: StatusTone;
} {
  const value = (location || status || "").toLowerCase();
  if (["failed", "dead", "corrupt"].includes(value) || status === "failed") {
    return { label: value === "corrupt" ? "异常" : "失败", tone: "danger" };
  }
  if (["processing", "running"].includes(value)) return { label: "运行中", tone: "success" };
  if (value === "retry") return { label: "等待重试", tone: "warning" };
  if (["unavailable", "unobservable"].includes(value)) return { label: statusLabelZh(value), tone: "warning" };
  if (["ready", "pending", "idle"].includes(value)) return { label: "等待中", tone: "neutral" };
  if (value === "disabled") return { label: "已停用", tone: "neutral" };
  if (["completed", "published", "success"].includes(value)) return { label: "成功", tone: "success" };
  return { label: statusLabelZh(status), tone: "neutral" };
}

/**
 * Derive the display metadata for a run result.
 */
export function runResultMeta(status?: string | null): {
  label: string;
  tone: StatusTone;
} {
  if (status === "success") return { label: "成功", tone: "success" };
  if (status === "failed") return { label: "失败", tone: "danger" };
  if (status === "skipped") return { label: "跳过", tone: "warning" };
  return { label: "暂无记录", tone: "neutral" };
}

export type TaskStatusFilter = "all" | "running" | "waiting" | "failed" | "unavailable" | "disabled";

/**
 * Check whether a task's status/location matches the selected status filter.
 */
export function taskMatchesStatus(
  filter: TaskStatusFilter,
  status: string,
  location?: string | null,
): boolean {
  if (filter === "all") return true;
  const value = (location || status || "").toLowerCase();
  if (filter === "running") return ["running", "processing"].includes(value);
  if (filter === "waiting") return ["idle", "ready", "pending", "retry"].includes(value);
  if (filter === "failed") return ["failed", "dead", "corrupt"].includes(value);
  if (filter === "unavailable") return ["unavailable", "unobservable"].includes(value);
  if (filter === "disabled") return value === "disabled";
  return true;
}

/**
 * Sum all queue totals (ready + processing + retry + dead + corrupt).
 */
export function computeQueueTotal(
  totals: { ready: number; processing: number; retry: number; dead: number; corrupt: number } | undefined,
): number {
  if (!totals) return 0;
  return totals.ready + totals.processing + totals.retry + totals.dead + totals.corrupt;
}

/**
 * Sum only the failed/error queue totals (dead + corrupt).
 */
export function computeFailedQueueTotal(
  totals: { dead: number; corrupt: number } | undefined,
): number {
  if (!totals) return 0;
  return totals.dead + totals.corrupt;
}

/**
 * Format a duration in seconds to a human-readable Chinese string.
 */
export function formatDuration(seconds?: number | null): string {
  const value = Math.max(0, Number(seconds || 0));
  if (value < 60) return `${Math.round(value)} 秒`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟`;
  return `${(value / 3600).toFixed(value >= 36_000 ? 0 : 1)} 小时`;
}

/**
 * Format a short date from "YYYY-MM-DD" to "MM-DD".
 */
export function formatShortDate(value: string): string {
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) return value;
  return `${month}-${day}`;
}

/**
 * Format bytes to a human-readable string.
 */
export function formatBytes(value?: number | null): string {
  const bytes = Math.max(0, Number(value || 0));
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

/**
 * Map health severity to badge tone.
 */
export function healthTone(severity: "ok" | "warning" | "error"): StatusTone {
  if (severity === "ok") return "success";
  if (severity === "warning") return "warning";
  return "danger";
}

/**
 * Map a trace/outbox/queue status to a badge tone.
 */
export function traceStatusTone(status?: string | null): StatusTone {
  if (status === "completed" || status === "published") return "success";
  if (["failed", "dead", "corrupt"].includes(status || "")) return "danger";
  if (["processing", "retry", "pending", "leased"].includes(status || "")) return "warning";
  return "neutral";
}

/**
 * Map a queue location value to its Chinese label.
 */
export function queueLocationLabelZh(value?: string | null): string {
  if (!value) return "—";
  const key = String(value).trim().toLowerCase();
  const labels: Record<string, string> = {
    ready: "待处理队列",
    processing: "处理中队列",
    retry: "重试队列",
    dead: "死信队列",
    corrupt: "损坏队列",
  };
  return labels[key] || `${statusLabelZh(value)}队列`;
}

/**
 * Map a severity level to its Chinese label.
 */
export function severityLabelZh(value?: string | null): string {
  if (value === "error") return "错误";
  if (value === "warning") return "警告";
  return "正常";
}
