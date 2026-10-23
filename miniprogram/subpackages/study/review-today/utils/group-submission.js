function buildGroupReviews(options) {
  const reviews = []
  for (let index = 0; index < options.groupQuestions.length; index++) {
    const question = options.groupQuestions[index]
    if (!options.isQuestionAnswered(question, options.answers)) {
      return { error: 'incomplete', index }
    }
    const requestId = options.getRequestId(question)
    if (
      !question.question_version_id ||
      question.occurrence_seq === undefined ||
      question.occurrence_seq === null ||
      !requestId
    ) {
      return { error: 'version', index }
    }
    reviews.push({
      schedule_id: question.schedule_id,
      question_id: question.question_id,
      question_version_id: question.question_version_id,
      occurrence_seq: question.occurrence_seq,
      request_id: requestId,
      user_answer: options.answers[question.schedule_id] || '',
    })
  }
  if (reviews.length === 0) return { error: 'empty' }
  return { reviews }
}

function buildGroupResult(options) {
  const submittedScheduleIds = new Set(options.reviews.map(item => String(item.schedule_id)))
  const matched = submittedScheduleIds.has(String(options.question.schedule_id))
    ? findMatchingResult(options.results, options.question)
    : null
  const isAnswered = options.isQuestionAnswered(options.question, options.answers)
  const expectedResult = submittedScheduleIds.has(String(options.question.schedule_id))
  const resultMissing = expectedResult && !matched
  const submitFailed = resultMissing || Boolean(matched && matched.success === false)
  const wasSubmitted = Boolean(matched) && !submitFailed
  const refreshRequired = Boolean(matched && options.failureNeedsRefresh(matched))
  const retryable = resultMissing || Boolean(
    matched &&
    matched.success === false &&
    !refreshRequired &&
    matched.retryable !== false
  )
  return {
    ...options.enrichForResult(options.question),
    isCorrect: wasSubmitted ? Boolean(matched.is_correct) : false,
    correctAnswer: wasSubmitted ? (matched.correct_answer || '') : '',
    userAnswer: options.answers[options.question.schedule_id] || '',
    wasAnswered: isAnswered,
    wasSubmitted,
    submitFailed,
    submitError: submitFailed
      ? ((matched && matched.error) || (resultMissing ? '批改结果缺失，已保留待重试' : '提交失败，请重试'))
      : '',
    submitErrorCode: matched && matched.error_code ? String(matched.error_code) : '',
    refreshRequired,
    retryable,
    wasSkipped: !expectedResult && !isAnswered && !wasSubmitted && !submitFailed,
    masteryPercent: wasSubmitted && matched && Number.isFinite(Number(matched.mastery_percent))
      ? Number(matched.mastery_percent)
      : null,
    mastered: Boolean(wasSubmitted && matched && matched.mastered),
  }
}

function findMatchingResult(results, question) {
  const matchingResults = (results || []).filter(result => {
    if (result.schedule_id !== undefined && result.schedule_id !== null) {
      if (String(result.schedule_id) !== String(question.schedule_id)) return false
      if (result.question_version_id != null && String(result.question_version_id) !== String(question.question_version_id)) return false
      if (result.occurrence_seq != null && String(result.occurrence_seq) !== String(question.occurrence_seq)) return false
      return true
    }
    return String(result.question_id) === String(question.question_id)
  })
  return matchingResults[0] || null
}

module.exports = {
  buildGroupReviews,
  buildGroupResult,
}
