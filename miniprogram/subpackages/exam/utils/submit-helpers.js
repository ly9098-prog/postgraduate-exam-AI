/**
 * Pure helpers for exam submission, extracted from exam-runner/index.js.
 */

/**
 * Build the final submit answers array from pending item states.
 *
 * - selected_answer is trimmed and uppercased, or null if empty.
 * - used_time is clamped to [0, 6 hours].
 */
function buildFinalSubmitAnswers(itemIds, pending) {
  return (itemIds || []).map(function(itemId) {
    var value = (pending && pending[itemId]) || {}
    return {
      item_id: Number(itemId),
      selected_answer: String(value.selected_answer || '').trim().toUpperCase() || null,
      marked_for_review: !!value.marked_for_review,
      used_time: Math.min(6 * 60 * 60, Math.max(0, Number(value.used_time || 0))),
    }
  })
}

/**
 * Classify a submit error as retryable (network/timeout/server) or not.
 */
function isRetryableSubmitError(error) {
  var status = Number(error && error.statusCode)
  return status === 0 || status === 408 || status === 425 || status === 429 || status >= 500
}

module.exports = { buildFinalSubmitAnswers, isRetryableSubmitError }
