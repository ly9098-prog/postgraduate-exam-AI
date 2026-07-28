/**
 * Formula reader content normalisation.
 *
 * Goals:
 * 1. Do not delete repeated user content.
 * 2. Treat single newlines in prose like normal browser whitespace.
 * 3. Preserve explicit blank paragraphs.
 * 4. Convert only conservative math runs to $...$ for the KaTeX plugin.
 */

function decodeBasicEntities(value) {
  return String(value == null ? '' : value)
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function stripOuterMathDelimiters(value) {
  var source = String(value == null ? '' : value).trim()
  var changed = true
  while (changed && source) {
    changed = false
    var pairs = [
      ['$$', '$$'],
      ['\\[', '\\]'],
      ['\\(', '\\)'],
      ['$', '$'],
    ]
    for (var i = 0; i < pairs.length; i++) {
      var start = pairs[i][0]
      var end = pairs[i][1]
      if (source.indexOf(start) === 0 && source.lastIndexOf(end) === source.length - end.length && source.length > start.length + end.length) {
        source = source.slice(start.length, source.length - end.length).trim()
        changed = true
        break
      }
    }
  }
  return source
}

var UNICODE_GREEK_LATEX = {
  'α': 'alpha', 'β': 'beta', 'γ': 'gamma', 'δ': 'delta', 'ε': 'epsilon',
  'ζ': 'zeta', 'η': 'eta', 'θ': 'theta', 'ι': 'iota', 'κ': 'kappa',
  'λ': 'lambda', 'μ': 'mu', 'ν': 'nu', 'ξ': 'xi', 'ο': 'omicron',
  'π': 'pi', 'ρ': 'rho', 'σ': 'sigma', 'ς': 'varsigma', 'τ': 'tau',
  'υ': 'upsilon', 'φ': 'phi', 'χ': 'chi', 'ψ': 'psi', 'ω': 'omega',
  'ϵ': 'varepsilon', 'ϑ': 'vartheta', 'ϖ': 'varpi', 'ϱ': 'varrho',
  'ϕ': 'varphi',
  'Γ': 'Gamma', 'Δ': 'Delta', 'Θ': 'Theta', 'Λ': 'Lambda', 'Ξ': 'Xi',
  'Π': 'Pi', 'Σ': 'Sigma', 'Υ': 'Upsilon', 'Φ': 'Phi', 'Ψ': 'Psi',
  'Ω': 'Omega',
}

function replaceUnicodeGreek(value) {
  return String(value == null ? '' : value).replace(/[α-ωΑ-Ωϵϑϖϱϕ]/g, function (symbol) {
    var command = UNICODE_GREEK_LATEX[symbol]
    // Some uppercase Greek glyphs are visually identical to Latin letters and
    // do not have a KaTeX command (for example Α and Β). Keep those as-is.
    return command ? '\\' + command + '{}' : symbol
  })
}

function replaceUnicodeMath(value) {
  return replaceUnicodeGreek(value)
    .replace(/(?:→|->)/g, '\\to ')
    .replace(/(?:∞|\binfinity\b)/gi, '\\infty ')
    .replace(/≤/g, '\\le ')
    .replace(/≥/g, '\\ge ')
    .replace(/≠/g, '\\ne ')
    .replace(/≈/g, '\\approx ')
    .replace(/∑/g, '\\sum ')
}

function normalizeTrendPhrases(value) {
  return String(value == null ? '' : value)
    .replace(/([A-Za-z][A-Za-z0-9_]*)\s*趋于\s*(?:正)?无穷/g, '$1 -> infinity')
    .replace(/([A-Za-z][A-Za-z0-9_]*)\s*趋于\s*([+\-]?\d+(?:\.\d+)?)/g, '$1 -> $2')
}

function trimOuterParentheses(value) {
  var source = String(value == null ? '' : value).trim()
  if (source.length >= 2 && source.charAt(0) === '(' && source.charAt(source.length - 1) === ')') {
    var depth = 0
    var wrapsWholeValue = true
    for (var i = 0; i < source.length; i++) {
      var ch = source.charAt(i)
      if (ch === '(') depth += 1
      else if (ch === ')') depth -= 1
      if (depth === 0 && i < source.length - 1) {
        wrapsWholeValue = false
        break
      }
      if (depth < 0) {
        wrapsWholeValue = false
        break
      }
    }
    if (wrapsWholeValue && depth === 0) return source.slice(1, -1).trim()
  }
  return source
}

function normalizeFractionOperand(value) {
  return normalizeFunctionNames(trimOuterParentheses(value))
    .replace(/[ \t]+/g, ' ')
    .trim()
}

function normalizeExponent(value) {
  var source = String(value == null ? '' : value).trim()
  if (!source || /\\frac\s*\{/.test(source)) return source
  var simple = source.match(/^([A-Za-z0-9]+)\s*\/\s*([A-Za-z0-9]+)$/)
  if (simple) return '\\frac{' + simple[1] + '}{' + simple[2] + '}'
  return source
}

function normalizePowers(value) {
  var source = String(value == null ? '' : value)

  // Admin history contains both ^(1/x) and ^{1/x}. Convert only simple
  // slash exponents; already-correct nested LaTeX such as ^{\frac{1}{x}}
  // is deliberately left untouched.
  source = source.replace(/\^\s*\(\s*([^()]*)\s*\)/g, function (_, exponent) {
    return '^{' + normalizeExponent(exponent) + '}'
  })
  source = source.replace(/\^\s*\{\s*([^{}]*)\s*\}/g, function (match, exponent) {
    if (/\\frac\s*\{/.test(exponent)) return match
    return '^{' + normalizeExponent(exponent) + '}'
  })
  source = source.replace(/\^\s*([+\-]?\d+)(?=$|[^0-9])/g, '^{$1}')
  return source
}

function normalizeFractions(value) {
  var source = String(value == null ? '' : value)
  var functionName = '(?:arcsin|arccos|arctan|sin|cos|tan|cot|sec|csc|ln|log|det|exp)'

  // Parenthesised numerator: (sin x)/x, (x+1)/(x-1), etc. Run this
  // before simple fractions so the numerator remains one semantic unit.
  source = source.replace(/\(\s*([^()]+?)\s*\)\s*\/\s*(\([^()]+\)|[A-Za-z0-9]+)(?=$|[\s,;=+\-*^)\]}])/g, function (_, numerator, denominator) {
    return '\\frac{' + normalizeFractionOperand(numerator) + '}{' + normalizeFractionOperand(denominator) + '}'
  })

  // Function fractions without numerator parentheses: sin x/x, sin 2x/x.
  var functionFraction = new RegExp('((?:\\\\)?' + functionName + '\\s+(?:\\d+\\s*)?[A-Za-z][A-Za-z0-9]*)\\s*\\/\\s*(\\([^()]+\\)|[A-Za-z0-9]+)', 'gi')
  source = source.replace(functionFraction, function (_, numerator, denominator) {
    return '\\frac{' + normalizeFractionOperand(numerator) + '}{' + normalizeFractionOperand(denominator) + '}'
  })

  // Function denominator: x/sin x.
  var functionDenominator = new RegExp('(^|[\\s(=+\\-*,])([A-Za-z0-9]+)\\s*\\/\\s*((?:\\\\)?' + functionName + '\\s+(?:\\d+\\s*)?[A-Za-z][A-Za-z0-9]*)', 'gi')
  source = source.replace(functionDenominator, function (_, prefix, numerator, denominator) {
    return prefix + '\\frac{' + normalizeFractionOperand(numerator) + '}{' + normalizeFractionOperand(denominator) + '}'
  })

  // Conservative atom fractions. This covers 1/x and 1/(1+x) while the
  // isMathRun guards keep dates, URLs and paths out of this conversion path.
  source = source.replace(/(^|[\s(=+\-*,])([A-Za-z0-9]+)\s*\/\s*(\([^()]+\)|[A-Za-z0-9]+)(?=$|[\s,;=+\-*^)\]}])/g, function (_, prefix, numerator, denominator) {
    return prefix + '\\frac{' + normalizeFractionOperand(numerator) + '}{' + normalizeFractionOperand(denominator) + '}'
  })

  return source
}

function normalizeLatexSource(value) {
  var source = decodeBasicEntities(value)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/?(?:p|div|li)[^>]*>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/\r\n?/g, '\n')
    .trim()

  source = normalizeEnvironmentCommands(source)
  source = stripOuterMathDelimiters(source)
    .replace(/^\\begin\{(?:equation\*?|displaymath)\}/, '')
    .replace(/\\end\{(?:equation\*?|displaymath)\}$/, '')
    .trim()

  // Protect LaTeX row breaks before removing display delimiters. Without this,
  // a valid `\\[4pt]` row break is partially consumed as `\[` and leaks the
  // literal text `4pt]` into the formula shown by the mini-program.
  source = protectFormulaRowBreaks(source)

  // Remove editor delimiters without removing escaped currency symbols.
  source = source
    .replace(/\$\$/g, '\n')
    .replace(/\\\[|\\\]/g, '\n')
    .replace(/\\\(|\\\)/g, '')
    .replace(/(^|[^\\])\$/g, '$1')

  // The admin editor preserves explicit top-level line breaks as separate
  // centered rows. Row breaks inside cases/matrix environments remain inside
  // those environments, while a row break after an environment creates a new
  // outer row (for example the “即 …” line below a cases formula).
  source = source.replace(/\n+/g, FORMULA_ROW_BREAK_TOKEN)
  var rows = splitTopLevelFormulaRows(source)

  if (rows.length > 1) {
    var multilineEnvironment = rows.some(function (row) { return /(^|[^\\])&/.test(row) })
      ? 'aligned'
      : 'gathered'
    source = '\\begin{' + multilineEnvironment + '}' + rows.join(' \\\\[7pt] ') + '\\end{' + multilineEnvironment + '}'
  } else {
    source = rows.length ? rows[0] : ''
    source = source.replace(/(?:\s*\\(?:qquad|quad)\s*)+/g, ' \\qquad ')
  }

  source = replaceUnicodeMath(source)
  source = normalizeFunctionNames(source)
    .replace(/[ \t]+/g, ' ')
    .trim()

  source = normalizeDeterminantNotation(source)
  source = wrapCjkTextInMath(source)

  return source
}

function formulaComplexity(source) {
  var latex = String(source || '')
  var commands = (latex.match(/\\[a-zA-Z]+/g) || []).length
  var operators = (latex.match(/[=,+;]|\\(?:qquad|quad|frac|sum|prod|int|lim|sqrt|begin)/g) || []).length
  return latex.replace(/\\[a-zA-Z]+/g, 'M').replace(/[{}_\^\s]/g, '').length + commands * 5 + operators * 7
}

function splitFormulaGroup(value) {
  var source = String(value || '').trim()
  if (!source || /\\begin\s*\{/.test(source)) return []

  var parts = source.split(/\s*\\(?:qquad|quad)\s*/).map(function (part) {
    return part.trim().replace(/[,，;；]+$/, '').trim()
  }).filter(Boolean)

  // Three or more sibling identities are better presented as a responsive
  // group on a phone. Two-part expressions often encode one logical equation,
  // so keep them together unless the editor explicitly creates separate blocks.
  if (parts.length < 3 || parts.length > 6) return []
  for (var i = 0; i < parts.length; i++) {
    if (formulaComplexity(parts[i]) > 108) return []
    if (!/(?:=|<|>|\\(?:approx|sim|le|ge|ne|to)\b)/.test(parts[i])) return []
  }
  return parts
}

function normalizeFunctionNames(value) {
  // Avoid turning an already valid "\\sin" into "\\\\sin".
  return String(value || '').replace(
    /(^|[^\\A-Za-z])(lim|arcsin|arccos|arctan|sin|cos|tan|cot|sec|csc|ln|log|det|exp)(?=[^A-Za-z]|$)/g,
    function (_, prefix, name) { return prefix + '\\' + name },
  )
}

var FORMULA_ROW_BREAK_TOKEN = '\u0007FORMULA_ROW_BREAK\u0007'
var STRUCTURED_ENVIRONMENT_NAME = '(?:aligned|align\\*?|gathered|cases|matrix|pmatrix|bmatrix|vmatrix|array)'

/**
 * Repair legacy environment commands that were saved without braces.
 *
 * Examples:
 *   \\begincases ... \\endcases
 *   \\begin cases ... \\end cases
 *
 * Valid commands such as \\begin{cases} are left untouched.
 */
function normalizeEnvironmentCommands(value) {
  return String(value == null ? '' : value).replace(
    new RegExp('\\\\(begin|end)\\s*(' + STRUCTURED_ENVIRONMENT_NAME + ')(?![A-Za-z])', 'g'),
    function (_, command, environment) {
      return '\\' + command + '{' + environment + '}'
    },
  )
}

function stripOuterGroupingBraces(value) {
  var source = String(value == null ? '' : value).trim()
  var changed = true

  while (changed && source.charAt(0) === '{' && source.charAt(source.length - 1) === '}') {
    changed = false
    var depth = 0
    for (var i = 0; i < source.length; i++) {
      var ch = source.charAt(i)
      if (ch === '\\') {
        i += 1
        continue
      }
      if (ch === '{') depth += 1
      else if (ch === '}') depth -= 1

      if (depth === 0) {
        if (i === source.length - 1) {
          source = source.slice(1, -1).trim()
          changed = true
        }
        break
      }
      if (depth < 0) break
    }
  }

  return source
}

function protectFormulaRowBreaks(value) {
  return String(value == null ? '' : value).replace(/\\\\(?:\s*\[[^\]]*\])?/g, FORMULA_ROW_BREAK_TOKEN)
}

function restoreFormulaRowBreaks(value, withSpacing) {
  var separator = withSpacing ? ' \\\\[6pt] ' : ' \\\\ '
  return String(value == null ? '' : value).split(FORMULA_ROW_BREAK_TOKEN).join(separator)
}

function splitTopLevelFormulaRows(value) {
  var source = String(value == null ? '' : value)
  var rows = ['']
  var environmentDepth = 0
  var environmentPattern = /^\\(begin|end)\{(?:aligned|align\*?|gathered|cases|matrix|pmatrix|bmatrix|vmatrix|array)\}/
  var cursor = 0

  while (cursor < source.length) {
    if (source.indexOf(FORMULA_ROW_BREAK_TOKEN, cursor) === cursor) {
      if (environmentDepth === 0) rows.push('')
      else rows[rows.length - 1] += FORMULA_ROW_BREAK_TOKEN
      cursor += FORMULA_ROW_BREAK_TOKEN.length
      continue
    }

    var environment = source.slice(cursor).match(environmentPattern)
    if (environment) {
      rows[rows.length - 1] += environment[0]
      if (environment[1] === 'begin') environmentDepth += 1
      else environmentDepth = Math.max(0, environmentDepth - 1)
      cursor += environment[0].length
      continue
    }

    rows[rows.length - 1] += source.charAt(cursor)
    cursor += 1
  }

  return rows.map(function (row) {
    return restoreFormulaRowBreaks(row, true).replace(/^[ \t]+|[ \t]+$/g, '')
  }).filter(Boolean)
}

/**
 * Keep Chinese descriptions inside a LaTeX expression in text mode.
 *
 * The admin preview accepts formulas such as
 *   \begin{cases}0,&n 为正奇数\\2I_n,&n 为正偶数\end{cases}
 * as one expression.  The mini-program must do the same instead of splitting
 * the expression at the first Chinese character. Existing \text{...} blocks
 * are temporarily protected so this transform remains idempotent.
 */
function wrapCjkTextInMath(value) {
  var source = String(value == null ? '' : value)
  if (!source || !/[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]/.test(source)) return source

  var protectedText = []
  var commands = ['\\text{', '\\textrm{', '\\textbf{', '\\textit{', '\\mathrm{']
  var result = ''
  var cursor = 0

  while (cursor < source.length) {
    var foundAt = -1
    var foundCommand = ''
    for (var i = 0; i < commands.length; i++) {
      var index = source.indexOf(commands[i], cursor)
      if (index >= 0 && (foundAt < 0 || index < foundAt)) {
        foundAt = index
        foundCommand = commands[i]
      }
    }

    if (foundAt < 0) {
      result += source.slice(cursor)
      break
    }

    result += source.slice(cursor, foundAt)
    var bodyStart = foundAt + foundCommand.length
    var block = scanBalancedBraces(source.slice(bodyStart))
    if (!block) {
      result += foundCommand
      cursor = bodyStart
      continue
    }

    var fullBlock = source.slice(foundAt, bodyStart + block.consumed)
    var token = '\u0007CJKTEXT' + protectedText.length + '\u0007'
    protectedText.push(fullBlock)
    result += token
    cursor = bodyStart + block.consumed
  }

  result = result.replace(/[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]+/g, function (text) {
    return '\\text{' + text + '}'
  })

  return result.replace(/\u0007CJKTEXT(\d+)\u0007/g, function (_, index) {
    return protectedText[Number(index)] || ''
  })
}

/* ── Determinant notation scanner helpers ── */

/**
 * Scan balanced parentheses (handling nesting).
 * source must start with '('.
 * Returns { inner: string, consumed: number } or null.
 */
function scanBalancedParens(source) {
  if (source.charAt(0) !== '(') return null
  var depth = 1
  var pos = 1
  while (pos < source.length && depth > 0) {
    if (source.charAt(pos) === '\\') { pos += 2; continue }
    if (source.charAt(pos) === '(') depth++
    else if (source.charAt(pos) === ')') depth--
    if (depth > 0) pos++
  }
  if (depth !== 0) return null
  return { inner: source.slice(1, pos), consumed: pos + 1 }
}

/**
 * Scan balanced braces { } (handling nesting).
 * The opening { has already been consumed by the caller.
 * Returns { consumed: number } or null if unclosed.
 */
function scanBalancedBraces(source) {
  var depth = 1
  var pos = 0
  while (pos < source.length) {
    if (source.charAt(pos) === '\\') { pos += 2; continue }
    if (source.charAt(pos) === '{') depth++
    else if (source.charAt(pos) === '}') {
      depth--
      if (depth < 0) return null
      if (depth === 0) return { consumed: pos + 1 }
    }
    pos++
  }
  return null
}

/**
 * Scan to the matching \end{envName} considering nesting.
 * source must start with \begin{envName}.
 * Returns { inner: string, endPos: number } or null.
 */
function scanMatchingEnd(source, envName) {
  var beginTag = '\\begin{' + envName + '}'
  var endTag = '\\end{' + envName + '}'
  if (source.indexOf(beginTag) !== 0) return null
  var depth = 1
  var pos = beginTag.length
  while (pos < source.length && depth > 0) {
    if (source.indexOf(beginTag, pos) === pos) { depth++; pos += beginTag.length }
    else if (source.indexOf(endTag, pos) === pos) { depth--; pos += depth >= 0 ? endTag.length : 0 }
    else { pos++ }
  }
  if (depth > 0) return null
  return {
    inner: source.slice(beginTag.length, pos - endTag.length),
    endPos: pos,
  }
}

/**
 * Convert \det and \operatorname{det} notation to \left|...\right|
 * (determinant vertical bars).
 *
 * Applies after normalizeFunctionNames so all variants are already \det.
 * Uses a character scanner instead of naive regex to handle nested parens
 * and avoid false matches inside \text{...}.
 */
function normalizeDeterminantNotation(source) {
  var s = String(source || '')
  var result = ''
  var i = 0

  while (i < s.length) {
    // Skip \text{...} blocks entirely to avoid corrupting prose
    if (s.slice(i).indexOf('\\text{') === 0) {
      var textBlock = scanBalancedBraces(s.slice(i + '\\text{'.length))
      if (textBlock) {
        result += s.slice(i, i + '\\text{'.length + textBlock.consumed)
        i += '\\text{'.length + textBlock.consumed
        continue
      }
    }

    // Detect \det or \operatorname{det}
    var detPattern = s.slice(i).match(/^\\det\b/)
    var operPattern = s.slice(i).match(/^\\operatorname\{det\}/)
    if (!detPattern && !operPattern) {
      result += s.charAt(i)
      i++
      continue
    }

    var matched = (detPattern || operPattern)[0]
    var after = s.slice(i + matched.length)
    var ws = (after.match(/^\s*/) || [''])[0]
    after = after.slice(ws.length)

    // Case 1: \det\begin{pmatrix}...\end{pmatrix} → \begin{vmatrix}...\end{vmatrix}
    if (after.indexOf('\\begin{pmatrix}') === 0) {
      var env = scanMatchingEnd(after, 'pmatrix')
      if (env) {
        result += '\\begin{vmatrix}' + env.inner + '\\end{vmatrix}'
        i += matched.length + ws.length + env.endPos
        continue
      }
    }

    // Case 2: \det(...) with balanced parentheses
    if (after.charAt(0) === '(') {
      var parens = scanBalancedParens(after)
      if (parens) {
        result += '\\left|' + parens.inner + '\\right|'
        i += matched.length + ws.length + parens.consumed
        continue
      }
    }

    // Case 3: \det X where X is a single letter (e.g. \det A, \det Q)
    var symbol = after.match(/^([A-Za-z])/)
    if (symbol) {
      result += '\\left|' + symbol[1] + '\\right|'
      i += matched.length + ws.length + 1
      continue
    }

    // No recognised argument pattern — leave \det as-is
    result += s.charAt(i)
    i++
  }

  return result
}

function normalizeNamedOperators(value) {
  // KaTeX does not expose every textbook operator as a dedicated command.
  // Historical formula data commonly stores `sgn x` as plain text, while
  // newer records may already contain `\operatorname{sgn}`. Convert only the
  // former and leave the latter untouched.
  return String(value || '').replace(
    /(^|[^\\A-Za-z{])(sgn)(?=\s*[A-Za-z0-9([{\\]|\s*$)/gi,
    function (_, prefix, name) { return prefix + '\\operatorname{' + name.toLowerCase() + '}' },
  )
}

/**
 * Regularise leftover dirty-data patterns before sending the formula to KaTeX.
 *
 * This handles common historical data issues without stripping braces that are
 * part of valid LaTeX:
 *  - Unclosed \text{...  →  close with }
 *  - Severely unbalanced braces  →  remove orphaned braces
 *
 * The approach is conservative: balance known commands rather than strip all
 * braces, so valid LaTeX like \frac{1}{2} is never broken.
 */
function sanitizeLatexContent(value) {
  var source = String(value || '')
  if (!source) return source

  // Count opening and closing braces
  var openCount = 0
  var closeCount = 0
  for (var j = 0; j < source.length; j++) {
    if (source.charAt(j) === '{') openCount++
    if (source.charAt(j) === '}') closeCount++
  }

  // If braces are unbalanced, fix them. This prevents KaTeX from choking on
  // e.g. "\text{且换元过程满足公式条件" (missing closing }).
  if (openCount > closeCount) {
    // Close the most likely unclosed \text{ by appending the missing }
    source = source + new Array(openCount - closeCount + 1).join('}')
  } else if (closeCount > openCount) {
    // Remove trailing orphan closes — but be conservative: only strip excess
    // closing braces that appear at the very end of the string, since valid
    // LaTeX uses } before other content (e.g. \frac{1}{2}).
    while (closeCount > openCount && /\}$/.test(source)) {
      source = source.replace(/\}\s*$/, '')
      closeCount--
    }
  }

  return source
}

function normalizeMathRun(value) {
  var source = stripOuterMathDelimiters(String(value || '').trim())
  if (!source) return ''

  source = replaceUnicodeMath(source)
    .replace(/√\s*\(([^)]+)\)/g, '\\sqrt{$1}')
    .replace(/(^|[^\\A-Za-z])lim\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*(?:\\to|→|->)\s*([^)]+)\)/gi, function (_, prefix, variable, target) {
      return prefix + '\\lim_{' + variable + '\\to ' + replaceUnicodeMath(target).trim() + '}'
    })

  // Sanitize common dirty-data patterns before structure transforms, so
  // incomplete \text{... etc. are tolerant rather than producing red errors.
  source = sanitizeLatexContent(source)

  // Structure-sensitive transformations must happen before generic function
  // escaping. Otherwise the reader merely italicises legacy text such as
  // (sin x)/x instead of producing a real KaTeX fraction.
  source = normalizePowers(source)
  source = normalizeFractions(source)
  source = normalizeNamedOperators(source)
  source = normalizeFunctionNames(source)
    .replace(/\s*=\s*/g, '=')
    .replace(/[ \t]+/g, ' ')
    .trim()
  source = normalizeDeterminantNotation(source)
  source = wrapCjkTextInMath(source)
  return source
}

function ensureDisplayStyle(value) {
  var source = String(value || '').trim()
  if (!source || /^\\(?:displaystyle|textstyle|scriptstyle|scriptscriptstyle)\b/.test(source)) return source
  return '\\displaystyle ' + source
}

function isMathRun(value) {
  var source = String(value || '').trim()
  if (!source || /^\d+(?:\.\d+)?$/.test(source)) return false

  // Common prose tokens that contain slashes/dashes must never be promoted to
  // KaTeX. These guards are intentionally evaluated before operator checks.
  if (/^\d{4}[\/-]\d{1,2}[\/-]\d{1,2}$/.test(source)) return false
  if (/^[vV]?\d+(?:\.\d+){1,}$/.test(source)) return false
  if (/^(?:https?:)?\/\//i.test(source) || /^www\./i.test(source)) return false
  if (/^[A-Za-z]:[\\/]/.test(source)) return false
  if (/^(?:\.{0,2}\/|\/)[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)+$/.test(source)) return false
  if (/^\$\s*\d/.test(source) || /^(?:USD|RMB|CNY)\s*\$?\s*\d/i.test(source)) return false

  // Any LaTeX control word is a strong math signal after URLs and filesystem
  // paths have already been protected above. A whitelist caused valid commands
  // such as \operatorname, \lfloor and \rfloor to leak into the UI as source.
  if (/\\[A-Za-z]+/.test(source)) return true
  if (/(?:lim|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|ln|log|det|exp|sgn)\s*\(?/i.test(source)) return true
  if (/[A-Za-z0-9)}\]]\s*(?:=|≠|≈|≤|≥|<|>|→|->|\+|\-|\*|\/|\^|_)/.test(source)) return true
  if (/(?:=|≠|≈|≤|≥|<|>|→|->|\+|\-|\*|\/|\^|_)\s*[A-Za-z0-9({\[]/.test(source)) return true
  return /[A-Za-z].*[∞∑√]/.test(source)
}

function collapseProseWhitespace(value) {
  var source = String(value == null ? '' : value)
    .replace(/\r\n?/g, '\n')
    .replace(/\u00a0/g, ' ')

  var paragraphToken = '\u0007PARAGRAPH\u0007'
  source = source
    .replace(/\n[ \t]*\n+/g, paragraphToken)
    .replace(/[ \t]*\n[ \t]*/g, ' ')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(new RegExp(paragraphToken, 'g'), '<br/><br/>')
  return source
}

function protectPlainTokens(source, store) {
  var pattern = /https?:\/\/[^\s<>"']+|www\.[^\s<>"']+|[A-Za-z]:[\\/][^\s<>"']+|(?:\.{0,2}\/|\/)[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)+|\b\d{4}[\/-]\d{1,2}[\/-]\d{1,2}\b|\b[vV]\d+(?:\.\d+){1,}\b|(?:USD|RMB|CNY)\s*\$?\s*\d+(?:\.\d+)?|\$\s*\d+(?:\.\d+)?/g
  return source.replace(pattern, function (match) {
    var key = '\u0007TEXT' + store.length + '\u0007'
    store.push(escapeHtml(match))
    return key
  })
}

function protectExplicitMath(source, store) {
  return source.replace(/\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|\$(?:\\.|[^$\\\n])+\$/g, function (match) {
    var inner = match
    var display = false
    if (match.indexOf('\\[') === 0 || match.indexOf('$$') === 0) display = true
    inner = normalizeMathRun(stripOuterMathDelimiters(match))
    var normalized = display ? '$$' + inner + '$$' : '$' + ensureDisplayStyle(inner) + '$'
    var key = '\u0007MATH' + store.length + '\u0007'
    store.push(normalized)
    return key
  })
}

function extractStandaloneStructuredMath(source) {
  var candidate = normalizeEnvironmentCommands(String(source == null ? '' : source).trim())
  if (!candidate) return null

  // Keep sentence punctuation outside the formula while still allowing the
  // formula itself to be wrapped in one or more harmless grouping braces.
  var punctuation = ''
  var punctuationMatch = candidate.match(/([,.;:，。；：！？!?、]+)$/)
  if (punctuationMatch) {
    punctuation = punctuationMatch[1]
    candidate = candidate.slice(0, candidate.length - punctuation.length).trim()
  }

  candidate = stripOuterMathDelimiters(candidate)
  candidate = stripOuterGroupingBraces(candidate)

  var envPattern = new RegExp('\\\\begin\\{(' + STRUCTURED_ENVIRONMENT_NAME + ')\\}', 'g')
  var match = envPattern.exec(candidate)
  if (!match) return null

  var envStart = match.index
  var environment = scanMatchingEnd(candidate.slice(envStart), match[1])
  if (!environment) return null

  var formulaEnd = envStart + environment.endPos
  var prefix = candidate.slice(0, envStart).trim()
  var suffix = candidate.slice(formulaEnd).trim()

  // Prefixes such as I_n= are mathematical. Plain Chinese prose is not, so a
  // sentence containing an embedded cases block continues through the mixed
  // prose tokenizer instead of swallowing the entire sentence into KaTeX.
  if (prefix && !isMathRun(prefix)) return null
  if (suffix && !/^[{}()[\],.;:，。；：！？!?、\s]+$/.test(suffix)) return null

  var formula = stripOuterGroupingBraces(candidate.slice(0, formulaEnd) + suffix)
  var normalized = normalizeLatexSource(formula)
  if (!normalized) return null
  return {
    html: '$' + ensureDisplayStyle(normalized) + '$',
    suffix: punctuation,
  }
}

function processPlainTextNode(value) {
  // Convert Greek glyphs before tokenisation. Otherwise a label such as
  // "(1+x)^α展开" is split into the invalid fragment "(1+x)^" and the
  // remaining prose, which makes KaTeX report "Expected group after '^'".
  var source = normalizeEnvironmentCommands(
    replaceUnicodeGreek(normalizeTrendPhrases(collapseProseWhitespace(decodeBasicEntities(value)))),
  )
  var structuredMath = extractStandaloneStructuredMath(source)
  if (structuredMath) {
    return structuredMath.html + escapeHtml(structuredMath.suffix)
  }

  var protectedText = []
  var protectedMath = []
  source = protectPlainTokens(source, protectedText)
  source = protectExplicitMath(source, protectedMath)

  var result = ''
  var cursor = 0
  // Deliberately excludes newlines (already normalised) and Chinese punctuation,
  // so prose cannot be swallowed into one malformed KaTeX expression.
  var pattern = /[A-Za-z0-9\\()[\]{}_^+\-*\/=<>→∞≈≠≤≥∑√·, \t]+/g
  var match
  while ((match = pattern.exec(source))) {
    result += escapeHtml(source.slice(cursor, match.index))
    var run = match[0]
    var leading = (run.match(/^\s*/) || [''])[0]
    var trailing = (run.match(/\s*$/) || [''])[0]
    var core = run.slice(leading.length, run.length - trailing.length)
    result += escapeHtml(leading)
    if (isMathRun(core)) result += '$' + ensureDisplayStyle(normalizeMathRun(core)) + '$'
    else result += escapeHtml(core)
    result += escapeHtml(trailing)
    cursor = match.index + run.length
  }
  result += escapeHtml(source.slice(cursor))

  result = result.replace(/\u0007MATH(\d+)\u0007/g, function (_, index) {
    return protectedMath[Number(index)] || ''
  })
  result = result.replace(/\u0007TEXT(\d+)\u0007/g, function (_, index) {
    return protectedText[Number(index)] || ''
  })

  // collapseProseWhitespace intentionally generated these tags.
  return result.replace(/&lt;br\/&gt;/g, '<br/>')
}

function normalizeMixedContent(value) {
  var source = String(value == null ? '' : value).trim()
  if (!source) return ''

  // Preserve trusted markup for mp-html / Parser sanitisation, while only
  // normalising the text nodes between tags.
  var tagPattern = /(<\/?[A-Za-z][^>]*>)/g
  return source.split(tagPattern).map(function (part) {
    return /^<\/?[A-Za-z][^>]*>$/.test(part) ? part : processPlainTextNode(part)
  }).join('').trim()
}

/**
 * Decode fields that may have been JSON-stringified one or more times.
 *
 * The admin detail page already supports these legacy shapes, for example:
 *   conditions: '[{"expression":"a ≠ 0","note":""}]'
 *   symbol_notes: '[{"symbol":"Delta=b^2-4ac","note":"判别式"}]'
 *   secondary_conclusions / error_tips: '["结论一","结论二"]'
 *
 * Keep ordinary prose untouched when it is not valid JSON.
 */
function decodeStructuredValue(value) {
  var current = value
  for (var i = 0; i < 3 && typeof current === 'string'; i++) {
    var source = current.trim()
    if (!source) return ''
    try {
      current = JSON.parse(source)
    } catch (_) {
      break
    }
  }
  return current
}

function readStructuredText(record, keys) {
  if (!record || typeof record !== 'object') return ''
  for (var i = 0; i < keys.length; i++) {
    var value = record[keys[i]]
    if (value !== undefined && value !== null && typeof value !== 'object') {
      return String(value)
    }
  }
  return ''
}

function normalizeStructuredItem(item, kind) {
  if (item === undefined || item === null) return null
  if (typeof item !== 'object') {
    var scalar = String(item).trim()
    return scalar ? { primary: scalar, note: '' } : null
  }

  var primaryKeys = kind === 'conditions'
    ? ['expression', 'text', 'content', 'value']
    : kind === 'symbols'
      ? ['symbol', 'text', 'content', 'value']
      : ['text', 'content', 'conclusion', 'message', 'expression', 'value']
  var primary = readStructuredText(item, primaryKeys).trim()
  var note = readStructuredText(item, ['note', 'description', 'remark']).trim()

  // Some historical error-tip records only contain a note/message field.
  if (!primary && note && kind !== 'conditions' && kind !== 'symbols') {
    primary = note
    note = ''
  }
  if (!primary && !note) return null
  return { primary: primary, note: note }
}

/**
 * Convert JSON-encoded structured fields into safe rich-text HTML.
 * Formula fragments are passed through the same mixed prose/KaTeX pipeline as
 * normal text, so the mini-program matches the admin `/formulas/[id]` preview.
 */
function normalizeStructuredContent(value, kind) {
  var parsed = decodeStructuredValue(value)
  var items

  if (Array.isArray(parsed)) items = parsed
  else if (parsed && typeof parsed === 'object') items = [parsed]
  else return normalizeMixedContent(parsed)

  var normalizedItems = items.map(function (item) {
    return normalizeStructuredItem(item, kind)
  }).filter(Boolean)

  if (!normalizedItems.length) return ''

  var isBulleted = kind === 'secondary' || kind === 'errors'
  var rows = normalizedItems.map(function (item, index) {
    var primaryHtml = normalizeMixedContent(item.primary)
    var noteHtml = normalizeMixedContent(item.note)
    var rowClass = 'fc-structured-row' + (index === 0 ? ' is-first' : '')
    var marker = isBulleted ? '<span class="fc-structured-marker">•</span>' : ''
    var note = noteHtml
      ? '<span class="fc-structured-note"> — ' + noteHtml + '</span>'
      : ''
    return '<div class="' + rowClass + '">' + marker + '<span class="fc-structured-primary">' + primaryHtml + '</span>' + note + '</div>'
  })

  return '<div class="fc-structured-list ' + (isBulleted ? 'is-bulleted' : 'is-plain') + '">' + rows.join('') + '</div>'
}

function prepareFormulaBlocks(card) {
  var blocks = card && Array.isArray(card.formula_blocks) ? card.formula_blocks : []
  var prepared = []

  blocks.forEach(function (block, index) {
    var normalized = typeof block === 'string' ? { latex: block } : Object.assign({}, block || {})
    var latex = normalizeLatexSource(normalized.latex || normalized.formula || normalized.content)
    if (!latex) return

    var visualRows = latex
      .replace(/\\begin\{(?:aligned|align\*?|gathered|cases|matrix|pmatrix|bmatrix|vmatrix|array)\}/g, '')
      .replace(/\\end\{(?:aligned|align\*?|gathered|cases|matrix|pmatrix|bmatrix|vmatrix|array)\}/g, '')
      .split(/\\\\(?:\[[^\]]*\])?/)
      .map(function (row) { return row.trim() })
      .filter(Boolean)
    var rowComplexities = visualRows.map(formulaComplexity)
    var complexity = rowComplexities.length ? Math.max.apply(Math, rowComplexities) : formulaComplexity(latex)
    var isMultiline = visualRows.length > 1
    var groupedLatex = splitFormulaGroup(latex)
    var isGrouped = groupedLatex.length >= 3
    prepared.push(Object.assign({}, normalized, {
      latex: latex,
      _key: String(normalized.id || normalized.label || index) + '-' + index + '-' + latex.length,
      isGrouped: isGrouped,
      formulaParts: groupedLatex.map(function (part, partIndex) {
        return {
          latex: part,
          _key: String(index) + '-' + String(partIndex) + '-' + String(part.length),
        }
      }),
      isScrollable: !isGrouped && complexity > 108,
      sizeClass: !isGrouped && complexity > 185 ? 'is-dense' : (!isGrouped && complexity > 120 ? 'is-compact' : ''),
      isMultiline: !isGrouped && isMultiline,
      lineCount: visualRows.length || 1,
      scrollLeft: 0,
    }))
  })

  return prepared
}

function prepareContentHtml(card) {
  card = card || {}
  return {
    summaryHtml: normalizeMixedContent(card.summary),
    conditionsHtml: normalizeStructuredContent(card.conditions, 'conditions'),
    symbolNotesHtml: normalizeStructuredContent(card.symbol_notes, 'symbols'),
    secondaryHtml: normalizeStructuredContent(card.secondary_conclusions, 'secondary'),
    errorTipsHtml: normalizeStructuredContent(card.error_tips, 'errors'),
    examples: (Array.isArray(card.examples) ? card.examples : []).map(function (example) {
      var item = example || {}
      return Object.assign({}, item, {
        questionHtml: normalizeMixedContent(item.question),
        solutionHtml: normalizeMixedContent(item.short_solution),
        answerHtml: normalizeMixedContent(item.answer),
        errorTipHtml: normalizeMixedContent(item.error_tip),
      })
    }),
  }
}

function createRenderKey(card) {
  card = card || {}
  try {
    return JSON.stringify([
      card.id,
      card.title,
      card.formula_blocks,
      card.summary,
      card.conditions,
      card.symbol_notes,
      card.secondary_conclusions,
      card.error_tips,
      card.examples,
    ])
  } catch (_) {
    return String(card.id || '') + '|' + String(card.title || '')
  }
}

module.exports = {
  createRenderKey: createRenderKey,
  ensureDisplayStyle: ensureDisplayStyle,
  normalizeLatexSource: normalizeLatexSource,
  normalizeMathRun: normalizeMathRun,
  normalizeMixedContent: normalizeMixedContent,
  decodeStructuredValue: decodeStructuredValue,
  normalizeStructuredContent: normalizeStructuredContent,
  prepareContentHtml: prepareContentHtml,
  prepareFormulaBlocks: prepareFormulaBlocks,
  splitFormulaGroup: splitFormulaGroup,
  sanitizeLatexContent: sanitizeLatexContent,
  normalizeDeterminantNotation: normalizeDeterminantNotation,
  normalizeEnvironmentCommands: normalizeEnvironmentCommands,
}
