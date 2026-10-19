import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import type { ImportQuestionItem } from "@/lib/api/types";
import {
  editStateFromItem,
  isMultiBlankChoice,
  parseOptionsToEditable,
  textFromImport,
} from "./review-edit-state";

const modulePath = fileURLToPath(new URL("./review-edit-state.ts", import.meta.url));
const moduleSource = readFileSync(modulePath, "utf8");

function dependencyViolations(source: string): string[] {
  const file = ts.createSourceFile(modulePath, source, ts.ScriptTarget.Latest, true);
  const violations: string[] = [];
  function walk(node: ts.Node) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      if (![
        "@/lib/api/types",
        "@/lib/question-types",
        "./components/multi-blank-choice-utils",
      ].includes(node.moduleSpecifier.text)) {
        violations.push(node.moduleSpecifier.text);
      }
    }
    if (ts.isCallExpression(node) &&
      ["fetch", "window.fetch", "globalThis.fetch"].includes(node.expression.getText(file))) {
      violations.push(node.expression.getText(file));
    }
    ts.forEachChild(node, walk);
  }
  walk(file);
  return violations;
}

const baseItem = {
  id: 1,
  batch_id: "batch",
  source_type: "pdf",
  status: "pending",
  ai_generated: false,
  ai_answer_flag: false,
  risk_flags: [],
  risk_level: "low",
  risk_reasons: [],
  created_at: "",
  updated_at: "",
} satisfies ImportQuestionItem;

describe("import review edit state", () => {
  it("resolves stem and option values through the established legacy field order", () => {
    const item = {
      ...baseItem,
      parsed_content: { stem: "", text: "stem from text" },
      raw_data: { stem: "raw stem", options: ["raw A"] },
      parsed_options: ["parsed A", { label: "B", content: "parsed B" }],
    } as unknown as ImportQuestionItem;
    expect(textFromImport(item)).toBe("");
    expect(parseOptionsToEditable(item)).toEqual([
      { key: "A", text: "parsed A" },
      { key: "B", text: "parsed B" },
    ]);
  });

  it("supports rich option objects and object-shaped option maps", () => {
    expect(parseOptionsToEditable({
      ...baseItem,
      parsed_options: {
        A: { text: "image choice", segments: [{ type: "image", url: "/a.png" }] },
        B: "plain choice",
        C: 3,
        D: { text: null },
      },
    })).toEqual([
      { key: "A", text: "image choice", segments: [{ type: "image", url: "/a.png" }] },
      { key: "B", text: "plain choice" },
      { key: "C", text: "3" },
      { key: "D", text: "[object Object]", segments: undefined },
    ]);
  });

  it("uses parsed content blank groups for multi-blank options and answers", () => {
    const item = {
      ...baseItem,
      question_type: "multi_blank_choice",
      parsed_answer: "①:B;②:A",
      parsed_content: {
        blank_option_groups: [
          { id: "①", options: [{ key: "A", text: "same" }, { key: "B", text: "other" }] },
          { id: "②", options: [{ key: "A", text: "same" }, { key: "B", text: "other" }] },
        ],
      },
    } as unknown as ImportQuestionItem;
    const state = editStateFromItem(item);
    expect(state.multiBlank).toMatchObject({
      answerMap: { "①": "B", "②": "A" },
      usesSharedOptions: true,
      sharedOptions: [{ key: "A", text: "same" }, { key: "B", text: "other" }],
    });
    expect(state.options).toHaveLength(4);
  });

  it("keeps the historical empty-group fallback and reports invalid source data", () => {
    const state = editStateFromItem({
      ...baseItem,
      question_type: "multi_blank_multiple_choice",
      parsed_content: { blank_option_groups: [{ id: "①", options: [{ key: "A", text: "only one" }] }] },
    } as unknown as ImportQuestionItem);
    expect(state.multiBlank).toMatchObject({
      groups: [],
      answerMap: {},
      usesSharedOptions: false,
      sharedOptions: [],
      dedupErrors: ["parsed_content 中存在 blank_option_groups 但数据无效，请检查数据完整性"],
    });
    expect(isMultiBlankChoice("multi_blank_multiple_choice")).toBe(true);
    expect(isMultiBlankChoice("single_choice")).toBe(false);
  });

  it("keeps the editor adapter independent from page, network, and browser modules", () => {
    expect(dependencyViolations(moduleSource)).toEqual([]);
    const file = ts.createSourceFile(modulePath, moduleSource, ts.ScriptTarget.Latest, true);
    function walk(node: ts.Node) {
      if (ts.isFunctionDeclaration(node) || ts.isArrowFunction(node)) {
        const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line;
        const end = file.getLineAndCharacterOfPosition(node.end).line;
        expect(end - start + 1, node.getText(file)).toBeLessThanOrEqual(50);
      }
      ts.forEachChild(node, walk);
    }
    walk(file);
    expect(moduleSource.trimEnd().split("\n").length).toBeLessThanOrEqual(300);
  });
});
