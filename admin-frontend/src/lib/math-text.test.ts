import { describe, expect, it } from "vitest";
import { tokenizeMathText } from "./math-text";

describe("tokenizeMathText raw set notation", () => {
  it("keeps graph edge sets with Chinese separators as verbatim text", () => {
    const source = "【2015统考真题】设有向图G=(V,E),顶点集V=V0,V1,V2,V3，边集E={<v0,V1>，<v0,V2>，<v0,V3>}。若从顶点V开始遍历。";
    const segments = tokenizeMathText(source);

    expect(segments.some((segment) =>
      segment.type === "text" && segment.value.includes("E={<v0,V1>，<v0,V2>，<v0,V3>}"),
    )).toBe(true);
    expect(segments.some((segment) =>
      segment.type === "math" && /[{}]/.test(segment.value),
    )).toBe(false);
  });

  it("keeps an OCR-damaged unclosed edge set out of KaTeX", () => {
    const source = "边集 E={<v0,V1>，<v0,V2>，<v0,V3>。若从顶点V开始遍历。";
    const segments = tokenizeMathText(source);
    const rawSet = segments.find((segment) => segment.value.includes("E={<v0,V1>"));

    expect(rawSet?.type).toBe("text");
    expect(rawSet?.value).toContain("E={<v0,V1>，<v0,V2>，<v0,V3>");
  });

  it("still renders normal LaTeX expressions as math", () => {
    const segments = tokenizeMathText(String.raw`函数 y=\\frac{1}{2}x^2 的图像`);

    expect(segments.some((segment) =>
      segment.type === "math" && segment.value.includes("\\frac{1}{2}"),
    )).toBe(true);
  });
});
