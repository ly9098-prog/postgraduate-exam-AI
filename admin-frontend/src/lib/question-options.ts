import type { AdminQuestion, QuestionOptionsValue } from "@/lib/api/types";

/**
 * Normalized option representation for display.
 */
export type NormalizedQuestionOption = {
  key: string;
  text?: string;
  imageUrl?: string;
};

const OPTION_KEYS = new Set(["key", "label", "name"]);
const OPTION_TEXT_KEYS = new Set([
  "text",
  "content",
  "option",
  "value",
  "stem",
]);
const OPTION_IMAGE_KEYS = new Set(["url", "image_url", "imageUrl", "src"]);

/**
 * Extract raw options from a question object.
 *
 * Priority:
 *  1. question.options (top-level)
 *  2. question.content.options
 *  3. question.content.parsed_options
 *  4. question.content.option_list
 *
 * Returns null when no structured options are found.
 */
export function resolveQuestionOptions(
  question: AdminQuestion | Record<string, unknown> | null | undefined,
): QuestionOptionsValue {
  if (!question) return null;

  // Check 1: top-level options
  if (question.options != null) {
    if (!_isEmptyOptionsValue(question.options)) {
      return question.options as QuestionOptionsValue;
    }
  }

  // Check 2–4: content-fields
  const content = question.content;
  if (content && typeof content === "object" && !Array.isArray(content)) {
    for (const field of ["options", "parsed_options", "option_list"] as const) {
      const val = (content as Record<string, unknown>)[field];
      if (val != null && !_isEmptyOptionsValue(val)) {
        return val as QuestionOptionsValue;
      }
    }
  }

  return null;
}

function _isEmptyOptionsValue(val: unknown): boolean {
  if (typeof val === "object" && !Array.isArray(val) && val !== null) {
    return Object.keys(val).length === 0;
  }
  if (typeof val === "string") return val === "";
  if (Array.isArray(val)) return val.length === 0;
  return false;
}

/**
 * Normalize raw options into a uniform array of { key, text?, imageUrl? }.
 *
 * Supported input formats:
 *  - { A: "text", B: "text" }       (object with key-value)
 *  - { A: { text: "…", url: "…" } } (object with rich values)
 *  - ["text", "text"]               (array of strings)
 *  - [{ key: "A", text: "…" }, …]   (array of objects)
 *  - "A. text\nB. text"             (formatted string)
 *  - null / undefined / "" → []
 */
export function normalizeQuestionOptions(
  raw: QuestionOptionsValue | undefined,
): NormalizedQuestionOption[] {
  if (raw == null) return [];
  if (typeof raw === "string") {
    return normalizeStringOptions(raw);
  }

  if (Array.isArray(raw)) {
    return normalizeArrayOptions(raw);
  }

  // Object (Record) format
  return normalizeRecordOptions(raw);
}

// ─── string format ────────────────────────────────────────────────

function normalizeStringOptions(raw: string): NormalizedQuestionOption[] {
  const trimmed = raw.trim();
  if (!trimmed) return [];

  const lines = trimmed.split(/\n+/).filter(Boolean);
  if (lines.length >= 1) {
    const result: NormalizedQuestionOption[] = [];
    for (const line of lines) {
      const match = line.match(
        /^([A-Za-z0-9一二三四五六七八九十]+)\s*[.、，,]\s*(.*)/,
      );
      if (match) {
        result.push({
          key: match[1].toUpperCase(),
          text: match[2].trim(),
        });
      } else {
        // No label prefix — use index as key
        result.push({
          key: String(result.length + 1),
          text: line.trim(),
        });
      }
    }
    if (result.length > 0) return result;
  }
  // Single line, no labels — return as one item
  return [{ key: "1", text: trimmed }];
}

// ─── array format ─────────────────────────────────────────────────

function normalizeArrayOptions(raw: unknown[]): NormalizedQuestionOption[] {
  if (raw.length === 0) return [];
  const result: NormalizedQuestionOption[] = [];
  const labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  for (let i = 0; i < raw.length; i++) {
    const item = raw[i];
    if (item == null) continue;
    if (
      typeof item === "string" ||
      typeof item === "number" ||
      typeof item === "boolean"
    ) {
      result.push({
        key: labels[i] ?? String(i + 1),
        text: String(item),
      });
    } else if (typeof item === "object") {
      const obj = item as Record<string, unknown>;
      const key = extractKey(obj, labels[i] ?? String(i + 1));
      const text = extractText(obj);
      const imageUrl = extractImageUrl(obj);
      if (text || imageUrl) {
        result.push({
          key,
          text: text || undefined,
          imageUrl: imageUrl || undefined,
        });
      }
    }
  }
  return result;
}

// ─── record (object) format ───────────────────────────────────────

function normalizeRecordOptions(
  raw: Record<string, unknown>,
): NormalizedQuestionOption[] {
  const entries = Object.entries(raw);
  if (entries.length === 0) return [];

  // Determine sort order: natural key order if keys look like A,B,C or 1,2,3
  const sorted = keysLikeAlphaNumeric(entries.map(([k]) => k))
    ? entries.sort(([a], [b]) => compareAlphaNumericKeys(a, b))
    : entries;

  const result: NormalizedQuestionOption[] = [];
  for (const [key, value] of sorted) {
    if (value == null) continue;
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      result.push({ key: key.toUpperCase(), text: String(value) });
    } else if (typeof value === "object" && !Array.isArray(value)) {
      const obj = value as Record<string, unknown>;
      const text = extractText(obj);
      const imageUrl = extractImageUrl(obj);
      const childKey = extractKey(obj, key);
      if (text || imageUrl) {
        result.push({
          key: childKey.toUpperCase(),
          text: text || undefined,
          imageUrl: imageUrl || undefined,
        });
      } else {
        // Fallback: serialize
        result.push({ key: key.toUpperCase(), text: JSON.stringify(value) });
      }
    } else {
      result.push({ key: key.toUpperCase(), text: String(value) });
    }
  }
  return result;
}

// ─── helpers ───────────────────────────────────────────────────────

function extractKey(
  obj: Record<string, unknown>,
  fallback: string,
): string {
  for (const k of OPTION_KEYS) {
    const v = obj[k];
    if (v != null && typeof v === "string") return v;
  }
  return fallback;
}

function extractText(
  obj: Record<string, unknown>,
): string | undefined {
  for (const k of OPTION_TEXT_KEYS) {
    const v = obj[k];
    if (
      v != null &&
      (typeof v === "string" || typeof v === "number" || typeof v === "boolean")
    ) {
      return String(v);
    }
  }
  return undefined;
}

function extractImageUrl(
  obj: Record<string, unknown>,
): string | undefined {
  for (const k of OPTION_IMAGE_KEYS) {
    const v = obj[k];
    if (v != null && typeof v === "string" && v.trim()) return v.trim();
  }
  return undefined;
}

function keysLikeAlphaNumeric(keys: string[]): boolean {
  if (keys.length === 0) return false;
  return keys.every((k) => /^[A-Za-z0-9]+$/.test(k));
}

function compareAlphaNumericKeys(a: string, b: string): number {
  // Numeric keys first
  const aNum = /^\d+$/.test(a) ? parseInt(a, 10) : NaN;
  const bNum = /^\d+$/.test(b) ? parseInt(b, 10) : NaN;
  if (!isNaN(aNum) && !isNaN(bNum)) return aNum - bNum;
  if (!isNaN(aNum)) return -1;
  if (!isNaN(bNum)) return 1;
  // Alpha keys: sort by length then alphabetically (A, B, C, …, AA, AB, …)
  if (a.length !== b.length) return a.length - b.length;
  return a.localeCompare(b);
}
