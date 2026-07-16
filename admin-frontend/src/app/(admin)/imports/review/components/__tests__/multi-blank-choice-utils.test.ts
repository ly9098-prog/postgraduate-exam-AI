import { describe, it, expect } from "vitest";
import {
  normalizeBlankOptionGroups,
  deduplicateGroupOptions,
  extractMultiBlankSource,
  parseBlankAnswer,
  serializeBlankAnswer,
  haveIdenticalOptionSets,
  getSharedOptions,
  updateSharedOption,
  validateBlankAnswerMap,
  buildMultiBlankSavePayload,
  getMultiBlankSaveState,
  reduceMultiBlankEditState,
  syncDerivedMultiBlankFields,
  type BlankOptionGroup,
  type BlankOption,
  type BlankAnswerMap,
  type MultiBlankEditState,
  type MultiBlankAction,
} from "../multi-blank-choice-utils";

// ── helpers ────────────────────────────────────────────────────────────────

function makeOpt(key: string, text: string, segments?: Record<string, unknown>[]): BlankOption {
  return segments ? { key, text, segments } : { key, text };
}

function makeGroup(id: string, opts: BlankOption[]): BlankOptionGroup {
  return { id, options: opts };
}

// ── normalizeBlankOptionGroups ─────────────────────────────────────────────

describe("normalizeBlankOptionGroups", () => {
  it("returns empty array for null", () => {
    expect(normalizeBlankOptionGroups(null)).toEqual([]);
  });

  it("returns empty array for undefined", () => {
    expect(normalizeBlankOptionGroups(undefined)).toEqual([]);
  });

  it("returns empty array for non-array", () => {
    expect(normalizeBlankOptionGroups("not-array")).toEqual([]);
  });

  it("normalizes array format with array-of-objects options", () => {
    const input = [
      {
        id: "①",
        options: [
          { key: "a", text: "选项一" },
          { key: "B", text: "选项二" },
        ],
      },
      {
        id: "②",
        options: [
          { key: "C", text: "选项三" },
          { key: "d", text: "选项四" },
        ],
      },
    ];
    const result = normalizeBlankOptionGroups(input);
    expect(result).toHaveLength(2);
    expect(result[0].id).toBe("①");
    expect(result[0].options[0]).toEqual({ key: "A", text: "选项一" });
    expect(result[0].options[1]).toEqual({ key: "B", text: "选项二" });
    expect(result[1].id).toBe("②");
    expect(result[1].options[0]).toEqual({ key: "C", text: "选项三" });
    expect(result[1].options[1]).toEqual({ key: "D", text: "选项四" });
  });

  it("normalizes groups with object format options", () => {
    const input = [
      {
        id: "①",
        options: { A: "aaa", B: "bbb", C: "ccc" },
      },
    ];
    const result = normalizeBlankOptionGroups(input);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("①");
    expect(result[0].options).toEqual([
      { key: "A", text: "aaa" },
      { key: "B", text: "bbb" },
      { key: "C", text: "ccc" },
    ]);
  });

  it("filters out groups with empty id", () => {
    const input = [
      { id: "", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
      { id: "①", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
    ];
    const result = normalizeBlankOptionGroups(input);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("①");
  });

  it("filters out groups with fewer than 2 valid options", () => {
    const input = [
      { id: "①", options: [{ key: "A", text: "x" }] },
      { id: "②", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
    ];
    const result = normalizeBlankOptionGroups(input);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("②");
  });

  it("preserves original group order", () => {
    const input = [
      { id: "③", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
      { id: "①", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
      { id: "②", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
    ];
    const result = normalizeBlankOptionGroups(input);
    expect(result.map((g) => g.id)).toEqual(["③", "①", "②"]);
  });

  it("preserves segments on options", () => {
    const input = [
      {
        id: "①",
        options: [
          { key: "A", text: "x", segments: [{ type: "text", value: "hello" }] },
          { key: "B", text: "y" },
        ],
      },
    ];
    const result = normalizeBlankOptionGroups(input);
    expect(result[0].options[0].segments).toEqual([{ type: "text", value: "hello" }]);
    expect(result[0].options[1].segments).toBeUndefined();
  });

  it("does not mutate input", () => {
    const input = [
      { id: "①", options: [{ key: "A", text: "original" }, { key: "B", text: "original" }] },
    ];
    const original = JSON.stringify(input);
    normalizeBlankOptionGroups(input);
    expect(JSON.stringify(input)).toBe(original);
  });
});

// ── haveIdenticalOptionSets ───────────────────────────────────────────────

describe("haveIdenticalOptionSets", () => {
  it("returns true for identical groups", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "选项一"), makeOpt("B", "选项二")]),
      makeGroup("②", [makeOpt("A", "选项一"), makeOpt("B", "选项二")]),
    ];
    expect(haveIdenticalOptionSets(groups)).toBe(true);
  });

  it("returns false for different option keys", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "选项一"), makeOpt("B", "选项二")]),
      makeGroup("②", [makeOpt("A", "选项一"), makeOpt("C", "选项三")]),
    ];
    expect(haveIdenticalOptionSets(groups)).toBe(false);
  });

  it("returns false for different option texts", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "选项一"), makeOpt("B", "选项二")]),
      makeGroup("②", [makeOpt("A", "选项一"), makeOpt("B", "选项二-diff")]),
    ];
    expect(haveIdenticalOptionSets(groups)).toBe(false);
  });

  it("returns false for different option counts", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "一"), makeOpt("B", "二")]),
      makeGroup("②", [makeOpt("A", "一"), makeOpt("B", "二"), makeOpt("C", "三")]),
    ];
    expect(haveIdenticalOptionSets(groups)).toBe(false);
  });

  it("returns false for fewer than 2 groups", () => {
    const groups = [makeGroup("①", [makeOpt("A", "一"), makeOpt("B", "二")])];
    expect(haveIdenticalOptionSets(groups)).toBe(false);
  });

  it("returns false when segments differ", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "一", [{ type: "img" }]), makeOpt("B", "二")]),
      makeGroup("②", [makeOpt("A", "一"), makeOpt("B", "二")]),
    ];
    expect(haveIdenticalOptionSets(groups)).toBe(false);
  });

  it("handles 3+ identical groups", () => {
    const opt = [makeOpt("A", "一"), makeOpt("B", "二")];
    const groups = [makeGroup("①", opt), makeGroup("②", opt), makeGroup("③", opt)];
    expect(haveIdenticalOptionSets(groups)).toBe(true);
  });
});

// ── getSharedOptions ───────────────────────────────────────────────────────

describe("getSharedOptions", () => {
  it("returns first group's options when all identical", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "一"), makeOpt("B", "二")]),
      makeGroup("②", [makeOpt("A", "一"), makeOpt("B", "二")]),
    ];
    const result = getSharedOptions(groups);
    expect(result).toEqual([{ key: "A", text: "一" }, { key: "B", text: "二" }]);
  });

  it("returns empty array when groups differ", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "一")]),
      makeGroup("②", [makeOpt("B", "二")]),
    ];
    expect(getSharedOptions(groups)).toEqual([]);
  });

  it("returns empty array for single group", () => {
    const groups = [makeGroup("①", [makeOpt("A", "一"), makeOpt("B", "二")])];
    expect(getSharedOptions(groups)).toEqual([]);
  });

  it("returns deep copy, not reference", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "一")]),
      makeGroup("②", [makeOpt("A", "一")]),
    ];
    const result = getSharedOptions(groups);
    result[0].text = "modified";
    expect(groups[0].options[0].text).toBe("一");
  });
});

// ── parseBlankAnswer ───────────────────────────────────────────────────────

describe("parseBlankAnswer", () => {
  const groupIds = ["①", "②"];

  it("parses canonical format ①:B;②:D", () => {
    expect(parseBlankAnswer("①:B;②:D", groupIds)).toEqual({ "①": "B", "②": "D" });
  });

  it("parses OCR format ①B、②D", () => {
    expect(parseBlankAnswer("①B、②D", groupIds)).toEqual({ "①": "B", "②": "D" });
  });

  it("parses parenthesized format (1)B、(2)D", () => {
    expect(parseBlankAnswer("(1)B、(2)D", groupIds)).toEqual({ "1": "B", "2": "D" });
  });

  it("parses 第1空B format", () => {
    expect(parseBlankAnswer("第1空B 第2空D", groupIds)).toEqual({ "1": "B", "2": "D" });
  });

  it("parses positional B,D when count matches", () => {
    expect(parseBlankAnswer("B,D", groupIds)).toEqual({ "①": "B", "②": "D" });
  });

  it("does not parse positional when count mismatches", () => {
    const result = parseBlankAnswer("B", groupIds);
    expect(Object.keys(result)).toHaveLength(0);
  });

  it("returns empty map for null", () => {
    expect(parseBlankAnswer(null, groupIds)).toEqual({});
  });

  it("returns empty map for undefined", () => {
    expect(parseBlankAnswer(undefined, groupIds)).toEqual({});
  });

  it("returns empty map for empty string", () => {
    expect(parseBlankAnswer("", groupIds)).toEqual({});
  });

  it("normalizes lowercase to uppercase", () => {
    expect(parseBlankAnswer("①:a;②:c", groupIds)).toEqual({ "①": "A", "②": "C" });
  });

  it("handles semicolons and Chinese semicolons", () => {
    expect(parseBlankAnswer("①:A；②:D", groupIds)).toEqual({ "①": "A", "②": "D" });
  });
});

// ── serializeBlankAnswer ──────────────────────────────────────────────────

describe("serializeBlankAnswer", () => {
  const groupIds = ["①", "②", "③"];

  it("produces canonical format", () => {
    expect(serializeBlankAnswer({ "①": "B", "②": "D" }, groupIds)).toBe("①:B;②:D");
  });

  it("follows group order", () => {
    expect(serializeBlankAnswer({ "②": "D", "①": "B" }, groupIds)).toBe("①:B;②:D");
  });

  it("omits empty slots", () => {
    expect(serializeBlankAnswer({ "①": "B" }, groupIds)).toBe("①:B");
  });

  it("returns empty string for empty map", () => {
    expect(serializeBlankAnswer({}, groupIds)).toBe("");
  });

  it("only includes slots in groupIds", () => {
    expect(serializeBlankAnswer({ "①": "B", "④": "D" }, groupIds)).toBe("①:B");
  });
});

// ── updateSharedOption ─────────────────────────────────────────────────────

describe("updateSharedOption", () => {
  const groups = [
    makeGroup("①", [makeOpt("A", "选项一"), makeOpt("B", "选项二")]),
    makeGroup("②", [makeOpt("A", "选项一"), makeOpt("B", "选项二")]),
  ];

  it("updates all groups", () => {
    const result = updateSharedOption(groups, "A", { text: "新选项" });
    expect(result[0].options[0].text).toBe("新选项");
    expect(result[1].options[0].text).toBe("新选项");
  });

  it("does not mutate input", () => {
    const original = JSON.stringify(groups);
    updateSharedOption(groups, "A", { text: "新" });
    expect(JSON.stringify(groups)).toBe(original);
  });

  it("only updates matching key", () => {
    const result = updateSharedOption(groups, "A", { text: "新" });
    expect(result[0].options[1].text).toBe("选项二");
    expect(result[1].options[1].text).toBe("选项二");
  });
});

// ── validateBlankAnswerMap ────────────────────────────────────────────────

describe("validateBlankAnswerMap", () => {
  const groups = [
    makeGroup("①", [makeOpt("A", "一"), makeOpt("B", "二")]),
    makeGroup("②", [makeOpt("C", "三"), makeOpt("D", "四")]),
  ];

  it("returns valid for complete valid answers", () => {
    const result = validateBlankAnswerMap(groups, { "①": "A", "②": "D" });
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it("reports missing slots", () => {
    const result = validateBlankAnswerMap(groups, { "①": "A" });
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes("②"))).toBe(true);
  });

  it("reports extra slots", () => {
    const result = validateBlankAnswerMap(groups, { "①": "A", "②": "D", "③": "C" });
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes("③"))).toBe(true);
  });

  it("reports invalid option key", () => {
    const result = validateBlankAnswerMap(groups, { "①": "Z", "②": "D" });
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes("Z"))).toBe(true);
  });
});

// ── Immutability (cross-function) ──────────────────────────────────────────

describe("immutability", () => {
  it("normalizeBlankOptionGroups does not mutate input", () => {
    const input = [
      { id: "①", options: [{ key: "A", text: "original" }, { key: "B", text: "original" }] },
    ];
    const copy = JSON.parse(JSON.stringify(input));
    normalizeBlankOptionGroups(input);
    expect(input).toEqual(copy);
  });
});

describe("normalizeBlankOptionGroups - prefix stripping", () => {
  it("strips group-ID prefix from option keys in array format", () => {
    const input = [
      { id: "①", options: [{ key: "①A", text: "a" }, { key: "①B", text: "b" }, { key: "①C", text: "c" }] },
      { id: "②", options: [{ key: "②A", text: "d" }, { key: "②B", text: "e" }, { key: "②C", text: "f" }] },
    ];
    const result = normalizeBlankOptionGroups(input);
    expect(result[0].options.map((o) => o.key)).toEqual(["A", "B", "C"]);
    expect(result[1].options.map((o) => o.key)).toEqual(["A", "B", "C"]);
    expect(result[0].options.map((o) => o.text)).toEqual(["a", "b", "c"]);
    expect(result[1].options.map((o) => o.text)).toEqual(["d", "e", "f"]);
  });

  it("strips numeric prefix from option keys", () => {
    const input = [
      { id: "1", options: [{ key: "1A", text: "x" }, { key: "1B", text: "y" }] },
    ];
    const result = normalizeBlankOptionGroups(input);
    expect(result[0].options.map((o) => o.key)).toEqual(["A", "B"]);
  });

  it("does not strip non-prefix single character", () => {
    const input = [
      { id: "①", options: [{ key: "A", text: "a" }, { key: "B", text: "b" }, { key: "C", text: "c" }] },
    ];
    const result = normalizeBlankOptionGroups(input);
    expect(result[0].options.map((o) => o.key)).toEqual(["A", "B", "C"]);
  });
});

// ── deduplicateGroupOptions ───────────────────────────────────────────

describe("deduplicateGroupOptions", () => {
  it("leaves clean groups unchanged", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
      makeGroup("②", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
    ];
    const result = deduplicateGroupOptions(groups);
    expect(result.groups[0].options).toHaveLength(4);
    expect(result.groups[1].options).toHaveLength(4);
    expect(result.warnings).toHaveLength(0);
    expect(result.errors).toHaveLength(0);
  });

  it("folds fully identical duplicates with warning", () => {
    const groups = [
      makeGroup("①", [
        makeOpt("A", "2"), makeOpt("B", "m"),
        makeOpt("C", "2m−1"), makeOpt("D", "2m"),
        makeOpt("A", "2"), makeOpt("B", "m"), // dupes
        makeOpt("C", "2m−1"), makeOpt("D", "2m"), // dupes
      ]),
    ];
    const result = deduplicateGroupOptions(groups);
    expect(result.groups[0].options).toHaveLength(4);
    expect(result.groups[0].options.map((o) => o.key)).toEqual(["A", "B", "C", "D"]);
    expect(result.warnings.length).toBeGreaterThanOrEqual(1);
    expect(result.errors).toHaveLength(0);
  });

  it("detects conflicting duplicates as errors", () => {
    const groups = [
      makeGroup("①", [
        makeOpt("A", "2"), makeOpt("A", "different"),
      ]),
    ];
    const result = deduplicateGroupOptions(groups);
    expect(result.errors.length).toBeGreaterThanOrEqual(1);
    expect(result.errors.some((e) => e.includes("不一致"))).toBe(true);
    // Conflicting duplicates are kept (not auto-resolved)
    expect(result.groups[0].options).toHaveLength(2);
  });

  it("allows same text under different keys", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "same"), makeOpt("B", "same")]),
    ];
    const result = deduplicateGroupOptions(groups);
    expect(result.groups[0].options).toHaveLength(2);
    expect(result.warnings).toHaveLength(0);
    expect(result.errors).toHaveLength(0);
  });

  it("does not mutate input", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "2"), makeOpt("A", "2")]),
    ];
    const origLen = groups[0].options.length;
    deduplicateGroupOptions(groups);
    expect(groups[0].options).toHaveLength(origLen);
  });

  it("processes all groups independently", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "x"), makeOpt("B", "y"), makeOpt("A", "x")]),
      makeGroup("②", [makeOpt("A", "x"), makeOpt("B", "y")]),
    ];
    const result = deduplicateGroupOptions(groups);
    expect(result.groups[0].options).toHaveLength(2);
    expect(result.groups[1].options).toHaveLength(2);
  });
});

// ── Data flow integration tests ─────────────────────────────────────

describe("data flow - shared options", () => {
  it("sharedOptions is 4, not 8 for two identical groups", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
      makeGroup("②", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
    ];
    expect(haveIdenticalOptionSets(groups)).toBe(true);
    const shared = getSharedOptions(groups);
    expect(shared).toHaveLength(4);
    expect(shared.map((o) => o.key)).toEqual(["A", "B", "C", "D"]);
  });

  it("getSharedOptions returns deep copy", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "2"), makeOpt("B", "m")]),
      makeGroup("②", [makeOpt("A", "2"), makeOpt("B", "m")]),
    ];
    const shared = getSharedOptions(groups);
    shared[0].text = "modified";
    expect(groups[0].options[0].text).toBe("2");
  });

  it("updateSharedOption syncs all groups, each stays 4", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
      makeGroup("②", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
    ];
    const result = updateSharedOption(groups, "B", { text: "M" });
    expect(result[0].options).toHaveLength(4);
    expect(result[1].options).toHaveLength(4);
    expect(result[0].options[1].text).toBe("M");
    expect(result[1].options[1].text).toBe("M");
  });

  it("two consecutive updates don't produce 8 items", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
      makeGroup("②", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
    ];
    let current = updateSharedOption(groups, "B", { text: "M" });
    expect(current[0].options).toHaveLength(4);
    expect(current[1].options).toHaveLength(4);
    current = updateSharedOption(current, "C", { text: "C_new" });
    expect(current[0].options).toHaveLength(4);
    expect(current[1].options).toHaveLength(4);
  });
});

describe("data flow - answer management", () => {
  const groups = [
    makeGroup("①", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
    makeGroup("②", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
  ];
  const groupIds = groups.map((g) => g.id);

  it("parses canonical answer ①:D;②:A", () => {
    const result = parseBlankAnswer("①:D;②:A", groupIds);
    expect(result).toEqual({ "①": "D", "②": "A" });
  });

  it("serializes answer following group order", () => {
    const result = serializeBlankAnswer({ "①": "D", "②": "A" }, groupIds);
    expect(result).toBe("①:D;②:A");
  });

  it("per-slot answer options are each 4, not 8", () => {
    expect(groups[0].options).toHaveLength(4);
    expect(groups[1].options).toHaveLength(4);
  });

  it("different slots can select same key", () => {
    const validation = validateBlankAnswerMap(groups, { "①": "A", "②": "A" });
    expect(validation.valid).toBe(true);
  });

  it("reports missing slots", () => {
    const validation = validateBlankAnswerMap(groups, { "①": "A" });
    expect(validation.valid).toBe(false);
    expect(validation.errors.some((e) => e.includes("②"))).toBe(true);
  });
});

describe("data flow - edge cases", () => {
  it("empty groups haveIdenticalOptionSets is false", () => {
    expect(haveIdenticalOptionSets([])).toBe(false);
  });

  it("single group haveIdenticalOptionSets is false", () => {
    const group = makeGroup("①", [makeOpt("A", "x"), makeOpt("B", "y")]);
    expect(haveIdenticalOptionSets([group])).toBe(false);
  });

  it("single group getSharedOptions is empty", () => {
    const group = makeGroup("①", [makeOpt("A", "x"), makeOpt("B", "y")]);
    expect(getSharedOptions([group])).toEqual([]);
  });

  it("options with segments compare correctly", () => {
    const a = makeOpt("A", "x", [{ type: "img", url: "a.png" }]);
    const b = makeOpt("A", "x", [{ type: "img", url: "a.png" }]);
    const c = makeOpt("A", "x", [{ type: "img", url: "b.png" }]);
    const groupsAB = [makeGroup("①", [a, makeOpt("B", "y")]), makeGroup("②", [b, makeOpt("B", "y")])];
    const groupsAC = [makeGroup("①", [a, makeOpt("B", "y")]), makeGroup("②", [c, makeOpt("B", "y")])];
    expect(haveIdenticalOptionSets(groupsAB)).toBe(true);
    expect(haveIdenticalOptionSets(groupsAC)).toBe(false);
  });
});

describe("save payload validation", () => {
  it("payload has 2 groups with 4 options each and parsed_options null", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
      makeGroup("②", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
    ];
    const answerMap = { "①": "D", "②": "A" };
    const answer = serializeBlankAnswer(answerMap, groups.map((g) => g.id));
    const parsedOptions = null;
    const payload = {
      question_type: "multi_blank_choice",
      answer,
      parsed_options: parsedOptions,
      parsed_content: { blank_option_groups: groups },
    };

    expect(payload.parsed_options).toBeNull();
    expect((payload.parsed_content.blank_option_groups as BlankOptionGroup[])).toHaveLength(2);
    expect((payload.parsed_content.blank_option_groups as BlankOptionGroup[])[0].options).toHaveLength(4);
    expect((payload.parsed_content.blank_option_groups as BlankOptionGroup[])[1].options).toHaveLength(4);
    expect(payload.answer).toBe("①:D;②:A");
  });

  it("init → save → re-init keeps 4 options per group", () => {
    const groups = [
      makeGroup("①", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
      makeGroup("②", [makeOpt("A", "2"), makeOpt("B", "m"), makeOpt("C", "2m−1"), makeOpt("D", "2m")]),
    ];
    // Simulate save: serialize groups to JSON (like API would)
    const serialized = JSON.parse(JSON.stringify(groups));
    // Re-init: normalize and dedup
    const reinit = deduplicateGroupOptions(serialized);
    expect(reinit.groups[0].options).toHaveLength(4);
    expect(reinit.groups[1].options).toHaveLength(4);
  });
});

// ── extractMultiBlankSource ───────────────────────────────────────────

describe("extractMultiBlankSource", () => {
  it("extracts from parsed_content.blank_option_groups", () => {
    const item = {
      parsed_content: {
        blank_option_groups: [
          { id: "①", options: [{ key: "A", text: "2" }, { key: "B", text: "m" }] },
          { id: "②", options: [{ key: "A", text: "2" }, { key: "B", text: "m" }] },
        ],
      },
      parsed_answer: "①:A;②:B",
    };
    const result = extractMultiBlankSource(item);
    expect(result.source).toBe("parsed_content");
    expect(result.groups).toHaveLength(2);
    expect(result.answer).toBe("①:A;②:B");
    expect(result.errors).toHaveLength(0);
  });

  it("falls back to raw_data when parsed_content is absent", () => {
    const item = {
      raw_data: {
        blank_option_groups: [
          { id: "①", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
          { id: "②", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
        ],
      },
      parsed_answer: "①:A;②:B",
    };
    const result = extractMultiBlankSource(item);
    expect(result.source).toBe("raw_data");
    expect(result.groups).toHaveLength(2);
    expect(result.warnings.some((w) => w.includes("历史原始数据"))).toBe(true);
  });

  it("returns error when parsed_content exists but blank_option_groups is invalid", () => {
    const item = {
      parsed_content: { text: "some stem" },
      raw_data: {
        blank_option_groups: [
          { id: "①", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
        ],
      },
    };
    const result = extractMultiBlankSource(item);
    // Should NOT silently fall through to raw_data
    expect(result.source).toBe("parsed_content");
    expect(result.groups).toHaveLength(0);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it("returns none when no source has data", () => {
    const item = { parsed_answer: "" };
    const result = extractMultiBlankSource(item);
    expect(result.source).toBe("none");
    expect(result.groups).toHaveLength(0);
  });

  it("folds identical duplicates and reports warning", () => {
    const item = {
      parsed_content: {
        blank_option_groups: [
          { id: "①", options: [{ key: "A", text: "2" }, { key: "A", text: "2" }, { key: "B", text: "m" }] },
        ],
      },
    };
    const result = extractMultiBlankSource(item);
    // Single group < 2 → should not be valid
    expect(result.groups).toHaveLength(0);
  });

  it("does not mutate input", () => {
    const item = {
      parsed_content: {
        blank_option_groups: [
          { id: "①", options: [{ key: "A", text: "2" }, { key: "B", text: "m" }] },
          { id: "②", options: [{ key: "A", text: "2" }, { key: "B", text: "m" }] },
        ],
      },
    };
    const original = JSON.stringify(item);
    extractMultiBlankSource(item as unknown as Record<string, unknown>);
    expect(JSON.stringify(item)).toBe(original);
  });
});

// ── buildMultiBlankSavePayload ────────────────────────────────────────

describe("buildMultiBlankSavePayload", () => {
  function makeGroup(id: string, opts: Array<{ key: string; text: string }>) {
    return { id, options: opts.map((o) => ({ ...o })) };
  }

  const validGroups = [
    makeGroup("①", [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }]),
    makeGroup("②", [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }]),
  ];
  const validAnswerMap = { "①": "D", "②": "A" };
  const item = { parsed_analysis: "analysis text", subject_id: 1 };

  it("produces valid payload for correct input", () => {
    const result = buildMultiBlankSavePayload(item, validGroups, validAnswerMap, "stem");
    expect(result.errors).toHaveLength(0);
    expect(result.payload).not.toBeNull();
    expect(result.payload!.answer).toBe("①:D;②:A");
    expect(result.payload!.question_type).toBe("multi_blank_choice");
    expect(result.payload!.parsed_options).toBeNull();
  });

  it("includes blank_option_groups in parsed_content", () => {
    const result = buildMultiBlankSavePayload(item, validGroups, validAnswerMap, "stem");
    const pc = result.payload!.parsed_content as Record<string, unknown>;
    expect(pc.blank_option_groups).toEqual(validGroups);
  });

  it("includes stem text in parsed_content", () => {
    const result = buildMultiBlankSavePayload(item, validGroups, validAnswerMap, "test stem");
    const pc = result.payload!.parsed_content as Record<string, unknown>;
    expect(pc.text).toBe("test stem");
  });

  it("does not include UI-only temp fields", () => {
    const result = buildMultiBlankSavePayload(item, validGroups, validAnswerMap, "stem");
    const keys = Object.keys(result.payload!);
    expect(keys).not.toContain("rawAnswerDraft");
    expect(keys).not.toContain("rawAnswerError");
    expect(keys).not.toContain("dedupWarnings");
    expect(keys).not.toContain("dedupErrors");
  });

  it("errors when groups < 2", () => {
    const result = buildMultiBlankSavePayload(
      item,
      [makeGroup("①", [{ key: "A", text: "x" }, { key: "B", text: "y" }])],
      { "①": "A" },
      "stem",
    );
    expect(result.errors.length).toBeGreaterThan(0);
    expect(result.payload).toBeNull();
  });

  it("errors on duplicate group IDs", () => {
    const groups = [
      makeGroup("①", [{ key: "A", text: "x" }, { key: "B", text: "y" }]),
      makeGroup("①", [{ key: "A", text: "x" }, { key: "B", text: "y" }]),
    ];
    const result = buildMultiBlankSavePayload(item, groups, { "①": "A" }, "stem");
    expect(result.errors.some((e) => e.includes("重复"))).toBe(true);
    expect(result.payload).toBeNull();
  });

  it("errors when group has < 2 options", () => {
    const groups = [
      makeGroup("①", [{ key: "A", text: "x" }]),
      makeGroup("②", [{ key: "A", text: "x" }, { key: "B", text: "y" }]),
    ];
    const result = buildMultiBlankSavePayload(item, groups, { "①": "A", "②": "A" }, "stem");
    expect(result.errors.some((e) => e.includes("至少需要 2 个选项"))).toBe(true);
    expect(result.payload).toBeNull();
  });

  it("errors on missing slot in answer", () => {
    const result = buildMultiBlankSavePayload(item, validGroups, { "①": "D" }, "stem");
    expect(result.errors.some((e) => e.includes("缺少空"))).toBe(true);
    expect(result.payload).toBeNull();
  });

  it("errors on invalid answer key", () => {
    const result = buildMultiBlankSavePayload(item, validGroups, { "①": "Z", "②": "A" }, "stem");
    expect(result.errors.some((e) => e.includes("不在选项内"))).toBe(true);
    expect(result.payload).toBeNull();
  });

  it("errors on extra slot in answer", () => {
    const result = buildMultiBlankSavePayload(item, validGroups, { "①": "D", "②": "A", "③": "B" }, "stem");
    expect(result.errors.some((e) => e.includes("未知空位"))).toBe(true);
    expect(result.payload).toBeNull();
  });

  it("errors on conflicting duplicate options", () => {
    const groups = [
      makeGroup("①", [{ key: "A", text: "2" }, { key: "A", text: "different" }, { key: "B", text: "m" }, { key: "C", text: "x" }]),
      makeGroup("②", [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "x" }, { key: "D", text: "y" }]),
    ];
    const result = buildMultiBlankSavePayload(item, groups, { "①": "A", "②": "B" }, "stem");
    expect(result.errors.length).toBeGreaterThan(0);
    expect(result.payload).toBeNull();
  });

  it("deduplicates identical repeats without error", () => {
    const groups = [
      makeGroup("①", [{ key: "A", text: "2" }, { key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }]),
      makeGroup("②", [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }]),
    ];
    const result = buildMultiBlankSavePayload(item, groups, { "①": "D", "②": "A" }, "stem");
    expect(result.payload).not.toBeNull();
    if (result.payload) {
      const pc = result.payload.parsed_content as Record<string, unknown>;
      const bg = pc.blank_option_groups as BlankOptionGroup[];
      expect(bg[0].options).toHaveLength(4);
    }
  });

  it("canonical answer follows group order", () => {
    const unorderedGroups = [
      makeGroup("②", [{ key: "A", text: "x" }, { key: "B", text: "y" }]),
      makeGroup("①", [{ key: "A", text: "x" }, { key: "B", text: "y" }]),
    ];
    const result = buildMultiBlankSavePayload(item, unorderedGroups, { "①": "B", "②": "A" }, "stem");
    expect(result.payload!.answer).toBe("②:A;①:B");
  });

  it("preserves existing parsed_content fields", () => {
    const itemWithExtra = {
      ...item,
      parsed_content: {
        segments: [{ type: "text", value: "hello" }],
      },
    };
    const result = buildMultiBlankSavePayload(
      itemWithExtra,
      validGroups,
      validAnswerMap,
      "stem",
    );
    const pc = result.payload!.parsed_content as Record<string, unknown>;
    expect(pc.segments).toEqual([{ type: "text", value: "hello" }]);
    expect(pc.blank_option_groups).toEqual(validGroups);
  });

  it("does not mutate input", () => {
    const groupsCopy = JSON.parse(JSON.stringify(validGroups));
    const mapCopy = { ...validAnswerMap };
    buildMultiBlankSavePayload(item, validGroups, validAnswerMap, "stem");
    expect(validGroups).toEqual(groupsCopy);
    expect(validAnswerMap).toEqual(mapCopy);
  });

  it("returns payload even when item is null/undefined", () => {
    const result = buildMultiBlankSavePayload(null, validGroups, validAnswerMap, "stem");
    expect(result.payload).not.toBeNull();
    expect(result.payload!.subject_id).toBeUndefined();
  });
});

// ── Data flow: answerMap ↔ canonical answer sync ─────────────────────

describe("answerMap canonical answer sync", () => {
  const makeGroup = (id: string, opts: Array<{ key: string; text: string }>) => ({
    id,
    options: opts.map((o) => ({ ...o })),
  });

  const groups = [
    makeGroup("①", [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }]),
    makeGroup("②", [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }]),
  ];
  const groupIds = groups.map((g) => g.id);

  it("click ①D → answerMap and canonical sync", () => {
    const answerMap = { "①": "D" };
    const canonical = serializeBlankAnswer(answerMap, groupIds);
    expect(canonical).toBe("①:D");
    expect(answerMap).toEqual({ "①": "D" });
  });

  it("click ①D then ②A → both preserved", () => {
    let answerMap: Record<string, string> = {};
    answerMap = { ...answerMap, "①": "D" };
    answerMap = { ...answerMap, "②": "A" };
    const canonical = serializeBlankAnswer(answerMap, groupIds);
    expect(canonical).toBe("①:D;②:A");
    expect(answerMap).toEqual({ "①": "D", "②": "A" });
  });

  it("clear ① → answer incomplete", () => {
    const answerMap: Record<string, string> = { "①": "D", "②": "A" };
    const { "①": _removed, ...rest } = answerMap;
    const canonical = serializeBlankAnswer(rest, groupIds);
    expect(canonical).toBe("②:A");
    expect(Object.keys(rest)).toHaveLength(1);
  });

  it("group ID rename migrates answerMap key", () => {
    const oldAnswerMap = { "①": "D", "②": "A" };
    const newAnswerMap: Record<string, string> = {};
    for (const [k, v] of Object.entries(oldAnswerMap)) {
      newAnswerMap[k === "①" ? "(1)" : k] = v;
    }
    const newGroupIds = ["(1)", "②"];
    const canonical = serializeBlankAnswer(newAnswerMap, newGroupIds);
    expect(canonical).toBe("(1):D;②:A");
    expect(newAnswerMap["(1)"]).toBe("D");
    expect(newAnswerMap["①"]).toBeUndefined();
  });

  it("delete group removes its answer from canonical", () => {
    const answerMap = { "①": "D", "②": "A", "③": "B" };
    const newGroupIds = ["①", "②"]; // ③ removed
    const canonical = serializeBlankAnswer(answerMap, newGroupIds);
    expect(canonical).toBe("①:D;②:A");
  });

  it("add group → answer incomplete until filled", () => {
    const answerMap = { "①": "D", "②": "A" };
    const validation1 = validateBlankAnswerMap(groups, answerMap);
    expect(validation1.valid).toBe(true);
    const validation2 = validateBlankAnswerMap(
      [...groups, makeGroup("③", [{ key: "A", text: "x" }, { key: "B", text: "y" }])],
      { ...answerMap },
    );
    expect(validation2.valid).toBe(false);
  });

  it("group order change → canonical order follows", () => {
    const answerMap = { "①": "D", "②": "A" };
    const reversed = serializeBlankAnswer(answerMap, ["②", "①"]);
    expect(reversed).toBe("②:A;①:D");
  });

  it("save payload uses answerMap-derived answer, not item.parsed_answer", () => {
    const result = buildMultiBlankSavePayload(
      { parsed_answer: "old answer" },
      groups,
      { "①": "D", "②": "A" },
      "stem",
    );
    expect(result.payload?.answer).toBe("①:D;②:A");
  });
});

// ── reduceMultiBlankEditState ──────────────────────────────────────────

describe("reduceMultiBlankEditState", () => {
  const baseState: MultiBlankEditState = {
    groups: [
      { id: "①", options: [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }] },
      { id: "②", options: [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }] },
    ],
    answerMap: { "①": "D", "②": "A" },
    usesSharedOptions: true,
    sharedOptions: [],
  };

  it("toggle_answer: select new option", () => {
    const next = reduceMultiBlankEditState(baseState, {
      type: "toggle_answer",
      groupId: "①",
      optionKey: "B",
    });
    expect(next.answerMap["①"]).toBe("B");
    expect(next.answerMap["②"]).toBe("A");
  });

  it("toggle_answer: deselect same option", () => {
    const next = reduceMultiBlankEditState(baseState, {
      type: "toggle_answer",
      groupId: "①",
      optionKey: "D",
    });
    expect(next.answerMap["①"]).toBeUndefined();
    expect(next.answerMap["②"]).toBe("A");
  });

  it("toggle_answer: sets hasUnappliedDraft=false", () => {
    const state = { ...baseState, hasUnappliedDraft: true };
    const next = reduceMultiBlankEditState(state, {
      type: "toggle_answer", groupId: "①", optionKey: "B",
    });
    expect(next.hasUnappliedDraft).toBe(false);
  });

  it("toggle_answer: closure-safe (sequential toggles)", () => {
    const next1 = reduceMultiBlankEditState(baseState, {
      type: "toggle_answer", groupId: "①", optionKey: "B",
    });
    const next2 = reduceMultiBlankEditState(next1, {
      type: "toggle_answer", groupId: "②", optionKey: "C",
    });
    expect(next2.answerMap["①"]).toBe("B");
    expect(next2.answerMap["②"]).toBe("C");
  });

  it("apply_answer_map: replaces answerMap entirely", () => {
    const next = reduceMultiBlankEditState(baseState, {
      type: "apply_answer_map",
      answerMap: { "①": "A", "②": "D" },
    });
    expect(next.answerMap).toEqual({ "①": "A", "②": "D" });
  });

  it("apply_answer_map: clears hasUnappliedDraft", () => {
    const state = { ...baseState, hasUnappliedDraft: true };
    const next = reduceMultiBlankEditState(state, {
      type: "apply_answer_map",
      answerMap: { "①": "A", "②": "D" },
    });
    expect(next.hasUnappliedDraft).toBe(false);
  });

  it("update_shared_options: applies to all groups, keeps usesSharedOptions=true", () => {
    const next = reduceMultiBlankEditState(baseState, {
      type: "update_shared_options",
      options: [{ key: "X", text: "new" }, { key: "Y", text: "opts" }],
    });
    expect(next.groups[0].options).toEqual([{ key: "X", text: "new" }, { key: "Y", text: "opts" }]);
    expect(next.groups[1].options).toEqual([{ key: "X", text: "new" }, { key: "Y", text: "opts" }]);
    expect(next.usesSharedOptions).toBe(true);
  });

  it("update_shared_options: cleans up invalid answerMap entries", () => {
    const state = {
      ...baseState,
      answerMap: { "①": "D", "②": "A" },
    };
    const next = reduceMultiBlankEditState(state, {
      type: "update_shared_options",
      options: [{ key: "A", text: "only-a" }, { key: "B", text: "only-b" }],
    });
    expect(next.answerMap["①"]).toBeUndefined();
    expect(next.answerMap["②"]).toBe("A");
  });

  it("update_group_options: updates single group only", () => {
    const next = reduceMultiBlankEditState(baseState, {
      type: "update_group_options",
      groupId: "②",
      options: [{ key: "P", text: "p" }, { key: "Q", text: "q" }],
    });
    expect(next.groups[0].options).toHaveLength(4);
    expect(next.groups[1].options).toEqual([{ key: "P", text: "p" }, { key: "Q", text: "q" }]);
  });

  it("rename_group: migrates answerMap key", () => {
    const next = reduceMultiBlankEditState(baseState, {
      type: "rename_group",
      oldId: "①",
      newId: "(1)",
    });
    expect(next.groups[0].id).toBe("(1)");
    expect(next.answerMap["(1)"]).toBe("D");
    expect(next.answerMap["①"]).toBeUndefined();
  });

  it("remove_group: removes group and its answerMap entry", () => {
    const next = reduceMultiBlankEditState(baseState, {
      type: "remove_group",
      groupId: "②",
    });
    expect(next.groups).toHaveLength(1);
    expect(next.answerMap["②"]).toBeUndefined();
    expect(next.answerMap["①"]).toBe("D");
  });

  it("split_shared_groups: sets usesSharedOptions=false", () => {
    const next = reduceMultiBlankEditState(baseState, {
      type: "split_shared_groups",
    });
    expect(next.usesSharedOptions).toBe(false);
  });

  it("set_draft_state: updates hasUnappliedDraft", () => {
    const next = reduceMultiBlankEditState(baseState, {
      type: "set_draft_state",
      hasUnappliedDraft: true,
    });
    expect(next.hasUnappliedDraft).toBe(true);
  });

  it("set_draft_state: clears hasUnappliedDraft", () => {
    const state = { ...baseState, hasUnappliedDraft: true };
    const next = reduceMultiBlankEditState(state, {
      type: "set_draft_state",
      hasUnappliedDraft: false,
    });
    expect(next.hasUnappliedDraft).toBe(false);
  });

  it("does not mutate input state", () => {
    const original = { ...baseState, answerMap: { ...baseState.answerMap } };
    const originalCopy = { ...original.answerMap };
    reduceMultiBlankEditState(baseState, { type: "toggle_answer", groupId: "①", optionKey: "B" });
    expect(baseState.answerMap).toEqual(originalCopy);
  });
});

// ── syncDerivedMultiBlankFields ────────────────────────────────────────

describe("syncDerivedMultiBlankFields", () => {
  it("computes canonical answer from answerMap", () => {
    const result = syncDerivedMultiBlankFields(
      { answer: "old" },
      {
        groups: [
          { id: "①", options: [] },
          { id: "②", options: [] },
        ],
        answerMap: { "①": "B", "②": "C" },
        usesSharedOptions: false,
        sharedOptions: [],
      },
    );
    expect(result.answer).toBe("①:B;②:C");
  });

  it("computes sharedOptions when usesSharedOptions and groups match", () => {
    const result = syncDerivedMultiBlankFields(
      { answer: "" },
      {
        groups: [
          { id: "①", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
          { id: "②", options: [{ key: "A", text: "x" }, { key: "B", text: "y" }] },
        ],
        answerMap: {},
        usesSharedOptions: true,
        sharedOptions: [],
      },
    );
    expect(result.multiBlank.sharedOptions).toHaveLength(2);
  });

  it("returns empty sharedOptions when usesSharedOptions is false", () => {
    const result = syncDerivedMultiBlankFields(
      { answer: "" },
      {
        groups: [
          { id: "①", options: [{ key: "A", text: "x" }] },
          { id: "②", options: [{ key: "B", text: "y" }] },
        ],
        answerMap: {},
        usesSharedOptions: false,
        sharedOptions: [],
      },
    );
    expect(result.multiBlank.sharedOptions).toEqual([]);
  });
});

// ── getMultiBlankSaveState ─────────────────────────────────────────────

describe("getMultiBlankSaveState", () => {
  const validGroups = [
    { id: "①", options: [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }] },
    { id: "②", options: [{ key: "A", text: "2" }, { key: "B", text: "m" }, { key: "C", text: "2m−1" }, { key: "D", text: "2m" }] },
  ];
  const completeAnswerMap = { "①": "D", "②": "A" };

  it("canSave=true with valid groups and complete answerMap", () => {
    const result = getMultiBlankSaveState(validGroups, completeAnswerMap, [], [], false);
    expect(result.canSave).toBe(true);
    expect(result.errors).toEqual([]);
  });

  it("canSave=false when groups < 2", () => {
    const result = getMultiBlankSaveState([validGroups[0]], {}, [], [], false);
    expect(result.canSave).toBe(false);
    expect(result.errors.some((e) => e.includes("至少需要"))).toBe(true);
  });

  it("canSave=false when answerMap missing a group", () => {
    const result = getMultiBlankSaveState(validGroups, { "①": "D" }, [], [], false);
    expect(result.canSave).toBe(false);
    expect(result.errors.some((e) => e.includes("尚未选择"))).toBe(true);
  });

  it("canSave=false when answer value not in option keys", () => {
    const result = getMultiBlankSaveState(validGroups, { "①": "D", "②": "Z" }, [], [], false);
    expect(result.canSave).toBe(false);
    expect(result.errors.some((e) => e.includes("不在选项内"))).toBe(true);
  });

  it("canSave=false when answerMap has phantom slot", () => {
    const result = getMultiBlankSaveState(validGroups, { "①": "D", "②": "A", "③": "B" }, [], [], false);
    expect(result.canSave).toBe(false);
    expect(result.errors.some((e) => e.includes("未知空位"))).toBe(true);
  });

  it("canSave=false when dedupErrors present", () => {
    const result = getMultiBlankSaveState(validGroups, completeAnswerMap, [], ["冲突: 选项 A"], false);
    expect(result.canSave).toBe(false);
  });

  it("canSave=false when hasUnappliedDraft is true", () => {
    const result = getMultiBlankSaveState(validGroups, completeAnswerMap, [], [], true);
    expect(result.canSave).toBe(false);
    expect(result.errors.some((e) => e.includes("未应用"))).toBe(true);
  });

  it("canSave=false when group has < 2 options", () => {
    const groups = [
      { id: "①", options: [{ key: "A", text: "x" }] },
      { id: "②", options: [{ key: "B", text: "y" }, { key: "C", text: "z" }] },
    ];
    const result = getMultiBlankSaveState(groups, { "①": "A", "②": "B" }, [], [], false);
    expect(result.canSave).toBe(false);
    expect(result.errors.some((e) => e.includes("至少需要"))).toBe(true);
  });

  it("non-blocking dedupWarnings do not prevent save", () => {
    const result = getMultiBlankSaveState(validGroups, completeAnswerMap, ["重复项已折叠"], [], false);
    expect(result.canSave).toBe(true);
    expect(result.warnings).toHaveLength(1);
  });

  it("empty groups returns canSave=false immediately", () => {
    const result = getMultiBlankSaveState([], {}, [], [], false);
    expect(result.canSave).toBe(false);
  });
});
