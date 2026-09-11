
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
function repairAiLatexControlEscapes(value) {
var source = String(value || '')
if (!source || source.indexOf('$') < 0) return source
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
