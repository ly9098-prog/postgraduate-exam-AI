/**
 * Shared utilities for rendering API text that mixes Chinese prose and math.
 *
 * The backend stores formulas in several forms:
 * - raw math: y=ax^2+bx+c
 * - LaTeX: (-\\infty,+\\infty)
 * - mixed prose: a>0 时 ...；a<0 时 ...
 * - occasionally JSON/double-escaped strings
 *
 * These helpers normalize all of them into KaTeX-ready segments without
 * requiring the backend data to be rewritten.
 */

export type MathTextSegment = {
  type: "text" | "math";
  value: string;
  displayMode: boolean;
};

const EXPLICIT_MATH_RE = /\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$|\$[^$\n]+?\$/g;

// Chinese characters intentionally are not included: they naturally delimit
// a formula from surrounding prose.
const POSSIBLE_MATH_RUN_RE = /[A-Za-z0-9\\()[\]{}_^+\-*\/=<>≤≥≠≈∞→←±×÷′'.,:;|\sαβγδεζηθικλμνξοπρστυφχωψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ∀∃∍∂∇∈∉∋∏∑−√∛∜∫∬∭∮∯∰∥∦∅ℕℤℚℝℂℙℵℏ∠∡∢∘∙∟∣∤∵∴]+/g;

const PURE_NUMBER_RE = /^[+-]?\d+(?:\.\d+)?$/;
const VERSION_RE = /^v?\d+(?:\.\d+){1,3}$/i;
const DATE_RE = /^\d{4}[-/]\d{1,2}[-/]\d{1,2}$/;

/** Decode values that may be JSON-stringified more than once. */
export function decodeApiText(value: unknown): string {
  if (value === null || value === undefined) return "";

  let current: unknown = value;
  for (let i = 0; i < 3 && typeof current === "string"; i += 1) {
    const trimmed = current.trim();
    if (!trimmed) return current;

    // Only attempt JSON parsing when the value visibly looks encoded. This
    // avoids treating ordinary math such as [0,1] as application data.
    const looksEncoded =
      (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
      (trimmed.startsWith("[") && trimmed.endsWith("]") && /["{]/.test(trimmed)) ||
      (trimmed.startsWith("{") && trimmed.endsWith("}"));

    if (!looksEncoded) break;

    try {
      current = JSON.parse(trimmed);
    } catch {
      break;
    }
  }

  let text = typeof current === "string" ? current : JSON.stringify(current);
  if (typeof text !== "string") text = String(current);

  // Legacy records can contain a second escaping layer: \\frac instead of \frac.
  for (let i = 0; i < 2; i += 1) {
    text = text.replace(/\\\\(?=[A-Za-z])/g, "\\");
  }

  return text;
}

/**
 * Detect source-code snippets before the generic math tokenizer sees them.
 *
 * Programming exercises often contain C/C++-style expressions such as
 * `return ((x > 0) ? x * f(x - 1) : 2);`.  The math tokenizer would otherwise
 * classify large ASCII runs containing `>`, `=`, braces, etc. as LaTeX, which
 * can make code render in KaTeX error markup and even appear visually reordered.
 */
export function looksLikeProgrammingCode(value: unknown): boolean {
  const text = decodeApiText(value).trim();
  if (!text) return false;

  const hasStatementPunctuation = /[;{}]/.test(text);
  const hasProgrammingKeyword = new RegExp(
    "\\b(?:auto|bool|break|case|char|class|const|continue|default|do|double|else|enum|" +
    "float|for|if|int|long|main|namespace|private|protected|public|return|short|" +
    "signed|sizeof|static|struct|switch|typedef|union|unsigned|void|while|printf|scanf|cout|cin)\\b",
  ).test(text);
  const hasFunctionBlock = /\b[A-Za-z_]\w*\s*\([^\n{};]*\)\s*\{/.test(text);
  const hasTernaryStatement = /\?[^\n;{}]*:[^\n;{}]*;/.test(text);
  const hasPreprocessorDirective = /^\s*#\s*(?:include|define|if|ifdef|ifndef)\b/m.test(text);

  return (hasProgrammingKeyword && hasStatementPunctuation) ||
    hasFunctionBlock ||
    hasTernaryStatement ||
    hasPreprocessorDirective;
}

export function stripMathDelimiters(value: string): string {
  const text = value.trim();
  const pairs: Array<[string, string]> = [
    ["\\(", "\\)"],
    ["\\[", "\\]"],
    ["$$", "$$"],
    ["$", "$"],
  ];

  for (const [open, close] of pairs) {
    if (text.startsWith(open) && text.endsWith(close)) {
      return text.slice(open.length, text.length - close.length).trim();
    }
  }

  return text;
}

function normalizeFractions(source: string): string {
  let text = source;

  // Run several passes so nested/simple fractions are normalized after an
  // outer replacement, e.g. (-b/(2a), (4ac-b^2)/(4a)).
  for (let i = 0; i < 4; i += 1) {
    const before = text;

    // (numerator)/(denominator)
    text = text.replace(
      /\(([^()]+)\)\s*\/\s*\(([^()]+)\)/g,
      (_match, numerator: string, denominator: string) =>
        `\\frac{${numerator.trim()}}{${denominator.trim()}}`,
    );

    // -b/(2a), x_1/(2a), 4ac/(2a)
    text = text.replace(
      /(-?(?:\\[A-Za-z]+|[A-Za-z0-9]+)(?:_\{[^{}]+\}|_[A-Za-z0-9]+)?(?:\^\{[^{}]+\}|\^[A-Za-z0-9]+)?)\s*\/\s*\(([^()]+)\)/g,
      (_match, numerator: string, denominator: string) =>
        `\\frac{${numerator.trim()}}{${denominator.trim()}}`,
    );

    // (a+b)/c
    text = text.replace(
      /\(([^()]+)\)\s*\/\s*((?:\\[A-Za-z]+|[A-Za-z0-9]+)(?:_\{[^{}]+\}|_[A-Za-z0-9]+)?(?:\^\{[^{}]+\}|\^[A-Za-z0-9]+)?)/g,
      (_match, numerator: string, denominator: string) =>
        `\\frac{${numerator.trim()}}{${denominator.trim()}}`,
    );

    // b/a, c/a, 1/2. Avoid touching slash-based dates because this function
    // is only called after a segment has already been classified as math.
    text = text.replace(
      /(-?(?:\\[A-Za-z]+|[A-Za-z0-9]+)(?:_\{[^{}]+\}|_[A-Za-z0-9]+)?(?:\^\{[^{}]+\}|\^[A-Za-z0-9]+)?)\s*\/\s*((?:\\[A-Za-z]+|[A-Za-z0-9]+)(?:_\{[^{}]+\}|_[A-Za-z0-9]+)?(?:\^\{[^{}]+\}|\^[A-Za-z0-9]+)?)/g,
      (_match, numerator: string, denominator: string) =>
        `\\frac{${numerator.trim()}}{${denominator.trim()}}`,
    );

    if (text === before) break;
  }

  return text;
}

/** Convert a raw expression into canonical KaTeX-compatible LaTeX. */
export function normalizeLatexExpression(value: unknown): string {
  let text = stripMathDelimiters(decodeApiText(value));
  if (!text) return "";

  text = text
    .replace(/−/g, "-")
    .replace(/∞/g, "\\infty ")
    .replace(/≠/g, "\\ne ")
    .replace(/≤/g, "\\le ")
    .replace(/≥/g, "\\ge ")
    .replace(/≈/g, "\\approx ")
    .replace(/→/g, "\\to ")
    .replace(/←/g, "\\leftarrow ")
    .replace(/±/g, "\\pm ")
    .replace(/×/g, "\\times ")
    .replace(/÷/g, "\\div ")
    .replace(/′/g, "'")
    .replace(/(?<!\\)\b(?:infinity|infty)\b/gi, "\\infty ")
    .replace(/\*\*/g, "^");

  // Normalize common unbraced super/subscripts before fraction conversion.
  text = text.replace(/\^([+-]?\d+)/g, "^{$1}");
  text = text.replace(/_([0-9]+)/g, "_{$1}");
  text = text.replace(/\b([A-Za-z])_(min|max)\b/g, (_m, base: string, op: string) => `${base}_{\\${op}}`);
  text = text.replace(/\b([A-Za-z])_([A-Za-z]{2,}[A-Za-z0-9]*)\b/g, "$1_{$2}");

  text = normalizeFractions(text);
  text = text.replace(/\\frac\{-([^{}]+)\}\{([^{}]+)\}/g, "-\\frac{$1}{$2}");

  // Standard function names. The negative lookbehind prevents turning \sin
  // into \\sin when the backend already supplied LaTeX.
  const functions = [
    "arcsin", "arccos", "arctan", "sin", "cos", "tan", "cot", "sec", "csc",
    "ln", "log", "lg", "lim", "exp", "det", "max", "min", "sup", "inf",
  ];
  for (const name of functions) {
    text = text.replace(new RegExp(`(?<!\\\\)\\b${name}\\b`, "g"), `\\${name}`);
  }

  // Unicode Greek / math symbol replacement (after normalizeFractions to avoid false fraction detection)
  text = text
    .replace(/β/g, "\\beta ")
    .replace(/γ/g, "\\gamma ")
    .replace(/δ/g, "\\delta ")
    .replace(/ε/g, "\\varepsilon ")
    .replace(/ζ/g, "\\zeta ")
    .replace(/η/g, "\\eta ")
    .replace(/θ/g, "\\theta ")
    .replace(/ι/g, "\\iota ")
    .replace(/κ/g, "\\kappa ")
    .replace(/λ/g, "\\lambda ")
    .replace(/μ/g, "\\mu ")
    .replace(/ν/g, "\\nu ")
    .replace(/ξ/g, "\\xi ")
    .replace(/ο/g, "o ")
    .replace(/π/g, "\\pi ")
    .replace(/ρ/g, "\\rho ")
    .replace(/σ/g, "\\sigma ")
    .replace(/τ/g, "\\tau ")
    .replace(/υ/g, "\\upsilon ")
    .replace(/φ/g, "\\phi ")
    .replace(/χ/g, "\\chi ")
    .replace(/ψ/g, "\\psi ")
    .replace(/ω/g, "\\omega ")
    .replace(/Α/g, "\\Alpha ")
    .replace(/Β/g, "\\Beta ")
    .replace(/Γ/g, "\\Gamma ")
    .replace(/Δ/g, "\\Delta ")
    .replace(/Ε/g, "\\Epsilon ")
    .replace(/Ζ/g, "\\Zeta ")
    .replace(/Η/g, "\\Eta ")
    .replace(/Θ/g, "\\Theta ")
    .replace(/Ι/g, "\\Iota ")
    .replace(/Κ/g, "\\Kappa ")
    .replace(/Λ/g, "\\Lambda ")
    .replace(/Μ/g, "\\Mu ")
    .replace(/Ν/g, "\\Nu ")
    .replace(/Ξ/g, "\\Xi ")
    .replace(/Ο/g, "O ")
    .replace(/Π/g, "\\Pi ")
    .replace(/Ρ/g, "\\Rho ")
    .replace(/Σ/g, "\\Sigma ")
    .replace(/Τ/g, "\\Tau ")
    .replace(/Υ/g, "\\Upsilon ")
    .replace(/Φ/g, "\\Phi ")
    .replace(/Χ/g, "\\Chi ")
    .replace(/Ψ/g, "\\Psi ")
    .replace(/Ω/g, "\\Omega ")
    .replace(/∀/g, "\\forall ")
    .replace(/∃/g, "\\exists ")
    .replace(/∍/g, "\\ni ")
    .replace(/∂/g, "\\partial ")
    .replace(/∇/g, "\\nabla ")
    .replace(/∈/g, "\\in ")
    .replace(/∉/g, "\\notin ")
    .replace(/∋/g, "\\ni ")
    .replace(/∏/g, "\\prod ")
    .replace(/∑/g, "\\sum ")
    .replace(/−/g, "-")
    .replace(/√/g, "\\sqrt ")
    .replace(/∛/g, "\\sqrt[3] ")
    .replace(/∜/g, "\\sqrt[4] ")
    .replace(/∫/g, "\\int ")
    .replace(/∬/g, "\\iint ")
    .replace(/∭/g, "\\iiint ")
    .replace(/∮/g, "\\oint ")
    .replace(/∞/g, "\\infty ")
    .replace(/∠/g, "\\angle ")
    .replace(/∡/g, "\\measuredangle ")
    .replace(/∢/g, "\\sphericalangle ")
    .replace(/∘/g, "\\circ ")
    .replace(/∙/g, "\\bullet ")
    .replace(/∵/g, "\\because ")
    .replace(/∴/g, "\\therefore ")
    .replace(/∥/g, "\\parallel ")
    .replace(/∦/g, "\\nparallel ")
    .replace(/∅/g, "\\emptyset ")
    .replace(/ℕ/g, "\\mathbb{N}")
    .replace(/ℤ/g, "\\mathbb{Z}")
    .replace(/ℚ/g, "\\mathbb{Q}")
    .replace(/ℝ/g, "\\mathbb{R}")
    .replace(/ℂ/g, "\\mathbb{C}")
    .replace(/ℙ/g, "\\mathbb{P}")
    .replace(/ℵ/g, "\\aleph ")
    .replace(/ℏ/g, "\\hbar ");

  // Improve spacing while preserving command boundaries.
  text = text
    .replace(/[ \t]+/g, " ")
    .replace(/\s*,\s*/g, ", ")
    .trim();

  return text;
}

function looksLikeMath(value: string): boolean {
  const text = value.trim();
  if (!text) return false;
  if (PURE_NUMBER_RE.test(text) || VERSION_RE.test(text) || DATE_RE.test(text)) return false;

  if (/\\[A-Za-z]+/.test(text)) return true;
  if (/[∞≤≥≠≈→←±×÷αβγδεζηθικλμνξοπρστυφχψω∀∃∂∇∈∉∏∑∫∬∭∮√∛∜∠∡∢∘∙∥∅ℕℤℚℝℂℙℵℏ∵∴]/.test(text)) return true;
  if (/[=<>]/.test(text) && /[A-Za-z0-9]/.test(text)) return true;
  if (/[\^_]/.test(text) && /[A-Za-z0-9]/.test(text)) return true;
  if (/\//.test(text) && /[A-Za-z0-9()]/.test(text)) return true;
  if (/[A-Za-z](?:'{1,3})/.test(text)) return true;

  // Variables and monomials that occur between Chinese prose, such as
  // "a 决定..."、"x 轴"、"2a（定号）".
  if (/^[+-]?\d*[A-Za-z](?:[A-Za-z0-9]*)?$/.test(text)) return true;

  // Coordinate pairs / intervals containing algebraic content.
  if (/^[\[(].*[,].*[\])]$/.test(text) && /[A-Za-z\\∞]/.test(text)) return true;

  return false;
}

function splitPlainText(source: string): MathTextSegment[] {
  const segments: MathTextSegment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  POSSIBLE_MATH_RUN_RE.lastIndex = 0;
  while ((match = POSSIBLE_MATH_RUN_RE.exec(source)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: source.slice(lastIndex, match.index), displayMode: false });
    }

    const run = match[0];
    const leading = run.match(/^[\s]+/)?.[0] ?? "";
    const trailing = run.match(/[\s]+$/)?.[0] ?? "";
    const core = run.slice(leading.length, run.length - trailing.length);

    if (leading) segments.push({ type: "text", value: leading, displayMode: false });

    if (core) {
      // Inline source-code fragments (for example `if (...) { for (...) ... }`)
      // can satisfy the generic math heuristics because they contain operators
      // such as `>=`, `<` and `=`. Never feed those runs to KaTeX: incomplete
      // snippets in analysis text commonly contain unmatched braces and would be
      // rendered as red KaTeX parse errors. Keep them as ordinary text instead.
      if (looksLikeProgrammingCode(core)) {
        segments.push({ type: "text", value: core, displayMode: false });
      } else if (looksLikeMath(core)) {
        segments.push({ type: "math", value: normalizeLatexExpression(core), displayMode: false });
      } else {
        segments.push({ type: "text", value: core, displayMode: false });
      }
    }

    if (trailing) segments.push({ type: "text", value: trailing, displayMode: false });
    lastIndex = match.index + run.length;
  }

  if (lastIndex < source.length) {
    segments.push({ type: "text", value: source.slice(lastIndex), displayMode: false });
  }

  return segments;
}

/** Split mixed prose into text and KaTeX-ready math segments. */
export function tokenizeMathText(value: unknown): MathTextSegment[] {
  const source = decodeApiText(value);
  if (!source) return [];

  const segments: MathTextSegment[] = [];
  let lastIndex = 0;

  EXPLICIT_MATH_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = EXPLICIT_MATH_RE.exec(source)) !== null) {
    if (match.index > lastIndex) {
      segments.push(...splitPlainText(source.slice(lastIndex, match.index)));
    }

    const token = match[0];
    segments.push({
      type: "math",
      value: normalizeLatexExpression(token),
      displayMode: token.startsWith("\\[") || token.startsWith("$$"),
    });
    lastIndex = match.index + token.length;
  }

  if (lastIndex < source.length) {
    segments.push(...splitPlainText(source.slice(lastIndex)));
  }

  // Merge adjacent text segments to keep the React tree small.
  return segments.reduce<MathTextSegment[]>((result, segment) => {
    const previous = result[result.length - 1];
    if (previous && previous.type === "text" && segment.type === "text") {
      previous.value += segment.value;
    } else if (segment.value) {
      result.push({ ...segment });
    }
    return result;
  }, []);
}
