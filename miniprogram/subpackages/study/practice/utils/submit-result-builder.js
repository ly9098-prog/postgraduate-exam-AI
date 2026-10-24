/**
 * Build stored results and light question list from server response + submission snapshot.
 *
 * Pure functions extracted from practice.js doSubmit to make the result-merging
 * contract testable without a page instance.
 */

/**
 * Merge server-returned results with skipped/partial questions from the submission.
 *
 * - Server results with status 'skipped' that are in partialQuestionIds are
 *   reclassified as 'partial'.
 * - Questions not present in server results but in the question source are
 *   appended as skipped/partial.
 */
function buildStoredResults(options) {
  var serverResults = options.serverResults || []
  var partialQuestionIds = options.partialQuestionIds || []
  var snapshotAnswerMap = options.snapshotAnswerMap || {}
  var snapshotAnsweredFlags = options.snapshotAnsweredFlags || {}
  var questionSource = options.questionSource || []

  var partialQuestionIdSet = {}
  partialQuestionIds.forEach(function(id) { partialQuestionIdSet[String(id)] = true })

  var storedResults = serverResults.map(function(rr) {
    var questionId = String(rr.question_id)
    var isPartial = rr.status === 'skipped' && partialQuestionIdSet[questionId]
    return Object.assign({}, rr, {
      status: isPartial ? 'partial' : rr.status,
      _local_partial: !!isPartial,
      user_answer: snapshotAnswerMap[questionId] || '',
    })
  })

  var submittedResultMap = {}
  storedResults.forEach(function(rr) { submittedResultMap[String(rr.question_id)] = true })

  questionSource.forEach(function(q) {
    if (!q || !q.id || submittedResultMap[String(q.id)] || snapshotAnsweredFlags[String(q.id)]) return
    var isPartial = !!partialQuestionIdSet[String(q.id)]
    storedResults.push({
      question_id: q.id,
      user_answer: snapshotAnswerMap[String(q.id)] || '',
      is_correct: false,
      status: isPartial ? 'partial' : 'skipped',
      _local_partial: isPartial,
      _local_skipped: !isPartial,
    })
  })

  return storedResults
}

/**
 * Build a light-weight question list for result page rendering.
 * Only carries fields needed by the result page, not full question objects.
 */
function buildLightQuestions(questionSource) {
  var lightQuestions = []
  for (var qi = 0; qi < questionSource.length; qi++) {
    var qq = questionSource[qi]
    if (qq && qq.id) {
      lightQuestions.push({
        id: qq.id,
        question_version_id: qq.question_version_id || null,
        question_version: qq.question_version || null,
        stem: (qq.content && (qq.content.text || qq.content.stem)) || qq.stem || '',
        options: qq.options || null,
        question_type: qq.question_type || '',
      })
    }
  }
  return lightQuestions
}

/**
 * Compute display skipped count: server skipped minus partial count, floored at 0.
 */
function computeDisplaySkippedCount(serverSkippedCount, partialCount) {
  return Math.max(0, (Number(serverSkippedCount) || 0) - (Number(partialCount) || 0))
}

module.exports = {
  buildStoredResults,
  buildLightQuestions,
  computeDisplaySkippedCount,
}
