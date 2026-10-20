import { readFileSync } from "node:fs";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const modules = [
  {
    path: "./hooks/use-review-action-mutation.ts",
    imports: ["react", "@tanstack/react-query", "../review-action-requests"],
  },
  {
    path: "./hooks/use-review-update-mutation.ts",
    imports: ["@tanstack/react-query", "@/lib/api/types", "../review-save-request"],
  },
  {
    path: "./hooks/use-review-answer-mutations.ts",
    imports: ["@tanstack/react-query", "@/lib/api/types"],
  },
  {
    path: "./hooks/use-review-complete-mutation.ts",
    imports: ["@tanstack/react-query", "@/lib/api/types"],
  },
  {
    path: "./hooks/use-review-batch-answer-mutations.ts",
    imports: ["@tanstack/react-query", "@/lib/api/types"],
  },
  {
    path: "./hooks/use-review-image-answer-mutations.ts",
    imports: ["@tanstack/react-query", "@/lib/api/types"],
  },
  {
    path: "./review-save-request.ts",
    imports: [
      "@/lib/api/types",
      "./components/multi-blank-choice-utils",
      "./review-edit-state",
    ],
  },
  {
    path: "./components/batch-answer-results.tsx",
    imports: ["lucide-react", "@/components/ui/button", "@/lib/api/types"],
  },
  {
    path: "./components/image-answer-results.tsx",
    imports: ["lucide-react", "@/components/ui/button", "@/lib/api/types"],
  },
  {
    path: "./review-answer-selection.ts",
    imports: ["@/lib/question-types"],
  },
  {
    path: "./components/review-answer-editor.tsx",
    imports: ["@/components/ui/input", "../review-edit-state", "../review-answer-selection"],
  },
  {
    path: "./hooks/use-review-segment-drag.ts",
    imports: ["react", "@/lib/segment-utils"],
  },
  {
    path: "./components/review-visual-segment-editor.tsx",
    imports: ["react", "lucide-react", "@/lib/segment-utils", "../hooks/use-review-segment-drag"],
  },
];

function violations(source: string, allowed: string[]) {
  const file = ts.createSourceFile("review-action.tsx", source, ts.ScriptTarget.Latest, true);
  const result: string[] = [];
  function walk(node: ts.Node) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      if (!allowed.includes(node.moduleSpecifier.text)) result.push(node.moduleSpecifier.text);
    }
    if (ts.isCallExpression(node) &&
      ["fetch", "window.fetch", "globalThis.fetch"].includes(node.expression.getText(file))) {
      result.push(node.expression.getText(file));
    }
    ts.forEachChild(node, walk);
  }
  walk(file);
  return result;
}

describe("review action feature boundaries", () => {
  it.each(modules)("keeps $path inside its feature dependencies and size budget", (module) => {
    const source = readFileSync(new URL(module.path, import.meta.url), "utf8");
    expect(violations(source, module.imports)).toEqual([]);
    expect(source.trimEnd().split("\n").length).toBeLessThanOrEqual(300);
    const file = ts.createSourceFile(module.path, source, ts.ScriptTarget.Latest, true);
    function walk(node: ts.Node) {
      if (ts.isFunctionDeclaration(node) || ts.isArrowFunction(node)) {
        const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line;
        const end = file.getLineAndCharacterOfPosition(node.end).line;
        expect(end - start + 1, node.getText(file)).toBeLessThanOrEqual(50);
      }
      ts.forEachChild(node, walk);
    }
    walk(file);
  });

  it("keeps the review page free of inline action mutation ownership", () => {
    const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    expect(source).not.toContain("executeReviewActionRequest");
    expect(source).not.toContain("batchIdempotencyKeysRef");
    expect(source).not.toContain("buildMultiBlankSavePayload");
    expect(source).not.toContain('answer_status: "manual_verified"');
    expect(source).not.toContain("/answers/preview");
    expect(source).not.toContain("/answers/apply");
    expect(source).not.toContain("/answers/image/preview");
    expect(source).not.toContain("/answers/image/apply");
  });
});
