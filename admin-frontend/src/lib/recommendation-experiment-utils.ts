/**
 * Pure helpers for recommendation experiment creation, extracted from
 * experiments/page.tsx submitCreate. All validation logic is detached from
 * the mutation so it can be tested independently.
 */

import type { ExperimentCreate, ExperimentVariant } from "@/lib/api/types";

export type ExperimentParseResult =
  | { ok: true; variants: ExperimentVariant[] }
  | { ok: false; message: string };

/**
 * Parse and validate a JSON variants string for experiment creation.
 * Returns the parsed variants on success, or an error message on failure.
 */
export function parseExperimentVariants(raw: string): ExperimentParseResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw || "[]");
  } catch {
    return { ok: false, message: "分组 JSON 格式错误" };
  }
  if (!Array.isArray(parsed) || parsed.length < 2) {
    return { ok: false, message: "分组必须是 JSON 数组，且至少需要 2 个分组" };
  }
  const variants = parsed as ExperimentVariant[];
  const validShape = variants.every(
    (variant) =>
      variant &&
      typeof variant.key === "string" &&
      variant.key.trim().length > 0 &&
      typeof variant.strategy === "string" &&
      variant.strategy.trim().length > 0 &&
      typeof variant.ratio === "number" &&
      Number.isFinite(variant.ratio) &&
      variant.ratio >= 0 &&
      variant.ratio <= 1,
  );
  if (!validShape) {
    return { ok: false, message: "每个分组都需要有效的 key、strategy 和 0~1 ratio" };
  }
  if (new Set(variants.map((v) => v.key.trim())).size !== variants.length) {
    return { ok: false, message: "分组 key 不能重复" };
  }
  const ratioSum = variants.reduce((sum, v) => sum + v.ratio, 0);
  if (Math.abs(ratioSum - 1) > 1e-6) {
    return { ok: false, message: `分组 ratio 总和必须为 1，当前为 ${ratioSum.toFixed(4)}` };
  }
  return { ok: true, variants };
}

/**
 * Build the experiment creation payload from validated inputs.
 * Returns null if the name is empty.
 */
export function buildExperimentPayload(
  name: string,
  scene: string,
  variants: ExperimentVariant[],
): Pick<ExperimentCreate, "name" | "scene" | "variants" | "traffic_ratio"> | null {
  const trimmed = name.trim();
  if (!trimmed) return null;
  return {
    name: trimmed,
    scene,
    variants,
    traffic_ratio: 1.0,
  };
}
