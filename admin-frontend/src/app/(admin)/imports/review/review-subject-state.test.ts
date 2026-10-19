import { describe, expect, it } from "vitest";
import { getLeafSubjectOptions } from "./review-subject-state";

describe("import review subject options", () => {
  it("prefers explicit is_leaf metadata", () => {
    const options = [
      { id: 1, is_leaf: false, path: "1" },
      { id: 2, is_leaf: true, parent_id: 1, path: "1/2" },
    ];
    expect(getLeafSubjectOptions(options)).toEqual([options[1]]);
  });

  it("falls back from parent ids to ancestor paths and then all options", () => {
    expect(getLeafSubjectOptions([
      { id: 1, parent_id: null },
      { id: 2, parent_id: 1 },
      { id: 3, parent_id: 2 },
    ]).map((subject) => subject.id)).toEqual([3]);
    expect(getLeafSubjectOptions([
      { id: 10, path: "10" },
      { id: 11, path: "10 / 11" },
      { id: 12, path: "10/11/12" },
    ]).map((subject) => subject.id)).toEqual([12]);
    const noMetadata = [{ id: 20 }, { id: 21 }];
    expect(getLeafSubjectOptions(noMetadata)).toEqual(noMetadata);
    expect(getLeafSubjectOptions([])).toEqual([]);
  });
});
