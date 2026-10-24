import { describe, it, expect } from "vitest";
import { resolveAiModels, computeUsageRate } from "./ai-model-resolver";
import type { AdminAiModelConfig } from "./api/types";

function makeModel(overrides: Partial<AdminAiModelConfig>): AdminAiModelConfig {
  return {
    id: 1,
    name: "test-model",
    display_name: "Test Model",
    provider: "openai",
    api_base_url: null,
    api_key_encrypted: null,
    is_enabled: true,
    is_default: false,
    sort_order: 0,
    feature: null,
    features: null,
    created_at: "",
    updated_at: "",
    deleted_at: null,
    ...overrides,
  } as AdminAiModelConfig;
}

describe("resolveAiModels", () => {
  it("returns null for all categories when list is empty", () => {
    const result = resolveAiModels([]);
    expect(result.ocr).toBeNull();
    expect(result.completion).toBeNull();
    expect(result.analysis).toBeNull();
    expect(result.vision).toBeNull();
  });

  it("resolves ocr model by feature priority", () => {
    const models = [
      makeModel({ display_name: "OCR Model", features: ["ocr_fix"] }),
    ];
    const result = resolveAiModels(models);
    expect(result.ocr).toBe("OCR Model");
  });

  it("resolves completion model", () => {
    const models = [
      makeModel({ display_name: "Completion Model", features: ["completion"] }),
    ];
    const result = resolveAiModels(models);
    expect(result.completion).toBe("Completion Model");
  });

  it("resolves analysis model", () => {
    const models = [
      makeModel({ display_name: "Analysis Model", features: ["analysis"] }),
    ];
    const result = resolveAiModels(models);
    expect(result.analysis).toBe("Analysis Model");
  });

  it("resolves vision model from paddle provider", () => {
    const models = [
      makeModel({ display_name: "Paddle Vision", provider: "paddleocr", features: ["vision"] }),
    ];
    const result = resolveAiModels(models);
    expect(result.vision).toBe("Paddle Vision");
  });

  it("excludes disabled models", () => {
    const models = [
      makeModel({ display_name: "Disabled", is_enabled: false, features: ["ocr"] }),
    ];
    const result = resolveAiModels(models);
    expect(result.ocr).toBeNull();
  });

  it("excludes embedding models from chat resolution", () => {
    const models = [
      makeModel({ display_name: "Embedding", features: ["embedding", "ocr"] }),
    ];
    const result = resolveAiModels(models);
    expect(result.ocr).toBeNull();
  });

  it("falls back to untagged model", () => {
    const models = [
      makeModel({ display_name: "Untagged", features: null }),
    ];
    const result = resolveAiModels(models);
    expect(result.ocr).toBe("Untagged");
  });

  it("falls back to first candidate when no feature match", () => {
    const models = [
      makeModel({ display_name: "Generic", features: ["unknown_feature"] }),
    ];
    const result = resolveAiModels(models);
    expect(result.ocr).toBe("Generic");
  });
});

describe("computeUsageRate", () => {
  it("computes percentage", () => {
    expect(computeUsageRate(50, 100)).toBe(50);
  });

  it("clamps to 100", () => {
    expect(computeUsageRate(150, 100)).toBe(100);
  });

  it("returns 0 when limit is 0", () => {
    expect(computeUsageRate(50, 0)).toBe(0);
  });

  it("returns 0 when limit is negative", () => {
    expect(computeUsageRate(50, -1)).toBe(0);
  });

  it("returns 0 when calls is 0", () => {
    expect(computeUsageRate(0, 100)).toBe(0);
  });
});
