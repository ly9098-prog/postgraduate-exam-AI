var { containsCode } = require('./stem-render-dependencies')
var { _toPlainInlineMathText, _toPlainSimpleInlineMathText } = require('./stem-render-text')
function _isCodeBlock(text) {
if (!text || !text.trim()) return false
if (/^```/.test(text.trim())) return true
if (!containsCode(text)) return false
var lines = text.split('\n')
var structuralCount = 0
for (var i = 0; i < lines.length; i++) {
var line = lines[i].trim()
if (/[{}\s]/.test(line) && /[{]/.test(line)) structuralCount++
if (/;$/.test(line)) structuralCount++
if (/^\s*(if|else|for|while|do|switch|case|return|struct|class)\b/.test(line)) structuralCount++
if (structuralCount >= 2) return true
}
return structuralCount >= 1
}
function _scoreCodeContent(text) {
if (!text) return 0
var score = 0
if (/^(int|void|char|float|double|long|boolean|String|unsigned|short)\b/.test(text)) score += 2
if (/\b(for|while|if|switch|do|catch)\s*\(/.test(text)) score += 2
if (/\b(return|printf|scanf|malloc|free|sizeof|typedef)\b/.test(text)) score += 2
if (/\([^)]*\)/.test(text)) score += 1
if (/;/.test(text)) score += 1
if (/[{}]/.test(text)) score += 1
if (/\+\+|--/.test(text)) score += 1
if (/[+\-*/%&|^]?=(?!=)/.test(text)) score += 1
if (/->|::/.test(text)) score += 1
return score
}
function _hasSentenceEnding(text) {
return /[。！？：；\n.!?:]\s*$/.test(text)
}
function _findCredibleCodeStart(text) {
var kwType = /\b(int|void|char|float|double|long|boolean|String|unsigned|short)\s+\w+/g
var kwControl = /\b(for|while|if|switch|do)\s*\(/g
var kwReturn = /\b(return|printf|scanf|malloc|free)\s*[;(]/g
var match
while ((match = kwType.exec(text)) !== null) {
var pos = match.index
var before = text.slice(0, pos).trim()
if (!before) continue
var after = text.slice(pos)
if (_hasSentenceEnding(before) && _scoreCodeContent(after) >= 4) {
return pos
}
}
while ((match = kwControl.exec(text)) !== null) {
var pos2 = match.index
var before2 = text.slice(0, pos2).trim()
if (!before2) continue
var after2 = text.slice(pos2)
if (_hasSentenceEnding(before2) && _scoreCodeContent(after2) >= 4) {
return pos2
}
}
while ((match = kwReturn.exec(text)) !== null) {
var pos3 = match.index
var before3 = text.slice(0, pos3).trim()
if (!before3) continue
var after3 = text.slice(pos3)
if (_hasSentenceEnding(before3) && _scoreCodeContent(after3) >= 4) {
return pos3
}
}
return -1
}
function splitInlineTextAndCode(text) {
if (!text || !text.trim()) return [{ type: 'RICH_TEXT', text: text || '' }]
var trimmed = text.trim()
var codeStart = _findCredibleCodeStart(trimmed)
if (codeStart === -1) {
return [{ type: 'RICH_TEXT', text: trimmed }]
}
var before = trimmed.slice(0, codeStart).trim()
var after = trimmed.slice(codeStart).trim()
var blocks = []
if (before) blocks.push({ type: 'RICH_TEXT', text: before })
if (after) blocks.push({ type: 'CODE', text: after })
return blocks
}
function splitStemBlocks(text) {
if (!text || !text.trim()) return [{ type: 'RICH_TEXT', text: text || '' }]
var source = String(text)
var rawParas = source.split(/\n\n+/)
var classified = []
for (var p = 0; p < rawParas.length; p++) {
var para = rawParas[p].trim()
if (!para) continue
var inlineBlocks = splitInlineTextAndCode(para)
if (inlineBlocks.length > 1) {
for (var ib = 0; ib < inlineBlocks.length; ib++) {
classified.push(inlineBlocks[ib])
}
} else {
var type = _classifyParagraph(para)
classified.push({ type: type, text: para })
}
}
if (classified.length === 0) return [{ type: 'RICH_TEXT', text: '' }]
var merged = []
for (var k = 0; k < classified.length; k++) {
if (merged.length > 0 && merged[merged.length - 1].type === classified[k].type) {
merged[merged.length - 1].text += '\n\n' + classified[k].text
} else {
merged.push({ type: classified[k].type, text: classified[k].text })
}
}
return merged
}
function containsUnresolvedLatex(text) {
var value = String(text || '')
var complexCmds = 'frac|sqrt|sum|prod|int|iint|iiint|oint|begin|end|left|right|'
+ 'matrix|pmatrix|vmatrix|bmatrix|cases|align|array|displaystyle|'
+ 'text|mbox|lim|log|ln|lg|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan'
return (
/\$\$[\s\S]*?\$\$/.test(value) ||
/\$[^$\n]+?\$/.test(value) ||
new RegExp('\\\\(' + complexCmds + ')\\b').test(value)
)
}
function _classifyParagraph(text) {
if (!text) return 'RICH_TEXT'
if (/^```/.test(text.trim())) return 'CODE'
var isCode = _isCodeBlock(text)
if (isCode) return 'CODE'
var plain = _toPlainInlineMathText(text) || _toPlainSimpleInlineMathText(text)
if (typeof plain === 'string' && plain.length > 0 && !containsUnresolvedLatex(plain)) {
return 'RICH_TEXT'
}
if (/\$\$[\s\S]*?\$\$/.test(text)) return 'LATEX'
if (/\\[a-zA-Z]+/.test(text) && !/\\[nrt]/.test(text)) return 'LATEX'
return 'RICH_TEXT'
}
module.exports = {
  _isCodeBlock,
  _scoreCodeContent,
  _hasSentenceEnding,
  _findCredibleCodeStart,
  splitInlineTextAndCode,
  splitStemBlocks,
  containsUnresolvedLatex,
  _classifyParagraph,
}
