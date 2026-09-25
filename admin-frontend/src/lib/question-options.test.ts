import { describe, it, expect } from "vitest";
import {
  addBlankOptionToAllGroups,
  addBlankOptionToGroup,
  extractBlankSlotIds,
  normalizeBlankOptionGroups,
  resolveQuestionOptions,
  normalizeQuestionOptions,
} from "./question-options";
import type { NormalizedQuestionOption } from "./question-options";


// ─── grouped option mutations ─────────────────────────────────────

describe("extractBlankSlotIds", () => {
  it("extracts anonymous parentheses like the empty-state question", () => {
    expect(extractBlankSlotIds("交互系统称为（ ），批处理称为（ ），实时系统为（ ）。")).toEqual([
      "1",
      "2",
      "3",
    ]);
  });

  it("uses the backend marker priority", () => {
    expect(extractBlankSlotIds("① 第一空；② 第二空；___")).toEqual(["①", "②"]);
    expect(extractBlankSlotIds("(1)甲 (2)乙")).toEqual(["1", "2"]);
    expect(extractBlankSlotIds("___ 和 ____")).toEqual(["1", "2"]);
  });
});

describe("addBlankOptionToAllGroups", () => {
  it("creates missing groups so the empty state can add its first option", () => {
    expect(addBlankOptionToAllGroups(null, ["1", "2", "2"])).toEqual([
      { id: "1", options: [{ key: "A", text: "" }] },
      { id: "2", options: [{ key: "A", text: "" }] },
    ]);
  });

  it("adds the same next available key to every existing group", () => {
    const groups = [
      { id: "1", options: [{ key: "A", text: "甲" }] },
      { id: "2", options: [{ key: "A", text: "乙" }] },
    ];

    expect(addBlankOptionToAllGroups(groups, [])).toEqual([
      { id: "1", options: [{ key: "A", text: "甲" }, { key: "B", text: "" }] },
      { id: "2", options: [{ key: "A", text: "乙" }, { key: "B", text: "" }] },
    ]);
  });
});

describe("addBlankOptionToGroup", () => {
  it("appends the next free letter to array options without changing other groups", () => {
    const groups = [
      {
        id: "①",
        options: [
          { key: "A", text: "甲", segments: [{ type: "text", text: "甲" }] },
          { key: "C", text: "丙" },
        ],
      },
      { id: "②", options: [{ key: "A", text: "另一空" }] },
    ];

    const result = addBlankOptionToGroup(groups, "①");

    expect(normalizeBlankOptionGroups(result)[0].options).toEqual([
      { key: "A", text: "甲" },
      { key: "C", text: "丙" },
      { key: "B", text: "" },
    ]);
    expect((result as typeof groups)[0].options[0].segments).toEqual([
      { type: "text", text: "甲" },
    ]);
    expect((result as typeof groups)[1]).toBe(groups[1]);
  });

  it("preserves record-style options", () => {
    const groups = [{ id: "①", options: { A: "甲", B: { text: "乙", url: "/b.png" } } }];

    expect(addBlankOptionToGroup(groups, "①")).toEqual([
      { id: "①", options: { A: "甲", B: { text: "乙", url: "/b.png" }, C: "" } },
    ]);
  });

  it("does not add beyond Z", () => {
    const options = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").map((key) => ({ key, text: key }));
    const groups = [{ id: "①", options }];

    expect(addBlankOptionToGroup(groups, "①")).toEqual(groups);
  });
});

// ─── resolveQuestionOptions ───────────────────────────────────────

describe("resolveQuestionOptions", () => {
  it("returns null for null/undefined input", () => {
    expect(resolveQuestionOptions(null)).toBeNull();
    expect(resolveQuestionOptions(undefined)).toBeNull();
  });

  it("returns top-level options when present", () => {
    const q = { options: { A: "optA", B: "optB" } };
    expect(resolveQuestionOptions(q)).toEqual({ A: "optA", B: "optB" });
  });

  it("returns top-level array options when present", () => {
    const q = { options: ["optA", "optB"] };
    expect(resolveQuestionOptions(q)).toEqual(["optA", "optB"]);
  });

  it("returns top-level string options when present", () => {
    const q = { options: "A. optA\nB. optB" };
    expect(resolveQuestionOptions(q)).toBe("A. optA\nB. optB");
  });

  it("skips empty top-level options and falls back to content", () => {
    const q = { options: {}, content: { options: { A: "fromContent" } } };
    expect(resolveQuestionOptions(q)).toEqual({ A: "fromContent" });
  });

  it("skips empty string top-level options and falls back", () => {
    const q = { options: "", content: { parsed_options: { A: "fallback" } } };
    expect(resolveQuestionOptions(q)).toEqual({ A: "fallback" });
  });

  it("skips empty array top-level options and falls back", () => {
    const q = { options: [], content: { options: { A: "fallback" } } };
    expect(resolveQuestionOptions(q)).toEqual({ A: "fallback" });
  });

  it("checks content.options as second priority", () => {
    const q = {
      options: null,
      content: { options: { A: "fromContent" } },
    };
    expect(resolveQuestionOptions(q)).toEqual({ A: "fromContent" });
  });

  it("checks content.parsed_options as third priority", () => {
    const q = {
      options: null,
      content: { parsed_options: { X: "parsed" } },
    };
    expect(resolveQuestionOptions(q)).toEqual({ X: "parsed" });
  });

  it("checks content.option_list as fourth priority", () => {
    const q = {
      options: null,
      content: { option_list: ["first", "second"] },
    };
    expect(resolveQuestionOptions(q)).toEqual(["first", "second"]);
  });

  it("returns null when no options found anywhere", () => {
    const q = { options: null, content: { text: "stem" } };
    expect(resolveQuestionOptions(q)).toBeNull();
  });

  it("returns null when content fields are all empty", () => {
    const q = {
      options: null,
      content: { options: {}, parsed_options: {}, option_list: [] },
    };
    expect(resolveQuestionOptions(q)).toBeNull();
  });
});

// ─── normalizeQuestionOptions — object format ─────────────────────

describe("normalizeQuestionOptions — object format", () => {
  it("normalizes simple key-value object", () => {
    const result = normalizeQuestionOptions({ A: "42", B: "O(n)", C: "O(log n)", D: "O(1)" });
    expect(result).toHaveLength(4);
    expect(result[0]).toEqual({ key: "A", text: "42" });
    expect(result[1]).toEqual({ key: "B", text: "O(n)" });
    expect(result[2]).toEqual({ key: "C", text: "O(log n)" });
    expect(result[3]).toEqual({ key: "D", text: "O(1)" });
  });

  it("sorts options by key order (A, B, C, D)", () => {
    const result = normalizeQuestionOptions({ D: "d", B: "b", A: "a", C: "c" });
    expect(result.map((o) => o.key)).toEqual(["A", "B", "C", "D"]);
  });

  it("handles object with rich option values", () => {
    const result = normalizeQuestionOptions({
      A: { text: "option A" },
      B: { text: "option B", url: "/img/b.png" },
    });
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual({ key: "A", text: "option A" });
    expect(result[1]).toEqual({ key: "B", text: "option B", imageUrl: "/img/b.png" });
  });

  it("extracts key from child object label/key fields", () => {
    const result = normalizeQuestionOptions({
      A: { label: "X", content: "renamed" },
    });
    expect(result[0].key).toBe("X");
  });
});

// ─── normalizeQuestionOptions — array format ──────────────────────

describe("normalizeQuestionOptions — array format", () => {
  it("normalizes array of strings with auto-label", () => {
    const result = normalizeQuestionOptions(["optA", "optB", "optC", "optD"]);
    expect(result).toHaveLength(4);
    expect(result[0]).toEqual({ key: "A", text: "optA" });
    expect(result[1]).toEqual({ key: "B", text: "optB" });
    expect(result[3]).toEqual({ key: "D", text: "optD" });
  });

  it("normalizes array of objects", () => {
    const result = normalizeQuestionOptions([
      { key: "A", text: "Alice" },
      { key: "B", text: "Bob" },
    ]);
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual({ key: "A", text: "Alice" });
    expect(result[1]).toEqual({ key: "B", text: "Bob" });
  });

  it("handles empty array", () => {
    expect(normalizeQuestionOptions([])).toEqual([]);
  });
});

// ─── normalizeQuestionOptions — string format ─────────────────────

describe("normalizeQuestionOptions — string format", () => {
  it("parses formatted string with labels", () => {
    const result = normalizeQuestionOptions("A. 60,90,280\nB. 60,90,350\nC. 60,85,110,350\nD. 60,90,110,350");
    expect(result).toHaveLength(4);
    expect(result[0]).toEqual({ key: "A", text: "60,90,280" });
    expect(result[2]).toEqual({ key: "C", text: "60,85,110,350" });
  });

  it("returns empty for empty string", () => {
    expect(normalizeQuestionOptions("")).toEqual([]);
  });
});

// ─── normalizeQuestionOptions — null/undefined ────────────────────

describe("normalizeQuestionOptions — null/undefined", () => {
  it("returns empty for null", () => {
    expect(normalizeQuestionOptions(null)).toEqual([]);
  });

  it("returns empty for undefined", () => {
    expect(normalizeQuestionOptions(undefined)).toEqual([]);
  });
});

// ─── normalizeQuestionOptions — LaTeX ─────────────────────────────

describe("normalizeQuestionOptions — LaTeX", () => {
  it("preserves LaTeX in text", () => {
    const result = normalizeQuestionOptions({ A: "\\sum_{i=1}^{n} i", B: "O(\\log n)" });
    expect(result[0].text).toBe("\\sum_{i=1}^{n} i");
    expect(result[1].text).toBe("O(\\log n)");
  });
});

// ─── normalizeQuestionOptions — image options ─────────────────────

describe("normalizeQuestionOptions — image options", () => {
  it("handles image option with url field", () => {
    const result = normalizeQuestionOptions({
      A: { text: "", url: "/img/a.png" },
    });
    expect(result[0]).toEqual({ key: "A", imageUrl: "/img/a.png" });
  });

  it("handles image option with imageUrl field", () => {
    const result = normalizeQuestionOptions({
      A: { text: "", imageUrl: "/img/a.png" },
    });
    expect(result[0].imageUrl).toBe("/img/a.png");
  });

  it("handles image option with image_url field", () => {
    const result = normalizeQuestionOptions({
      A: { text: "", image_url: "/img/a.png" },
    });
    expect(result[0].imageUrl).toBe("/img/a.png");
  });

  it("handles image option with src field", () => {
    const result = normalizeQuestionOptions({
      A: { text: "", src: "/img/a.png" },
    });
    expect(result[0].imageUrl).toBe("/img/a.png");
  });
});

// ─── normalizeQuestionOptions — edge cases ────────────────────────

describe("normalizeQuestionOptions — edge cases", () => {
  it("does not crash on mixed data types", () => {
    const result = normalizeQuestionOptions({
      A: 42,
      B: true,
      C: { unexpected: true },
      D: null,
      E: "text",
    } as Record<string, unknown>);
    // null values are skipped
    expect(result.length).toBe(4);
  });

  it("does not crash on deeply nested data", () => {
    const result = normalizeQuestionOptions({
      A: { nested: { deep: { value: "x" } } },
    });
    // Falls back to JSON.stringify
    expect(result[0].text).toContain("deep");
  });

  it("handles numeric and boolean values", () => {
    const result = normalizeQuestionOptions({ A: 0, B: false });
    expect(result[0].text).toBe("0");
    expect(result[1].text).toBe("false");
  });
});

// ─── resolveQuestionOptions with full AdminQuestion-like shape ────

describe("resolveQuestionOptions — AdminQuestion shape", () => {
  it("extracts from question.options (the common case)", () => {
    const q = {
      content: { text: "stem" },
      options: { A: "optA", B: "optB" },
    };
    expect(resolveQuestionOptions(q)).toEqual({ A: "optA", B: "optB" });
  });

  it("falls back to content.options when top-level is null", () => {
    const q = {
      content: { options: { A: "contentOpt" } },
      options: null,
    };
    expect(resolveQuestionOptions(q)).toEqual({ A: "contentOpt" });
  });

  it("falls back to content.parsed_options when content.options is empty", () => {
    const q = {
      content: { options: {}, parsed_options: { A: "parsed" } },
      options: null,
    };
    expect(resolveQuestionOptions(q)).toEqual({ A: "parsed" });
  });
});
