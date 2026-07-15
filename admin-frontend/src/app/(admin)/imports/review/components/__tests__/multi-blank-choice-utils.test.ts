import { describe, it, expect } from "vitest";
import {
  normalizeBlankOptionGroups,
  deduplicateGroupOptions,
  parseBlankAnswer,
  serializeBlankAnswer,
  haveIdenticalOptionSets,
  getSharedOptions,
  updateSharedOption,
  validateBlankAnswerMap,
  type BlankOptionGroup,
  type BlankOption,
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
