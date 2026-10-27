var { tableStructure } = require('./stem-render-dependencies')
var { _repairFalseNumberMarkerBreaks } = require('./stem-render-text')
var { _cleanStemText } = require('./stem-render-options')
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
if (type === 'image' || type === 'table_image' || type === 'code_image') {
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
if (!_segmentsHaveComparableStemPayload(segments)) return true
var segmentText = _repairFalseNumberMarkerBreaks(_segmentsToText(segments))
var cleanedSegmentText = _cleanStemText(segmentText, options, optionKeys)
var canonicalComparable = String(cleanedStem || '').replace(/\s+/g, '')
var segmentComparable = String(cleanedSegmentText || '').replace(/\s+/g, '')
if (!canonicalComparable || !segmentComparable) return canonicalComparable === segmentComparable
if (canonicalComparable === segmentComparable) return true

// Structured questions may keep the prose stem in content.text/content.stem while
// carrying the code as an additional segment.  In that shape, comparing the full
// segment payload against the prose-only canonical stem rejects a valid SEGMENTS
// render and silently drops the code block.  Keep the stale-segment guard for the
// non-code content, but allow code segments to extend an otherwise matching stem.
if (_hasCodeSegments(segments)) {
var nonCodeSegments = segments.filter(function (segment) {
return !segment || typeof segment !== 'object' || String(segment.type || '').trim().toLowerCase() !== 'code'
})
if (_segmentsHaveComparableStemPayload(nonCodeSegments)) {
var nonCodeText = _repairFalseNumberMarkerBreaks(_segmentsToText(nonCodeSegments))
var cleanedNonCodeText = _cleanStemText(nonCodeText, options, optionKeys)
var nonCodeComparable = String(cleanedNonCodeText || '').replace(/\s+/g, '')
if (canonicalComparable === nonCodeComparable) return true
}
}
return false
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
  _segmentsHaveComparableStemPayload,
  _segmentsAgreeWithCanonicalStem,
  _textToSegments,
  _repairFalseRangeBreaksInSegments,
}
