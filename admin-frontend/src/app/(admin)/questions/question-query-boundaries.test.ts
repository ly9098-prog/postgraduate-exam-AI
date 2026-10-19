import { readFileSync } from "node:fs";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const modules = [
  {
    path: "./question-queries.ts",
    imports: ["@tanstack/react-query", "./question-api"],
  },
  {
    path: "./hooks/use-question-queries.ts",
    imports: ["@tanstack/react-query", "../question-api", "../question-queries"],
  },
];

function violations(source: string, allowed: string[]) {
  const file = ts.createSourceFile("query.ts", source, ts.ScriptTarget.Latest, true);
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
    expect(violations('import Store from "@/lib/auth/auth-store";', module.imports))
      .toEqual(["@/lib/auth/auth-store"]);
  });

  it("keeps direct read providers and inline query ownership out of the page", () => {
    const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const file = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const forbidden = new Set([
      "useQuery", "fetchQuestions", "fetchQuestionDetail",
      "fetchQuestionVersions", "fetchQuestionVersionDetail",
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
