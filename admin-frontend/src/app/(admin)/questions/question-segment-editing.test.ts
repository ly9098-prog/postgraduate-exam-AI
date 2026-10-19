import { describe, expect, it } from "vitest";
import type { QuestionEditRequest } from "@/lib/api/types";
import {
  addQuestionCodeSegment, replaceQuestionSegments, updateCodeSegmentField,
} from "./question-segment-editing";

describe("structured question draft updates", () => {
  it("replaces segments while retaining non-content edits and structured metadata", () => {
    const form = { answer: "B", content: { stem: "old", custom: { layout: "kept" } } };
    const segments = [{ type: "text", text: "new" }, { type: "code", code: "int x;" }];
    const next = replaceQuestionSegments(form, segments);
    expect(next).toEqual({
      answer: "B", content: {
        stem: "old", text: "old", custom: { layout: "kept" },
        render_mode: "segments", segments,
      },
    });
    expect(next.content?.segments).toBe(segments);
    expect(form).toEqual({ answer: "B", content: { stem: "old", custom: { layout: "kept" } } });
  });

  it("preserves an independent stem after deleting body text", () => {
    const form = { content: { stem: "stale", segments: [{ type: "text", text: "old" }] } };
    const segments = [{ type: "code", code: "int x;" }, { type: "text", option_key: "A", text: "yes" }];
    expect(replaceQuestionSegments(form, segments).content?.stem).toBe("stale");
  });

  it("synchronizes or clears a legacy stem that duplicates code", () => {
    const form = { content: { stem: "old code", segments: [{ type: "code", code: "old code" }] } };
    expect(replaceQuestionSegments(form, [{ type: "code", code: "new code" }]).content?.stem)
      .toBe("new code");
    expect(replaceQuestionSegments(form, []).content?.stem).toBe("");
  });

  it("keeps the legacy stem when no explicit text segments ever existed", () => {
    const next = replaceQuestionSegments({ content: { stem: "legacy stem" } }, [{ type: "code" }]);
    expect(next.content?.stem).toBe("legacy stem");
  });

  it.each([
    [[], 0],
    [[{ type: "text", text: "stem" }, { type: "image", url: "image" }], 1],
    [[{ type: "table" }, { type: "text", text: "stem" }], 0],
    [[{ type: "text", text: "stem" }, { type: "newline" }], 2],
    [[{ type: "code", code: "first" }, { type: "image" }, { type: "code", code: "last" },
      { type: "table" }], 3],
  ] as const)("inserts code at the existing boundary for %s", (segments, position) => {
    const form: QuestionEditRequest = { answer: "B", content: { stem: "stem", segments } };
    const before = structuredClone(form);
    const next = addQuestionCodeSegment(form);
    const expected: Record<string, unknown>[] = [...segments];
    expected.splice(position, 0, { type: "code", code: "", language: "" });
    expect(next.content?.segments).toEqual(expected);
    expect(next.answer).toBe("B");
    expect(next.content?.render_mode).toBe("segments");
    expect(form).toEqual(before);
  });

  it("filters invalid segment entries before adding a code block", () => {
    const next = addQuestionCodeSegment({ content: {
      stem: "stem", segments: [null, 1, [], { type: "text", text: "stem" }],
    } });
    expect(next.content?.segments).toEqual([
      { type: "text", text: "stem" }, { type: "code", code: "", language: "" },
    ]);
  });

  it.each(["caption", "language"] as const)(
    "clears an optional %s field while retaining alt and imported metadata", (field) => {
      const segment = { type: "code", code: "int x;", caption: "title", language: "c",
        alt: "accessibility", region_id: "region" };
      expect(updateCodeSegmentField(segment, field, "new")).toEqual({ ...segment, [field]: "new" });
      const next = updateCodeSegmentField(segment, field, "");
      expect(Object.hasOwn(next, field)).toBe(false);
      expect(next.alt).toBe("accessibility");
      expect(next.region_id).toBe("region");
      expect(segment[field]).toBe(field === "caption" ? "title" : "c");
    },
  );

  it("sets canonical code, removes duplicate text, and permits an empty draft", () => {
    const segment = { type: "code", text: "legacy", caption: "title", language: "c" };
    expect(updateCodeSegmentField(segment, "code", "")).toEqual({
      type: "code", code: "", caption: "title", language: "c",
    });
    expect(updateCodeSegmentField(segment, "code", "new")).toEqual({
      type: "code", code: "new", caption: "title", language: "c",
    });
    expect(segment.text).toBe("legacy");
  });
});
