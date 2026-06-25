/**
 * =============================================================================
 * STEM RENDER INVARIANT MODULE
 * =============================================================================
 *
 * Centralized render-mode decision for all question stems in the miniprogram.
 *
 * RENDER MODES (in priority order):
 *   SEGMENTS  — Uses <math-question> component with pre-rendered formula images.
 *               Applicable only when config.enableMathImage=true AND
 *               content.render_mode === 'segments'.
 *   RICH_TEXT — Uses native <rich-text> with programmatic nodes. Applicable when
 *               stem has newlines or HTML tags but NO LaTeX (no $$, no \commands).
 *               Also handles plain single-line text (Unicode math conversion).
 *   LATEX     — Uses <mp-html> with KaTeX plugin. Applicable when stem contains
 *               display math ($$...$$) or complex LaTeX commands (\frac, \sqrt, etc.).
 *
 * THIRD-PARTY COMPONENT ADMISSION RULES:
 *   When introducing a new render component (e.g., markdown, table-render):
 *   1. DECLARE input format: What string format does the component consume?
 *   2. DECLARE applicability scope: Which question types/subjects use it?
 *   3. DECLARE fallback path: What happens if the component fails to render?
 *   4. CANNOT be the default fallback renderer. RICH_TEXT is always the
 *      universal fallback. New components must have a specific, narrow scope.
 *   5. Add a new RENDER_MODE constant and a priority-check branch in
 *      buildRenderModel() BEFORE the RICH_TEXT fallback.
 *   6. Must update ALL pages' WXML templates in the same commit (see docs/render-invariant.md).
 *
 * RENDER INVARIANT:
 *   For a given cleaned stem text, exactly ONE render mode must be selected.
 *   If the same stem hash produces different modes across renders, RenderGuard
 *   emits a console.error in DEV mode.
 *
 * RenderModel is IMMUTABLE. Pages must not modify mode, richTextNodes, html, or segments.
 * New rendering capabilities must be added here, never patched at the page layer.
 * =============================================================================
 */

var appConfig = require('../config')
var { formatInlineMathText, replaceSimpleLatexCommands } = require('./math-format')
var { containsCode } = require('./code-reconstructor')

var RENDER_MODE = {
  RICH_TEXT: 'RICH_TEXT',
  LATEX: 'LATEX',
  SEGMENTS: 'SEGMENTS',
  CODE: 'CODE',
}

// ---- render guard ----

var _renderGuardState = {}
var _activePage = 'unknown'

function resetRenderGuard() {
  _renderGuardState = {}
}

function setRenderGuardPage(page) {
  _activePage = page
}

function _renderGuardCheck(questionId, stemHash, mode) {
  if (!appConfig.DEV) return
  if (!questionId || !stemHash) return

  var key = String(questionId)
  var entry = _renderGuardState[key]
  if (!entry) {
    _renderGuardState[key] = { page: _activePage, hash: stemHash, mode: mode, count: 1 }
    return
  }

  entry.count++
  if (entry.hash === stemHash && entry.mode !== mode) {
    console.error(
      '[RENDER_INVARIANT_VIOLATION] Same stem (hash=' + stemHash +
      ') got different render modes across renders\n' +
      '  page: ' + _activePage + '\n' +
      '  questionId: ' + questionId + '\n' +
      '  previous mode: ' + entry.mode + ' (call #' + (entry.count - 1) + ')\n' +
      '  current mode:  ' + mode + ' (call #' + entry.count + ')\n' +
      '  This indicates a render path conflict. Check buildRenderModel() decision tree.'
    )
  }
  if (entry.hash !== stemHash) {
    _renderGuardState[key] = { page: _activePage, hash: stemHash, mode: mode, count: entry.count }
  }
}

// ---- text processing ----

function _formatHtmlTextSegment(text) {
  return String(text || '').split('\n').map(function (line) {
    var escaped = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    if (/(```|[{};=]|\/\/)/.test(line)) return escaped.replace(/\t/g, '    ').replace(/ /g, '&nbsp;')
    return escaped.replace(/ {2,}/g, function (spaces) { return ' ' + '&nbsp;'.repeat(spaces.length - 1) })
  }).join('<br>')
}

function _textToHtml(text) {
  if (!text) return ''
  var parts = text.split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/)
  var out = parts.map(function (part, i) {
    if (i % 2 === 1) return part.replace(/\\(n|t|r)(?![a-zA-Z])/g, ' ')
    return _formatHtmlTextSegment(part)
  })
  return '<p>' + out.join('') + '</p>'
}

function _deduplicateLines(text) {
  if (!text) return text
  var lines = text.split('\n')
  var out = []
  for (var i = 0; i < lines.length; i++) {
    if (i === 0 || lines[i].trim() !== lines[i - 1].trim()) {
      out.push(lines[i])
    }
  }
  return out.join('\n')
}

function _trimEmptyLines(lines) {
  var start = 0
  var end = lines.length
  while (start < end && !String(lines[start]).trim()) start++
  while (end > start && !String(lines[end - 1]).trim()) end--
  return lines.slice(start, end)
}

function _sameNormalizedLines(left, right) {
  if (left.length !== right.length || left.length === 0) return false
  for (var i = 0; i < left.length; i++) {
    if (String(left[i]).trim() !== String(right[i]).trim()) return false
  }
  return true
}

function _deduplicateRepeatedText(text) {
  if (!text) return text
  var stripped = String(text).trim()
  var half = Math.floor(stripped.length / 2)
  if (half > 0) {
    if (stripped.slice(0, half) === stripped.slice(half)) return stripped.slice(0, half).replace(/\n+$/, '').trim()
    var candidate = stripped.slice(0, half).trim()
    if (candidate && stripped.slice(half).trim() === candidate) return candidate

    // Fuzzy half-string match: compare with normalized content (handles OCR punctuation drift)
    var leftNorm = String(stripped.slice(0, half)).replace(/\s+/g, '').replace(/[，。、；：！？,.;:!?…—·"''""（）()【】《》<>]/g, '').trim()
    var rightNorm = String(stripped.slice(half)).replace(/\s+/g, '').replace(/[，。、；：！？,.;:!?…—·"''""（）()【】《》<>]/g, '').trim()
    if (leftNorm && leftNorm === rightNorm) {
      return stripped.slice(0, half).replace(/\n+$/, '').trim()
    }

    // Sentence-boundary fuzzy dedup: try splitting at sentence endings near the midpoint
    // Handles single-line duplicates where half-string cut doesn't align with sentence boundary
    var _normPuncRe = /[，。、；：！？,.;:!?…—·"''""（）()【】《》<>]/g
    var _sentenceEndRe = /[。！？；\n]/g
    var _sMatch
    while ((_sMatch = _sentenceEndRe.exec(stripped)) !== null) {
      var _sPos = _sMatch.index + 1  // position after the sentence-ending char
      if (Math.abs(_sPos - half) <= Math.floor(half * 0.35)) {
        var _sLeft = stripped.slice(0, _sPos).trim()
        var _sRight = stripped.slice(_sPos).trim()
        if (_sLeft && _sRight) {
          var _sLeftNorm = _sLeft.replace(/\s+/g, '').replace(_normPuncRe, '')
          var _sRightNorm = _sRight.replace(/\s+/g, '').replace(_normPuncRe, '')
          if (_sLeftNorm && _sLeftNorm === _sRightNorm) {
            return _sLeft
          }
        }
      }
    }
  }

  var lines = stripped.split('\n')
  // Line-level dedup with exact normalized comparison
  for (var split = 1; split < lines.length; split++) {
    var left = _trimEmptyLines(lines.slice(0, split))
    var right = _trimEmptyLines(lines.slice(split))
    if (_sameNormalizedLines(left, right)) return left.join('\n').trim()
  }

  // Line-level dedup with fuzzy comparison (handles minor punctuation drift between copies)
  for (var split2 = 2; split2 < lines.length; split2++) {
    var left2 = _trimEmptyLines(lines.slice(0, split2))
    var right2 = _trimEmptyLines(lines.slice(split2))
    if (left2.length === right2.length && left2.length > 0) {
      var allMatch = true
      for (var li = 0; li < left2.length; li++) {
        var ln = String(left2[li]).trim().replace(/\s+/g, '').replace(/[，。、；：！？,.;:!?…—·"''""（）()【】《》<>]/g, '')
        var rn = String(right2[li]).trim().replace(/\s+/g, '').replace(/[，。、；：！？,.;:!?…—·"''""（）()【】《》<>]/g, '')
        if (ln !== rn) { allMatch = false; break }
      }
      if (allMatch) return left2.join('\n').trim()
    }
  }

  // Paragraph-level dedup: if content splits into paragraphs and the first
  // matches the last (by normalized content), keep only unique paragraphs.
  if (lines.length >= 4) {
    var paragraphs = stripped.split(/\n\n+/)
    if (paragraphs.length >= 2) {
      var firstPara = paragraphs[0].trim()
      var lastPara = paragraphs[paragraphs.length - 1].trim()
      var firstNorm = firstPara.replace(/\s+/g, '')
      var lastNorm = lastPara.replace(/\s+/g, '')
      if (firstNorm && firstNorm === lastNorm) {
        paragraphs.pop()
        return paragraphs.join('\n\n').trim()
      }
    }
  }

  return stripped
}

function _needsRichRender(text) {
  if (!text) return false
  return /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/.test(text) || /<\/?[a-z][\s\S]*>/i.test(text) || /\n/.test(text)
}

function _escapeRegExp(text) {
  return String(text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function _toPlainInlineMathText(text) {
  if (!text) return ''
  var source = String(text)
  if (/\n/.test(source)) return null
  if (/\$\$[\s\S]*?\$\$/.test(source) || /<\/?[a-z][\s\S]*>/i.test(source)) return null
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

function _stripLeadingOptionLabel(key, value) {
  var text = String(value || '').trim()
  if (!key || !text) return text
  var label = _escapeRegExp(String(key).trim())
  var labelPattern = new RegExp('^' + label + '[\\s\\u00A0]*[.。．、:：）)]\\s*', 'i')
  if (/^\s*\$/.test(text)) {
    var inner = text.replace(/^\s*\$\s*/, '')
    return '$' + inner.replace(labelPattern, '')
  }
  return text.replace(labelPattern, '')
}

function _normalizeOptionText(text) {
  return String(text || '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function _buildOptionPattern(key, value) {
  var label = _escapeRegExp(String(key || '').trim())
  var normalizedValue = _normalizeOptionText(value)
  if (!label || !normalizedValue) return ''

  var spaces = '[\\s\\u00A0]*'
  var separator = '[.。．、:：）)]'
  var valuePattern = _escapeRegExp(normalizedValue).replace(/\s+/g, '[\\s\\u00A0]+')
  return '' + label + spaces + separator + spaces + valuePattern
}

function _stripEmbeddedOptionBlock(stemText, options) {
  if (!stemText || !options) return stemText
  var patterns = Object.keys(options)
    .sort()
    .map(function (key) { return _buildOptionPattern(key, options[key]) })
    .filter(Boolean)

  if (patterns.length < 2) return stemText

  var gap = '(?:\\s|<br>|\\n|\\r|&nbsp;)*'
  var blockRegex = new RegExp('' + gap + patterns.join(gap) + '\\s*$', 'i')
  return blockRegex.test(stemText) ? stemText.replace(blockRegex, '').trim() : stemText
}

function _findOptionLabelMatches(text, optionKeys) {
  if (!text || !optionKeys || optionKeys.length < 2) return []
  var labels = optionKeys.map(_escapeRegExp).join('|')
  var labelMarker = '(?:^|[\\s\\n\\r])(?:' + labels + ')[\\s\\u00A0]*[.。．、:：）)]'
  var labelRegex = new RegExp(labelMarker, 'g')
  var matches = []
  var match
  while ((match = labelRegex.exec(text)) !== null) {
    var index = match.index + (match[0].match(/^[\s\n\r]/) ? 1 : 0)
    matches.push(index)
  }
  return matches
}

function _hasTrailingOptionBlock(text, optionKeys) {
  if (!text || !optionKeys || optionKeys.length < 2) return false
  var keys = optionKeys.map(function (key) { return String(key || '').trim() }).filter(Boolean)
  if (keys.length < 2) return false

  var spaces = '[\\s\\u00A0]*'
  var separator = '[.。．、:：）)]'
  var marker = function (key, prefix) { return '' + prefix + _escapeRegExp(key) + spaces + separator }
  var first = marker(keys[0], '^' + spaces)
  var second = marker(keys[1], '[\\s\\n\\r]+')
  var required = new RegExp(first + '[\\s\\S]+?' + second, 'i')
  if (!required.test(text)) return false

  var labels = keys.map(_escapeRegExp).join('|')
  var labelRegex = new RegExp('(?:^|[\\s\\n\\r])(?:' + labels + ')' + spaces + separator, 'g')
  var found = []
  var match
  while ((match = labelRegex.exec(text)) !== null) {
    found.push(String(match[0]).replace(/^[\s\n\r]+/, '').charAt(0).toUpperCase())
  }
  if (found.length < 2) return false
  return found[0] === keys[0].toUpperCase() && found[1] === keys[1].toUpperCase()
}

function _stripTrailingOptionBlockByLabels(stemText, optionKeys) {
  if (!stemText || !optionKeys || optionKeys.length < 2) return stemText
  var matches = _findOptionLabelMatches(stemText, optionKeys)

  if (matches.length < 2) return stemText

  for (var i = 0; i < matches.length; i++) {
    var suffix = stemText.slice(matches[i])
    if (_hasTrailingOptionBlock(suffix, optionKeys)) return stemText.slice(0, matches[i]).trim()
  }

  return stemText
}

function _removeTrailingOptionKeys(text, optionKeys) {
  if (!text || !optionKeys || optionKeys.length === 0) return text
  var keys = optionKeys.map(_escapeRegExp).join('')
  var pattern = new RegExp('\\s+[' + keys + ']\\s*$', 'g')
  return text.replace(pattern, '')
}

function _cleanStemText(stemText, options, optionKeys) {
  var dedupedStem = _deduplicateRepeatedText(_deduplicateLines(stemText))
  var withoutExactOptions = _stripEmbeddedOptionBlock(dedupedStem, options)
  var withoutLabelOptions = _stripTrailingOptionBlockByLabels(withoutExactOptions, optionKeys)
  return _removeTrailingOptionKeys(withoutLabelOptions, optionKeys)
}

function _segmentsToText(segments) {
  if (!Array.isArray(segments)) return ''
  return segments.map(function (seg) {
    if (!seg) return ''
    if (seg.type === 'text' || seg.type === 'newline') return seg.text || ''
    return seg.alt ? '$' + seg.alt + '$' : ''
  }).join('')
}

function _textToSegments(text) {
  if (!text) return []
  var lines = String(text).split('\n')
  var segments = []
  lines.forEach(function (line, index) {
    if (line) segments.push({ type: 'text', text: line })
    if (index < lines.length - 1) segments.push({ type: 'newline' })
  })
  return segments
}

// ---- rich-text node builder ----

function _buildRichTextNodes(text) {
  var lines = String(text || '').split('\n')
  var children = []
  for (var i = 0; i < lines.length; i++) {
    if (i > 0) children.push({ name: 'br', attrs: {} })
    children.push({ type: 'text', text: lines[i] })
  }
  return [{ name: 'p', attrs: {}, children: children }]
}

// ---- hash ----

function _hashString(str) {
  var h = 0
  var s = String(str || '')
  for (var i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0
  }
  return h
}

function _hashStem(text) { return _hashString(text) }

// ---- render regression diff ----

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

    // Check indent (leading whitespace)
    var origIndent = orig.match(/^(\s*)/)[1]
    var rendIndent = rend.match(/^(\s*)/)[1]
    if (origIndent !== rendIndent) {
      issues.push({
        type: 'INDENT_MISMATCH',
        line: i + 1,
        detail: 'indent ' + JSON.stringify(origIndent) + ' → ' + JSON.stringify(rendIndent),
      })
    }

    // Check content (after stripping indent and normalizing internal whitespace)
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

// ---- DEV assertion ----

function _devAssertSinglePath(cleanedStem, content, resultMode) {
  if (!appConfig.DEV) return
  var modeFlags = []
  if (appConfig.enableMathImage && content && content.render_mode === 'segments') modeFlags.push('SEGMENTS')
  var hasLatex = /\\[a-zA-Z]+/.test(cleanedStem) || /\$\$[\s\S]*?\$\$/.test(cleanedStem)
  if (hasLatex) modeFlags.push('LATEX')
  // CODE mode is explicit — don't flag it as competing with RICH_TEXT
  if (!hasLatex && !containsCode(cleanedStem) && _needsRichRender(cleanedStem)) modeFlags.push('RICH_TEXT')
  // Note: TEXT_PLAIN is intentionally excluded — it's folded into RICH_TEXT path

  if (modeFlags.length > 1) {
    console.error(
      '[RENDER_INVARIANT_VIOLATION] Stem satisfies multiple render conditions: ' + modeFlags.join(', ') + '\n' +
      '  selected mode: ' + resultMode + '\n' +
      '  source tail: ' + cleanedStem.slice(-80)
    )
  }
}

// ---- render invariant assert ----

function _assertCodeRenderIntegrity(mode, rawText, html, richTextNodes) {
  if (!appConfig.DEV) return
  if (mode !== RENDER_MODE.CODE) return

  // CODE_RENDER_VIOLATION: CODE mode must NOT populate html or richTextNodes
  if (html.length > 0 || richTextNodes.length > 0) {
    console.error(
      '[CODE_RENDER_VIOLATION] CODE mode has non-empty html or richTextNodes\n' +
      '  html.length: ' + html.length + '\n' +
      '  richTextNodes.length: ' + richTextNodes.length + '\n' +
      '  CODE must render via <text> only (zero-HTML path)'
    )
  }

  // CODE_HTML_LEAK: rawText must not contain HTML entities
  var text = String(rawText || '')
  if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(text)) {
    console.error(
      '[CODE_HTML_LEAK] CODE rawText contains HTML entities\n' +
      '  rawText tail: ' + text.slice(-80) + '\n' +
      '  CODE must preserve raw characters, not HTML-encoded forms'
    )
  }
}

// ---- render trace ----

function _buildRenderTrace(questionId, sourceStem, mode, cleanedStem) {
  var trace = {
    questionId: questionId,
    timestamp: Date.now(),
    renderType: mode,
    pipeline: ['detect', 'route', 'render'],
  }
  if (mode === RENDER_MODE.CODE) {
    var before = String(sourceStem || '')
    var after = String(cleanedStem || '')
    trace.codeHashBefore = _hashString(before)
    trace.codeHashAfter = _hashString(after)
    trace.newlineCountBefore = (before.match(/\n/g) || []).length
    trace.newlineCountAfter = (after.match(/\n/g) || []).length
    trace.stemLengthBefore = before.length
    trace.stemLengthAfter = after.length
  }
  return trace
}

// ---- public API ----

/**
 * Build a RenderModel for a question stem.
 *
 * @param {Object} q - question object with .id, .content
 * @param {Object} [options] - question options {A: '...', B: '...'}
 * @param {Object} [cfg] - config override (defaults to appConfig)
 * @returns {Object} frozen RenderModel { mode, richTextNodes, html, segments }
 */
function buildRenderModel(q, options, cfg) {
  var effectiveConfig = cfg || appConfig
  var content = q && q.content
  var optionKeys = options ? Object.keys(options) : []

  // Extract raw stem text — prefer stem over text (stem has better code formatting)
  var stemText = (content && (content.stem || content.text)) || ''
  var sourceStemText = stemText || (content && _segmentsToText(content.segments)) || ''
  var cleanedStem = _cleanStemText(sourceStemText, options, optionKeys)
  var stemHash = _hashStem(cleanedStem)

  var mode, richTextNodes, html, segments, rawText

  // Priority 1: SEGMENTS (math-question with pre-rendered formula images)
  if (effectiveConfig.enableMathImage && content && content.render_mode === 'segments') {
    mode = RENDER_MODE.SEGMENTS
    segments = _textToSegments(cleanedStem)
    richTextNodes = []
    html = ''
  } else {
    // Try plain text conversion
    var plainStem = _toPlainInlineMathText(cleanedStem) || _toPlainSimpleInlineMathText(cleanedStem)
    var hasLatex = /\\[a-zA-Z]+/.test(cleanedStem) || /\$\$[\s\S]*?\$\$/.test(cleanedStem)

    // SAFE_MODE: bypass LATEX for code stems to prevent HTML contamination
    var selfHealCode = effectiveConfig.SAFE_MODE && containsCode(cleanedStem)

    if (hasLatex && !selfHealCode) {
      // Priority 2: LATEX (mp-html + KaTeX) — complex LaTeX
      mode = RENDER_MODE.LATEX
      html = _textToHtml(cleanedStem)
      richTextNodes = []
      segments = []
    } else if (containsCode(cleanedStem)) {
      // Priority 3: CODE (zero-HTML raw text with white-space: pre)
      mode = RENDER_MODE.CODE
      rawText = cleanedStem
      html = ''
      richTextNodes = []
      segments = []
      // Render regression diff: verify cleanedStem against sourceStemText
      var diffIssues = _renderDiff(sourceStemText, cleanedStem)
      if (diffIssues.length > 0) {
        _reportDiff(diffIssues, q && q.id)
      }
    } else {
      // Priority 4: RICH_TEXT (native <rich-text>) — all non-LaTeX, non-code, non-segments
      mode = RENDER_MODE.RICH_TEXT
      richTextNodes = _buildRichTextNodes(plainStem || cleanedStem)
      html = ''
      segments = []
    }
  }

  _devAssertSinglePath(cleanedStem, content, mode)
  _assertCodeRenderIntegrity(mode, cleanedStem, html, richTextNodes)
  _renderGuardCheck(q && q.id, stemHash, mode)

  var renderTrace = _buildRenderTrace(q && q.id, sourceStemText, mode, cleanedStem)

  var model = {
    mode: mode,
    richTextNodes: richTextNodes || [],
    html: html || '',
    segments: segments || [],
    rawText: rawText || '',
    renderTrace: renderTrace,
  }

  if (effectiveConfig.DEV && mode === RENDER_MODE.CODE) {
    if (renderTrace.codeHashBefore !== renderTrace.codeHashAfter) {
      console.warn(
        '[RENDER_TRACE] CODE hash changed for q' + (q && q.id) + '\n' +
        '  hashBefore: ' + renderTrace.codeHashBefore + '\n' +
        '  hashAfter:  ' + renderTrace.codeHashAfter + '\n' +
        '  newlines:   ' + renderTrace.newlineCountBefore + ' → ' + renderTrace.newlineCountAfter
      )
    }
  }

  if (effectiveConfig.DEV) {
    try { Object.freeze(model) } catch (_) { /* ignore if freeze not supported */ }
  }

  return model
}

// ---- option helpers (for page-level use) ----

function _optionTextToHtml(key, value) {
  var text = String(value || '').trim()
  if (!key) return _textToHtml(text)
  var keyPattern = new RegExp('^' + _escapeRegExp(String(key)) + '[\\s\\u00A0]*[.。．、:：）)]?\\s*', 'i')
  var normalized = keyPattern.test(text) ? text : key + '. ' + text
  return _textToHtml(normalized)
}

function buildOptionList(opts, optionKeys, selectedFlags) {
  return (optionKeys || []).map(function (key) {
    var optionText = _stripLeadingOptionLabel(key, (opts && opts[key]) || '')
    // Clean embedded newlines (OCR artifact) to prevent visual doubling
    var cleanedOptionText = optionText.replace(/[\r\n]+/g, ' ')
    var plainOptionText = _toPlainInlineMathText(cleanedOptionText)
    var needsRich = !plainOptionText && _needsRichRender(cleanedOptionText)
    return {
      key: key,
      _selected: !!(selectedFlags || {})[key],
      _text: plainOptionText || cleanedOptionText,
      _needsRich: needsRich,
      _html: needsRich ? _textToHtml(cleanedOptionText) : ''
    }
  })
}

module.exports = {
  RENDER_MODE: RENDER_MODE,
  buildRenderModel: buildRenderModel,
  resetRenderGuard: resetRenderGuard,
  setRenderGuardPage: setRenderGuardPage,

  // Option processing
  buildOptionList: buildOptionList,
  optionTextToHtml: _optionTextToHtml,

  // Text summarization (for list previews, not render modes)
  toPlainInlineMathText: _toPlainInlineMathText,

  // Shared text processing helpers
  needsRichRender: _needsRichRender,
  stripLeadingOptionLabel: _stripLeadingOptionLabel,

  // Hash utility for trace comparison
  computeCodeHash: _hashString,

  // Render regression diff
  renderDiff: _renderDiff,

  // Exported for tests and page-level use
  cleanStemText: _cleanStemText,
  textToHtml: _textToHtml,
  buildRichTextNodes: _buildRichTextNodes,
  segmentsToText: _segmentsToText,
  textToSegments: _textToSegments
}
