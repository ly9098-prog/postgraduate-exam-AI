import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const path = fileURLToPath(new URL("./question-api.ts", import.meta.url));
const source = readFileSync(path, "utf8");
const allowedImports = new Set(["@/lib/api/client", "@/lib/api/types"]);

function dependencyViolations(code: string): string[] {
  const file = ts.createSourceFile(path, code, ts.ScriptTarget.Latest, true);
  const violations: string[] = [];
  const walk = (node: ts.Node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const name = node.moduleSpecifier.text;
      if (!allowedImports.has(name)) violations.push(name);
    }
    if (ts.isCallExpression(node)) {
      const target = node.expression.getText(file);
      if (["fetch", "window.fetch", "globalThis.fetch"].includes(target)) {
        violations.push(target);
      }
    }
    ts.forEachChild(node, walk);
  };
  walk(file);
  return violations;
}

describe("question API boundary", () => {
  it("uses the existing API client without importing UI, auth or query state", () => {
    expect(dependencyViolations(source)).toEqual([]);
  });

  it("detects a reverse dependency on the page", () => {
    expect(dependencyViolations('import Page from "./page";')).toEqual(["./page"]);
  });

  it("detects a raw fetch bypass of authentication and tracing", () => {
    expect(dependencyViolations('fetch("/questions");')).toEqual(["fetch"]);
  });

  it("keeps new business files and functions within the size budget", () => {
    expect(source.trimEnd().split("\n").length).toBeLessThanOrEqual(300);
    const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
    for (const node of file.statements) {
      if (!ts.isFunctionDeclaration(node)) continue;
      const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line;
      const end = file.getLineAndCharacterOfPosition(node.end).line;
      expect(end - start + 1, node.name?.text).toBeLessThanOrEqual(50);
    }
  });
});
