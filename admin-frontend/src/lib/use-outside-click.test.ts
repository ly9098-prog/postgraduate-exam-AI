import { describe, expect, it } from "vitest";
import { useOutsideClick } from "./use-outside-click";

describe("useOutsideClick", () => {
  it("is a function with correct arity", () => {
    expect(typeof useOutsideClick).toBe("function");
    expect(useOutsideClick.length).toBe(3);
  });
});
