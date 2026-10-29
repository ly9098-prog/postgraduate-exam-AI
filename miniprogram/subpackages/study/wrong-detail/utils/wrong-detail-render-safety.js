function _checkRenderInvariant(page, renderModel) {
if (!renderModel) return
if (renderModel.mode === 'CODE' && renderModel.rawText) {
var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
if (hasHtmlLeak) {
console.error('[CODE_HTML_LEAK] wrong-detail CODE rawText contains HTML entities')
}
var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
if (hasRenderViolation) {
console.error('[CODE_RENDER_VIOLATION] wrong-detail CODE mode leaked into html/richTextNodes')
}
if ((hasHtmlLeak || hasRenderViolation) && !page.data.safeModeActive) {
page._enterSafeMode()
}
}
if (renderModel.mode === 'MIXED') {
if (!renderModel.blocks || renderModel.blocks.length === 0) {
console.error('[MIXED_RENDER_VIOLATION] wrong-detail MIXED mode but blocks is empty')
return
}
for (var mi = 0; mi < renderModel.blocks.length; mi++) {
var mBlock = renderModel.blocks[mi]
if (mBlock.type === 'CODE' && mBlock.rawText) {
if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
console.error('[CODE_HTML_LEAK] wrong-detail MIXED CODE block #' + mi + ' contains HTML entities')
}
}
}
}
}

function _recordRenderTrace(page, trace, deps) {
if (!trace || !deps.config.debug) return
if (!Array.isArray(page.data.renderTraces)) return
var traces = page.data.renderTraces.concat([trace]).slice(-20)
page.setData({ renderTraces: traces })
}

function _enterSafeMode(page, deps) {
console.warn('[SELF_HEAL] wrong-detail CODE render violation — entering SAFE_MODE')
page.setData({ safeModeActive: true })
if (page.data.wq) {
var raw = deps._processWqData(page.data.wq, true)
if (raw._renderModel) {
var currentQuestion = Object.assign({}, page.data.wq, {
_optionList: raw._optionList,
_optionKeys: raw._optionKeys,
_opts: raw._opts,
_blankOptionGroups: raw._blankOptionGroups,
_hasBlankOptionGroups: raw._blankOptionGroups.length > 0,
_renderModel: raw._renderModel,
})
page._errorTypeLabelText = raw.errorTypeLabelText
page.setData({
currentQuestion,
subjectLabelText: raw.subjectLabelText,
})
console.warn('[SELF_HEAL] wrong-detail re-rendered in SAFE_MODE, mode=' + raw._renderModel.mode)
}
}
}

module.exports = { _checkRenderInvariant, _recordRenderTrace, _enterSafeMode }
