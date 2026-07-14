import assert from "node:assert/strict";
import { normalizeLatexExpression, tokenizeMathText } from "../src/lib/math-text";

assert.equal(
  normalizeLatexExpression("(-b/(2a), (4ac-b^2)/(4a))"),
  "(-\\frac{b}{2a}, \\frac{4ac-b^{2}}{4a})",
);

const title = tokenizeMathText("二次函数 y=ax^2+bx+c");
assert.deepEqual(title, [
  { type: "text", value: "二次函数 ", displayMode: false },
  { type: "math", value: "y=ax^{2}+bx+c", displayMode: false },
]);

const range = tokenizeMathText(
  "a>0 时 [\\frac{4ac-b^2}{4a}, +\\infty)；a<0 时 (-\\infty, \\frac{4ac-b^2}{4a}]",
);
assert.equal(range.filter((segment) => segment.type === "math").length, 4);
assert.ok(range.some((segment) => segment.value.includes("\\infty")));

console.log("math-text tests passed");
