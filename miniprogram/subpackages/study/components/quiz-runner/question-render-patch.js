function appendRenderPatch(target, q, model, data) {
  var label = q._typeLabel || target._typeLabel(q)
  var codeLines = model.mode === 'CODE' ? target._splitCodeLines(model.rawText) : []
  var mixedBlocks = model.mode === 'MIXED' ? target._decorateMixedBlocks(model.blocks) : []
  var images = []
  var adapter
  try { adapter = require('../../utils/question-runner-adapter') } catch (e) { }
  if (adapter && typeof adapter.computeExtraImages === 'function') {
    images = adapter.computeExtraImages(q)
  } else if (adapter && typeof adapter.getQuestionImages === 'function') {
    images = adapter.getQuestionImages(q)
  } else if (Array.isArray(q.image_url)) {
    images = q.image_url.filter(function(u) { return u && typeof u === 'string' })
  } else if (q.content && Array.isArray(q.content.image_url)) {
    images = q.content.image_url.filter(function(u) { return u && typeof u === 'string' })
  }
  var knownModes = { SEGMENTS: true, RICH_TEXT: true, CODE: true, LATEX: true, MIXED: true }
  var unknownMode = !model.mode || !knownModes[model.mode]
  var fallbackText = ''
  if (unknownMode) {
    fallbackText = q.content && (q.content.text || q.content.stem) || ''
    if (!fallbackText) fallbackText = '该题内容暂时无法显示'
  }
  data._qTypeLabel = label
  data._codeLines = codeLines
  data._mixedBlocks = mixedBlocks
  data._questionImages = images
  data._renderUnknownMode = unknownMode
  data._renderFallbackText = fallbackText
}

module.exports = appendRenderPatch
