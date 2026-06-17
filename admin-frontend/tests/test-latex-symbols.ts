/**
 * Unit tests for admin-frontend/src/lib/latex-symbols.ts
 * Run: npx tsx test-latex-symbols.ts
 */
import { applyLatexSymbols, unescapeFunctionNames, LATEX_SYMBOLS } from "../src/lib/latex-symbols";

let passed = 0;
let failed = 0;

function assert(condition: boolean, msg: string) {
  if (condition) { passed++; return; }
  failed++;
  console.error("  FAIL:", msg);
}

function assertEq(actual: string, expected: string, msg: string) {
  if (actual === expected) { passed++; return; }
  failed++;
  console.error("  FAIL:", msg);
  console.error("    expected:", JSON.stringify(expected));
  console.error("    actual:", JSON.stringify(actual));
}

function group(name: string, fn: () => void) {
  console.log("\n" + name);
  fn();
}

group("applyLatexSymbols — basic symbols", () => {
  assertEq(applyLatexSymbols("\\leq"), "≤", "\\leq → ≤");
  assertEq(applyLatexSymbols("\\geq"), "≥", "\\geq → ≥");
  assertEq(applyLatexSymbols("\\neq"), "≠", "\\neq → ≠");
  assertEq(applyLatexSymbols("\\ldots"), "…", "\\ldots → …");
  assertEq(applyLatexSymbols("\\to"), "→", "\\to → →");
});

group("applyLatexSymbols — overlapping keys", () => {
  assertEq(applyLatexSymbols("\\ge"), "≥", "\\ge → ≥");
  assertEq(applyLatexSymbols("\\geq"), "≥", "\\geq → ≥ (not ge+q)");
  assertEq(applyLatexSymbols("\\le"), "≤", "\\le → ≤");
  assertEq(applyLatexSymbols("\\leq"), "≤", "\\leq → ≤ (not le+q)");
});

group("applyLatexSymbols — multi-backslash", () => {
  assertEq(applyLatexSymbols("\\\\leq"), "≤", "\\\\leq → ≤");
});

group("applyLatexSymbols — Greek", () => {
  assertEq(applyLatexSymbols("\\alpha"), "α", "\\alpha → α");
  assertEq(applyLatexSymbols("\\beta"), "β", "\\beta → β");
  assertEq(applyLatexSymbols("\\infty"), "∞", "\\infty → ∞");
  assertEq(applyLatexSymbols("\\Delta"), "Δ", "\\Delta → Δ");
  assertEq(applyLatexSymbols("\\varepsilon"), "ε", "\\varepsilon → ε");
});

group("applyLatexSymbols — relations", () => {
  assertEq(applyLatexSymbols("\\approx"), "≈", "\\approx → ≈");
  assertEq(applyLatexSymbols("\\equiv"), "≡", "\\equiv → ≡");
  assertEq(applyLatexSymbols("\\sim"), "∼", "\\sim → ∼");
});

group("applyLatexSymbols — arrows", () => {
  assertEq(applyLatexSymbols("\\Rightarrow"), "⇒", "\\Rightarrow → ⇒");
  assertEq(applyLatexSymbols("\\rightarrow"), "→", "\\rightarrow → →");
  assertEq(applyLatexSymbols("\\Leftrightarrow"), "⇔", "\\Leftrightarrow → ⇔");
});

group("applyLatexSymbols — sets", () => {
  assertEq(applyLatexSymbols("\\in"), "∈", "\\in → ∈");
  assertEq(applyLatexSymbols("\\subseteq"), "⊆", "\\subseteq → ⊆");
  assertEq(applyLatexSymbols("\\cup"), "∪", "\\cup → ∪");
});

group("applyLatexSymbols — compound", () => {
  assertEq(applyLatexSymbols("\\alpha + \\beta = \\gamma"), "α + β = γ", "Greek sum");
  assertEq(applyLatexSymbols("\\lim_{x \\to \\infty}"), "\\lim_{x → ∞}", "limit");
  assertEq(applyLatexSymbols("\\sum_{i=1}^{n}"), "∑_{i=1}^{n}", "sum");
  assertEq(applyLatexSymbols("\\int_{a}^{b}"), "∫_{a}^{b}", "int");
  assertEq(applyLatexSymbols("\\prod_{i=1}^{n}"), "∏_{i=1}^{n}", "prod");
});

group("applyLatexSymbols — no partial match on \\left", () => {
  assertEq(applyLatexSymbols("\\left"), "\\left", "\\left unchanged");
});

group("unescapeFunctionNames", () => {
  assertEq(unescapeFunctionNames("\\log"), "log", "\\log → log");
  assertEq(unescapeFunctionNames("\\sin"), "sin", "\\sin → sin");
  assertEq(unescapeFunctionNames("\\lim"), "lim", "\\lim → lim");
  assertEq(unescapeFunctionNames("\\det"), "det", "\\det → det");
  assertEq(unescapeFunctionNames("\\max"), "max", "\\max → max");
  assertEq(unescapeFunctionNames("\\min"), "min", "\\min → min");
  assertEq(unescapeFunctionNames("\\\\log"), "log", "\\\\log → log");
  assertEq(unescapeFunctionNames("\\alpha"), "\\alpha", "\\alpha unchanged");
  assertEq(unescapeFunctionNames("\\logarithm"), "\\logarithm", "\\logarithm unchanged (\\log not prefix of logarithm)");
  assertEq(unescapeFunctionNames("\\log_{2}"), "log_{2}", "\\log_{2} → log_{2} (still works with _)");
});

group("key set", () => {
  const keys = Object.keys(LATEX_SYMBOLS);
  assert(keys.length >= 85, "at least 85 entries (got " + keys.length + ")");
  assert(keys.indexOf("alpha") >= 0, "alpha exists");
  assert(keys.indexOf("infty") >= 0, "infty exists");
  assert(keys.indexOf("subseteq") >= 0, "subseteq exists");
  assert(keys.indexOf("sum") >= 0, "sum exists");
  assert(keys.indexOf("int") >= 0, "int exists");
  assert(keys.indexOf("prod") >= 0, "prod exists");
});

group("TS/JS sync check", async () => {
  const cp = await import("child_process");
  const path = await import("path");
  const result = cp.spawnSync("node", [
    path.resolve(__dirname, "../../scripts/check-latex-symbols-sync.js"),
  ], { cwd: path.resolve(__dirname, "../.."), encoding: "utf-8" });
  if (result.status !== 0) {
    console.error("  Sync check stderr:", result.stderr.trim());
  }
  assert(result.status === 0, "TS/JS symbol table sync (exit code " + result.status + ")");
});

console.log("\n" + "=".repeat(40));
console.log("Total: " + (passed + failed) + "  Passed: " + passed + "  Failed: " + failed);
if (failed > 0) process.exit(1);
