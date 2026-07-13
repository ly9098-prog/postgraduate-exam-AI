/**
 * Automated test for formula-normalize.ts
 *
 * Usage:
 *   npx tsx scripts/test-formula-normalize.ts
 *
 * Covers: positive cases, anti-regression, idempotency, null/empty/dollar amounts.
 */

import { normalizeFormulaText } from '../src/lib/formula-normalize';

interface TestCase {
  id: number;
  label: string;
  input: Parameters<typeof normalizeFormulaText>[0];
  expected: string | null | undefined;
}

const tests: TestCase[] = [
  // ── Anti-regression: already-correct LaTeX ──
  {
    id: 1,
    label: 'already-correct LaTeX unchanged',
    input: '\\(\\lim_{x\\to 0}\\frac{\\sin x}{x}=1\\)',
    expected: '\\(\\lim_{x\\to 0}\\frac{\\sin x}{x}=1\\)',
  },

  // ── Anti-regression: dates ──
  { id: 2, label: 'date slash', input: '2026/07/13', expected: '2026/07/13' },
  { id: 3, label: 'date dash', input: '2026-07-13', expected: '2026-07-13' },

  // ── Anti-regression: version ──
  { id: 4, label: 'version', input: 'v1.2.3', expected: 'v1.2.3' },

  // ── Anti-regression: Chinese numbers in prose ──
  {
    id: 5,
    label: 'chinese prose numbers',
    input: '不是0，不是1，共2种情况',
    expected: '不是0，不是1，共2种情况',
  },

  // ── Anti-regression: dollar amounts ──
  { id: 6, label: 'dollar amount standalone', input: '$100', expected: '$100' },
  { id: 7, label: 'dollar amount in text', input: '价格 $20', expected: '价格 $20' },
  { id: 8, label: 'dollar amount USD', input: 'USD $30', expected: 'USD $30' },

  // ── Positive: mixed Chinese + math ──
  {
    id: 9,
    label: 'mixed Chinese + sin x/x',
    input: '当 x→0 时，sin x/x→1',
    expected: '当 \\(x\\to 0\\) 时，\\(\\displaystyle \\frac{\\sin x}{x}\\to 1\\)',
  },

  // ── Positive: limit + displaystyle ──
  {
    id: 10,
    label: 'limit with infinity',
    input: '当 x→∞ 时，(1+1/x)^x→e',
    expected: '当 \\(x\\to \\infty\\) 时，\\(\\displaystyle (1+\\frac{1}{x})^x\\to e\\)',
  },

  // ── Positive: superscript to fraction ──
  {
    id: 11,
    label: 'superscript fraction',
    input: '当 x→0 时，(1+x)^(1/x)→e',
    expected: '当 \\(x\\to 0\\) 时，\\(\\displaystyle (1+x)^{\\frac{1}{x}}\\to e\\)',
  },

  // ── Positive: pure math multi-segment ──
  {
    id: 12,
    label: 'pure math limit+frac',
    input: 'lim(x→0)(sin x)/x = 1',
    expected: '\\(\\displaystyle \\lim_{x\\to 0}\\frac{\\sin x}{x} = 1\\)',
  },

  // ── Positive: 趋于 Chinese → LaTeX ──
  {
    id: 13,
    label: 'chinese quyu',
    input: 'x趋于0 时',
    expected: '\\(x\\to 0\\) 时',
  },

  // ── Positive: -> arrow ──
  {
    id: 14,
    label: 'dash-arrow and quyu-infinity',
    input: 'x -> 0，x趋于无穷',
    expected: '\\(x\\to 0\\)，\\(x\\to \\infty\\)',
  },

  // ── Positive: bracketless fraction ──
  {
    id: 15,
    label: 'bracketless fraction sin x/x',
    input: 'sin x/x',
    expected: '\\(\\displaystyle \\frac{\\sin x}{x}\\)',
  },

  // ── Semi-standard: fix inside existing \(...\) ──
  {
    id: 16,
    label: 'semi-standard inside delimiter',
    input: '\\(lim(x→0)\\)',
    expected: '\\(\\lim_{x\\to 0}\\)',
  },

  // ── Empty / null ──
  { id: 17, label: 'empty string', input: '', expected: '' },
  { id: 18, label: 'null', input: null, expected: null },
  { id: 19, label: 'undefined', input: undefined, expected: undefined },

  // ── More bracketless fraction variants ──
  {
    id: 20,
    label: 'bracketless tan x/x',
    input: 'tan x/x',
    expected: '\\(\\displaystyle \\frac{\\tan x}{x}\\)',
  },
  {
    id: 21,
    label: 'bracketless x/sin x',
    input: 'x/sin x',
    expected: '\\(\\displaystyle \\frac{x}{\\sin x}\\)',
  },

  // ── n→∞ with lim(n→∞) ──
  {
    id: 22,
    label: 'multi-segment with lim and arrow',
    input: '当 n→∞ 时，lim(n→∞)(1+1/n)^n = e',
    expected:
      '当 \\(n\\to \\infty\\) 时，\\(\\displaystyle \\lim_{n\\to \\infty }(1+\\frac{1}{n})^n = e\\)',
  },

  // ── Outer paren stripping ──
  {
    id: 23,
    label: 'outer paren stripping with spaces',
    input: '(1 + 1/x)',
    expected: '\\(\\displaystyle 1 + \\frac{1}{x}\\)',
  },
  {
    id: 24,
    label: 'outer paren stripping no spaces',
    input: '(1+1/x)',
    expected: '\\(\\displaystyle 1+\\frac{1}{x}\\)',
  },

  // ── Full prose segments from task spec ──
  {
    id: 25,
    label: 'full conditions text',
    input: '两个重要极限适用的前提是极限过程分别符合x → 0和x → ∞（或x → 0时(1 + x)^(1/x)）。',
    expected:
      '两个重要极限适用的前提是极限过程分别符合\\(x \\to 0\\)和\\(x \\to \\infty\\)（或\\(x \\to 0\\)时\\(\\displaystyle (1 + x)^{\\frac{1}{x}}\\)）。',
  },
  {
    id: 26,
    label: 'full errorTips text',
    input: '易错：lim(x → 0)(sin x)/x = 1，不是0；lim(x → 0)(sin 2x)/x = 2，不是1。第二个重要极限底数是(1 + 1/x)，不是(1 + x)。',
    expected:
      '易错：\\(\\displaystyle \\lim_{x \\to 0}\\frac{\\sin x}{x} = 1\\)，不是0；\\(\\displaystyle \\lim_{x \\to 0}\\frac{\\sin 2x}{x} = 2\\)，不是1。第二个重要极限底数是\\(\\displaystyle 1 + \\frac{1}{x}\\)，不是(1 + x)。',
  },

  // ── Simple prose expression stays plain (no LaTeX wrapping) ──
  {
    id: 27,
    label: 'simple prose (1 + x) stays plain',
    input: '(1 + x)',
    expected: '(1 + x)',
  },
];

/* ── Idempotency tests are derived from the positive cases above ── */

const idempotentSourceIds = [1, 9, 12, 15, 22, 23, 25, 26];

let passed = 0;
let failed = 0;
const failures: string[] = [];

for (const t of tests) {
  const result = normalizeFormulaText(t.input);

  if (result !== t.expected) {
    failed++;
    failures.push(
      `#${t.id} ${t.label}:\n` +
        `  expected: ${JSON.stringify(t.expected)}\n` +
        `  got:      ${JSON.stringify(result)}`,
    );
  } else {
    passed++;
  }
}

/* ── Idempotency: f(x) === f(f(x)) ── */

for (const id of idempotentSourceIds) {
  const t = tests.find((tc) => tc.id === id)!;
  const once = normalizeFormulaText(t.input);
  const twice = normalizeFormulaText(once);
  if (once !== twice) {
    failed++;
    failures.push(
      `#${id} idempotency FAILED:\n` +
        `  f(x):  ${JSON.stringify(once)}\n` +
        `  f(f): ${JSON.stringify(twice)}`,
    );
  } else {
    passed++;
  }
}

/* ── Report ── */

console.log(`\n  formula-normalize tests: ${passed} passed, ${failed} failed\n`);

if (failures.length > 0) {
  for (const msg of failures) {
    console.log('  FAIL  ' + msg.replace(/\n/g, '\n       ') + '\n');
  }
  process.exit(1);
} else {
  console.log('  All tests passed including idempotency checks.\n');
}
