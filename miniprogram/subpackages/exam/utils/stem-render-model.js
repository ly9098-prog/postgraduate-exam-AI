var { appConfig, containsCode, shouldReconstructCode, reconstructCode,
  sanitizeImportedCodeArtifacts, tableStructure } = require('./stem-render-dependencies')
var { _repairFalseNumberMarkerBreaks, _toPlainInlineMathText,
  _toPlainSimpleInlineMathText, _buildRichTextNodes, _textToHtml } = require('./stem-render-text')
var { _cleanStemText } = require('./stem-render-options')
var { _segmentsToText, _segmentsAgreeWithCanonicalStem, _hasCodeSegments,
  _repairFalseRangeBreaksInSegments, _textToSegments,
  _stemIsRepresentedByCodeSegment } = require('./stem-render-segments')
var { splitStemBlocks, containsUnresolvedLatex } = require('./stem-render-blocks')
var { _hashStem, _renderDiff, _reportDiff } = require('./stem-render-diagnostics')

function prepareStem(q, options) {
  var content = q && q.content
  var optionKeys = options ? Object.keys(options) : []
  var stemText = typeof content === 'string'
    ? content
    : ((content && (content.text || content.stem)) || '')
  var sourceStemText = stemText || (content && _segmentsToText(content.segments)) || ''
  sourceStemText = _repairFalseNumberMarkerBreaks(sourceStemText)
  var cleanedStem = _cleanStemText(sourceStemText, options, optionKeys)
  var stemHash = _hashStem(cleanedStem)
  return {
    content, optionKeys, stemText, sourceStemText, cleanedStem, stemHash,
    mode: undefined, richTextNodes: undefined, html: undefined,
    segments: undefined, rawText: undefined, blocks: undefined,
  }
}

function renderSegments(state, modes) {
  var content = state.content
  state.mode = modes.SEGMENTS
  state.segments = (content.segments && content.segments.length > 0)
    ? _repairFalseRangeBreaksInSegments(content.segments)
    : _textToSegments(state.cleanedStem)
  var hasTextualSegment = state.segments.some(function (segment) {
    var type = segment && typeof segment === 'object'
      ? String(segment.type || '').trim().toLowerCase() : ''
    return type === 'text' || type === 'newline'
  })
  if (!hasTextualSegment && state.stemText && state.cleanedStem &&
      !_stemIsRepresentedByCodeSegment(state.segments, state.cleanedStem)) {
    state.segments = _textToSegments(state.cleanedStem).concat(state.segments)
  }
  state.richTextNodes = []
  state.html = ''
  state.blocks = []
}

function renderRichTextBlock(text) {
  var plain = _toPlainInlineMathText(text) || _toPlainSimpleInlineMathText(text) || text
  return { type: 'RICH_TEXT', richTextNodes: _buildRichTextNodes(plain) }
}

function renderLatexBlock(text) {
  return { type: 'LATEX', html: _textToHtml(text) }
}

function renderCodeBlock(text, cfg) {
  var sanitized = sanitizeImportedCodeArtifacts(text)
  var rawText = sanitized
  if (!cfg || !cfg.DISABLE_CODE_RECONSTRUCT) {
    if (shouldReconstructCode(sanitized)) {
      rawText = reconstructCode(sanitized,
        { fixOperators: false, fixStructure: true, fixIndent: false })
    }
  }
  return { type: 'CODE', rawText: rawText }
}

function renderMixed(state, stemBlocks, config, modes) {
  state.mode = modes.MIXED
  state.blocks = []
  for (var i = 0; i < stemBlocks.length; i++) {
    var block = stemBlocks[i]
    if (block.type === 'CODE') {
      state.blocks.push(renderCodeBlock(block.text, config))
    } else if (block.type === 'LATEX') {
      state.blocks.push(renderLatexBlock(block.text))
    } else {
      state.blocks.push(renderRichTextBlock(block.text))
    }
  }
  state.richTextNodes = []
  state.html = ''
  state.rawText = ''
  state.segments = []
}

function hasLatexCommands(cleanedStem) {
  if (/\$\$[\s\S]*?\$\$/.test(cleanedStem)) return true
  var latexMatches = cleanedStem.match(/\\[a-zA-Z]+/g)
  if (!latexMatches) return false
  var cEscapes = { n: true, t: true, r: true }
  for (var i = 0; i < latexMatches.length; i++) {
    var cmd = latexMatches[i].slice(1)
    if (cmd.length > 2 || !cEscapes[cmd]) return true
  }
  return false
}

function renderPlain(state, text, modes) {
  state.mode = modes.RICH_TEXT
  state.richTextNodes = _buildRichTextNodes(text)
  state.html = ''
  state.segments = []
  state.blocks = []
  state.rawText = ''
}

function renderCode(state, q, config, modes) {
  state.mode = modes.CODE
  var sanitizedCode = sanitizeImportedCodeArtifacts(state.cleanedStem)
  var codeText = sanitizedCode
  if (!config.DISABLE_CODE_RECONSTRUCT && shouldReconstructCode(sanitizedCode)) {
    codeText = reconstructCode(sanitizedCode,
      { fixOperators: false, fixStructure: true, fixIndent: false })
  }
  state.rawText = codeText
  state.html = ''
  state.richTextNodes = []
  state.segments = []
  state.blocks = []
  var diffIssues = _renderDiff(state.sourceStemText, state.cleanedStem)
  if (diffIssues.length > 0) _reportDiff(diffIssues, q && q.id)
}

function renderSingle(state, q, config, modes) {
  var hasLatex = hasLatexCommands(state.cleanedStem)
  var selfHealCode = config.SAFE_MODE && containsCode(state.cleanedStem)
  var plainStem = _toPlainInlineMathText(state.cleanedStem) ||
    _toPlainSimpleInlineMathText(state.cleanedStem)
  var converted = typeof plainStem === 'string' && plainStem.length > 0 &&
    !containsUnresolvedLatex(plainStem)
  if (converted && !containsCode(state.cleanedStem)) {
    renderPlain(state, plainStem, modes)
  } else if (hasLatex && !selfHealCode) {
    state.mode = modes.LATEX
    state.html = _textToHtml(state.cleanedStem)
    state.richTextNodes = []
    state.segments = []
    state.blocks = []
  } else if (containsCode(state.cleanedStem)) {
    renderCode(state, q, config, modes)
  } else {
    // Keep the fallback's second conversion attempt and its original timing.
    state.mode = modes.RICH_TEXT
    var fallback = _toPlainInlineMathText(state.cleanedStem) ||
      _toPlainSimpleInlineMathText(state.cleanedStem) || state.cleanedStem
    state.richTextNodes = _buildRichTextNodes(fallback)
    state.html = ''
    state.segments = []
    state.blocks = []
    state.rawText = ''
  }
}

function selectPayload(state, q, options, config, modes) {
  var content = state.content
  var agrees = !content || _segmentsAgreeWithCanonicalStem(
    content.segments, state.cleanedStem, options, state.optionKeys)
  if (content && content.render_mode === 'segments' && agrees &&
      (config.enableMathImage || tableStructure.hasTableSegments(content.segments) ||
        _hasCodeSegments(content.segments))) {
    renderSegments(state, modes)
    return
  }
  var stemBlocks = splitStemBlocks(state.cleanedStem)
  var blockTypes = []
  for (var i = 0; i < stemBlocks.length; i++) {
    var type = stemBlocks[i].type
    if (blockTypes.indexOf(type) === -1) blockTypes.push(type)
  }
  if (blockTypes.length > 1) renderMixed(state, stemBlocks, config, modes)
  else renderSingle(state, q, config, modes)
}

function finishModel(model, config, modes, q) {
  var trace = model.renderTrace
  if (config.DEV && model.mode === modes.CODE) {
    if (trace.codeHashBefore !== trace.codeHashAfter) {
      console.warn(
        '[RENDER_TRACE] CODE hash changed for q' + (q && q.id) + '\n' +
        '  hashBefore: ' + trace.codeHashBefore + '\n' +
        '  hashAfter:  ' + trace.codeHashAfter + '\n' +
        '  newlines:   ' + trace.newlineCountBefore + ' → ' + trace.newlineCountAfter
      )
    }
  }
  if (config.DEV) {
    try { Object.freeze(model) } catch (_) { }
  }
  return model
}

function renderModel(q, options, cfg, modes, diagnostics) {
  var config = cfg || appConfig
  var state = prepareStem(q, options)
  selectPayload(state, q, options, config, modes)
  diagnostics._devAssertSinglePath(state.cleanedStem, state.content, state.mode)
  diagnostics._assertCodeRenderIntegrity(
    state.mode, state.cleanedStem, state.html, state.richTextNodes, state.blocks)
  diagnostics._assertBlockPayloadIntegrity(state.blocks)
  diagnostics._renderGuardCheck(q && q.id, state.stemHash, state.mode)
  var renderTrace = diagnostics._buildRenderTrace(
    q && q.id, state.sourceStemText, state.mode, state.cleanedStem, state.blocks)
  var model = {
    mode: state.mode,
    richTextNodes: state.richTextNodes || [],
    html: state.html || '',
    segments: state.segments || [],
    rawText: state.rawText || '',
    blocks: state.blocks || [],
    renderTrace: renderTrace,
  }
  diagnostics._assertExclusiveRenderPayload(model)
  return finishModel(model, config, modes, q)
}

module.exports = { renderModel }
