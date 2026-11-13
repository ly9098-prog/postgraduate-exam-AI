var { appConfig, questionImageCache } = require('./stem-render-dependencies')
var { _textToHtml, _needsRichRender, _escapeRegExp, _toPlainInlineMathText,
  _buildRichTextNodes, _normalizeLatexDelimiters, _hasLatexDelimiters } = require('./stem-render-text')
var { _stripLeadingOptionLabel, _cleanStemText } = require('./stem-render-options')
var { _segmentsToText, _textToSegments } = require('./stem-render-segments')
var { splitStemBlocks, splitInlineTextAndCode } = require('./stem-render-blocks')
var { RenderDiagnostics, _hashString, _renderDiff } = require('./stem-render-diagnostics')
var { renderModel } = require('./stem-render-model')
var _assetOrigin = (function () {
var base = (appConfig && appConfig.BASE_URL) || ''
var m = base.match(/^(https?:\/\/[^/]+)/)
return m ? m[1] : ''
})()
function _resolveAssetUrl(url) {
if (!url || typeof url !== 'string') return ''
var resolved = url
if (!/^https?:\/\//i.test(resolved) && resolved.charAt(0) === '/' && _assetOrigin) {
resolved = _assetOrigin + resolved
}
return questionImageCache.resolve(resolved)
}
var RENDER_MODE = {
RICH_TEXT: 'RICH_TEXT',
LATEX: 'LATEX',
SEGMENTS: 'SEGMENTS',
CODE: 'CODE',
MIXED: 'MIXED',
}
var diagnostics = new RenderDiagnostics(RENDER_MODE)
function resetRenderGuard() {
  diagnostics.resetRenderGuard()
}
function setRenderGuardPage(page) {
  diagnostics.setRenderGuardPage(page)
}
function buildRenderModel(q, options, cfg) {
  return renderModel(q, options, cfg, RENDER_MODE, diagnostics)
}
function _optionTextToHtml(key, value) {
var text = String(value || '').trim()
if (!key) return _textToHtml(text)
var keyPattern = new RegExp('^' + _escapeRegExp(String(key)) + '[\\s\\u00A0]*[.。．、:：）)]?\\s*', 'i')
var normalized = keyPattern.test(text) ? text : key + '. ' + text
return _textToHtml(normalized)
}
function buildOptionList(opts, optionKeys, selectedFlags) {
return (optionKeys || []).map(function (key) {
var optValue = (opts && opts[key]) || ''
var optSegments = typeof optValue === 'object' && optValue !== null ? (optValue.segments || null) : null
var optText = ''
if (optSegments && Array.isArray(optSegments) && optSegments.length > 0) {
optText = _segmentsToText(optSegments)
} else if (typeof optValue === 'object' && optValue !== null) {
optText = optValue.text || optValue.value || ''
} else {
optText = String(optValue)
}
var optionText = _stripLeadingOptionLabel(key, optText)
var cleanedOptionText = optionText.replace(/[\r\n]+/g, ' ')
var plainOptionText = _toPlainInlineMathText(cleanedOptionText)
var needsRich = !plainOptionText && _needsRichRender(cleanedOptionText)
var resolvedSegments = null
if (optSegments && Array.isArray(optSegments) && optSegments.length > 0) {
resolvedSegments = optSegments.map(function (seg) {
if (!seg || typeof seg !== 'object') return seg
if (seg.url) return Object.assign({}, seg, { url: _resolveAssetUrl(seg.url) })
return seg
})
}
return {
key: key,
_selected: !!(selectedFlags || {})[key],
_text: plainOptionText || cleanedOptionText,
_segments: resolvedSegments,
_needsRich: !optSegments && needsRich,
_html: !optSegments && needsRich ? _textToHtml(cleanedOptionText) : ''
}
})
}
module.exports = {
RENDER_MODE: RENDER_MODE,
buildRenderModel: buildRenderModel,
resetRenderGuard: resetRenderGuard,
setRenderGuardPage: setRenderGuardPage,
buildOptionList: buildOptionList,
optionTextToHtml: _optionTextToHtml,
toPlainInlineMathText: _toPlainInlineMathText,
needsRichRender: _needsRichRender,
stripLeadingOptionLabel: _stripLeadingOptionLabel,
computeCodeHash: _hashString,
renderDiff: _renderDiff,
cleanStemText: _cleanStemText,
textToHtml: _textToHtml,
normalizeLatexDelimiters: _normalizeLatexDelimiters,
hasLatexDelimiters: _hasLatexDelimiters,
buildRichTextNodes: _buildRichTextNodes,
segmentsToText: _segmentsToText,
textToSegments: _textToSegments,
splitStemBlocks: splitStemBlocks,
splitInlineTextAndCode: splitInlineTextAndCode,
resolveAssetUrl: _resolveAssetUrl,
}
