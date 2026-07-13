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

  source = stripOuterMathDelimiters(source)
    .replace(/^\\begin\{(?:equation\*?|displaymath)\}/, '')
    .replace(/\\end\{(?:equation\*?|displaymath)\}$/, '')
    .trim()

  var hasStructuredEnvironment = /\\begin\s*\{(?:aligned|align\*?|gathered|cases|matrix|pmatrix|bmatrix|vmatrix|array)\}/.test(source)

  // Remove editor delimiters without removing escaped currency symbols.
  source = source
    .replace(/\$\$/g, '\n')
    .replace(/\\\[|\\\]/g, '\n')
    .replace(/\\\(|\\\)/g, '')
    .replace(/(^|[^\\])\$/g, '$1')

  if (!hasStructuredEnvironment) {
    // A formula block in the admin editor is one visual row. Newlines and raw
    // LaTeX line breaks are therefore treated as horizontal spacing.
    source = source
      .replace(/\\\\(?:\[[^\]]*\])?/g, ' \\qquad ')
      .replace(/\n+/g, ' \\qquad ')
      .replace(/(?:\s*\\(?:qquad|quad)\s*)+/g, ' \\qquad ')
  } else {
    source = source.replace(/\n+/g, ' ')
  }

  source = replaceUnicodeMath(source)
    .replace(/[ \t]+/g, ' ')
    .trim()

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

function normalizeMathRun(value) {
  var source = stripOuterMathDelimiters(String(value || '').trim())
  if (!source) return ''

  source = replaceUnicodeMath(source)
    .replace(/√\s*\(([^)]+)\)/g, '\\sqrt{$1}')
    .replace(/(^|[^\\A-Za-z])lim\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*(?:\\to|→|->)\s*([^)]+)\)/gi, function (_, prefix, variable, target) {
      return prefix + '\\lim_{' + variable + '\\to ' + replaceUnicodeMath(target).trim() + '}'
    })

  // Structure-sensitive transformations must happen before generic function
  // escaping. Otherwise the reader merely italicises legacy text such as
  // (sin x)/x instead of producing a real KaTeX fraction.
  source = normalizePowers(source)
  source = normalizeFractions(source)
  source = normalizeFunctionNames(source)
    .replace(/\s*=\s*/g, '=')
    .replace(/[ \t]+/g, ' ')
    .trim()
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

  if (/\\(?:lim|frac|sqrt|sum|prod|int|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|ln|log|det|exp|to|infty|le|ge|ne|approx|begin|alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|kappa|lambda|mu|nu|xi|omicron|pi|varpi|rho|varrho|sigma|varsigma|tau|upsilon|phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega)\b/.test(source)) return true
  if (/(?:lim|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|ln|log|det|exp)\s*\(?/i.test(source)) return true
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

function processPlainTextNode(value) {
  // Convert Greek glyphs before tokenisation. Otherwise a label such as
  // "(1+x)^α展开" is split into the invalid fragment "(1+x)^" and the
  // remaining prose, which makes KaTeX report "Expected group after '^'".
  var source = replaceUnicodeGreek(normalizeTrendPhrases(collapseProseWhitespace(decodeBasicEntities(value))))
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

function prepareFormulaBlocks(card) {
  var blocks = card && Array.isArray(card.formula_blocks) ? card.formula_blocks : []
  var prepared = []

  blocks.forEach(function (block, index) {
    var normalized = typeof block === 'string' ? { latex: block } : Object.assign({}, block || {})
    var latex = normalizeLatexSource(normalized.latex || normalized.formula || normalized.content)
    if (!latex) return

    var complexity = formulaComplexity(latex)
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
      scrollLeft: 0,
    }))
  })

  return prepared
}

function prepareContentHtml(card) {
  card = card || {}
  return {
    summaryHtml: normalizeMixedContent(card.summary),
    conditionsHtml: normalizeMixedContent(card.conditions),
    symbolNotesHtml: normalizeMixedContent(card.symbol_notes),
    secondaryHtml: normalizeMixedContent(card.secondary_conclusions),
    errorTipsHtml: normalizeMixedContent(card.error_tips),
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
  prepareContentHtml: prepareContentHtml,
  prepareFormulaBlocks: prepareFormulaBlocks,
  splitFormulaGroup: splitFormulaGroup,
}
