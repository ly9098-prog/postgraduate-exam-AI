import { afterEach, describe, expect, it } from "vitest";
import { _resetApiBase, resolveAssetUrl } from "./asset-url";

afterEach(() => {
  delete process.env.NEXT_PUBLIC_API_BASE;
  _resetApiBase();
});

describe("resolveAssetUrl — no API base configured (production)", () => {
  it("returns root-relative asset paths as-is (same-origin)", () => {
    expect(resolveAssetUrl("/static/question-assets/447/a.png")).toBe(
      "/static/question-assets/447/a.png",
    );
  });

  it("passes through absolute https asset URLs", () => {
    expect(
      resolveAssetUrl("https://your-production-domain.example/static/question-assets/447/a.png"),
    ).toBe("https://your-production-domain.example/static/question-assets/447/a.png");
  });

  it("rejects localhost absolute URLs (fail closed)", () => {
    expect(resolveAssetUrl("http://localhost:8000/static/a.png")).toBe("");
    expect(resolveAssetUrl("http://127.0.0.1/x.png")).toBe("");
  });

  it("rejects non-relative ambiguous URLs (fail closed)", () => {
    expect(resolveAssetUrl("relative/no-leading-slash.png")).toBe("");
  });

  it("rejects unsafe schemes", () => {
    expect(resolveAssetUrl("javascript:alert(1)")).toBe("");
    expect(resolveAssetUrl("file:///etc/passwd")).toBe("");
  });

  it("treats empty/null as no asset", () => {
    expect(resolveAssetUrl(null)).toBe("");
    expect(resolveAssetUrl("")).toBe("");
  });
});

describe("resolveAssetUrl — API base configured", () => {
  it("prepends the API base to root-relative paths", () => {
    process.env.NEXT_PUBLIC_API_BASE = "https://api.example.com";
    _resetApiBase();
    expect(resolveAssetUrl("/static/a.png")).toBe(
      "https://api.example.com/static/a.png",
    );
  });
});
