import { describe, it, expect } from "vitest";
import {
  unresolvedTableCount,
  textFromContent,
  renderJson,
  statusTone,
  duplicateStatusTone,
} from "./review-page-utils";

describe("unresolvedTableCount", () => {
  it("returns 0 for null", () => {
    expect(unresolvedTableCount(null)).toBe(0);
  });
  it("returns 0 for non-object", () => {
    expect(unresolvedTableCount("string")).toBe(0);
  });
  it("returns 0 for object without segments", () => {
    expect(unresolvedTableCount({ foo: "bar" })).toBe(0);
  });
  it("returns 0 for segments without tables", () => {
    expect(unresolvedTableCount({ segments: [{ type: "text", content: "hello" }] })).toBe(0);
  });
  it("returns 0 for empty segments array", () => {
    expect(unresolvedTableCount({ segments: [] })).toBe(0);
  });
});

describe("textFromContent", () => {
  it("returns empty for null", () => {
    expect(textFromContent(null)).toBe("");
  });
  it("returns string content directly", () => {
    expect(textFromContent("hello")).toBe("hello");
  });
  it("extracts stem field", () => {
    expect(textFromContent({ stem: "question text" })).toBe("question text");
  });
  it("extracts text field", () => {
    expect(textFromContent({ text: "question text" })).toBe("question text");
  });
  it("falls back to JSON", () => {
    expect(textFromContent({ foo: "bar" })).toBe(JSON.stringify({ foo: "bar" }, null, 2));
  });
});

describe("renderJson", () => {
  it("returns dash for null/undefined/empty", () => {
    expect(renderJson(null)).toBe("—");
    expect(renderJson(undefined)).toBe("—");
    expect(renderJson("")).toBe("—");
  });
  it("returns string as-is", () => {
    expect(renderJson("hello")).toBe("hello");
  });
  it("returns number as string", () => {
    expect(renderJson(42)).toBe("42");
  });
  it("JSON-stringifies objects", () => {
    expect(renderJson({ a: 1 })).toBe('{\n  "a": 1\n}');
  });
});

describe("statusTone", () => {
  it("returns success for approved", () => { expect(statusTone("approved")).toBe("success"); });
  it("returns danger for rejected", () => { expect(statusTone("rejected")).toBe("danger"); });
  it("returns warning for re_pending", () => { expect(statusTone("re_pending")).toBe("warning"); });
  it("returns primary for unknown", () => { expect(statusTone("draft")).toBe("primary"); });
});

describe("duplicateStatusTone", () => {
  it("returns warning for possible_duplicate", () => { expect(duplicateStatusTone("possible_duplicate")).toBe("warning"); });
  it("returns success for normal", () => { expect(duplicateStatusTone("normal")).toBe("success"); });
  it("returns neutral for null", () => { expect(duplicateStatusTone(null)).toBe("neutral"); });
  it("returns neutral for undefined", () => { expect(duplicateStatusTone(undefined)).toBe("neutral"); });
});
