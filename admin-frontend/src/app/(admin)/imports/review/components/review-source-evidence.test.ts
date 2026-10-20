import { Children, createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewSourceEvidence } from "./review-source-evidence";

function render(raw_data?: Record<string, unknown>, parsed_content?: Record<string, unknown>) {
  return renderToStaticMarkup(createElement(ReviewSourceEvidence, { raw_data, parsed_content }));
}

function controls(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  return Children.toArray(node).flatMap((child) => {
    if (!isValidElement<Record<string, unknown>>(child)) return [];
    if (typeof child.type === "function") {
      return controls((child.type as (props: unknown) => ReactNode)(child.props));
    }
    const children = controls(child.props.children as ReactNode);
    return typeof child.type === "string" ? [child, ...children] : children;
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("review source evidence", () => {
  it("keeps raw text priority and truthy non-string JSON fallback", () => {
    expect(render()).toContain("暂无 OCR 原文");
    expect(render({})).not.toContain("暂无 OCR 原文");
    for (const raw of [
      { raw_text: "<raw>", ocr_text: "ignored" },
      { raw_text: "", ocr_text: "<raw>", text: "ignored" },
      { raw_text: 0, ocr_text: "", text: "<raw>", stem: "ignored" },
      { stem: "<raw>" },
    ]) {
      const html = render(raw);
      expect(html).toContain("&lt;raw&gt;");
      expect(html).not.toContain("ignored");
    }
    const fallback = render({ raw_text: { value: 1 }, ocr_text: "ignored" });
    expect(fallback).toContain("&quot;raw_text&quot;");
    expect(fallback).toContain("ignored");
  });

  it("shows full-page warnings only for literal true and keeps snapshot opening deferred", () => {
    const open = vi.fn();
    vi.stubGlobal("window", { open });
    for (const fullPage of [false, "true", 1]) {
      expect(render({}, { source_snapshot_url: "/snapshot.png", source_snapshot_full_page: fullPage }))
        .not.toContain("仅供审核使用");
    }
    const data = { source_snapshot_url: "/snapshot.png", source_snapshot_full_page: true };
    const html = render({}, data);
    expect(html).toContain("整页");
    expect(html).toContain("仅供审核使用，不会作为普通题图发布。");
    expect(open).not.toHaveBeenCalled();
    const image = controls(createElement(ReviewSourceEvidence, { parsed_content: data }))
      .find((element) => element.props.alt === "原题快照")!;
    (image.props.onClick as () => void)();
    expect(open).toHaveBeenCalledExactlyOnceWith("/snapshot.png", "_blank");
    expect(render({}, { source_snapshot_url: "" })).not.toContain("原题快照");
  });

  it("retains region-image precedence, page fallback and bbox-only rendering", () => {
    const region = { image_url: "/region.png", page_image_url: "/page.png", bbox: [1, 2, 3, 4] };
    const primary = render({}, { source_region: region, source_page: 3 });
    expect(primary).toContain('src="/region.png"');
    expect(primary).not.toContain('src="/page.png"');
    expect(primary).toContain("第 3 页");
    const page = render({}, { source_region: { ...region, image_url: "" } });
    expect(page).toContain('alt="原页截图"');
    expect(page).toContain('src="/page.png"');
    const bbox = render({}, { source_region: { bbox: [1, 2] } });
    expect(bbox).toContain("无原图对照");
    expect(bbox).toContain("bbox=[1,2]");
    expect(render({}, { source_page: 0 })).not.toContain("原图对照");
    expect(render({}, { source_region: {}, source_page: 0 })).toContain("无原图对照");
  });
});
