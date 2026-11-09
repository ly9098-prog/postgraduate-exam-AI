var { tableStructure } = require('./stem-render-dependencies')
var { _repairFalseNumberMarkerBreaks } = require('./stem-render-text')
var { _cleanStemText } = require('./stem-render-options')
var { isVisualSegmentType, hasVisualSegments } = require('./segment-types')
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
var caption = String(seg.caption != null ? seg.caption : '').trim()
var body = caption && code ? caption + '\n' + code : (caption || code)
return body ? '\n' + body + '\n' : ''
}
if (type === 'math_image') {
return seg.alt ? '$' + seg.alt + '$' : ''
}
if (isVisualSegmentType(type)) {
return seg.alt ? String(seg.alt) : ''
}
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
function _hasVisualSegments(segments) {
return hasVisualSegments(segments)
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
function _normalizeComparableForGuard(value) {
return String(value == null ? '' : value)
// OCR crops often keep a source question-number prefix or an image placeholder
// in one side only; those are not semantic differences.
.replace(/\[[^\]]{0,16}见上图[^\]]{0,8}\]/g, '')
.replace(/^[0-9]{1,3}[.、．]/, '')
.replace(/\s+/g, '')
// Full/half-width punctuation and quote/tilde variants are OCR noise.
.replace(/[。．：:；;，,、]/g, '')
.replace(/[“”"'‘’]/g, '')
.replace(/[~～\-—]/g, '')
}
function _comparableFromSegments(segments, options, optionKeys) {
var text = _repairFalseNumberMarkerBreaks(_segmentsToText(segments))
var cleaned = _cleanStemText(text, options, optionKeys)
return String(cleaned || '').replace(/\s+/g, '')
}
function _segmentsAgreeWithCanonicalStem(segments, cleanedStem, options, optionKeys, config) {
if (!_segmentsHaveComparableStemPayload(segments)) return true
var canonicalComparable = String(cleanedStem || '').replace(/\s+/g, '')
var segmentComparable = _comparableFromSegments(segments, options, optionKeys)
if (!canonicalComparable || !segmentComparable) return canonicalComparable === segmentComparable
if (canonicalComparable === segmentComparable) return true

// Structured questions may keep the prose stem in content.text/content.stem while
// carrying code or visual (image/table_image/code_image) segments as additional
// payload.  In that shape, comparing the full segment payload against the
// prose-only canonical stem rejects a valid SEGMENTS render and silently drops
// the code block or question image (e.g. an OCR table screenshot embedded as an
// image segment whose alt text never appears in the prose stem).  Keep the
// stale-segment guard for the remaining content, but allow code and visual
// segments to extend an otherwise matching stem.  math_image stays governed by
// enableMathImage: when the feature is off it neither renders nor blocks.
var ignoreMathImage = !(config && config.enableMathImage)
function matchesWithExtension(keepType) {
var candidateSegments = segments.filter(function (segment) {
if (!segment || typeof segment !== 'object') return false
var type = String(segment.type || '').trim().toLowerCase()
if (ignoreMathImage && type === 'math_image') return false
return keepType(type)
})
if (!_segmentsHaveComparableStemPayload(candidateSegments)) return false
var candidateGuard = _normalizeComparableForGuard(
_cleanStemText(_repairFalseNumberMarkerBreaks(_segmentsToText(candidateSegments)), options, optionKeys))
return _normalizeComparableForGuard(cleanedStem) === candidateGuard
}
if ((_hasCodeSegments(segments) || _hasVisualSegments(segments)) &&
matchesWithExtension(function (type) { return type !== 'code' && !isVisualSegmentType(type) })) {
return true
}
// Preserve the pre-fix acceptance where image alt text participated in the
// code-extension comparison, so code+image stems that used to render in
// SEGMENTS mode do not regress.
if (_hasVisualSegments(segments) &&
matchesWithExtension(function (type) { return type !== 'code' })) {
return true
}
return false
}
function _buildStrippedIndexMap(text) {
var indexMap = []
var stripped = ''
for (var i = 0; i < text.length; i++) {
var ch = text.charAt(i)
if (/\s/.test(ch)) continue
indexMap.push(i)
stripped += ch
}
indexMap.push(text.length)
return { indexMap: indexMap, stripped: stripped }
}
function _restoreTextSegmentFormatting(segments, canonicalStem) {
if (!Array.isArray(segments) || !segments.length) return segments
var canonical = String(canonicalStem == null ? '' : canonicalStem)
if (!canonical) return segments
var canonicalMap = _buildStrippedIndexMap(canonical)
var canonicalStripped = canonicalMap.stripped
if (!canonicalStripped) return segments
var indexMap = canonicalMap.indexMap
var textSegments = []
var joined = ''
for (var j = 0; j < segments.length; j++) {
var segment = segments[j]
if (!segment || typeof segment !== 'object') continue
if (String(segment.type || '').trim().toLowerCase() !== 'text') continue
textSegments.push(segment)
joined += String(segment.text || '').replace(/\s+/g, '')
}
if (!textSegments.length || joined !== canonicalStripped) return segments
var out = []
var cursor = 0
var changed = false
for (var k = 0; k < segments.length; k++) {
var current = segments[k]
if (!current || typeof current !== 'object') { out.push(current); continue }
var type = String(current.type || '').trim().toLowerCase()
if (type !== 'text') { out.push(current); continue }
var original = String(current.text || '')
var segmentStripped = original.replace(/\s+/g, '')
if (!segmentStripped) { out.push(current); continue }
if (canonicalStripped.substr(cursor, segmentStripped.length) !== segmentStripped) return segments
var start = indexMap[cursor]
var end = indexMap[cursor + segmentStripped.length]
cursor += segmentStripped.length
var replacement = canonical.slice(start, end).replace(/\s+$/, '')
if (replacement && replacement !== original) {
changed = true
out.push(Object.assign({}, current, { text: replacement }))
} else {
out.push(current)
}
}
return changed ? out : segments
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
module.exports = {
  _segmentsToText,
  _normalizeComparableText,
  _stemIsRepresentedByCodeSegment,
  _hasCodeSegments,
  _hasVisualSegments,
  _normalizeComparableForGuard,
  _restoreTextSegmentFormatting,
  _segmentsHaveComparableStemPayload,
  _segmentsAgreeWithCanonicalStem,
  _textToSegments,
  _repairFalseRangeBreaksInSegments,
}
