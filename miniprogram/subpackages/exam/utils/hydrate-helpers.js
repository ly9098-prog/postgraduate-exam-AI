/**
 * Pure helpers for exam attempt hydration, extracted from exam-runner/index.js.
 */

/**
 * Build a server answers lookup map from the API answers array.
 *
 * Keys are stringified item_ids; values are normalized answer objects.
 */
function buildServerAnswersMap(answers) {
  var map = Object.create(null)
  ;(answers || []).forEach(function(a) {
    map[String(a.item_id)] = {
      selected_answer: a.selected_answer || null,
      marked_for_review: !!a.marked_for_review,
      used_time: Math.max(0, Number(a.used_time || 0)),
    }
  })
  return map
}

/**
 * Merge server answer with pending local answer for an item.
 * Pending (unsaved local) takes precedence over server.
 */
function mergeAnswerState(serverAnswer, pendingAnswer) {
  return Object.assign({}, serverAnswer || {}, pendingAnswer || {})
}

/**
 * Build the result page URL for an exam attempt.
 */
function buildExamResultUrl(attemptId) {
  return '/subpackages/exam/result/index?attempt_id=' + attemptId
}

module.exports = { buildServerAnswersMap, mergeAnswerState, buildExamResultUrl }
