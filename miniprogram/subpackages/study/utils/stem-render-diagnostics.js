var { appConfig, containsCode } = require('./stem-render-dependencies')
var { _needsRichRender } = require('./stem-render-text')

function _hashString(str) {
var h = 0
var s = String(str || '')
for (var i = 0; i < s.length; i++) {
h = ((h << 5) - h + s.charCodeAt(i)) | 0
}
return h
}
function _hashStem(text) { return _hashString(text) }
function _renderDiff(original, rendered) {
var issues = []
if (!original && !rendered) return issues
var origLines = String(original || '').split('\n')
var rendLines = String(rendered || '').split('\n')
if (origLines.length !== rendLines.length) {
issues.push({
type: 'NEWLINE_MISMATCH',
detail: 'Line count: ' + origLines.length + ' → ' + rendLines.length,
})
}
var maxLines = Math.min(origLines.length, rendLines.length)
for (var i = 0; i < maxLines; i++) {
var orig = origLines[i]
var rend = rendLines[i]
var origIndent = orig.match(/^(\s*)/)[1]
var rendIndent = rend.match(/^(\s*)/)[1]
if (origIndent !== rendIndent) {
issues.push({
type: 'INDENT_MISMATCH',
line: i + 1,
detail: 'indent ' + JSON.stringify(origIndent) + ' → ' + JSON.stringify(rendIndent),
})
}
var origContent = orig.slice(origIndent.length).replace(/\s+$/, '').replace(/\s+/g, ' ')
var rendContent = rend.slice(rendIndent.length).replace(/\s+$/, '').replace(/\s+/g, ' ')
if (origContent !== rendContent) {
issues.push({
type: 'CONTENT_MISMATCH',
line: i + 1,
detail: JSON.stringify(origContent) + ' → ' + JSON.stringify(rendContent),
})
}
}
return issues
}
function _reportDiff(diffIssues, questionId) {
if (!appConfig.DEV || diffIssues.length === 0) return
console.warn(
'[RENDER_REGRESSION] CODE diff found ' + diffIssues.length + ' issue(s) for q' + questionId + '\n' +
diffIssues.map(function (d) {
return '  [' + d.type + '] line=' + (d.line || '-') + ' ' + d.detail
}).join('\n')
)
}

class RenderDiagnostics {
  constructor(RENDER_MODE) {
    this.RENDER_MODE = RENDER_MODE
    this._renderGuardState = {}
    this._activePage = 'unknown'
  }
resetRenderGuard() {
this._renderGuardState = {}
}
setRenderGuardPage(page) {
this._activePage = page
}
_renderGuardCheck(questionId, stemHash, mode) {
if (!appConfig.DEV) return
if (!questionId || !stemHash) return
var key = String(questionId)
var entry = this._renderGuardState[key]
if (!entry) {
this._renderGuardState[key] = { page: this._activePage, hash: stemHash, mode: mode, count: 1 }
return
}
entry.count++
if (entry.hash === stemHash && entry.mode !== mode) {
console.error(
'[RENDER_INVARIANT_VIOLATION] Same stem (hash=' + stemHash +
') got different render modes across renders\n' +
'  page: ' + this._activePage + '\n' +
'  questionId: ' + questionId + '\n' +
'  previous mode: ' + entry.mode + ' (call #' + (entry.count - 1) + ')\n' +
'  current mode:  ' + mode + ' (call #' + entry.count + ')\n' +
'  This indicates a render path conflict. Check buildRenderModel() decision tree.'
)
}
if (entry.hash !== stemHash) {
this._renderGuardState[key] = { page: this._activePage, hash: stemHash, mode: mode, count: entry.count }
}
}
_devAssertSinglePath(cleanedStem, content, resultMode) {
if (!appConfig.DEV) return
var modeFlags = []
if (appConfig.enableMathImage && content && content.render_mode === 'segments') modeFlags.push('SEGMENTS')
var hasLatex = (function() {
var t = cleanedStem
if (/\$\$[\s\S]*?\$\$/.test(t)) return true
var matches = t.match(/\\[a-zA-Z]+/g)
if (!matches) return false
var cEscapes = { n: true, t: true, r: true }
for (var i = 0; i < matches.length; i++) {
var c = matches[i].slice(1)
if (c.length > 2 || !cEscapes[c]) return true
}
return false
})()
if (hasLatex) modeFlags.push('LATEX')
if (!hasLatex && !containsCode(cleanedStem) && _needsRichRender(cleanedStem)) modeFlags.push('RICH_TEXT')
var isCodePath = resultMode === this.RENDER_MODE.CODE || resultMode === this.RENDER_MODE.MIXED
if (!isCodePath && modeFlags.length > 1) {
console.error(
'[RENDER_INVARIANT_VIOLATION] Stem satisfies multiple render conditions: ' + modeFlags.join(', ') + '\n' +
'  selected mode: ' + resultMode + '\n' +
'  source tail: ' + cleanedStem.slice(-80)
)
}
}
_assertCodeRenderIntegrity(mode, rawText, html, richTextNodes, blocks) {
if (!appConfig.DEV) return
if (mode === this.RENDER_MODE.MIXED) {
if (!blocks || blocks.length === 0) {
console.error(
'[MIXED_RENDER_VIOLATION] MIXED mode has empty blocks array'
)
return
}
for (var i = 0; i < blocks.length; i++) {
var block = blocks[i]
if (block.type === 'CODE') {
if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(String(block.rawText || ''))) {
console.error(
'[CODE_HTML_LEAK] MIXED CODE block #' + i + ' contains HTML entities\n' +
'  rawText tail: ' + String(block.rawText).slice(-80)
)
}
}
}
return
}
if (mode !== this.RENDER_MODE.CODE) return
if (html.length > 0 || richTextNodes.length > 0) {
console.error(
'[CODE_RENDER_VIOLATION] CODE mode has non-empty html or richTextNodes\n' +
'  html.length: ' + html.length + '\n' +
'  richTextNodes.length: ' + richTextNodes.length + '\n' +
'  CODE must render via <text> only (zero-HTML path)'
)
}
var text = String(rawText || '')
if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(text)) {
console.error(
'[CODE_HTML_LEAK] CODE rawText contains HTML entities\n' +
'  rawText tail: ' + text.slice(-80) + '\n' +
'  CODE must preserve raw characters, not HTML-encoded forms'
)
}
}
_assertExclusiveRenderPayload(model) {
if (!appConfig.DEV) return
var m = model || {}
var mode = m.mode
var active = 0
if (mode === this.RENDER_MODE.RICH_TEXT) {
active += m.richTextNodes && m.richTextNodes.length ? 1 : 0
if (m.html || m.rawText || (m.blocks && m.blocks.length)) {
console.error('[RENDER_PAYLOAD_CONFLICT] RICH_TEXT has extra payload')
}
}
if (mode === this.RENDER_MODE.LATEX) {
active += m.html ? 1 : 0
if ((m.richTextNodes && m.richTextNodes.length) || m.rawText || (m.blocks && m.blocks.length)) {
console.error('[RENDER_PAYLOAD_CONFLICT] LATEX has extra payload')
}
}
if (mode === this.RENDER_MODE.CODE) {
active += m.rawText ? 1 : 0
if (m.html || (m.richTextNodes && m.richTextNodes.length) || (m.blocks && m.blocks.length)) {
console.error('[RENDER_PAYLOAD_CONFLICT] CODE has extra payload')
}
}
if (mode === this.RENDER_MODE.MIXED) {
active += m.blocks && m.blocks.length ? 1 : 0
if (m.html || m.rawText || (m.richTextNodes && m.richTextNodes.length)) {
console.error('[RENDER_PAYLOAD_CONFLICT] MIXED has top-level payload')
}
}
if (mode === this.RENDER_MODE.SEGMENTS) {
active += m.segments && m.segments.length ? 1 : 0
if (m.html || m.rawText || (m.richTextNodes && m.richTextNodes.length) || (m.blocks && m.blocks.length)) {
console.error('[RENDER_PAYLOAD_CONFLICT] SEGMENTS has extra payload')
}
}
if (active !== 1) {
console.error('[RENDER_PAYLOAD_CONFLICT] expected exactly one active payload for mode=' + mode)
}
}
_assertBlockPayloadIntegrity(blocks) {
if (!appConfig.DEV || !Array.isArray(blocks)) return
for (var i = 0; i < blocks.length; i++) {
var b = blocks[i]
if (b.type === 'RICH_TEXT' && !(b.richTextNodes && b.richTextNodes.length)) {
console.error('[BLOCK_PAYLOAD] RICH_TEXT block #' + i + ' missing richTextNodes')
}
if (b.type === 'LATEX' && !b.html) {
console.error('[BLOCK_PAYLOAD] LATEX block #' + i + ' missing html')
}
if (b.type === 'CODE' && !b.rawText) {
console.error('[BLOCK_PAYLOAD] CODE block #' + i + ' missing rawText')
}
}
}
_buildRenderTrace(questionId, sourceStem, mode, cleanedStem, blocks) {
var trace = {
questionId: questionId,
timestamp: Date.now(),
renderType: mode,
pipeline: ['detect', 'route', 'render'],
}
if (mode === this.RENDER_MODE.CODE) {
var before = String(sourceStem || '')
var after = String(cleanedStem || '')
trace.codeHashBefore = _hashString(before)
trace.codeHashAfter = _hashString(after)
trace.newlineCountBefore = (before.match(/\n/g) || []).length
trace.newlineCountAfter = (after.match(/\n/g) || []).length
trace.stemLengthBefore = before.length
trace.stemLengthAfter = after.length
}
if (mode === this.RENDER_MODE.MIXED && Array.isArray(blocks)) {
trace.blockTypes = blocks.map(function (b) { return b.type })
}
return trace
}
}
module.exports = { RenderDiagnostics, _hashString, _hashStem, _renderDiff, _reportDiff }
