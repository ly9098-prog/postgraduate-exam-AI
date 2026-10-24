function buildSubmitResultPayload(options) {
  const submission = options.submission
  const submitResult = options.submitResult
  const questions = options.questions

  const snapshotAnswerMap = submission.answerMap || {}
  const snapshotAnsweredFlags = submission.answeredFlags || {}
  const total = Number(submission.total) || 0
  const unanswered = Number(submission.unanswered) || 0
  const partialCount = (submission.partialQuestionIds || []).length
  const questionSource = questions.length ? questions : (submission.recoveryQuestions || [])
  const storedResults = options.buildStoredResults({
    serverResults: submitResult.results || [],
    partialQuestionIds: submission.partialQuestionIds || [],
    snapshotAnswerMap,
    snapshotAnsweredFlags,
    questionSource,
  })
  const serverSkippedCount = Number(submitResult.total_skipped ?? unanswered) || 0
  const displaySkippedCount = options.computeDisplaySkippedCount(serverSkippedCount, partialCount)

  return {
    correct: submitResult.total_correct || 0,
    wrong: submitResult.total_wrong || 0,
    skipped: displaySkippedCount,
    partial: partialCount,
    total,
    subject_id: submission.selectedSubjectId,
    subject_name: submission.selectedSubjectName,
    duration: Number(submission.duration) || 0,
    traceId: submitResult.trace_id || submission.traceId || options.traceId || '',
    results: storedResults,
    questions: options.buildLightQuestions(questionSource),
    comboCount: Number(submission.comboCount) || 0,
    knowledge_session: submitResult.knowledge_session || submission.knowledgeScope || null,
    request_id: submission.requestId || '',
    _cacheKey: options.cacheKey,
    _userId: options.userId,
    _createdAt: options.createdAt,
  }
}

module.exports = {
  buildSubmitResultPayload,
}
