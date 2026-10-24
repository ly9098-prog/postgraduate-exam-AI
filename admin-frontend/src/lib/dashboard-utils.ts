/**
 * Pure helpers for admin dashboard page, extracted from dashboard/page.tsx.
 */

import type { DashboardQuestionStats } from "@/lib/api/types";

/**
 * Format a number for display, or return "--" for invalid values.
 */
export function numberValue(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("zh-CN")
    : "--";
}

/**
 * Convert review status stats to pie chart data.
 * Handles both array and object formats from the API.
 */
export function toPieData(
  input?: DashboardQuestionStats["by_review_status"],
): Array<{ name: string; count: number }> {
  if (!input) return [];
  if (Array.isArray(input)) return input;
  return Object.entries(input).map(([name, count]) => ({
    name,
    count: Number(count),
  }));
}

/**
 * Normalize a series of possibly-undefined numbers to finite numbers (0 for invalid).
 */
export function normalizeSeries(
  values: Array<number | undefined | null>,
): number[] {
  return values.map((value) =>
    typeof value === "number" && Number.isFinite(value) ? value : 0,
  );
}

/**
 * Compute the reviewed rate percentage string from pie data.
 * Counts approved + published as reviewed; returns "--" when total is 0.
 */
export function computeReviewRate(
  pieData: Array<{ name: string; count: number }>,
): string {
  const reviewTotal = pieData.reduce((sum, item) => sum + item.count, 0);
  if (reviewTotal <= 0) return "--";
  const reviewedCount = pieData
    .filter((item) => ["approved", "published"].includes(item.name))
    .reduce((sum, item) => sum + item.count, 0);
  return `${((reviewedCount / reviewTotal) * 100).toFixed(1)}%`;
}

/**
 * Sum the pending queue counts (ready + processing + retry).
 * Each field defaults to 0 when undefined.
 */
export function computeQueuePending(
  totals: { ready?: number; processing?: number; retry?: number } | undefined,
): number {
  if (!totals) return 0;
  return (totals.ready ?? 0) + (totals.processing ?? 0) + (totals.retry ?? 0);
}

/**
 * Sum the error queue counts (dead + corrupt).
 * Each field defaults to 0 when undefined.
 */
export function computeQueueErrors(
  totals: { dead?: number; corrupt?: number } | undefined,
): number {
  if (!totals) return 0;
  return (totals.dead ?? 0) + (totals.corrupt ?? 0);
}

export type RedisStatusTone = "muted" | "ok" | "error";

/**
 * Derive the Redis status badge from diagnostics data.
 * Returns {tone, label} for the dashboard indicator.
 */
export function computeRedisStatus(
  isLoading: boolean,
  data: { configured?: boolean; available?: boolean } | undefined,
): { tone: RedisStatusTone; label: string } {
  if (isLoading) return { tone: "muted", label: "检测中" };
  if (!data) return { tone: "muted", label: "未获取" };
  const configured = data.configured === true;
  if (!configured) return { tone: "muted", label: "未配置" };
  return data.available === true
    ? { tone: "ok", label: "正常" }
    : { tone: "error", label: "不可用" };
}

export type TaskQueueStatusTone = "muted" | "ok" | "warning" | "error";

/**
 * Derive the task-queue status badge from diagnostics data and computed
 * pending/error counts.
 */
export function computeTaskQueueStatus(
  isLoading: boolean,
  data: { configured?: boolean } | undefined,
  queuePending: number,
  queueErrors: number,
): { tone: TaskQueueStatusTone; label: string } {
  if (isLoading) return { tone: "muted", label: "检测中" };
  if (!data) return { tone: "muted", label: "未获取" };
  if (data.configured !== true) return { tone: "muted", label: "未启用" };
  if (queueErrors > 0) return { tone: "error", label: `异常 ${queueErrors}` };
  if (queuePending > 0) return { tone: "warning", label: `积压 ${queuePending}` };
  return { tone: "ok", label: "正常" };
}
