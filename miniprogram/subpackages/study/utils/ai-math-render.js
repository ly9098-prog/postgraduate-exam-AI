
var stemRender = require('./stem-render')
var mathFormat = require('./math-format')
var CONTROL_PREFIX = {
8: 'b',
9: 't',
10: 'n',
12: 'f',
13: 'r',
}
var RECOVERABLE_COMMANDS = {
backslash: true, bar: true, begin: true, beta: true, bgroup: true,
big: true, Big: true, bigg: true, Bigg: true, binom: true, bmatrix: true,
boldsymbol: true, boxed: true, brace: true, brack: true,
fbox: true, frac: true, forall: true,
nabla: true, ne: true, neg: true, neq: true, nexists: true, nmid: true,
not: true, notin: true, nparallel: true, nu: true,
rangle: true, rbrace: true, rceil: true, rfloor: true, rho: true,
right: true, rightarrow: true, Rightarrow: true,
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
out += ' '
}
}
return out.replace(/[ \t]+/g, ' ').trim()
}
function normalizeAiMathDelimiters(value) {
var source = String(value || '')
if (!source) return source
// AI providers commonly emit Markdown/LaTeX delimiters \(...\) and \[...\].
// mp-html's bundled KaTeX plugin consumes $...$ / $$...$$ only, so normalize
// these equivalent delimiters before repairing JSON control-escape damage.
source = source.replace(/\\\[([\s\S]*?)\\\]/g, function (_, inner) {
return '$$' + inner + '$$'
})
source = source.replace(/\\\(([\s\S]*?)\\\)/g, function (_, inner) {
return '$' + inner + '$'
})
return source
}
function repairAiLatexControlEscapes(value) {
var source = normalizeAiMathDelimiters(value)
if (!source || source.indexOf('$') < 0) return source
return source.replace(/(\$\$|\$)([\s\S]*?)\1/g, function (_, delimiter, inner) {
return delimiter + _repairFormulaInner(inner) + delimiter
})
}
function hasDelimitedMath(value) {
return /(\$\$|\$)[\s\S]*?\1/.test(normalizeAiMathDelimiters(value))
}
// Bare script runs (2^{32}, a_1) that the model left outside $...$ while other
// formulas in the same passage were delimited. Math-mode braces here are
// almost always formulas, so wrap them for the mp-html KaTeX plugin instead
// of leaking literal ^{...} next to rendered math. The base must not continue
// a preceding letter, letter+digit pair, backslash, underscore or opening
// brace: compound tokens such as x10, snake_case identifiers such as flag_used
// and x_axis, \log-type commands and nested-brace bodies such as x^{a_{1}}
// never become a script base. Unbraced script bodies are restricted to digit
// runs and rewritten to ^{...}/_{...} so 2^32 renders as 2^{32} instead of
// 2^3 followed by a stray 2; bodies stay ASCII math only (no newlines, no
// CJK) so prose annotations cannot be swallowed into a malformed formula.
var BARE_SCRIPT_MATH = /(?<![A-Za-z\\_{])(?<![A-Za-z][0-9])(([0-9]+|[A-Za-z])((?:[\^_]\{[-0-9A-Za-z+=,.()/\t  ]+\}|[\^_][0-9]+)+))/g
function _braceBareNumericScripts(run) {
return String(run).replace(/([\^_])([0-9]+)/g, '$1{$2}')
}
function wrapBareScriptMath(source) {
var parts = String(source || '').split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/)
var out = ''
for (var i = 0; i < parts.length; i++) {
var part = parts[i]
if (i % 2 === 1) {
out += part
continue
}
// A plain part can still contain an unpaired '$' (e.g. a currency sign). Any
// delimiter inserted there could re-pair with it and pull prose into math, so
// leave such parts untouched.
if (!part || part.indexOf('$') !== -1) {
out += part
continue
}
var pos = 0
BARE_SCRIPT_MATH.lastIndex = 0
var match
while ((match = BARE_SCRIPT_MATH.exec(part)) !== null) {
out += part.slice(pos, match.index)
var run = _braceBareNumericScripts(match[1])
var prevChar = out.length > 0 ? out.charAt(out.length - 1) : ''
var nextChar = match.index + match[1].length < part.length
? part.charAt(match.index + match[1].length)
: (i + 1 < parts.length ? '$' : '')
// The mp-html latex plugin tokenizes /\${1,2}/, so a delimiter directly
// touching an existing math span would form '$$' and destroy both formulas.
if (prevChar === '$' || nextChar === '$') {
out += run
} else {
out += '$' + run + '$'
}
pos = match.index + match[1].length
}
out += part.slice(pos)
}
return out
}
function wrapBareScriptMathInHtml(html) {
// alreadyHtml sources contain tags and attributes; only text nodes are
// eligible for wrapping so markup and attribute values stay untouched.
return String(html || '').split(/(<[^>]*>)/).map(function (chunk, index) {
if (index % 2 === 1) return chunk
return wrapBareScriptMath(chunk)
}).join('')
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
if (containsMath) {
var katexSource = alreadyHtml ? wrapBareScriptMathInHtml(repaired) : wrapBareScriptMath(repaired)
return {
raw: original,
text: _plainMathFallback(repaired),
html: alreadyHtml ? katexSource : stemRender.textToHtml(katexSource),
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
normalizeAiMathDelimiters: normalizeAiMathDelimiters,
repairAiLatexControlEscapes: repairAiLatexControlEscapes,
hasDelimitedMath: hasDelimitedMath,
buildAiRichText: buildAiRichText,
}
