/**
 * =============================================================================
 * STEM RENDER INVARIANT MODULE
 * =============================================================================
 *
 * Centralized render-mode decision for all question stems in the miniprogram.
 *
 * RENDER MODES (in priority order):
 *   SEGMENTS  — Uses <math-question> component with pre-rendered formula images.
 *               Applicable when content.render_mode === 'segments' and either
 *               formula-image rendering is enabled or a native table.v2 segment exists.
 *   MIXED     — Multiple block types within a single stem (text + code, etc.).
 *               Each block renders independently via its own path.
 *   LATEX     — Uses <mp-html> with KaTeX plugin. Applicable when stem contains
 *               display math ($$...$$) or complex LaTeX commands (\frac, \sqrt, etc.).
 *   CODE      — Uses scroll-view + <text> (zero-HTML). For pure code stems.
 *               Compressed single-line code is conservatively reconstructed.
 *   RICH_TEXT — Uses native <rich-text> with programmatic nodes. Applicable when
 *               stem has newlines or HTML tags but NO LaTeX (no $$, no \commands).
 *               Also handles plain single-line text (Unicode math conversion).
 *
 * RENDER INVARIANT:
 *   For a given cleaned stem text, exactly ONE render mode must be selected.
 *   MIXED is one mode — its internal blocks do not count as separate render paths.
 *   If the same stem hash produces different modes across renders, RenderGuard
 *   emits a console.error in DEV mode.
 *
 * RenderModel is IMMUTABLE in DEV. Pages must not modify mode, richTextNodes,
 * html, blocks, or segments. New rendering capabilities must be added here,
 * never patched at the page layer.
 * =============================================================================
 */

var appConfig = require('../../../config')
var { formatInlineMathText, replaceSimpleLatexCommands } = require('./math-format')
var { containsCode, shouldReconstructCode, reconstructCode, sanitizeImportedCodeArtifacts } = require('./code-reconstructor')
var tableStructure = require('./table-structure')
var questionImageCache = require('./question-image-cache')

// Derive static asset origin from API base URL
var _assetOrigin = (function () {
  var base = (appConfig && appConfig.BASE_URL) || ''
  // Strip /api/v1 (or any /api/... path) to get origin
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

// ---- canonical form for dedup ----

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

  // OCR / import can persist a visual wrap inside a compact numeric interval.
  // Native rich-text then treats that wrap as authored content, so `(0~9)` can
  // become `(0~\n9)` even when the current device has enough horizontal space.
  // Keep the repair deliberately narrow to digit-to-digit ranges around ~ / ～.
  source = source
    .replace(/(\d)[ \t]*([~～])[ \t]*\n[ \t]*(\d)/g, '$1$2$3')
    .replace(/(\d)[ \t]*\n[ \t]*([~～])[ \t]*(\d)/g, '$1$2$3')
    .replace(/(\d)[ \t]*([~～])[ \t]*<br\s*\/?>[ \t]*(\d)/gi, '$1$2$3')

  // Compatibility repair for already-imported questions produced by the legacy
  // number-marker normalizer.  It could mistake the numeric suffix of an ASCII
  // identifier for a list marker and persist a newline, for example:
  //   (v1,v2)10  ->  (v1,v\n2)10
  // Only join the lines when `2)` is immediately followed by another compact
  // identifier/number token.  A real list item normally looks like `2) text`
  // (space after the marker), so it is intentionally left untouched.
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

  // Full-text half dedup: compare canonical forms of left/right halves
  var stripped = normalized.trim()
  var half = Math.floor(stripped.length / 2)
  if (half > 0) {
    var leftHalf = stripped.slice(0, half)
    var rightHalf = stripped.slice(half)
    if (_toCanonicalForm(leftHalf) === _toCanonicalForm(rightHalf) && _toCanonicalForm(leftHalf).trim()) {
      return leftHalf.replace(/\n+$/, '').trim()
    }
  }

  // Paragraph-level dedup: compare adjacent paragraphs by canonical form
  var paragraphs = stripped.split(/\n\n+/)
  if (paragraphs.length >= 2) {
    var result = []
    for (var i = 0; i < paragraphs.length; i++) {
      var current = paragraphs[i]
      if (i > 0) {
        var prev = paragraphs[i - 1]
        var isCodeBlock = containsCode(current) || containsCode(prev)

        if (isCodeBlock) {
          // Code paragraphs: dedup only when exactly identical
          if (current.trim() === prev.trim()) continue
        } else {
          // Text paragraphs: dedup when canonical forms match
          if (_toCanonicalForm(current) === _toCanonicalForm(prev)) continue
        }
      }
      result.push(current)
    }

    // Also check first vs last paragraph (non-adjacent duplicate)
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
  return /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/.test(text) || /<\/?[a-z][\s\S]*>/i.test(text) || /\n/.test(text)
}

function _escapeRegExp(text) {
  return String(text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function _toPlainInlineMathText(text) {
  if (!text) return ''
  var source = _repairFalseNumberMarkerBreaks(String(text))
  if (/\$\$[\s\S]*?\$\$/.test(source) || /<\/?[a-z][\s\S]*>/i.test(source)) return null
  // OCR may insert a visual newline beside a simple command such as \geq.
  // Convert it first; _buildRichTextNodes preserves any remaining line breaks.
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
  // Normalize line endings, then dedup (canonical comparison — no line-level dedup)
  var normalized = String(stemText || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  var dedupedStem = _deduplicateRepeatedText(normalized)
  var withoutExactOptions = _stripEmbeddedOptionBlock(dedupedStem, options)
  var withoutLabelOptions = _stripTrailingOptionBlockByLabels(withoutExactOptions, optionKeys)
  return _removeTrailingOptionKeys(withoutLabelOptions, optionKeys)
}

function _segmentsToText(segments) {
  if (!Array.isArray(segments)) return ''
  return segments.map(function (seg) {
    if (!seg) return ''
    var type = String(seg.type || '').trim().toLowerCase()
    if (type === 'text') return seg.text || ''
    if (type === 'newline') return '\n'
    if (type === 'table' || type === 'table_markdown') return tableStructure.tableToText(seg)
    if (type === 'code') {
      var code = String(seg.code != null ? seg.code : (seg.text != null ? seg.text : '')).trimEnd()
      // segment.alt describes the region for accessibility/import diagnostics;
      // it must not be injected into the visible stem. Only explicit caption is content.
      var caption = String(seg.caption != null ? seg.caption : '').trim()
      var body = caption && code ? caption + '\n' + code : (caption || code)
      return body ? '\n' + body + '\n' : ''
    }
    if (type === 'math_image') {
      return seg.alt ? '$' + seg.alt + '$' : ''
    }
    if (type === 'image' || type === 'table_image' || type === 'code_image') {
      return seg.alt ? String(seg.alt) : ''
    }
    // Unknown segment `alt` values are import/accessibility metadata. Only
    // explicit text is allowed to participate in a plain-text fallback.
    return seg.text != null ? String(seg.text) : ''
  }).join('')
}

function _normalizeComparableText(value) {
  return String(value == null ? '' : value).replace(/\r\n?/g, '\n').trim()
}

function _stemIsRepresentedByCodeSegment(segments, stemText) {
  var normalizedStem = _normalizeComparableText(stemText)
  if (!normalizedStem || !Array.isArray(segments)) return false
  return segments.some(function (segment) {
    if (!segment || typeof segment !== 'object') return false
    if (String(segment.type || '').trim().toLowerCase() !== 'code') return false
    var code = _normalizeComparableText(segment.code != null ? segment.code : segment.text)
    var caption = _normalizeComparableText(segment.caption)
    var withCaption = caption && code ? caption + '\n' + code : (caption || code)
    return normalizedStem === code || normalizedStem === _normalizeComparableText(withCaption)
  })
}

function _hasCodeSegments(segments) {
  if (!Array.isArray(segments)) return false
  return segments.some(function (segment) {
    return segment && typeof segment === 'object' && String(segment.type || '').trim().toLowerCase() === 'code'
  })
}

function _segmentsHaveComparableStemPayload(segments) {
  if (!Array.isArray(segments)) return false
  return segments.some(function (segment) {
    if (!segment || typeof segment !== 'object') return false
    var type = String(segment.type || '').trim().toLowerCase()
    if (type === 'text') return String(segment.text || '').trim().length > 0
    if (type === 'code') return String(segment.code != null ? segment.code : (segment.text || '')).trim().length > 0
    if (type === 'table' || type === 'table_markdown') return true
    if (type === 'math_image') return String(segment.alt || '').trim().length > 0
    return false
  })
}

function _segmentsAgreeWithCanonicalStem(segments, cleanedStem, options, optionKeys) {
  // Image-only segment payloads intentionally coexist with the canonical text,
  // so they are not evidence of a stale stem snapshot.  When segments contain
  // their own text/code/table/math representation, however, make sure it still
  // describes the same stem before allowing SEGMENTS mode to override text.
  if (!_segmentsHaveComparableStemPayload(segments)) return true
  var segmentText = _repairFalseNumberMarkerBreaks(_segmentsToText(segments))
  var cleanedSegmentText = _cleanStemText(segmentText, options, optionKeys)
  var canonicalComparable = String(cleanedStem || '').replace(/\s+/g, '')
  var segmentComparable = String(cleanedSegmentText || '').replace(/\s+/g, '')
  if (!canonicalComparable || !segmentComparable) return canonicalComparable === segmentComparable
  return canonicalComparable === segmentComparable
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

function _repairFalseRangeBreaksInSegments(segments) {
  if (!Array.isArray(segments) || !segments.length) return []
  var repaired = segments.map(function (segment) {
    if (!segment || typeof segment !== 'object') return segment
    var copy = Object.assign({}, segment)
    if (String(copy.type || '').trim().toLowerCase() === 'text' && copy.text != null) {
      copy.text = _repairFalseNumberMarkerBreaks(String(copy.text))
    }
    return copy
  })

  var out = []
  for (var i = 0; i < repaired.length; i++) {
    var current = repaired[i]
    var type = current && typeof current === 'object'
      ? String(current.type || '').trim().toLowerCase()
      : ''
    if (type === 'newline' && out.length > 0 && i + 1 < repaired.length) {
      var prev = out[out.length - 1]
      var next = repaired[i + 1]
      var prevType = prev && typeof prev === 'object' ? String(prev.type || '').trim().toLowerCase() : ''
      var nextType = next && typeof next === 'object' ? String(next.type || '').trim().toLowerCase() : ''
      if (prevType === 'text' && nextType === 'text') {
        var prevText = String(prev.text || '')
        var nextText = String(next.text || '')
        var joinsAfterTilde = /\d[ \t]*[~～][ \t]*$/.test(prevText) && /^[ \t]*\d/.test(nextText)
        var joinsBeforeTilde = /\d[ \t]*$/.test(prevText) && /^[ \t]*[~～][ \t]*\d/.test(nextText)
        if (joinsAfterTilde || joinsBeforeTilde) {
          prev.text = prevText.replace(/[ \t]+$/, '')
          next.text = nextText.replace(/^[ \t]+/, '')
          continue
        }
      }
    }
    out.push(current)
  }
  return out
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

// ---- split stem into blocks for MIXED mode ----

/**
 * Determine if a single block of text should be classified as CODE.
 * Uses a stricter per-block heuristic than containsCode() to avoid
 * false-positive on natural language containing code-like tokens.
 */
function _isCodeBlock(text) {
  if (!text || !text.trim()) return false
  // Markdown fenced code block
  if (/^```/.test(text.trim())) return true

  // Quick containsCode check — score >= 3 signals code
  if (!containsCode(text)) return false

  // Additional guard: require at least one structural code element
  // ({, }, ; at end of line, control flow keywords)
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

/**
 * Score the code-likeness of text after a potential code start position.
 * Returns a score >= 4 to be considered credible code.
 */
function _scoreCodeContent(text) {
  if (!text) return 0
  var score = 0

  // Type keyword at start (strong signal)
  if (/^(int|void|char|float|double|long|boolean|String|unsigned|short)\b/.test(text)) score += 2
  // Control flow with parens
  if (/\b(for|while|if|switch|do|catch)\s*\(/.test(text)) score += 2
  // return / printf / scanf / malloc / free / sizeof / typedef
  if (/\b(return|printf|scanf|malloc|free|sizeof|typedef)\b/.test(text)) score += 2
  // Function call with parens
  if (/\([^)]*\)/.test(text)) score += 1
  // Semicolons
  if (/;/.test(text)) score += 1
  // Braces
  if (/[{}]/.test(text)) score += 1
  // Increment / decrement
  if (/\+\+|--/.test(text)) score += 1
  // Assignment operators (but not ==)
  if (/[+\-*/%&|^]?=(?!=)/.test(text)) score += 1
  // Pointer / reference
  if (/->|::/.test(text)) score += 1

  return score
}

/**
 * Check if text ends with sentence-ending punctuation suitable as a
 * natural-language-to-code transition point.
 */
function _hasSentenceEnding(text) {
  // ASCII semicolon ; is excluded — it appears in code, not in natural-language
  // sentence endings. Only Chinese fullwidth ； and other sentence-final
  // punctuation (。！？：！？：\n.!?:) are recognized.
  return /[。！？：；\n.!?:]\s*$/.test(text)
}

/**
 * Find the first credible position where natural language transitions to
 * inline code on the same line.
 *
 * Algorithm:
 *   1. Scan for type keywords (int, void, …) and control flow (for, while, …)
 *      that could mark the start of inline code.
 *   2. For each candidate, verify the text BEFORE ends with sentence-ending
 *      punctuation and the text AFTER has sufficient code characteristics
 *      (score >= 4 via _scoreCodeContent).
 *
 * Returns the character index of the code start, or -1 if no credible
 * transition is found.
 */
function _findCredibleCodeStart(text) {
  // Type keyword followed by identifier
  var kwType = /\b(int|void|char|float|double|long|boolean|String|unsigned|short)\s+\w+/g
  // Control flow with parens
  var kwControl = /\b(for|while|if|switch|do)\s*\(/g
  // return / printf / scanf / malloc / free with paren or semicolon
  var kwReturn = /\b(return|printf|scanf|malloc|free)\s*[;(]/g

  var match

  // Try type keywords first (strongest signal)
  while ((match = kwType.exec(text)) !== null) {
    var pos = match.index
    var before = text.slice(0, pos).trim()
    if (!before) continue

    var after = text.slice(pos)
    if (_hasSentenceEnding(before) && _scoreCodeContent(after) >= 4) {
      return pos
    }
  }

  // Try control flow keywords
  while ((match = kwControl.exec(text)) !== null) {
    var pos2 = match.index
    var before2 = text.slice(0, pos2).trim()
    if (!before2) continue

    var after2 = text.slice(pos2)
    if (_hasSentenceEnding(before2) && _scoreCodeContent(after2) >= 4) {
      return pos2
    }
  }

  // Try return / printf / scanf / malloc / free
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

/**
 * Split a single block of text that has inline natural language followed
 * by code on the same line.
 *
 * Example:
 *   "下列程序的时间复杂度是（ ）。 int m=0; for(i=0;i<n;i++) m++;"
 *   → [{ type: 'RICH_TEXT', text: '下列程序的时间复杂度是（ ）。' },
 *       { type: 'CODE', text: 'int m=0; for(i=0;i<n;i++) m++;' }]
 *
 * When no credible split is found, returns a single RICH_TEXT block.
 *
 * @param {string} text - A single paragraph of text
 * @returns {Array<{type: string, text: string}>} blocks
 */
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

/**
 * Split a stem text into blocks for MIXED rendering.
 *
 * Algorithm:
 *   1. Split paragraphs by blank lines (double newlines).
 *   2. For each paragraph, try inline text+code splitting first.
 *   3. Classify each resulting block (or whole paragraph) as CODE, LATEX, or RICH_TEXT.
 *   4. Merge adjacent same-type blocks.
 *
 * @param {string} text - cleaned stem text (already deduplicated)
 * @returns {Array<{type: string, text: string}>} blocks
 */
function splitStemBlocks(text) {
  if (!text || !text.trim()) return [{ type: 'RICH_TEXT', text: text || '' }]

  var source = String(text)

  // Separate into raw paragraphs
  var rawParas = source.split(/\n\n+/)

  // Step 1: For each paragraph, try inline splitting, then classify
  var classified = []
  for (var p = 0; p < rawParas.length; p++) {
    var para = rawParas[p].trim()
    if (!para) continue

    // Try inline text+code splitting for same-line mixing
    var inlineBlocks = splitInlineTextAndCode(para)
    if (inlineBlocks.length > 1) {
      // Successfully split inline — add each block with pre-assigned type
      for (var ib = 0; ib < inlineBlocks.length; ib++) {
        classified.push(inlineBlocks[ib])
      }
    } else {
      // No inline split — classify the whole paragraph
      var type = _classifyParagraph(para)
      classified.push({ type: type, text: para })
    }
  }

  if (classified.length === 0) return [{ type: 'RICH_TEXT', text: '' }]

  // Merge adjacent same-type blocks
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

  // Check for fenced code
  if (/^```/.test(text.trim())) return 'CODE'

  // CODE check
  var isCode = _isCodeBlock(text)
  if (isCode) return 'CODE'

  // Try plain text conversion first — if simple inline LaTeX can be converted
  // to Unicode, prefer RICH_TEXT over LATEX
  var plain = _toPlainInlineMathText(text) || _toPlainSimpleInlineMathText(text)
  if (typeof plain === 'string' && plain.length > 0 && !containsUnresolvedLatex(plain)) {
    return 'RICH_TEXT'
  }

  // LATEX check — display math or complex LaTeX commands (exclude C escapes \n \t \r)
  if (/\$\$[\s\S]*?\$\$/.test(text)) return 'LATEX'
  if (/\\[a-zA-Z]+/.test(text) && !/\\[nrt]/.test(text)) return 'LATEX'

  return 'RICH_TEXT'
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
  // CODE mode or MIXED mode is explicit — don't flag it as competing with RICH_TEXT
  if (!hasLatex && !containsCode(cleanedStem) && _needsRichRender(cleanedStem)) modeFlags.push('RICH_TEXT')

  var isCodePath = resultMode === RENDER_MODE.CODE || resultMode === RENDER_MODE.MIXED
  if (!isCodePath && modeFlags.length > 1) {
    console.error(
      '[RENDER_INVARIANT_VIOLATION] Stem satisfies multiple render conditions: ' + modeFlags.join(', ') + '\n' +
      '  selected mode: ' + resultMode + '\n' +
      '  source tail: ' + cleanedStem.slice(-80)
    )
  }
}

// ---- render invariant assert ----

function _assertCodeRenderIntegrity(mode, rawText, html, richTextNodes, blocks) {
  if (!appConfig.DEV) return

  if (mode === RENDER_MODE.MIXED) {
    // MIXED mode: validate each CODE block
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

// ---- render payload assertions ----

function _assertExclusiveRenderPayload(model) {
  if (!appConfig.DEV) return
  var m = model || {}
  var mode = m.mode
  var active = 0

  if (mode === RENDER_MODE.RICH_TEXT) {
    active += m.richTextNodes && m.richTextNodes.length ? 1 : 0
    if (m.html || m.rawText || (m.blocks && m.blocks.length)) {
      console.error('[RENDER_PAYLOAD_CONFLICT] RICH_TEXT has extra payload')
    }
  }

  if (mode === RENDER_MODE.LATEX) {
    active += m.html ? 1 : 0
    if ((m.richTextNodes && m.richTextNodes.length) || m.rawText || (m.blocks && m.blocks.length)) {
      console.error('[RENDER_PAYLOAD_CONFLICT] LATEX has extra payload')
    }
  }

  if (mode === RENDER_MODE.CODE) {
    active += m.rawText ? 1 : 0
    if (m.html || (m.richTextNodes && m.richTextNodes.length) || (m.blocks && m.blocks.length)) {
      console.error('[RENDER_PAYLOAD_CONFLICT] CODE has extra payload')
    }
  }

  if (mode === RENDER_MODE.MIXED) {
    active += m.blocks && m.blocks.length ? 1 : 0
    if (m.html || m.rawText || (m.richTextNodes && m.richTextNodes.length)) {
      console.error('[RENDER_PAYLOAD_CONFLICT] MIXED has top-level payload')
    }
  }

  if (mode === RENDER_MODE.SEGMENTS) {
    active += m.segments && m.segments.length ? 1 : 0
    if (m.html || m.rawText || (m.richTextNodes && m.richTextNodes.length) || (m.blocks && m.blocks.length)) {
      console.error('[RENDER_PAYLOAD_CONFLICT] SEGMENTS has extra payload')
    }
  }

  if (active !== 1) {
    console.error('[RENDER_PAYLOAD_CONFLICT] expected exactly one active payload for mode=' + mode)
  }
}

function _assertBlockPayloadIntegrity(blocks) {
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

// ---- render trace ----

function _buildRenderTrace(questionId, sourceStem, mode, cleanedStem, blocks) {
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
  if (mode === RENDER_MODE.MIXED && Array.isArray(blocks)) {
    trace.blockTypes = blocks.map(function (b) { return b.type })
  }
  return trace
}

// ---- block rendering helpers ----

function _renderRichTextBlock(text) {
  var plain = _toPlainInlineMathText(text) || _toPlainSimpleInlineMathText(text) || text
  return {
    type: 'RICH_TEXT',
    richTextNodes: _buildRichTextNodes(plain),
  }
}

function _renderLatexBlock(text) {
  return {
    type: 'LATEX',
    html: _textToHtml(text),
  }
}

function _renderCodeBlock(text, cfg) {
  // First: sanitize imported code artifacts (dollar sign pollution)
  var sanitized = sanitizeImportedCodeArtifacts(text)
  var rawText = sanitized
  if (!cfg || !cfg.DISABLE_CODE_RECONSTRUCT) {
    if (shouldReconstructCode(sanitized)) {
      rawText = reconstructCode(sanitized, { fixOperators: false, fixStructure: true, fixIndent: false })
    }
  }
  return {
    type: 'CODE',
    rawText: rawText,
  }
}

// ---- public API ----

/**
 * Build a RenderModel for a question stem.
 *
 * @param {Object} q - question object with .id, .content
 * @param {Object} [options] - question options {A: '...', B: '...'}
 * @param {Object} [cfg] - config override (defaults to appConfig)
 * @returns {Object} frozen RenderModel { mode, richTextNodes, html, segments, blocks }
 */
function buildRenderModel(q, options, cfg) {
  var effectiveConfig = cfg || appConfig
  var content = q && q.content
  var optionKeys = options ? Object.keys(options) : []

  // ``text`` is the current authoring field. Student APIs reconcile text/stem,
  // but prefer text here as a compatibility guard for older backends where an
  // edited text could coexist with a stale stem.
  var stemText = typeof content === 'string'
    ? content
    : ((content && (content.text || content.stem)) || '')
  var sourceStemText = stemText || (content && _segmentsToText(content.segments)) || ''
  sourceStemText = _repairFalseNumberMarkerBreaks(sourceStemText)
  var cleanedStem = _cleanStemText(sourceStemText, options, optionKeys)
  var stemHash = _hashStem(cleanedStem)

  var mode, richTextNodes, html, segments, rawText, blocks

  // Priority 1: SEGMENTS (math-question with pre-rendered formula images).
  // A historical edit can leave content.text on the newest wording while the
  // structured segments still contain an older wording.  In that case segments
  // are not authoritative: fall through and render the canonical text instead.
  var segmentsAgreeWithStem = !content || _segmentsAgreeWithCanonicalStem(content.segments, cleanedStem, options, optionKeys)
  if (content && content.render_mode === 'segments' && segmentsAgreeWithStem && (effectiveConfig.enableMathImage || tableStructure.hasTableSegments(content.segments) || _hasCodeSegments(content.segments))) {
    mode = RENDER_MODE.SEGMENTS
    // Use API segments if available (includes text, image, math_image, table_image, code_image)
    segments = (content.segments && content.segments.length > 0)
      ? _repairFalseRangeBreaksInSegments(content.segments)
      : _textToSegments(cleanedStem)
    var hasTextualSegment = segments.some(function (segment) {
      var type = segment && typeof segment === 'object' ? String(segment.type || '').trim().toLowerCase() : ''
      return type === 'text' || type === 'newline'
    })
    if (!hasTextualSegment && stemText && cleanedStem && !_stemIsRepresentedByCodeSegment(segments, cleanedStem)) {
      // Only a canonical stem may be prepended. A segment-derived fallback
      // (for example a code-only question) is already represented by the
      // segment itself and must not be duplicated as a text block.
      segments = _textToSegments(cleanedStem).concat(segments)
    }
    richTextNodes = []
    html = ''
    blocks = []
  } else {
    // Try splitting into blocks for MIXED detection
    var stemBlocks = splitStemBlocks(cleanedStem)
    var blockTypes = []
    for (var bi = 0; bi < stemBlocks.length; bi++) {
      var bt = stemBlocks[bi].type
      if (blockTypes.indexOf(bt) === -1) blockTypes.push(bt)
    }

    if (blockTypes.length > 1) {
      // MIXED: different block types present
      mode = RENDER_MODE.MIXED
      blocks = []
      for (var bj = 0; bj < stemBlocks.length; bj++) {
        var sb = stemBlocks[bj]
        if (sb.type === 'CODE') {
          blocks.push(_renderCodeBlock(sb.text, effectiveConfig))
        } else if (sb.type === 'LATEX') {
          blocks.push(_renderLatexBlock(sb.text))
        } else {
          blocks.push(_renderRichTextBlock(sb.text))
        }
      }
      richTextNodes = []
      html = ''
      rawText = ''
      segments = []
    } else {
      // Single block type — use existing priority logic
      // Check for LaTeX commands excluding C escape sequences (\n, \t, \r, \0, \\)
      var hasLatex = (function() {
        if (/\$\$[\s\S]*?\$\$/.test(cleanedStem)) return true
        var latexMatches = cleanedStem.match(/\\[a-zA-Z]+/g)
        if (!latexMatches) return false
        var cEscapes = { n: true, t: true, r: true }
        for (var mi = 0; mi < latexMatches.length; mi++) {
          var cmd = latexMatches[mi].slice(1)
          if (cmd.length > 2 || !cEscapes[cmd]) return true
        }
        return false
      })()
      var selfHealCode = effectiveConfig.SAFE_MODE && containsCode(cleanedStem)

      // Priority 2a: Try plain text conversion first (simple inline LaTeX → Unicode)
      // Only if conversion succeeds with no unresolved LaTeX and no code present
      var plainStem = _toPlainInlineMathText(cleanedStem) || _toPlainSimpleInlineMathText(cleanedStem)
      var plainConversionSucceeded = typeof plainStem === 'string' && plainStem.length > 0 && !containsUnresolvedLatex(plainStem)

      if (plainConversionSucceeded && !containsCode(cleanedStem)) {
        // Simple inline LaTeX fully converted to plain text → RICH_TEXT
        mode = RENDER_MODE.RICH_TEXT
        richTextNodes = _buildRichTextNodes(plainStem)
        html = ''
        segments = []
        blocks = []
        rawText = ''
      } else if (hasLatex && !selfHealCode) {
        // Priority 2: LATEX (mp-html + KaTeX) — complex LaTeX
        mode = RENDER_MODE.LATEX
        html = _textToHtml(cleanedStem)
        richTextNodes = []
        segments = []
        blocks = []
      } else if (containsCode(cleanedStem)) {
        // Priority 3: CODE (zero-HTML raw text with white-space: pre)
        mode = RENDER_MODE.CODE
        // Sanitize imported code artifacts, then reconstruct if compressed
        var sanitizedCode = sanitizeImportedCodeArtifacts(cleanedStem)
        var codeText = sanitizedCode
        if (!effectiveConfig.DISABLE_CODE_RECONSTRUCT && shouldReconstructCode(sanitizedCode)) {
          codeText = reconstructCode(sanitizedCode, { fixOperators: false, fixStructure: true, fixIndent: false })
        }
        rawText = codeText
        html = ''
        richTextNodes = []
        segments = []
        blocks = []
        // Render regression diff: verify cleanedStem against sourceStemText
        var diffIssues = _renderDiff(sourceStemText, cleanedStem)
        if (diffIssues.length > 0) {
          _reportDiff(diffIssues, q && q.id)
        }
      } else {
        // Priority 4: RICH_TEXT (native <rich-text>) — all non-LaTeX, non-code, non-segments
        mode = RENDER_MODE.RICH_TEXT
        var plainStemFallback = _toPlainInlineMathText(cleanedStem) || _toPlainSimpleInlineMathText(cleanedStem) || cleanedStem
        richTextNodes = _buildRichTextNodes(plainStemFallback)
        html = ''
        segments = []
        blocks = []
        rawText = ''
      }
    }
  }

  _devAssertSinglePath(cleanedStem, content, mode)
  _assertCodeRenderIntegrity(mode, cleanedStem, html, richTextNodes, blocks)
  _assertBlockPayloadIntegrity(blocks)
  _renderGuardCheck(q && q.id, stemHash, mode)

  var renderTrace = _buildRenderTrace(q && q.id, sourceStemText, mode, cleanedStem, blocks)

  var model = {
    mode: mode,
    richTextNodes: richTextNodes || [],
    html: html || '',
    segments: segments || [],
    rawText: rawText || '',
    blocks: blocks || [],
    renderTrace: renderTrace,
  }

  _assertExclusiveRenderPayload(model)

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
  textToSegments: _textToSegments,

  // MIXED mode support
  splitStemBlocks: splitStemBlocks,
  splitInlineTextAndCode: splitInlineTextAndCode,

  // Asset URL resolution (for option image segments)
  resolveAssetUrl: _resolveAssetUrl,
}
