import { describe, expect, it, vi } from "vitest";
import type { QuestionListFilters } from "./question-list-state";
import {
  loadSavedFilters,
  saveCurrentFilters,
  type FilterStorage,
} from "./question-filter-persistence";

const KEY = "admin-question-saved-filter";

function storageWith(raw: string | null = null) {
  let stored = raw;
  const getItem = vi.fn((): string | null => stored);
  const setItem = vi.fn((key: string, value: string) => { stored = value; });
  const removeItem = vi.fn(() => { stored = null; });
  const storage: FilterStorage = { getItem, setItem, removeItem };
  return { storage, getItem, setItem, removeItem, getStored: () => stored };
}

const defaultFilters: QuestionListFilters = {
  subject_id: "1",
  is_active: "true",
  question_type: "multiple_choice",
  keyword: "test",
  year: "2024",
  difficulty: "3",
  import_batch_id: "batch-1",
  knowledge_point_id: "42",
};

describe("saveCurrentFilters", () => {
  it("persists filters to storage as JSON", () => {
    const { storage, setItem, getStored } = storageWith();
    const result = saveCurrentFilters(() => storage, defaultFilters);
    expect(result).toEqual({ ok: true });
    expect(setItem).toHaveBeenCalledExactlyOnceWith(KEY, JSON.stringify(defaultFilters));
    expect(getStored()).toBe(JSON.stringify(defaultFilters));
  });

  it("returns error when storage throws", () => {
    const { storage, setItem } = storageWith();
    setItem.mockImplementation(() => { throw new Error("quota exceeded"); });
    const result = saveCurrentFilters(() => storage, defaultFilters);
    expect(result.ok).toBe(false);
    expect(result.ok === false && result.message).toContain("筛选保存失败");
  });
});

describe("loadSavedFilters", () => {
  it("returns saved filters with is_active normalization", () => {
    const { storage } = storageWith(JSON.stringify(defaultFilters));
    const result = loadSavedFilters(() => storage);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.filters).toEqual(defaultFilters);
      expect(result.filters.is_active).toBe("true");
    }
  });

  it("normalizes legacy empty is_active to true", () => {
    const legacy = { ...defaultFilters, is_active: "" };
    const { storage } = storageWith(JSON.stringify(legacy));
    const result = loadSavedFilters(() => storage);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.filters.is_active).toBe("true");
    }
  });

  it("preserves explicit is_active=false", () => {
    const filters = { ...defaultFilters, is_active: "false" };
    const { storage } = storageWith(JSON.stringify(filters));
    const result = loadSavedFilters(() => storage);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.filters.is_active).toBe("false");
    }
  });

  it("returns closeMenu when no saved filters exist", () => {
    const { storage } = storageWith(null);
    const result = loadSavedFilters(() => storage);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toContain("暂无");
      expect(result.closeMenu).toBe(true);
    }
  });

  it("returns error for unparseable JSON", () => {
    const { storage } = storageWith("{invalid json");
    const result = loadSavedFilters(() => storage);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toContain("无法读取");
      expect(result.closeMenu).toBe(true);
    }
  });

  it("returns error when storage throws on read", () => {
    const { storage, getItem } = storageWith();
    getItem.mockImplementation(() => { throw new Error("unavailable"); });
    const result = loadSavedFilters(() => storage);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.closeMenu).toBe(true);
    }
  });
});
