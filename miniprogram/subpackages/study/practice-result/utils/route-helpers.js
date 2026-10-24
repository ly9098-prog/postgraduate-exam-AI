/**
 * Pure helpers for route validation and JSON decoding,
 * extracted from practice-result/index.js.
 */

/**
 * Validate and normalize a practice return route.
 * Only known knowledge map/study routes are accepted.
 */
function normalizePracticeReturnRoute(value) {
  var route = String(value || '').trim().slice(0, 512)
  if (!route) return ''
  if (!/^\/subpackages\/(?:knowledge\/knowledge-(?:detail|subject)|study\/knowledge-(?:detail|subject))\/index(?:\?.*)?$/.test(route)) return ''
  return route
}

/**
 * Safely decode a JSON string, trying both raw and URI-decoded forms.
 */
function safeDecodeJson(value) {
  if (!value || typeof value !== 'string') return null
  var candidates = [value]
  try { candidates.push(decodeURIComponent(value)) } catch (e) {}
  for (var i = 0; i < candidates.length; i++) {
    var text = candidates[i]
    try {
      var parsed = JSON.parse(text)
      if (parsed && typeof parsed === 'object') return parsed
    } catch (e) {}
  }
  return null
}

module.exports = { normalizePracticeReturnRoute, safeDecodeJson }
