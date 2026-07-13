/**
 * Formula text normalisation for admin-end conditions / error_tips fields.
 *
 * Converts non-standard Chinese math notation into standard LaTeX so that
 * the mini-program and admin frontend can render it without guessing.
 *
 * Idempotent: normalizeFormulaText(x) === normalizeFormulaText(normalizeFormulaText(x))
 * Stable: try/catch wraps the whole pipeline; on error returns original + console.warn
 */

/* ── Regretion-safe patterns ── */

// Patterns that must NEVER be treated as math
const DATE_RE = /^\d{4}\s*[/\-年]\s*\d{1,2}\s*[/\-月]\s*\d{1,2}[日]?$/;
const VERSION_RE = /^v\d+\.\d+(?:\.\d+)?$/;
const PLAIN_NUMBER_RE = /^\d+(?:\.\d+)?$/;
const DOLLAR_AMOUNT_RE = /^\$\d+(?:\.\d{2})?$/;

/* ── Chinese math terms ── */

function preprocessChineseTerms(s: string): string {
  // x**趋于**number/symbol   (NOT "趋于" in purely Chinese context)
  s = s.replace(/([A-Za-z)\]}]\s*|\b)趋于\s*(无穷|[0-9A-Za-z∞(])/g, '$1→$2');
  // x**->**number/symbol/infinity    (with optional spaces)
  s = s.replace(/([A-Za-z0-9)])\s*->\s*(infinity|无穷|[0-9A-Za-z∞(])/gi, '$1→$2');
  // x**=>**y
  s = s.replace(/([A-Za-z0-9)])\s*=>\s*([A-Za-z0-9(])/g, '$1⇒$2');
  // singular word "infinity" at end of a math-like run
  s = s.replace(/\binfinity\b/gi, '∞');
  // standalone "无穷" when preceded by math context
  s = s.replace(/([→∞A-Za-z0-9)\]}]\s*)无穷/g, '$1∞');
  return s;
}

/* ── Delimiter protection ── */

// Regex to match ALL four kinds of math delimiters
const ALL_DELIM_RE = /\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\]|\$\$([\s\S]*?)\$\$|\$([^$\n]+?)\$/g;

type ProtectedBlock = { key: string; wrapped: string };

function protectOrNormalizeDelimiters(source: string): { text: string; blocks: ProtectedBlock[] } {
  const blocks: ProtectedBlock[] = [];
  let counter = 0;

  const text = source.replace(ALL_DELIM_RE, (_match, group1, group2, group3, group4) => {
    let inner: string;
    let open: string, close: string;

    if (group1 !== undefined) {
      inner = group1; open = '\\('; close = '\\)';
    } else if (group2 !== undefined) {
      inner = group2; open = '\\['; close = '\\]';
    } else if (group3 !== undefined) {
      inner = group3; open = '$$'; close = '$$';
    } else {
      inner = group4; open = '$'; close = '$';
    }

    // Normalise inner content if it still contains non-standard notation
    const normalised = normalizePureMath(inner);

    // Re-wrap with the ORIGINAL delimiter characters (not the raw match)
    // Normalise: raw → non-backslashed delimiter + normalised + closing
    const delimOpen = open === '\\(' ? '\\(' : open === '\\[' ? '\\[' : open;
    const delimClose = close === '\\)' ? '\\)' : close === '\\]' ? '\\]' : close;
    const wrapped = delimOpen + normalised + delimClose;

    const key = 'PROTECTED_' + (counter++) + '';
    blocks.push({ key, wrapped });
    return key;
  });

  return { text, blocks };
}

function restoreDelimiters(s: string, blocks: ProtectedBlock[]): string {
  for (const { key, wrapped } of blocks) {
    // We need to escape backslashes for the replacement string
    // since JS replace treats $ specially. Use split-join instead.
    s = s.split(key).join(wrapped);
  }
  return s;
}

function maybeStripOuterParens(s: string): string {
  // Only consider expressions wrapped entirely in one pair of outer parentheses.
  if (!s.startsWith('(') || !s.endsWith(')')) return s;

  // Check that the opening paren at index 0 closes only at the last position.
  let depth = 0;
  for (let i = 0; i < s.length - 1; i++) {
    if (s[i] === '(') depth++;
    else if (s[i] === ')') depth--;
    if (depth === 0) return s; // closes too early — not the outermost pair
  }

  // Only strip when the expression contains a structured fraction.
  // Bare parentheses around "a + b" are harmless but unnecessary around
  // "1 + \frac{1}{x}" once the fraction renders vertically.
  if (!s.includes('\\frac')) return s;

  return s.slice(1, -1).trim();
}

/* ── Pure math normalizer (no wrapping) ── */

function normalizePureMath(source: string): string {
  let s = source.trim();
  if (!s) return source;

  // Limit pattern: lim(x→0) → \lim_{x\to 0}
  s = s.replace(/lim\s*\(([^()]+)\)/g, (_m, arg: string) => {
    const inner = arg
      .replace(/→/g, '\\to ')
      .replace(/\s+$/g, '')
      .trim();
    return '\\lim_{' + inner + '}';
  });

  // Simple numeric fraction: number/letter or letter/number
  s = s.replace(/(\d+)\s*\/\s*([A-Za-z0-9∞π{}]+)/g, '\\frac{$1}{$2}');
  s = s.replace(/([A-Za-z0-9∞π)}])\s*\/\s*(\d+)/g, '\\frac{$1}{$2}');

  // Bracketless fraction: function-args / expr
  // Match patterns like "sin x/x", "tan 2x/y", "x/sin x"
  const FUNC_NAMES = 'sin|cos|tan|cot|sec|csc|ln|log|lg|det|exp|max|min';
  // numerator = function + args, denominator = simple expr
  s = s.replace(
    new RegExp(
      '(' + FUNC_NAMES + ')\\s+([A-Za-z0-9∞π]+)\\s*/\\s*([A-Za-z0-9∞π{}]+)',
      'g'
    ),
    '\\frac{\\$1 $2}{$3}'
  );
  // denominator = function + args, numerator = simple expr
  s = s.replace(
    new RegExp(
      '([A-Za-z0-9∞π)]+)\\s*/\\s*(' + FUNC_NAMES + ')\\s+([A-Za-z0-9∞π]+)',
      'g'
    ),
    '\\frac{$1}{\\$2 $3}'
  );

  // Parenthesized fraction: (expr)/(expr)
  s = s.replace(/\(([^()]+)\)\s*\/\s*\(([^()]+)\)/g, '\\frac{$1}{$2}');
  // Mixed fraction: (expr)/simple or simple/(expr)
  s = s.replace(/\(([^()]+)\)\s*\/\s*([A-Za-z0-9∞π{}]+)/g, '\\frac{$1}{$2}');
  s = s.replace(/([A-Za-z0-9∞π)}]+)\s*\/\s*\(([^()]+)\)/g, '\\frac{$1}{$2}');

  // Superscript: ^(expr) → ^{expr} with optional fraction inside
  s = s.replace(/\^\(([^()]+)\)/g, (_m, inner: string) => {
    const normalized = inner.replace(/\s*\/\s*/g, '}{');
    if (normalized !== inner) {
      // contains a slash → make a fraction
      return '^{\\frac{' + normalized + '}}';
    }
    return '^{' + inner.trim() + '}';
  });
  // ^digit → ^{digit}
  s = s.replace(/\^(\d+)/g, '^{$1}');

  // Unicode math symbols → LaTeX commands
  s = s.replace(/→/g, '\\to ');
  s = s.replace(/⇒/g, '\\Rightarrow ');
  s = s.replace(/∞/g, '\\infty ');
  s = s.replace(/≤/g, '\\le ');
  s = s.replace(/≥/g, '\\ge ');
  s = s.replace(/≠/g, '\\ne ');
  s = s.replace(/≈/g, '\\approx ');
  s = s.replace(/∑/g, '\\sum ');

  // Strip outer parentheses when the entire expression is wrapped in parens
  // and contains a structured fraction (e.g. /(1 + \/frac{1}{x})/ → /1 + \/frac{1}{x}/).
  // In prose, people wrap isolated expressions in parens for clarity, but once
  // converted to LaTeX the parens visually duplicate the natural grouping.
  s = maybeStripOuterParens(s);

  // Function name normalisation — word boundary, not preceded by backslash
  const funcNames = [
    'lim', 'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
    'arcsin', 'arccos', 'arctan',
    'ln', 'lg', 'log', 'det', 'exp', 'max', 'min',
  ];
  for (const name of funcNames) {
    const regex = new RegExp('(?<!\\\\)\\b' + name + '\\b', 'g');
    s = s.replace(regex, '\\' + name);
  }

  // Collapse multiple spaces
  s = s.replace(/[ \t]+/g, ' ').trim();

  return s;
}

/* ── Math-like detection ── */

function isMathLike(segment: string): boolean {
  const s = segment.trim();
  if (!s) return false;

  // Skip protected placeholder blocks — they contain \x07 bell characters
  if (s.indexOf('\x07') !== -1) return false;

  // Anti-regression: pure numbers, dates, versions, dollar amounts
  if (PLAIN_NUMBER_RE.test(s)) return false;
  if (DATE_RE.test(s)) return false;
  if (VERSION_RE.test(s)) return false;
  if (DOLLAR_AMOUNT_RE.test(s)) return false;

  // Must contain at least one math indicator
  if (/\\/.test(s)) return true; // already has LaTeX commands

  // Math function keywords
  if (/\b(lim|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|ln|lg|log|det|exp|max|min)\b/i.test(s)) return true;

  // Unicode math symbols
  if (/[→∞≤≥≠≈∑⇒]/.test(s)) return true;

  // Superscript
  if (/\^[\d(]/.test(s)) return true;

  // Fraction (slash between expressions)
  if (/\([^()]+\)\s*\//.test(s) && /\/\s*\(/.test(s)) return true;

  // Bracketless fraction pattern: func x / y
  if (new RegExp('\\b(sin|cos|tan|cot|sec|csc|ln|log|lg|det|exp)\\s+[A-Za-z0-9∞π]+\\s*/\\s*', 'i').test(s)) return true;
  if (new RegExp('/\\s*\\b(sin|cos|tan|cot|sec|csc|ln|log|lg|det|exp)\\s+', 'i').test(s)) return true;

  // Equals sign with adjacent identifier
  if (/[A-Za-z0-9)]\s*=\s*/.test(s) || /\s*=\s*[A-Za-z0-9(]/.test(s)) return true;

  // Contains operators (+, -, *, /) between expressions, not just at ends
  if (/[A-Za-z0-9)][+\-*/][A-Za-z0-9(]/.test(s)) return true;

  return false;
}

/* ── Segment math runs and process each ── */

// Characters that form a potential math run (ASCII + specific Unicode math chars)
// Deliberately excludes CJK characters so Chinese prose acts as a natural delimiter.
const MATH_RUN_RE = /[A-Za-z0-9\\(){}\[\]_^+\-*\/=<>∞→≈≠≤≥∑√·,\. \t$\x07]+/g;

// Check whether a formula is "complex" enough to warrant \displaystyle
function needsDisplaystyle(s: string): boolean {
  return /\\frac|\\lim|\\sum|\\prod|\\int/.test(s);
}

function processSegments(source: string): string {
  const result: string[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = MATH_RUN_RE.exec(source)) !== null) {
    // Non-run text before this segment
    if (match.index > lastIndex) {
      result.push(source.slice(lastIndex, match.index));
    }

    const run = match[0];
    const leading = (run.match(/^[\s,\.]*/) || [''])[0];
    const trailing = (run.match(/[\s,\.]*$/) || [''])[0];
    const core = run.slice(leading.length, run.length - trailing.length);

    result.push(leading);

    if (isMathLike(core)) {
      let normalized = normalizePureMath(core);

      // Add \displaystyle for complex formulas
      if (needsDisplaystyle(normalized) && !normalized.startsWith('\\displaystyle')) {
        normalized = '\\displaystyle ' + normalized;
      }

      result.push('\\(' + normalized + '\\)');
    } else {
      // Plain text — leave as-is (it's already ASCII run that isn't math)
      result.push(core);
    }

    result.push(trailing);
    lastIndex = match.index + run.length;
  }

  // Trailing non-run text
  if (lastIndex < source.length) {
    result.push(source.slice(lastIndex));
  }

  return result.join('');
}

/* ── Public API ── */

/**
 * Normalise raw formula text to standard LaTeX.
 *
 * - Wraps detected math segments in \(...\)
 * - Preserves existing \(...\) / \[...\] / $$...$$ / $...$ content (normalises inside if needed)
 * - Handles Chinese math terms: 趋于→→, 无穷→∞, ->→→, infinity→∞
 * - Supports bracketless fractions: sin x/x → \frac{\sin x}{x}
 * - Idempotent: calling twice yields the same result
 *
 * Returns the original value for null/undefined/empty inputs.
 * On error, returns the original text with a console.warn.
 */
export function normalizeFormulaText(text: string | null | undefined): string | null | undefined {
  // Null / undefined / empty guard
  if (text == null) return text;
  const trimmed = text.trim();
  if (!trimmed) return text;

  try {
    // Step 0: Pre-process Chinese math terms (趋于, 无穷, ->, infinity)
    let s = preprocessChineseTerms(trimmed);

    // Step 1: Protect/clean existing LaTeX delimiters
    const { text: protectedText, blocks } = protectOrNormalizeDelimiters(s);

    // Step 2-5: Segment, detect, normalise, \displaystyle, wrap
    const processed = processSegments(protectedText);

    // Step 6: Restore protected delimiters
    const restored = restoreDelimiters(processed, blocks);

    return restored;
  } catch (err) {
    console.warn('[formula-normalize] normalizeFormulaText failed, returning original', err);
    return text;
  }
}

/**
 * Batch-normalise multiple fields.
 * Only the fields present in the input object are returned.
 */
export function normalizeFormulaFields(fields: {
  conditions?: string;
  errorTips?: string;
}): { conditions?: string; errorTips?: string } {
  const result: { conditions?: string; errorTips?: string } = {};
  if ('conditions' in fields) result.conditions = normalizeFormulaText(fields.conditions) ?? undefined;
  if ('errorTips' in fields) result.errorTips = normalizeFormulaText(fields.errorTips) ?? undefined;
  return result;
}
