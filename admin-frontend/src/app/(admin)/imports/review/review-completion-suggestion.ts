import type { ImportQuestionItem } from "@/lib/api/types";

export function completeSuggestionFromItem(
  item: ImportQuestionItem | null | undefined,
): Record<string, unknown> | null {
  const suggestion = item?.ai_metadata?.complete_suggestion;
  if (suggestion && typeof suggestion === "object" && !Array.isArray(suggestion)) {
    return suggestion as Record<string, unknown>;
  }
  return null;
}

export function stringSuggestion(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

export function normalizeAnswerForCompare(value: unknown): string {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const compact = text.replace(/[，、；;\s]+/g, ",").replace(/^,+|,+$/g, "");
  const upper = compact.toUpperCase();
  if (/^[A-Z](?:,[A-Z])*$/.test(upper)) {
    return upper.split(",").filter(Boolean).sort().join(",");
  }
  return compact;
}

export function answersEquivalent(left: unknown, right: unknown): boolean {
  const a = normalizeAnswerForCompare(left);
  const b = normalizeAnswerForCompare(right);
  return Boolean(a && b && a === b);
}
