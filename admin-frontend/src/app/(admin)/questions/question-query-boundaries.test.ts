import { readFileSync } from "node:fs";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const modules = [
  {
    path: "./question-option-editing.ts",
    imports: ["@/lib/api/types", "@/lib/question-options", "./question-content-editing"],
  },
  {
    path: "./components/question-option-editor.tsx",
    imports: [
      "lucide-react", "@/components/ui/button",
      "@/components/questions/question-image-field", "@/components/questions/quick-add-options",
      "../question-option-editing", "@/lib/question-options", "@/lib/question-types",
      "@/lib/api/types", "react", "../hooks/use-question-immediate-mutations",
    ],
  },
  {
    path: "./question-editor-events.ts",
    imports: [],
  },
  {
    path: "./hooks/use-question-editor.ts",
    imports: [
      "react", "@/lib/api/types", "../question-edit-draft", "../question-edit-patch",
      "../question-editor-events",
    ],
  },
  {
    path: "./question-version-comparison.ts",
    imports: ["@/lib/api/types", "@/lib/question-options", "@/lib/question-types"],
  },
  {
    path: "./components/question-difficulty-badge.tsx",
    imports: ["lucide-react"],
  },
  {
    path: "./components/question-type-badge.tsx",
    imports: ["lucide-react", "@/lib/question-types"],
  },
  {
    path: "./components/question-custom-checkbox.tsx",
    imports: ["lucide-react"],
  },
  {
    path: "./components/question-secondary-info.tsx",
    imports: ["@/lib/api/types"],
  },
  {
    path: "./components/question-answer-display.tsx",
    imports: ["@/components/ui/math-formula", "@/lib/question-options", "../question-display-helpers"],
  },
  {
    path: "./components/question-version-value.tsx",
    imports: [
      "@/components/ui/math-formula", "@/components/question-content-renderer",
      "@/components/question-options", "@/components/questions/question-analysis",
      "@/components/questions/question-knowledge-points-editor",
      "@/lib/question-options", "@/lib/api/types", "../question-content-editing",
      "../question-version-comparison", "./question-difficulty-badge",
    ],
  },
  {
    path: "./components/question-version-diff.tsx",
    imports: ["../question-version-comparison", "./question-version-value"],
  },
  {
    path: "./components/question-version-comparison.tsx",
    imports: ["lucide-react", "../question-version-comparison", "./question-version-diff"],
  },
  {
    path: "./question-segment-editing.ts",
    imports: ["@/lib/api/types", "./question-content-editing"],
  },
  {
    path: "./components/question-code-editor.tsx",
    imports: [
      "lucide-react", "@/components/ui/button",
      "../question-content-editing", "../question-segment-editing",
    ],
  },
  {
    path: "./components/question-table-editors.tsx",
    imports: [
      "@/components/structured-table-editor", "@/lib/structured-table",
      "../question-content-editing",
    ],
  },
  {
    path: "./question-edit-draft.ts",
    imports: ["@/lib/api/types", "@/lib/question-options", "./question-content-editing"],
  },
  {
    path: "./question-edit-patch.ts",
    imports: ["@/lib/api/types", "@/lib/question-options", "./question-content-editing"],
  },
  {
    path: "./question-queries.ts",
    imports: ["@tanstack/react-query", "./question-api"],
  },
  {
    path: "./hooks/use-question-queries.ts",
    imports: ["@tanstack/react-query", "../question-api", "../question-queries"],
  },
  {
    path: "./hooks/use-question-update.ts",
    imports: [
      "@tanstack/react-query", "@/lib/api/types", "../question-api",
      "../question-edit-patch", "../question-queries",
    ],
  },
  {
    path: "./hooks/use-question-delete.ts",
    imports: ["react", "@tanstack/react-query", "../question-api", "../question-queries"],
  },
  {
    path: "./hooks/use-question-immediate-mutations.ts",
    imports: [
      "react", "@tanstack/react-query", "@/lib/api/types", "../question-api",
      "../question-content-editing", "../question-edit-draft",
      "../question-edit-patch", "../question-immediate-owner", "../question-queries",
    ],
  },
  {
    path: "./question-immediate-owner.ts",
    imports: [],
  },
  {
    path: "./question-display-helpers.ts",
    imports: ["@/lib/asset-url", "@/lib/question-types", "./question-content-editing"],
  },
  {
    path: "./question-filter-persistence.ts",
    imports: ["./question-list-state"],
  },
  {
    path: "./question-export-payload.ts",
    imports: ["./question-api", "./question-list-state"],
  },
  {
    path: "./question-version-labels.ts",
    imports: ["@/components/questions/question-version-picker", "@/lib/api/types"],
  },
  {
    path: "./question-query-params.ts",
    imports: ["./question-api", "./question-list-state"],
  },
];

function violations(source: string, allowed: string[]) {
  const file = ts.createSourceFile("query.tsx", source, ts.ScriptTarget.Latest, true);
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

describe("question query feature boundaries", () => {
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

  it.each(modules)("detects reverse imports and request bypasses for $path", (module) => {
    expect(violations('import Page from "./page";', module.imports)).toEqual(["./page"]);
    expect(violations('fetch("/questions");', module.imports)).toEqual(["fetch"]);
    expect(violations(
      'const View = () => <button onClick={() => fetch("/questions")} />;',
      module.imports,
    )).toEqual(["fetch"]);
    expect(violations('import Store from "@/lib/auth/auth-store";', module.imports))
      .toEqual(["@/lib/auth/auth-store"]);
  });

  it("keeps direct read providers and inline query ownership out of the page", () => {
    const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const file = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const forbidden = new Set([
      "useQuery", "fetchQuestions", "fetchQuestionDetail",
      "fetchQuestionVersions", "fetchQuestionVersionDetail", "useMutation",
      "deleteQuestion", "deleteQuestionBatch", "updateQuestion",
    ]);
    const calls: string[] = [];
    function walk(node: ts.Node) {
      if (ts.isCallExpression(node) && forbidden.has(node.expression.getText(file))) {
        calls.push(node.expression.getText(file));
      }
      ts.forEachChild(node, walk);
    }
    walk(file);
    expect(calls).toEqual([]);
  });
});
