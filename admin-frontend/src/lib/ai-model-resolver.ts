/**
 * Resolve display names for AI model features from a model config list.
 *
 * Pure function — extracted from ai-settings/page.tsx to make the
 * model resolution contract testable without React hooks.
 */

import type { AdminAiModelConfig } from "@/lib/api/types";

function isPaddleOcrProvider(provider: string): boolean {
  const p = provider.toLowerCase().replace(/_/g, "-");
  return p === "paddle" || p.startsWith("paddleocr");
}

type ResolveMode = "chat" | "paddle";

interface ResolvedModels {
  ocr: string | null;
  completion: string | null;
  analysis: string | null;
  vision: string | null;
}

/**
 * Resolve model display names for each feature category.
 *
 * - `ocr`: first model with ocr_fix/text_correction/ocr feature (non-paddle)
 * - `completion`: first model with completion feature
 * - `analysis`: first model with analysis feature
 * - `vision`: first model with vision feature (paddle provider)
 */
export function resolveAiModels(list: AdminAiModelConfig[]): ResolvedModels {
  const resolve = (
    featurePriority: string[],
    mode: ResolveMode = "chat",
  ): string | null => {
    const candidates = list.filter((m) => {
      const features = m.features ?? (m.feature ? [m.feature] : []);
      const isEmbedding = features.includes("embedding");
      return (
        m.is_enabled &&
        !isEmbedding &&
        (mode === "paddle"
          ? isPaddleOcrProvider(m.provider)
          : !isPaddleOcrProvider(m.provider))
      );
    });
    for (const feature of featurePriority) {
      const featured = candidates.find((m) =>
        (m.features ?? []).includes(feature),
      );
      if (featured) return featured.display_name;
    }
    const untagged = candidates.find(
      (m) => !m.features || m.features.length === 0,
    );
    if (untagged) return untagged.display_name;
    return candidates[0]?.display_name ?? null;
  };

  return {
    ocr: resolve(["ocr_fix", "text_correction", "ocr"]),
    completion: resolve(["completion"]),
    analysis: resolve(["analysis"]),
    vision: resolve(["vision"], "paddle"),
  };
}

/**
 * Compute usage rate percentage, clamped to [0, 100].
 */
export function computeUsageRate(
  callCount: number,
  monthlyLimit: number,
): number {
  if (monthlyLimit <= 0) return 0;
  return Math.min(
    Math.round((callCount / monthlyLimit) * 100),
    100,
  );
}
