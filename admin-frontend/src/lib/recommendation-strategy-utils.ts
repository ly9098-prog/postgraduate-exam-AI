/**
 * Pure helpers for recommendation strategy page, extracted from
 * strategies/page.tsx. Covers config-json parsing, scored-weight extraction,
 * graph-config extraction, and form-field number parsing.
 */

import type { RecommendationStrategy } from "@/lib/api/types";

export const SCORED_WEIGHT_FIELDS = [
  ["due_weight", "复习到期"],
  ["weakness_weight", "薄弱知识"],
  ["wrong_weight", "历史错题"],
  ["new_question_weight", "新题探索"],
  ["diversity_weight", "知识多样性"],
  ["path_weight", "知识图谱/路径"],
] as const;

export type ScoredWeightKey = (typeof SCORED_WEIGHT_FIELDS)[number][0];

export const DEFAULT_SCORED_WEIGHTS: Record<ScoredWeightKey, number> = {
  due_weight: 1,
  weakness_weight: 1,
  wrong_weight: 1,
  new_question_weight: 1,
  diversity_weight: 1,
  path_weight: 1,
};

export const DEFAULT_GRAPH_CONFIG = {
  weak_target_limit: 5,
  max_depth: 2,
  max_nodes: 24,
  prerequisite_mastery_threshold: 60,
  prerequisite_confidence_threshold: 0.3,
};

/**
 * Safely coerce an unknown value to a plain record, returning {} for
 * non-objects or arrays.
 */
export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/**
 * Resolve the strategy_type from config_json, falling back to name mapping.
 */
export function getStrategyType(strategy: RecommendationStrategy): string {
  const configured = asRecord(strategy.config_json).strategy_type;
  if (configured) return String(configured);
  const byName: Record<string, string> = {
    default_scored: "scored",
    default_weakness_vector: "weakness_vector",
    default_knowledge_path: "knowledge_path",
    default_similar_vector: "similar_vector",
    default_random: "fallback_random",
    default_fallback: "fallback",
  };
  return byName[strategy.name] ?? "";
}

/**
 * True when the strategy uses scored or hybrid_graph type.
 */
export function isScoredStrategy(strategy: RecommendationStrategy): boolean {
  return strategy.name === "default_scored" || ["scored", "hybrid_graph"].includes(getStrategyType(strategy));
}

/**
 * Extract scored weights from a strategy's config_json, falling back to
 * defaults for each missing/invalid field.
 */
export function getScoredWeights(strategy: RecommendationStrategy): Record<ScoredWeightKey, number> {
  const scored = asRecord(asRecord(strategy.config_json).scored_weights);
  return Object.fromEntries(
    SCORED_WEIGHT_FIELDS.map(([key]) => {
      const value = Number(scored[key]);
      return [key, Number.isFinite(value) ? value : DEFAULT_SCORED_WEIGHTS[key]];
    }),
  ) as Record<ScoredWeightKey, number>;
}

/**
 * Extract the graph sub-config from a strategy's config_json, falling back to
 * defaults for each missing/invalid numeric field.
 */
export function getGraphConfig(strategy: RecommendationStrategy) {
  const graph = asRecord(asRecord(strategy.config_json).graph);
  const num = (key: keyof typeof DEFAULT_GRAPH_CONFIG) => {
    const value = Number(graph[key]);
    return Number.isFinite(value) ? value : DEFAULT_GRAPH_CONFIG[key];
  };
  return {
    weak_target_limit: num("weak_target_limit"),
    max_depth: num("max_depth"),
    max_nodes: num("max_nodes"),
    prerequisite_mastery_threshold: num("prerequisite_mastery_threshold"),
    prerequisite_confidence_threshold: num("prerequisite_confidence_threshold"),
  };
}

/**
 * Parse a numeric form field within [min, max], returning null when the field
 * is empty, non-finite, or out of range.
 */
export function parseNumberField(
  form: Record<string, string | undefined>,
  key: string,
  min: number,
  max: number,
): number | null {
  const raw = form[key]?.trim();
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value >= min && value <= max ? value : null;
}
