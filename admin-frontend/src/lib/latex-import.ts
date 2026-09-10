export type LatexImportIssueSeverity = "error" | "warning" | "info";

export type LatexImportIssue = {
  id: string;
  severity: LatexImportIssueSeverity;
  line: number | null;
  title: string;
  detail: string;
};

export type LatexImportInspection = {
  formulaCount: number;
  inlineCount: number;
  blockCount: number;
  alternateDelimiterCount: number;
  unicodeMathCount: number;
  bareCommandCount: number;
  codeFenceCount: number;
  issues: LatexImportIssue[];
  errorCount: number;
  warningCount: number;
};

type MathRange = {
  start: number;
  end: number;
  bodyStart: number;
  bodyEnd: number;
  kind: "inline" | "block";
  alternate: boolean;
};

const UNICODE_MATH_RE = /[⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉√∑∏∫∞≤≥≠≈⇒⇔→←∂∇∈∉∪∩±×÷αβγδεζηθλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ]/g;
const BARE_LATEX_COMMAND_RE = /\\(?:frac|sqrt|sum|prod|int|lim|alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|phi|omega|infty|partial|nabla|leq|geq|neq|approx|times|cdot|to|Rightarrow|begin|end)\b/g;

function isEscaped(text: string, index: number): boolean {
  let slashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && text[cursor] === "\\"; cursor -= 1) slashCount += 1;
  return slashCount % 2 === 1;
}

function lineAt(text: string, index: number): number {
  let line = 1;
  for (let cursor = 0; cursor < index; cursor += 1) {
    if (text[cursor] === "\n") line += 1;
  }
  return line;
}

function blankPreservingNewlines(value: string): string {
  return value.replace(/[^\n]/g, " ");
}

function maskFencedCode(source: string): { text: string; fenceCount: number; unclosedFenceLine: number | null } {
  const chars = source.split("");
  let cursor = 0;
  let fenceCount = 0;
  let unclosedFenceLine: number | null = null;

  while (cursor < source.length) {
    const start = source.indexOf("```", cursor);
    if (start < 0) break;
    fenceCount += 1;
    const end = source.indexOf("```", start + 3);
    if (end < 0) {
      unclosedFenceLine = lineAt(source, start);
      const masked = blankPreservingNewlines(source.slice(start));
      for (let i = start; i < source.length; i += 1) chars[i] = masked[i - start];
      break;
    }
    fenceCount += 1;
    const masked = blankPreservingNewlines(source.slice(start, end + 3));
    for (let i = start; i < end + 3; i += 1) chars[i] = masked[i - start];
    cursor = end + 3;
  }

  return { text: chars.join(""), fenceCount, unclosedFenceLine };
}

function findSingleDollarClose(text: string, start: number): number {
  for (let cursor = start; cursor < text.length; cursor += 1) {
    if (text[cursor] === "\n") return -1;
    if (text[cursor] !== "$" || isEscaped(text, cursor)) continue;
    if (text[cursor - 1] === "$" || text[cursor + 1] === "$") continue;
    return cursor;
  }
  return -1;
}

function scanMathRanges(text: string, issues: LatexImportIssue[]): MathRange[] {
  const ranges: MathRange[] = [];
  let cursor = 0;

  while (cursor < text.length) {
    if (text.startsWith("$$", cursor) && !isEscaped(text, cursor)) {
      const close = text.indexOf("$$", cursor + 2);
      if (close < 0) {
        issues.push({
          id: `unclosed-block-dollar-${cursor}`,
          severity: "error",
          line: lineAt(text, cursor),
          title: "块级公式未闭合",
          detail: "检测到 $$ 起始符，但没有对应的结束 $$。",
        });
        cursor += 2;
        continue;
      }
      ranges.push({ start: cursor, end: close + 2, bodyStart: cursor + 2, bodyEnd: close, kind: "block", alternate: false });
      cursor = close + 2;
      continue;
    }

    if (text[cursor] === "$" && !isEscaped(text, cursor) && text[cursor - 1] !== "$" && text[cursor + 1] !== "$") {
      const close = findSingleDollarClose(text, cursor + 1);
      if (close < 0) {
        issues.push({
          id: `unclosed-inline-dollar-${cursor}`,
          severity: "error",
          line: lineAt(text, cursor),
          title: "行内公式未闭合",
          detail: "检测到单个 $ 起始符，但本行没有对应的结束 $。",
        });
        cursor += 1;
        continue;
      }
      ranges.push({ start: cursor, end: close + 1, bodyStart: cursor + 1, bodyEnd: close, kind: "inline", alternate: false });
      cursor = close + 1;
      continue;
    }

    if (text.startsWith("\\(", cursor)) {
      const close = text.indexOf("\\)", cursor + 2);
      if (close < 0) {
        issues.push({
          id: `unclosed-inline-paren-${cursor}`,
          severity: "error",
          line: lineAt(text, cursor),
          title: "兼容行内公式未闭合",
          detail: "检测到 \\(，但没有对应的 \\)。推荐统一使用 $...$。",
        });
        cursor += 2;
        continue;
      }
      ranges.push({ start: cursor, end: close + 2, bodyStart: cursor + 2, bodyEnd: close, kind: "inline", alternate: true });
      cursor = close + 2;
      continue;
    }

    if (text.startsWith("\\[", cursor)) {
      const close = text.indexOf("\\]", cursor + 2);
      if (close < 0) {
        issues.push({
          id: `unclosed-block-bracket-${cursor}`,
          severity: "error",
          line: lineAt(text, cursor),
          title: "兼容块级公式未闭合",
          detail: "检测到 \\[，但没有对应的 \\]。推荐统一使用 $$...$$。",
        });
        cursor += 2;
        continue;
      }
      ranges.push({ start: cursor, end: close + 2, bodyStart: cursor + 2, bodyEnd: close, kind: "block", alternate: true });
      cursor = close + 2;
      continue;
    }

    cursor += 1;
  }

  return ranges;
}

function inspectFormulaBody(source: string, range: MathRange, issues: LatexImportIssue[]) {
  const body = source.slice(range.bodyStart, range.bodyEnd);
  const stack: number[] = [];

  for (let offset = 0; offset < body.length; offset += 1) {
    const char = body[offset];
    if ((char === "{" || char === "}") && isEscaped(body, offset)) continue;
    if (char === "{") {
      stack.push(offset);
    } else if (char === "}") {
      if (stack.length === 0) {
        issues.push({
          id: `extra-brace-${range.start}-${offset}`,
          severity: "error",
          line: lineAt(source, range.bodyStart + offset),
          title: "公式花括号不平衡",
          detail: "检测到多余的 }，请检查 \\frac、\\sqrt、上下标等命令参数。",
        });
        break;
      }
      stack.pop();
    }
  }

  if (stack.length > 0) {
    issues.push({
      id: `missing-brace-${range.start}`,
      severity: "error",
      line: lineAt(source, range.bodyStart + stack[stack.length - 1]),
      title: "公式花括号未闭合",
      detail: "检测到 { 没有对应的 }，请补全 LaTeX 命令参数。",
    });
  }

  const envStack: Array<{ name: string; index: number }> = [];
  const envRe = /\\(begin|end)\{([^{}]+)\}/g;
  let match: RegExpExecArray | null;
  while ((match = envRe.exec(body)) !== null) {
    const [, kind, name] = match;
    if (kind === "begin") {
      envStack.push({ name, index: match.index });
      continue;
    }
    const last = envStack[envStack.length - 1];
    if (!last || last.name !== name) {
      issues.push({
        id: `env-mismatch-${range.start}-${match.index}`,
        severity: "error",
        line: lineAt(source, range.bodyStart + match.index),
        title: "LaTeX 环境不匹配",
        detail: `检测到 \\end{${name}} 没有对应的 \\begin{${name}}。`,
      });
    } else {
      envStack.pop();
    }
  }
  if (envStack.length > 0) {
    const last = envStack[envStack.length - 1];
    issues.push({
      id: `env-unclosed-${range.start}-${last.index}`,
      severity: "error",
      line: lineAt(source, range.bodyStart + last.index),
      title: "LaTeX 环境未闭合",
      detail: `\\begin{${last.name}} 缺少对应的 \\end{${last.name}}。`,
    });
  }
}

function maskRanges(text: string, ranges: MathRange[]): string {
  const chars = text.split("");
  for (const range of ranges) {
    const masked = blankPreservingNewlines(text.slice(range.start, range.end));
    for (let index = range.start; index < range.end; index += 1) chars[index] = masked[index - range.start];
  }
  return chars.join("");
}

export function inspectLatexImportText(source: string): LatexImportInspection {
  if (!source) {
    return {
      formulaCount: 0,
      inlineCount: 0,
      blockCount: 0,
      alternateDelimiterCount: 0,
      unicodeMathCount: 0,
      bareCommandCount: 0,
      codeFenceCount: 0,
      issues: [],
      errorCount: 0,
      warningCount: 0,
    };
  }

  const normalized = source.replace(/\r\n?/g, "\n");
  const issues: LatexImportIssue[] = [];
  const codeMasked = maskFencedCode(normalized);
  if (codeMasked.unclosedFenceLine !== null) {
    issues.push({
      id: "unclosed-code-fence",
      severity: "error",
      line: codeMasked.unclosedFenceLine,
      title: "代码围栏未闭合",
      detail: "检测到 ``` 起始围栏但缺少结束围栏。代码建议完整放入围栏，避免公式规则误处理代码符号。",
    });
  }

  const ranges = scanMathRanges(codeMasked.text, issues);
  ranges.forEach((range) => inspectFormulaBody(codeMasked.text, range, issues));

  const outsideMath = maskRanges(codeMasked.text, ranges);
  const unicodeMatches = Array.from(outsideMath.matchAll(UNICODE_MATH_RE));
  if (unicodeMatches.length > 0) {
    const first = unicodeMatches[0];
    issues.push({
      id: "unicode-math",
      severity: "warning",
      line: first.index === undefined ? null : lineAt(normalized, first.index),
      title: "发现 Unicode 数学符号",
      detail: "为保证 OCR、LLM 与 KaTeX 一致，建议使用标准 LaTeX，例如 x^2、\\sqrt{x}、\\sum、\\int、\\pi。",
    });
  }

  const bareCommandMatches = Array.from(outsideMath.matchAll(BARE_LATEX_COMMAND_RE));
  if (bareCommandMatches.length > 0) {
    const first = bareCommandMatches[0];
    issues.push({
      id: "bare-latex-command",
      severity: "warning",
      line: first.index === undefined ? null : lineAt(normalized, first.index),
      title: "LaTeX 命令位于定界符之外",
      detail: "建议把数学命令包在 $...$ 或 $$...$$ 中，避免正文与公式边界不明确。",
    });
  }

  const alternateDelimiterCount = ranges.filter((range) => range.alternate).length;
  if (alternateDelimiterCount > 0) {
    const first = ranges.find((range) => range.alternate);
    issues.push({
      id: "alternate-delimiters",
      severity: "info",
      line: first ? lineAt(normalized, first.start) : null,
      title: "检测到兼容定界符",
      detail: "\\(...\\) 与 \\[...\\] 可以导入，但标准格式建议分别使用 $...$ 与 $$...$$；可一键标准化。",
    });
  }

  const errorCount = issues.filter((issue) => issue.severity === "error").length;
  const warningCount = issues.filter((issue) => issue.severity === "warning").length;

  return {
    formulaCount: ranges.length,
    inlineCount: ranges.filter((range) => range.kind === "inline").length,
    blockCount: ranges.filter((range) => range.kind === "block").length,
    alternateDelimiterCount,
    unicodeMathCount: unicodeMatches.length,
    bareCommandCount: bareCommandMatches.length,
    codeFenceCount: Math.floor(codeMasked.fenceCount / 2),
    issues,
    errorCount,
    warningCount,
  };
}

function normalizeOutsideCode(value: string): string {
  let text = value;
  text = text.replace(/\\\(\$/g, "\\(");
  text = text.replace(/\$\\\)/g, "\\)");
  text = text.replace(/\\\[\$\$/g, "\\[");
  text = text.replace(/\$\$\\\]/g, "\\]");
  text = text.replace(/\\\(([\s\S]*?)\\\)/g, (_match, body: string) => `$${body}$`);
  text = text.replace(/\\\[([\s\S]*?)\\\]/g, (_match, body: string) => `$$${body}$$`);
  return text;
}

export function normalizeLatexImportDelimiters(source: string): string {
  if (!source) return source;
  const parts = source.split("```");
  return parts.map((part, index) => (index % 2 === 1 ? part : normalizeOutsideCode(part))).join("```");
}
