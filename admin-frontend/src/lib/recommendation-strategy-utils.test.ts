import { describe, it, expect } from "vitest";
import {
  asRecord,
  getStrategyType,
  isScoredStrategy,
  getScoredWeights,
  getGraphConfig,
  parseNumberField,
  DEFAULT_SCORED_WEIGHTS,
  DEFAULT_GRAPH_CONFIG,
} from "./recommendation-strategy-utils";
import type { RecommendationStrategy } from "./api/types";

const baseStrategy: RecommendationStrategy = {
  id: 1, name: "test", display_name: "Test", description: null,
  scene: "practice_smart", is_active: true, is_default: false,
  weight_vector_similarity: 0.3, weight_knowledge_overlap: 0.2,
  weight_difficulty_match: 0.1, weight_mastery_gap: 0.2,
  weight_path_priority: 0.1, exploration_ratio: 0.1,
  config_json: null,
};

describe("asRecord", () => {
  it("returns object as-is", () => {
    expect(asRecord({ a: 1 })).toEqual({ a: 1 });
  });
  it("returns empty for null", () => { expect(asRecord(null)).toEqual({}); });
  it("returns empty for undefined", () => { expect(asRecord(undefined)).toEqual({}); });
  it("returns empty for array", () => { expect(asRecord([1, 2])).toEqual({}); });
  it("returns empty for string", () => { expect(asRecord("x")).toEqual({}); });
  it("returns empty for number", () => { expect(asRecord(42)).toEqual({}); });
});

describe("getStrategyType", () => {
  it("reads from config_json", () => {
    const s = { ...baseStrategy, config_json: { strategy_type: "scored" } };
    expect(getStrategyType(s)).toBe("scored");
  });
  it("falls back to name mapping for default_scored", () => {
    expect(getStrategyType({ ...baseStrategy, name: "default_scored" })).toBe("scored");
  });
  it("falls back to name mapping for default_weakness_vector", () => {
    expect(getStrategyType({ ...baseStrategy, name: "default_weakness_vector" })).toBe("weakness_vector");
  });
  it("returns empty for unknown name and no config", () => {
    expect(getStrategyType({ ...baseStrategy, name: "custom" })).toBe("");
  });
});

describe("isScoredStrategy", () => {
  it("true for default_scored name", () => {
    expect(isScoredStrategy({ ...baseStrategy, name: "default_scored" })).toBe(true);
  });
  it("true for scored type", () => {
    expect(isScoredStrategy({ ...baseStrategy, config_json: { strategy_type: "scored" } })).toBe(true);
  });
  it("true for hybrid_graph type", () => {
    expect(isScoredStrategy({ ...baseStrategy, config_json: { strategy_type: "hybrid_graph" } })).toBe(true);
  });
  it("false for other strategies", () => {
    expect(isScoredStrategy({ ...baseStrategy, name: "other", config_json: { strategy_type: "random" } })).toBe(false);
  });
});

describe("getScoredWeights", () => {
  it("returns defaults when no scored_weights", () => {
    const w = getScoredWeights(baseStrategy);
    expect(w).toEqual(DEFAULT_SCORED_WEIGHTS);
  });
  it("reads values from config", () => {
    const s = { ...baseStrategy, config_json: { scored_weights: { due_weight: 2, weakness_weight: 0.5 } } };
    const w = getScoredWeights(s);
    expect(w.due_weight).toBe(2);
    expect(w.weakness_weight).toBe(0.5);
    expect(w.wrong_weight).toBe(1); // default
  });
  it("falls back to default for invalid values", () => {
    const s = { ...baseStrategy, config_json: { scored_weights: { due_weight: "bad" } } };
    expect(getScoredWeights(s).due_weight).toBe(1);
  });
});

describe("getGraphConfig", () => {
  it("returns defaults when no graph", () => {
    expect(getGraphConfig(baseStrategy)).toEqual(DEFAULT_GRAPH_CONFIG);
  });
  it("reads values from config", () => {
    const s = { ...baseStrategy, config_json: { graph: { max_depth: 3, max_nodes: 50 } } };
    const c = getGraphConfig(s);
    expect(c.max_depth).toBe(3);
    expect(c.max_nodes).toBe(50);
    expect(c.weak_target_limit).toBe(5); // default
  });
  it("falls back for invalid", () => {
    const s = { ...baseStrategy, config_json: { graph: { max_depth: "x" } } };
    expect(getGraphConfig(s).max_depth).toBe(DEFAULT_GRAPH_CONFIG.max_depth);
  });
});

describe("parseNumberField", () => {
  const form = { a: "0.5", b: "1.5", c: "", d: "abc", e: "-0.5" };
  it("parses valid in-range value", () => {
    expect(parseNumberField(form, "a", 0, 1)).toBe(0.5);
  });
  it("returns null for out-of-range", () => {
    expect(parseNumberField(form, "b", 0, 1)).toBeNull();
  });
  it("returns null for empty", () => {
    expect(parseNumberField(form, "c", 0, 1)).toBeNull();
  });
  it("returns null for non-numeric", () => {
    expect(parseNumberField(form, "d", 0, 1)).toBeNull();
  });
  it("returns null for negative out of range", () => {
    expect(parseNumberField(form, "e", 0, 1)).toBeNull();
  });
  it("returns null for missing key", () => {
    expect(parseNumberField(form, "missing", 0, 1)).toBeNull();
  });
  it("parses value in wider range", () => {
    expect(parseNumberField(form, "b", 0, 2)).toBe(1.5);
  });
});
