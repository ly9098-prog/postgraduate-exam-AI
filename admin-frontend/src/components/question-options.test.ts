import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { QuestionOptions } from "@/components/question-options";

describe("QuestionOptions", () => {
  it("never writes option keys through innerHTML", () => {
    const source = readFileSync(join(__dirname, "question-options.tsx"), "utf8");
    expect(source).not.toMatch(/innerHTML|dangerouslySetInnerHTML/);
  });

  it("renders markup-bearing option keys as escaped text", () => {
    const html = renderToStaticMarkup(
      createElement(QuestionOptions, {
        options: [{ key: '<img src=x onerror=alert(1)>', text: "", imageUrl: "/a.png" }],
      }),
    );
    expect(html).not.toContain("<img src=x");
    expect(html).toContain("&lt;img src=x");
  });
});
