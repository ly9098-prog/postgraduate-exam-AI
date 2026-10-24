/**
 * Pure helpers for reading practice result payloads from options/cache,
 * extracted from practice-result/index.js.
 */

/**
 * Check whether a payload contains detailed practice results.
 */
function hasDetailedPracticePayload(payload) {
  var source = payload && payload.data && typeof payload.data === 'object'
    ? payload.data
    : payload
  if (!source || typeof source !== 'object') return false
  return (Array.isArray(source.results) && source.results.length > 0) ||
    (Array.isArray(source.submitResults) && source.submitResults.length > 0) ||
    (Array.isArray(source.resultList) && source.resultList.length > 0)
}

/**
 * Read summary fields from URL/options parameters.
 * Returns null if no summary keys are present.
 */
function readSummaryFromOptions(options) {
  var keys = ['correct', 'wrong', 'skipped', 'partial', 'total', 'duration', 'subject_id', 'subject_name']
  if (!keys.some(function(key) { return options[key] !== undefined && options[key] !== null && options[key] !== '' })) return null
  var subjectName = options.subject_name || ''
  if (typeof subjectName === 'string') {
    try { subjectName = decodeURIComponent(subjectName) } catch (_) {}
  }
  return {
    total_correct: Number(options.correct) || 0,
    total_wrong: Number(options.wrong) || 0,
    total_skipped: Number(options.skipped) || 0,
    total_partial: Number(options.partial) || 0,
    total: Math.max(0, Number(options.total) || 0),
    duration: Math.max(0, Number(options.duration) || 0),
    subject_id: options.subject_id != null ? Number(options.subject_id) : null,
    subject_name: subjectName,
  }
}

module.exports = { hasDetailedPracticePayload, readSummaryFromOptions }
