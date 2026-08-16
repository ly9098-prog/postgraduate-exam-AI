/**
 * AI learning-advice math renderer helpers.
 *
 * Some historical AI-analysis rows contain LaTeX that was embedded in a JSON
 * string without escaping the backslash twice. After JSON decoding, commands
 * such as `\\neq`, `\\text`, `\\frac`, `\\right` and `\\beta` can therefore
 * become control characters (`\n`, `\t`, `\f`, `\r`, `\b`). That breaks the
 * `$...$` span and makes the raw formula source visible in <text>.
 *
 * This module repairs those control-character escapes only inside math
 * delimiters, then forces delimited math through mp-html/KaTeX. Normal prose
 * line breaks remain untouched.
 */

var stemRender = require('./stem-render')
var mathFormat = require('./math-format')

var CONTROL_PREFIX = {
  8: 'b',  // \b -> backspace, e.g. \beta / \begin / \bar
  9: 't',  // \t -> tab,       e.g. \text / \theta / \times
  10: 'n', // \n -> newline,   e.g. \neq / \nabla / \nu
  12: 'f', // \f -> formfeed,  e.g. \frac / \forall
  13: 'r', // \r -> carriage,  e.g. \right / \rho
}

// Commands whose first letter collides with a JSON control escape. Keep this
// conservative: an actual layout newline inside display math should become a
// space rather than being guessed into a LaTeX command.
var RECOVERABLE_COMMANDS = {
  // b...
  backslash: true, bar: true, begin: true, beta: true, bgroup: true,
  big: true, Big: true, bigg: true, Bigg: true, binom: true, bmatrix: true,
  boldsymbol: true, boxed: true, brace: true, brack: true,
  // f...
  fbox: true, frac: true, forall: true,
  // n...
  nabla: true, ne: true, neg: true, neq: true, nexists: true, nmid: true,
  not: true, notin: true, nparallel: true, nu: true,
  // r...
  rangle: true, rbrace: true, rceil: true, rfloor: true, rho: true,
  right: true, rightarrow: true, Rightarrow: true,
  // t...
  tan: true, tanh: true, tau: true, text: true, textbf: true, textit: true,
  textrm: true, textsf: true, texttt: true, theta: true, times: true,
  to: true, top: true, triangle: true, triangleleft: true, triangleright: true,
}

function _repairFormulaInner(inner) {
  var source = String(inner || '')
  var out = ''

  for (var i = 0; i < source.length; i++) {
    var ch = source.charAt(i)
    var code = source.charCodeAt(i)
    var prefix = CONTROL_PREFIX[code]

    if (!prefix) {
      out += ch
      continue
    }

    var rest = source.slice(i + 1)
    var match = rest.match(/^([A-Za-z]+)/)
    var suffix = match ? match[1] : ''
    var command = prefix + suffix

    if (suffix && RECOVERABLE_COMMANDS[command]) {
      out += '\\' + command
      i += suffix.length
    } else {
      // Treat genuine whitespace/control characters in math as spacing. This
      // keeps display formulas readable without corrupting surrounding prose.
      out += ' '
    }
  }

  return out.replace(/[ \t]+/g, ' ').trim()
}

function repairAiLatexControlEscapes(value) {
  var source = String(value || '')
  if (!source || source.indexOf('$') < 0) return source

  // Match $$...$$ before $...$. [\s\S] intentionally permits a corrupted
  // inline formula to contain the newline created by `\\neq` -> `\n` + `eq`.
  return source.replace(/(\$\$|\$)([\s\S]*?)\1/g, function (_, delimiter, inner) {
    return delimiter + _repairFormulaInner(inner) + delimiter
  })
}

function hasDelimitedMath(value) {
  return /(\$\$|\$)[\s\S]*?\1/.test(String(value || ''))
}

function _plainMathFallback(value) {
  var source = String(value || '')
  return mathFormat.formatInlineMathText(source)
    .replace(/\$\$?/g, '')
    .replace(/[ \t]+/g, ' ')
    .trim()
}

function buildAiRichText(value) {
  var original = String(value || '').trim()
  if (!original) {
    return { raw: '', text: '', html: '', needsRich: false }
  }

  var repaired = repairAiLatexControlEscapes(original)
  var alreadyHtml = /<\/?[a-z][\s\S]*>/i.test(repaired)
  var containsMath = hasDelimitedMath(repaired)

  // Delimited AI math should always take the KaTeX path. The generic question
  // renderer may intentionally collapse simple inline math to Unicode, but AI
  // advice mixes prose and formulas and must never expose `$...$` source.
  if (containsMath) {
    return {
      raw: original,
      text: _plainMathFallback(repaired),
      html: alreadyHtml ? repaired : stemRender.textToHtml(repaired),
      needsRich: true,
    }
  }

  var plain = stemRender.toPlainInlineMathText(repaired)
  var needsRich = !plain && stemRender.needsRichRender(repaired)
  return {
    raw: original,
    text: plain || repaired,
    html: needsRich ? (alreadyHtml ? repaired : stemRender.textToHtml(repaired)) : '',
    needsRich: needsRich,
  }
}

module.exports = {
  repairAiLatexControlEscapes: repairAiLatexControlEscapes,
  hasDelimitedMath: hasDelimitedMath,
  buildAiRichText: buildAiRichText,
}
