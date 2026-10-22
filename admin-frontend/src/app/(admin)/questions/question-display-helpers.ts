import { resolveAssetUrl } from "@/lib/asset-url";
import { canonicalizeQuestionType } from "@/lib/question-types";
import { contentSegments, segmentType } from "./question-content-editing";

/** Extract a URL string from an unknown image field value. */
export function imageUrlFromUnknown(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const record = value as Record<string, unknown>;
  for (const key of ["url", "src", "image_url", "imageUrl"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
  }
  return "";
}

/** Normalize an asset URL to a stable comparable form (trailing slashes removed). */
export function comparableAssetUrl(value: unknown): string {
  const raw = imageUrlFromUnknown(value);
  if (!raw) return "";
  const resolved = resolveAssetUrl(raw) || raw;
  return resolved.replace(/\/+$/, "");
}

/** Collect comparable keys for all rendered image-like segments in content. */
export function contentRenderedImageKeys(content: unknown): Set<string> {
  const keys = new Set<string>();
  contentSegments(content).forEach((segment) => {
    const type = segmentType(segment);
    if (!["image", "math_image", "table_image", "code_image"].includes(type)) return;
    const key = comparableAssetUrl(segment.url);
    if (key) keys.add(key);
  });
  return keys;
}

/** Return image URLs from the field that are not already rendered in content. */
export function fallbackQuestionImageUrls(
  content: unknown,
  imageUrlField: unknown,
): string[] {
  if (!Array.isArray(imageUrlField)) return [];
  const renderedKeys = contentRenderedImageKeys(content);
  const fallbackUrls = new Map<string, string>();
  imageUrlField.forEach((value: unknown) => {
    const raw = imageUrlFromUnknown(value);
    const key = comparableAssetUrl(raw);
    if (!raw || !key || renderedKeys.has(key)) return;
    fallbackUrls.set(key, raw);
  });
  return Array.from(fallbackUrls.values());
}

export function isMultiChoice(questionType: string): boolean {
  return canonicalizeQuestionType(questionType) === "multiple_choice";
}

export function isMultiBlankChoice(questionType: string): boolean {
  const code = canonicalizeQuestionType(questionType);
  return code === "multi_blank_choice" || code === "multi_blank_multiple_choice";
}

/** 多空（多选）选择题：每空可选多个选项 */
export function isMultiBlankMultipleChoice(questionType: string): boolean {
  return canonicalizeQuestionType(questionType) === "multi_blank_multiple_choice";
}

/** Split a choice answer string into unique, uppercased keys (comma/space separated). */
export function normalizedChoiceAnswerKeys(answer: string | null | undefined): string[] {
  const seen = new Set<string>();
  return String(answer ?? "")
    .split(/[,，\s]+/)
    .map((key) => key.trim().toUpperCase())
    .filter((key) => {
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}
