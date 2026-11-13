var { formatInlineMathText, containsCode } = require('./stem-render-dependencies')
function _formatHtmlTextSegment(text) {
return String(text || '').split('\n').map(function (line) {
var escaped = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
if (/(```|[{};=]|\/\/)/.test(line)) return escaped.replace(/\t/g, '    ').replace(/ /g, '&nbsp;')
return escaped.replace(/ {2,}/g, function (spaces) { return ' ' + '&nbsp;'.repeat(spaces.length - 1) })
}).join('<br>')
}
var LATEX_DELIMITER_PAIR = /\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)/g
function _normalizeLatexDelimiters(text) {
if (!text) return ''
var source = String(text)
if (source.indexOf('\\') === -1) return source
// Imports and model output also use \(...\)/\[...\]; the bundled mp-html KaTeX
// plugin only consumes $...$/$$...$$, so normalize equivalent delimiters here.
return source.replace(LATEX_DELIMITER_PAIR, function (match, blockInner, inlineInner, offset, whole) {
var replacement = blockInner !== undefined ? '$$' + blockInner + '$$' : '$' + inlineInner + '$'
var before = offset > 0 ? whole.charAt(offset - 1) : ''
var end = offset + match.length
var after = end < whole.length ? whole.charAt(end) : ''
// Adjacent math spans would collapse into one $$ token and mp-html drops
// both formulas; separate the junction with a space.
var padBefore = before === '$'
var padAfter = after === '$' || (after === '\\' && /^\\[\(\[]/.test(whole.slice(end)))
return (padBefore ? ' ' : '') + replacement + (padAfter ? ' ' : '')
})
}
function _hasLatexDelimiters(text) {
if (!text) return false
var source = String(text)
return /\\\([\s\S]*?\\\)/.test(source) || /\\\[[\s\S]*?\\\]/.test(source)
}
function _textToHtml(text) {
if (!text) return ''
var parts = _normalizeLatexDelimiters(text).split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/)
var out = parts.map(function (part, i) {
if (i % 2 === 1) return part.replace(/\\(n|t|r)(?![a-zA-Z])/g, ' ')
return _formatHtmlTextSegment(part)
})
return '<p>' + out.join('') + '</p>'
}
function _toCanonicalForm(text) {
if (!text) return ''
var s = String(text)
.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
.replace(/<[^>]+>/g, '')
.replace(/<br\s*\/?>/gi, '\n')
.replace(/&nbsp;/gi, ' ')
.replace(/&amp;/g, '&')
.replace(/&lt;/g, '<')
.replace(/&gt;/g, '>')
.replace(/&[#a-zA-Z0-9]+;/g, ' ')
.replace(/\$([^$\n]+?)\$/g, function(_, inner) {
var plain = formatInlineMathText(inner)
return /\\[a-zA-Z]+/.test(plain) ? '' : plain
})
.replace(/\s+/g, ' ')
.replace(/[，。、；：！？…—·"''""（）()【】《》<>]/g, function(ch) {
if ('，。、；：！？'.indexOf(ch) >= 0) return ' '
return ch
})
.trim()
return s
}
function _repairFalseNumberMarkerBreaks(text) {
if (!text) return text
var source = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n')
source = source
.replace(/(\d)[ \t]*([~～])[ \t]*\n[ \t]*(\d)/g, '$1$2$3')
.replace(/(\d)[ \t]*\n[ \t]*([~～])[ \t]*(\d)/g, '$1$2$3')
.replace(/(\d)[ \t]*([~～])[ \t]*<br\s*\/?>[ \t]*(\d)/gi, '$1$2$3')
return source.replace(
/([A-Za-z_][A-Za-z0-9_]*)[ \t]*\n[ \t]*(\d+[)）])(?=[A-Za-z0-9_])/g,
'$1$2'
)
}
function _trimEmptyLines(lines) {
var start = 0
var end = lines.length
while (start < end && !String(lines[start]).trim()) start++
while (end > start && !String(lines[end - 1]).trim()) end--
return lines.slice(start, end)
}
function _deduplicateRepeatedText(text) {
if (!text) return text
var normalized = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n')
var stripped = normalized.trim()
var half = Math.floor(stripped.length / 2)
if (half > 0) {
var leftHalf = stripped.slice(0, half)
var rightHalf = stripped.slice(half)
if (_toCanonicalForm(leftHalf) === _toCanonicalForm(rightHalf) && _toCanonicalForm(leftHalf).trim()) {
return leftHalf.replace(/\n+$/, '').trim()
}
}
var paragraphs = stripped.split(/\n\n+/)
if (paragraphs.length >= 2) {
var result = []
for (var i = 0; i < paragraphs.length; i++) {
var current = paragraphs[i]
if (i > 0) {
var prev = paragraphs[i - 1]
var isCodeBlock = containsCode(current) || containsCode(prev)
if (isCodeBlock) {
if (current.trim() === prev.trim()) continue
} else {
if (_toCanonicalForm(current) === _toCanonicalForm(prev)) continue
}
}
result.push(current)
}
if (result.length >= 3) {
var firstPara = result[0].trim()
var lastPara = result[result.length - 1].trim()
if (!containsCode(firstPara) && !containsCode(lastPara)) {
if (_toCanonicalForm(firstPara) === _toCanonicalForm(lastPara) && _toCanonicalForm(firstPara)) {
result.pop()
}
}
}
return result.join('\n\n').trim()
}
return stripped
}
function _needsRichRender(text) {
if (!text) return false
var source = _normalizeLatexDelimiters(text)
return /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/.test(source) || /<\/?[a-z][\s\S]*>/i.test(text) || /\n/.test(text)
}
function _escapeRegExp(text) {
return String(text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
function _toPlainInlineMathText(text) {
if (!text) return ''
var source = _repairFalseNumberMarkerBreaks(_normalizeLatexDelimiters(String(text)))
if (/\$\$[\s\S]*?\$\$/.test(source) || /<\/?[a-z][\s\S]*>/i.test(source)) return null
// Superscript/subscript syntax must keep the KaTeX render path.  The lightweight
// formatter can only flatten a subset of TeX scripts; stripping `$...$` first made
// expressions such as `O(n^{1/2})` leak literal `^{...}` into option text.
var hasUnflattenableScript = false
source.replace(/\$([^$\n]+?)\$/g, function (_, expr) {
if (/[_^]/.test(expr)) hasUnflattenableScript = true
return _
})
if (hasUnflattenableScript) return null
var plain = formatInlineMathText(source)
if (/\\[a-zA-Z]+/.test(plain)) return null
plain = plain.replace(/[ \t]+/g, ' ').replace(/\s+([，。！？；：,.!?;:])/g, '$1').trim()
return plain
}
function _toPlainSimpleInlineMathText(text) {
if (!text) return ''
var source = String(text)
if (/\$\$[\s\S]*?\$\$/.test(source) || /<\/?[a-z][\s\S]*>/i.test(source)) return null
if (!/\$[^$\n]+?\$/.test(source)) return null
var plain = source.replace(/\$([^$\n]+?)\$/g, function (_, inner) {
var value = formatInlineMathText(inner)
return /\\[a-zA-Z]+/.test(value) ? '$' + inner + '$' : value
})
return /\$[^$\n]+?\$/.test(plain) ? null : plain
}
function _buildRichTextNodes(text) {
var lines = String(text || '').split('\n')
var children = []
for (var i = 0; i < lines.length; i++) {
if (i > 0) children.push({ name: 'br', attrs: {} })
children.push({ type: 'text', text: lines[i] })
}
return [{ name: 'p', attrs: {}, children: children }]
}
module.exports = {
  _formatHtmlTextSegment,
  _textToHtml,
  _normalizeLatexDelimiters,
  _hasLatexDelimiters,
  _toCanonicalForm,
  _repairFalseNumberMarkerBreaks,
  _trimEmptyLines,
  _deduplicateRepeatedText,
  _needsRichRender,
  _escapeRegExp,
  _toPlainInlineMathText,
  _toPlainSimpleInlineMathText,
  _buildRichTextNodes,
}
