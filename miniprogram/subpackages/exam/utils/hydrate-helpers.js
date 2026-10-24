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

/**
 * Find the index of a target route in the page stack (searching backwards).
 *
 * Pure function — extracted from exam-runner _navigateToPaperList.
 * Returns -1 if not found.
 */
function findPageInStack(pages, targetRoute) {
  for (var i = pages.length - 2; i >= 0; i -= 1) {
    if (String((pages[i] || {}).route || '').replace(/^\//, '') === targetRoute) {
      return i
    }
  }
  return -1
}

/**
 * Build the paper list URL.
 */
function buildPaperListUrl() {
  return '/subpackages/exam/paper-list/index'
}

module.exports = { buildServerAnswersMap, mergeAnswerState, buildExamResultUrl, findPageInStack, buildPaperListUrl }

/**
 * Build a pending item state from an answer object.
 *
 * Pure function — extracted from exam-runner _queueItem.
 */
function buildPendingItem(answer) {
  var a = answer || {}
  return {
    selected_answer: a.selected_answer || null,
    marked_for_review: !!a.marked_for_review,
    used_time: Math.max(0, Number(a.used_time || 0)),
  }
}

/**
 * Compute answered count and progress percent from a question list.
 *
 * Pure function — extracted from exam-runner _setCountsOnly.
 */
function computeAnsweredProgress(questions) {
  var qs = questions || []
  var answeredCount = qs.reduce(function(n, q) { return n + (q._answered ? 1 : 0) }, 0)
  return {
    answeredCount: answeredCount,
    progressPercent: qs.length ? Math.round((answeredCount / qs.length) * 100) : 0,
  }
}

module.exports = { buildServerAnswersMap, mergeAnswerState, buildExamResultUrl, findPageInStack, buildPaperListUrl, buildPendingItem, computeAnsweredProgress }
