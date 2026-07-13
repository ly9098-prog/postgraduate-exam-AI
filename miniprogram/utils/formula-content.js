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

function replaceUnicodeMath(value) {
  return String(value == null ? '' : value)
    .replace(/→|->/g, '\\to ')
    .replace(/∞/g, '\\infty ')
    .replace(/≤/g, '\\le ')
    .replace(/≥/g, '\\ge ')
    .replace(/≠/g, '\\ne ')
    .replace(/≈/g, '\\approx ')
    .replace(/∑/g, '\\sum ')
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
  source = replaceUnicodeMath(source)
    .replace(/√\s*\(([^)]+)\)/g, '\\sqrt{$1}')
    .replace(/(^|[^\\A-Za-z])lim\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*(?:\\to|→|->)\s*([^)]+)\)/gi, function (_, prefix, variable, target) {
      return prefix + '\\lim_{' + variable + '\\to ' + target.trim() + '}'
    })
  source = normalizeFunctionNames(source)
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
  if (/\\(?:lim|frac|sqrt|sum|prod|int|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|ln|log|det|exp|to|infty|le|ge|ne|approx|begin)/.test(source)) return true
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
  var source = collapseProseWhitespace(decodeBasicEntities(value))
  var protectedMath = []
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
