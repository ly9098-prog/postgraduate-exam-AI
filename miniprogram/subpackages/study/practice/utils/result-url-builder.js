/**
 * Build the practice-result page URL from submission and server response data.
 *
 * Pure function — no page state, no wx APIs. Extracted from practice.js doSubmit
 * to keep the URL contract testable and stable.
 */

function buildPracticeResultUrl(options) {
  var correct = options.correct || 0
  var wrong = options.wrong || 0
  var skipped = options.skipped || 0
  var partial = options.partial || 0
  var total = options.total || 0
  var subjectId = options.subjectId
  var subjectName = options.subjectName || ''
  var duration = options.duration || 0
  var cacheKey = options.cacheKey
  var requestId = options.requestId || ''
  var recover = options.resultCacheStored ? '0' : '1'
  var source = options.source || ''
  var returnTo = options.returnTo || ''

  return [
    '/subpackages/study/practice-result/index',
    '?correct=' + correct,
    '&wrong=' + wrong,
    '&skipped=' + skipped,
    '&partial=' + partial,
    '&total=' + total,
    '&subject_id=' + subjectId,
    '&subject_name=' + encodeURIComponent(subjectName),
    '&duration=' + duration,
    '&_ck=' + cacheKey,
    '&_rid=' + encodeURIComponent(requestId),
    '&_recover=' + recover,
    '&source=' + encodeURIComponent(source),
    '&return_to=' + encodeURIComponent(returnTo),
  ].join('')
}

module.exports = { buildPracticeResultUrl }
