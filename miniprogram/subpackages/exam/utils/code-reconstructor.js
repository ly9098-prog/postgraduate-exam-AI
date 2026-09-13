
var _BROKEN_OP_PATTERNS = [
{ pattern: /(^|\W)\*\s*=(?!\s*=)/g, replacement: '$1*=' },
{ pattern: /(^|\W)\+\s*\+/g, replacement: '$1++' },
{ pattern: /(^|\W)\-\s*>(?!\s*>)/g, replacement: '$1->' },
{ pattern: /(^|\W)=\s*=(?!\s*=)/g, replacement: '$1==' },
{ pattern: /(^|\W)!\s*=/g, replacement: '$1!=' },
{ pattern: /(^|\W)<\s*=/g, replacement: '$1<=' },
{ pattern: /(^|\W)>\s*=/g, replacement: '$1>=' },
{ pattern: /\|\s*\|/g, replacement: '||' },
{ pattern: /&\s*&/g, replacement: '&&' },
]
var _CONTROL_KEYWORDS = [
'for', 'while', 'if', 'else if', 'else', 'switch',
'return', 'break', 'continue', 'struct', 'class', 'typedef',
'enum', 'case', 'default', 'catch', 'finally', 'try', 'do',
]
var _CODE_SIGNALS = [
'return', 'printf', 'scanf', 'malloc', 'free', 'NULL',
'struct', 'typedef', 'enum', 'union',
'int ', 'void ', 'char ', 'float ', 'double ',
'bool', 'const', 'static', 'sizeof',
'->', '::', '{', '}', ';',
'++', '--', '+=', '-=', '*=', '/=',
'#include', '#define', 'main(',
]
var _DS_KEYWORDS = [
'LNode', 'TNode', 'BiTNode', 'BiTree', 'BSTNode', 'LinkList',
'SqList', 'Stack', 'Queue', 'SqStack', 'ElemType', 'Status',
]
function containsCode(text) {
if (!text) return false
var score = 0
for (var i = 0; i < _CODE_SIGNALS.length; i++) {
if (text.indexOf(_CODE_SIGNALS[i]) !== -1) score++
}
for (var j = 0; j < _DS_KEYWORDS.length; j++) {
if (text.indexOf(_DS_KEYWORDS[j]) !== -1) score += 2
}
for (var k = 0; k < _CONTROL_KEYWORDS.length; k++) {
var kw = _CONTROL_KEYWORDS[k]
var re = new RegExp('\\b' + kw + '\\b')
if (re.test(text)) score++
}
return score >= 3
}
function shouldReconstructCode(text) {
if (!text) return false
if (!containsCode(text)) return false
var newlines = 0
for (var ni = 0; ni < text.length; ni++) {
if (text[ni] === '\n') newlines++
if (newlines > 1) return false
}
var semicolons = 0
var parenDepth = 0
for (var si = 0; si < text.length; si++) {
if (text[si] === '(') parenDepth++
if (text[si] === ')') parenDepth--
if (text[si] === ';' && parenDepth === 0) semicolons++
if (semicolons >= 2) return true
}
return false
}
function _fixOcrOperators(text) {
if (!text) return text
var result = text
for (var i = 0; i < _BROKEN_OP_PATTERNS.length; i++) {
result = result.replace(_BROKEN_OP_PATTERNS[i].pattern, _BROKEN_OP_PATTERNS[i].replacement)
}
return result
}
function _recoverCompressedStructure(text) {
if (!text) return text
var result = text
var kwPattern = _CONTROL_KEYWORDS.join('|')
var reBeforeKw = new RegExp('(\\S)\\s*(?=\\b(' + kwPattern + ')\\b)', 'g')
result = result.replace(reBeforeKw, '$1\n')
var reAfterSemicolon = new RegExp(';\\s*(?=\\b(' + kwPattern + '|' + _DS_KEYWORDS.join('|') + ')\\b)', 'g')
result = result.replace(reAfterSemicolon, ';\n')
result = result.replace(/}(\s*)(?=\b(else|catch|finally|while)\b)/g, '}\n$1')
return result
}
function _splitSemicolons(text) {
if (!text) return text
var lines = []
var current = ''
var parenDepth = 0
var inString = false
var stringChar = ''
for (var i = 0; i < text.length; i++) {
var ch = text[i]
var nextCh = text[i + 1] || ''
if ((ch === '"' || ch === "'") && (i === 0 || text[i - 1] !== '\\')) {
if (inString && ch === stringChar) {
inString = false
} else if (!inString) {
inString = true
stringChar = ch
}
}
if (!inString) {
if (ch === '(') {
parenDepth++
} else if (ch === ')') {
parenDepth--
}
if (ch === ';' && parenDepth === 0) {
current += ch
lines.push(current)
current = ''
continue
}
if (ch === '{' && nextCh && nextCh !== '\n') {
current += ch
lines.push(current)
current = ''
continue
}
if (ch === '}') {
if (current.trim()) {
lines.push(current)
}
current = '}'
if (nextCh && nextCh !== '\n' && nextCh !== '}') {
lines.push(current)
current = ''
continue
}
}
}
current += ch
}
if (current.trim()) {
lines.push(current)
}
return lines.join('\n')
}
function reconstructCode(text, opts) {
if (!text) return text
opts = opts || {}
var fixOperators = opts.fixOperators !== false
var fixStructure = opts.fixStructure !== false
var fixIndent = opts.fixIndent !== false
if (!containsCode(text)) return text
var result = text
if (fixOperators) {
result = _fixOcrOperators(result)
}
if (fixStructure) {
result = _recoverCompressedStructure(result)
result = _splitSemicolons(result)
result = result.replace(/\n{2,}/g, '\n').replace(/^\n/, '')
}
return result
}
function detectCodeLanguageHint(code) {
var text = String(code || '')
if (/<\?php/.test(text) || /\$_[A-Z]/.test(text)) {
return 'php'
}
if (/^#!\//.test(text) || /\$\{[A-Za-z_]/.test(text) || /\$\(.+\)/.test(text) || /\$\d\b/.test(text)) {
if (/\b(echo|export|source|cd\b|exit|chmod|chown|grep|sed|awk|cat|rm\b|mv\b|cp\b|ls\b|mkdir|rmdir)\b/.test(text)) {
return 'shell'
}
var dollarVars = text.match(/\$[A-Za-z_]\w*/g)
if (dollarVars && dollarVars.length >= 3 && !/[{}]/.test(text) && !/;/.test(text)) {
return 'shell'
}
}
if (/@[A-Za-z_]\w*\b/.test(text) && /%[A-Za-z_]\w*\b/.test(text)) {
return 'perl'
}
if (/@[A-Za-z_]\w*\b/.test(text) && /\$[A-Za-z_]\w*/.test(text) && !/[{}]/.test(text)) {
return 'perl'
}
if (/\$\{[^}]+\}/.test(text) || /\/[^/]*\$\/[gimsuy]*/.test(text) || /[`]/.test(text)) {
return 'js'
}
if (/\b(const|let|var)\s+\$/.test(text)) {
return 'js'
}
if (/\b(printf|scanf|int main|void main)\b/.test(text) ||
/(^|\W)#\s*(include|define|pragma|import)\b/.test(text)) {
return 'c-like'
}
if (/[{}]/.test(text) && /;/.test(text) && /\b(for|while|if|else|switch|case|return|typedef|struct)\b/.test(text)) {
return 'c-like'
}
return 'unknown'
}
function detectDollarArtifactPattern(code) {
var result = {
isLikelyArtifact: false,
hasTrailingDollarArtifact: false,
reasons: [],
}
var text = String(code || '')
if (!text || text.indexOf('$') === -1) return result
var trailingAfterBrace = text.match(/([;{}])[\t ]*\$(?=[\t ]*(?:\n|$))/g)
if (trailingAfterBrace && trailingAfterBrace.length > 0) {
result.reasons.push('TRAILING_AFTER_BRACE_SEMICOLON:' + trailingAfterBrace.length)
result.hasTrailingDollarArtifact = true
}
var standaloneLines = text.match(/^[\t ]*\$[\t ]*$/gm)
if (standaloneLines && standaloneLines.length > 0) {
result.reasons.push('STANDALONE_LINE:' + standaloneLines.length)
}
var lines = text.split('\n')
var dollarEndLineCount = 0
for (var i = 0; i < lines.length; i++) {
var trimmed = lines[i].trim()
if (trimmed.length > 0 && trimmed.charAt(trimmed.length - 1) === '$' && trimmed.charAt(trimmed.length - 2) !== '\\') {
dollarEndLineCount++
}
}
if (dollarEndLineCount >= 3) {
result.reasons.push('MULTI_LINE_TRAILING_DOLLAR:' + dollarEndLineCount)
}
if (result.hasTrailingDollarArtifact || (standaloneLines && standaloneLines.length > 0)) {
result.isLikelyArtifact = true
}
if (dollarEndLineCount >= 3 && !result.isLikelyArtifact) {
result.isLikelyArtifact = true
}
return result
}
function _removeDollarBeforeEscapedControlInStrings(code) {
var result = ''
var i = 0
var len = code.length
while (i < len) {
var ch = code[i]
if (ch === '/' && i + 1 < len && code[i + 1] === '/') {
var eol = code.indexOf('\n', i)
if (eol === -1) eol = len
result += code.slice(i, eol)
i = eol
continue
}
if (ch === '/' && i + 1 < len && code[i + 1] === '*') {
var endComment = code.indexOf('*/', i + 2)
if (endComment === -1) endComment = len - 2
result += code.slice(i, endComment + 2)
i = endComment + 2
continue
}
if (ch === "'") {
result += ch
i++
while (i < len) {
result += code[i]
if (code[i] === '\\' && i + 1 < len) {
i++
result += code[i]
} else if (code[i] === "'") {
i++
break
}
i++
}
continue
}
if (ch === '"') {
result += ch
i++
while (i < len) {
if (code[i] === '\\') {
result += code[i]
i++
if (i < len) {
result += code[i]
i++
}
continue
}
if (code[i] === '"') {
result += code[i]
i++
break
}
if (code[i] === '$' && i + 2 < len && code[i + 1] === '\\' &&
(code[i + 2] === 'n' || code[i + 2] === 'r' || code[i + 2] === 't')) {
i++
continue
}
result += code[i]
i++
}
continue
}
result += ch
i++
}
return result
}
function sanitizeImportedCodeArtifacts(code) {
var text = String(code || '')
if (!text || text.indexOf('$') === -1) return text
var language = detectCodeLanguageHint(text)
if (language === 'php' || language === 'shell' || language === 'perl') {
return text
}
var artifactInfo = detectDollarArtifactPattern(text)
if (!artifactInfo.isLikelyArtifact) {
return text
}
var dollarBefore = (text.match(/\$/g) || []).length
var result = text.replace(/([;{}])[\t ]*\$(?=[\t ]*(?:\n|$))/g, '$1')
result = result.replace(/^[\t ]*\$[\t ]*$/gm, '')
if (language === 'c-like' && artifactInfo.hasTrailingDollarArtifact) {
result = _removeDollarBeforeEscapedControlInStrings(result)
}
result = result.replace(/\n{3,}/g, '\n\n').replace(/^\n+/, '')
var dollarAfter = (result.match(/\$/g) || []).length
if (typeof console !== 'undefined' && dollarBefore !== dollarAfter) {
console.log('[CODE_ARTIFACT_SANITIZE]', {
removedDollarCount: dollarBefore - dollarAfter,
language: language,
reasons: artifactInfo.reasons,
})
}
return result
}
module.exports = {
reconstructCode: reconstructCode,
containsCode: containsCode,
shouldReconstructCode: shouldReconstructCode,
sanitizeImportedCodeArtifacts: sanitizeImportedCodeArtifacts,
detectCodeLanguageHint: detectCodeLanguageHint,
detectDollarArtifactPattern: detectDollarArtifactPattern,
}
