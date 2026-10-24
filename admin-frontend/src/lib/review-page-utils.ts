/**
 * Pure helpers for admin review page, extracted from review/page.tsx.
 */

import { normalizeStructuredTableSegment } from "@/lib/structured-table";

export function unresolvedTableCount(content: unknown): number {
  if (!content || typeof content !== "object" || Array.isArray(content)) return 0;
  const segments = (content as Record<string, unknown>).segments;
  if (!Array.isArray(segments)) return 0;
  return segments.reduce((count, segment) => {
    const table = normalizeStructuredTableSegment(segment);
    return count + (table?.requires_review ? 1 : 0);
  }, 0);
}

export function textFromContent(
  content: Record<string, unknown> | string | null | undefined,
): string {
  if (!content) return "";
  if (typeof content === "string") return content;
  const candidate = content.stem ?? content.text ?? content.question ?? content.title;
  if (typeof candidate === "string") return candidate;
  return JSON.stringify(content, null, 2);
}

export function renderJson(value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    return String(value);
  return JSON.stringify(value, null, 2);
}

export function statusTone(status: string): "success" | "danger" | "warning" | "primary" {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  if (status === "re_pending") return "warning";
  return "primary";
}

export function duplicateStatusTone(status: string | null | undefined): "warning" | "success" | "neutral" {
  if (status === "possible_duplicate") return "warning";
  if (status === "normal") return "success";
  return "neutral";
}
