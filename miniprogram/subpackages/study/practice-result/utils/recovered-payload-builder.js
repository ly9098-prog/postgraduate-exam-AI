/**
 * Build a recovered result payload from a submission snapshot and server submit result.
 *
 * Pure function — extracted from practice-result/index.js _buildRecoveredResultPayload.
 * The _userId and _createdAt fields are added by the caller.
 */
function buildRecoveredResultPayload(submission, submitResult, cacheKey) {
  var answerMap = submission.answerMap || {}
  var partialSet = {}
  ;(submission.partialQuestionIds || []).forEach(function(id) { partialSet[String(id)] = true })

  var results = (submitResult.results || []).map(function(item) {
    var qid = String(item.question_id)
    var isPartial = item.status === 'skipped' && !!partialSet[qid]
    return Object.assign({}, item, {
      status: isPartial ? 'partial' : item.status,
      _local_partial: isPartial,
      _local_skipped: item.status === 'skipped' && !isPartial,
      user_answer: answerMap[qid] || '',
    })
  })

  var partialCount = (submission.partialQuestionIds || []).length
  var skippedCount = Math.max(0, (Number(submitResult.total_skipped) || 0) - partialCount)

  return {
    correct: Number(submitResult.total_correct) || 0,
    wrong: Number(submitResult.total_wrong) || 0,
    skipped: skippedCount,
    partial: partialCount,
    total: Number(submission.total) || results.length,
    subject_id: submission.selectedSubjectId != null ? submission.selectedSubjectId : (submission.session && submission.session.subject_id != null ? submission.session.subject_id : null),
    subject_name: submission.selectedSubjectName || '',
    duration: Number(submission.duration != null ? submission.duration : (submission.session && submission.session.duration_sec)) || 0,
    traceId: submitResult.trace_id || submission.traceId || '',
    results: results,
    questions: (submission.recoveryQuestions || []).map(function(q) {
      return Object.assign({}, q, {
        id: q.id,
        stem: q.stem || '',
        question_type: q.question_type || '',
        content: q.content || (q.stem ? { stem: q.stem } : {}),
        options: q.options || null,
        image_url: q.image_url || null,
      })
    }),
    comboCount: Number(submission.comboCount) || 0,
    knowledge_session: submitResult.knowledge_session || submission.knowledgeScope || null,
    request_id: submission.requestId || '',
    _cacheKey: cacheKey || '',
    _createdAt: Date.now(),
  }
}

module.exports = { buildRecoveredResultPayload }
