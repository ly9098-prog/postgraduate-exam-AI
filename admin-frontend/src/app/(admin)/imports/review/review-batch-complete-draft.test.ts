import { describe, expect, it, vi } from "vitest";
import {
  BATCH_COMPLETE_ALL_FIELDS,
  BATCH_COMPLETE_DRAFT_KEY,
  clearBatchCompleteDraft,
  createDefaultBatchCompleteDraft,
  loadBatchCompleteDraft,
  saveBatchCompleteDraft,
  toggleBatchCompleteField,
  type BatchCompleteDraftStorage,
} from "./review-batch-complete-draft";

function storageWith(raw: string | null = null) {
  const getItem = vi.fn((): string | null => raw);
  const setItem = vi.fn<(key: string, value: string) => void>();
  const removeItem = vi.fn<(key: string) => void>();
  const storage: BatchCompleteDraftStorage = { getItem, setItem, removeItem };
  return { storage, getItem, setItem, removeItem };
}

describe("review batch completion draft", () => {
  it("creates fresh default fields for every form instance", () => {
    const first = createDefaultBatchCompleteDraft();
    const second = createDefaultBatchCompleteDraft();

    expect(first).toEqual({
      fields: ["answer", "analysis", "knowledge_points", "difficulty"],
      strategy: "fill_empty",
    });
    expect(first.fields).not.toBe(second.fields);
    expect(BATCH_COMPLETE_ALL_FIELDS).toHaveLength(10);
  });

  it("toggles one field while preserving all existing duplicate removals and append order", () => {
    expect(toggleBatchCompleteField(["answer", "analysis"], "tags")).toEqual([
      "answer",
      "analysis",
      "tags",
    ]);
    expect(toggleBatchCompleteField(["answer", "analysis", "answer"], "answer")).toEqual([
      "analysis",
    ]);
    expect(toggleBatchCompleteField([], "stem")).toEqual(["stem"]);
  });

  it("saves the existing payload shape and lets an injected clock determine savedAt", () => {
    const { storage, setItem } = storageWith();
    const now = vi.fn(() => 123456);

    saveBatchCompleteDraft(() => storage, ["answer", "tags"], "force_overwrite", now);

    expect(now).toHaveBeenCalledOnce();
    expect(setItem).toHaveBeenCalledWith(
      BATCH_COMPLETE_DRAFT_KEY,
      '{"fields":["answer","tags"],"strategy":"force_overwrite","savedAt":123456}',
    );
  });

  it("silently ignores storage provider, quota, and clock failures", () => {
    expect(() => saveBatchCompleteDraft(
      () => {
        throw new Error("blocked");
      },
      ["answer"],
      "fill_empty",
    )).not.toThrow();

    const { storage } = storageWith();
    storage.setItem = vi.fn(() => {
      throw new Error("quota");
    });
    expect(() => saveBatchCompleteDraft(() => storage, ["answer"], "fill_empty")).not.toThrow();
    expect(() => saveBatchCompleteDraft(
      () => storage,
      ["answer"],
      "fill_empty",
      () => {
        throw new Error("clock");
      },
    )).not.toThrow();
  });

  it("clears the exact existing key and silently ignores storage failures", () => {
    const { storage, removeItem } = storageWith();
    clearBatchCompleteDraft(() => storage);
    expect(removeItem).toHaveBeenCalledWith(BATCH_COMPLETE_DRAFT_KEY);

    const failing = storageWith().storage;
    failing.removeItem = vi.fn(() => {
      throw new Error("blocked");
    });
    expect(() => clearBatchCompleteDraft(() => failing)).not.toThrow();
    expect(() => clearBatchCompleteDraft(() => {
      throw new Error("blocked");
    })).not.toThrow();
  });

  it("restores only array fields and normalizes every unknown strategy to fill_empty", () => {
    const { storage } = storageWith(JSON.stringify({
      fields: ["answer", 7],
      strategy: "force_overwrite",
      savedAt: 1,
    }));
    expect(loadBatchCompleteDraft(() => storage)).toEqual({
      fields: ["answer", 7],
      strategy: "force_overwrite",
    });

    for (const strategy of [undefined, null, "other", "", 1, false]) {
      const { storage: otherStorage } = storageWith(JSON.stringify({ fields: [], strategy }));
      expect(loadBatchCompleteDraft(() => otherStorage)).toEqual({
        fields: [],
        strategy: "fill_empty",
      });
    }
  });

  it("returns null for missing, malformed, and non-array draft data", () => {
    expect(loadBatchCompleteDraft(() => storageWith(null).storage)).toBeNull();
    expect(loadBatchCompleteDraft(() => storageWith("not json").storage)).toBeNull();
    expect(loadBatchCompleteDraft(() => storageWith("null").storage)).toBeNull();
    expect(loadBatchCompleteDraft(() => storageWith("{}").storage)).toBeNull();
    expect(loadBatchCompleteDraft(() => storageWith('{"fields":"answer"}').storage)).toBeNull();
    expect(loadBatchCompleteDraft(() => {
      throw new Error("blocked");
    })).toBeNull();

    const { storage } = storageWith();
    storage.getItem = vi.fn(() => {
      throw new Error("blocked");
    });
    expect(loadBatchCompleteDraft(() => storage)).toBeNull();
  });
});
