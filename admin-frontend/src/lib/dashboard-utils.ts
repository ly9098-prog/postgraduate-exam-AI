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
