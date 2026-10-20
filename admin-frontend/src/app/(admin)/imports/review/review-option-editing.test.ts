import { describe, expect, it } from "vitest";
import { removeReviewOptionSegment, updateReviewOptionText } from "./review-option-editing";

describe("review option editing", () => {
  it("updates only text while retaining segment and extension metadata", () => {
    const segments = [{ type: "image", url: "/a.png", asset_hash: "hash" }];
    const options = [{ key: "A", text: "old", segments, extra: 7 }, { key: "B", text: "b" }];
    const next = updateReviewOptionText(options, 0, "new");
    expect(next[0]).toEqual({ ...options[0], text: "new" });
    expect(next[0].segments).toBe(segments);
    expect(next[1]).toBe(options[1]);
    expect(options[0].text).toBe("old");
  });

  it("removes by original index and writes undefined only after the last segment is removed", () => {
    const text = { type: "text", text: "hidden" };
    const image = { type: "image", url: "/a.png" };
    const options = [{ key: "A", text: "old", segments: [text, image], extra: 7 }];
    const next = removeReviewOptionSegment(options, 0, 1);
    expect(next[0]).toEqual({ ...options[0], segments: [text] });
    expect(next[0].segments![0]).toBe(text);
    expect(removeReviewOptionSegment(next, 0, 0)[0].segments).toBeUndefined();
    expect(options[0].segments).toEqual([text, image]);
    expect(removeReviewOptionSegment([{ key: "B", text: "" }], 0, 0)[0]).toEqual({
      key: "B", text: "", segments: undefined,
    });
  });
});
