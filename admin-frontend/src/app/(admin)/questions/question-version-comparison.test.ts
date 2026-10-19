import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { QuestionVersionComparison } from "./components/question-version-comparison";
import { QuestionVersionDiff } from "./components/question-version-diff";
import { QuestionVersionValue } from "./components/question-version-value";
import {
  questionVersionFields, versionValueText, type QuestionSnapshot,
} from "./question-version-comparison";

const snapshot: QuestionSnapshot = {
  content: { stem: "a stem" }, answer: "A", difficulty: 2, options: { A: "option" },
};
const props = {
  enabled: true, questionType: "single_choice", left: snapshot, right: snapshot,
  leftTitle: "当前版本", rightTitle: "v1", loading: false, pendingLabel: null,
};

describe("question version field projection", () => {
  it.each([
    [undefined, "—"], [null, "—"], ["", "—"], [false, "false"],
    [0, "0"], ["0", "0"], [[], "[]"], [{ a: 1 }, '{\n  "a": 1\n}'],
  ])("keeps the existing serialized comparison for %j", (value, expected) => {
    expect(versionValueText(value)).toBe(expected);
  });

  it("projects all fields in display order without mutating snapshots", () => {
    const before = structuredClone(snapshot);
    const fields = questionVersionFields("single_choice", snapshot, snapshot);
    expect(fields.map((field) => field.label)).toEqual(["题干", "选项", "答案", "解析", "难度", "知识点"]);
    expect(fields[0].leftValue).toBe(snapshot.content);
    expect(fields[1].rightValue).toBe(snapshot.options);
    expect(fields[3].leftValue).toBe(null);
    expect(fields[5].rightValue).toBe(null);
    expect(snapshot).toEqual(before);
  });

  it.each(["multi_blank_choice", "multi_blank_multiple_choice"])(
    "selects both historical option groups using current type %s", (type) => {
      const left = { ...snapshot, content: {
        blank_option_groups: [{ id: "1", options: { A: "left" } }],
      } };
      const right = { ...snapshot, content: {
        blank_groups: [{ id: "2", options: { B: "right" } }],
      } };
      const field = questionVersionFields(type, left, right)[1];
      expect(field.leftValue).toEqual(left.content.blank_option_groups);
      expect(field.rightValue).toEqual(right.content.blank_groups);
    },
  );
});

describe("question version comparison display", () => {
  it("renders nothing before selection and the skeleton while initial data is loading", () => {
    expect(renderToStaticMarkup(createElement(QuestionVersionComparison, {
      ...props, enabled: false,
    }))).toBe("");
    const html = renderToStaticMarkup(createElement(QuestionVersionComparison, {
      ...props, right: undefined, loading: true,
    }));
    expect(html).toContain("animate-pulse");
    expect(html).not.toContain("查看原始版本数据");
  });

  it("retains displayed snapshots and their labels while a new version is fetching", () => {
    const html = renderToStaticMarkup(createElement(QuestionVersionComparison, {
      ...props, loading: true, pendingLabel: "v2",
    }));
    expect(html).toContain("正在切换到 v2");
    expect(html).toContain("opacity-60");
    expect(html).toContain("&quot;v1&quot;");
    expect(html).toContain("查看原始版本数据");
    expect(html).not.toContain("animate-pulse");
  });

  it("uses single emphasized content for unchanged stems and two labeled columns for changes", () => {
    const same = renderToStaticMarkup(createElement(QuestionVersionDiff, {
      label: "题干", leftValue: snapshot.content, rightValue: snapshot.content,
      leftTitle: "left", rightTitle: "right",
    }));
    expect(same).toContain("无变更");
    expect(same).toContain("text-sm leading-7");
    expect(same).not.toContain("md:grid-cols-2");
    const changed = renderToStaticMarkup(createElement(QuestionVersionDiff, {
      label: "答案", leftValue: "A", rightValue: "B", leftTitle: "left", rightTitle: "right",
    }));
    expect(changed).toContain("有变更");
    expect(changed).toContain("md:grid-cols-2");
    expect(changed).toContain("left");
    expect(changed).toContain("right");
  });

  it("preserves serialized equality including empty sentinels and object key ordering", () => {
    const diff = (leftValue: unknown, rightValue: unknown) =>
      renderToStaticMarkup(createElement(QuestionVersionDiff, {
        label: "other", leftValue, rightValue, leftTitle: "left", rightTitle: "right",
      }));
    expect(diff(null, "")).toContain("无变更");
    expect(diff(0, "0")).toContain("无变更");
    expect(diff({ a: 1, b: 2 }, { b: 2, a: 1 })).toContain("有变更");
  });

  it.each([
    ["选项", null, "—"], ["选项", { A: "choice" }, "choice"],
    ["答案", "", "—"], ["解析", { text: "explanation" }, "explanation"],
    ["难度", "invalid", "—"], ["难度", 3, "中等"],
    ["知识点", ["point"], "point"], ["unknown", { key: "value" }, "value"],
  ])("renders %s values through existing specialized components", (label, value, text) => {
    expect(renderToStaticMarkup(createElement(QuestionVersionValue, { label, value }))).toContain(text);
  });
});
