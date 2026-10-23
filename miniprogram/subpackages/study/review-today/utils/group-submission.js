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

function mergeResultsByScheduleId(oldResults, newResults) {
  const order = []
  const byScheduleId = {}
  ;(oldResults || []).forEach(item => {
    const scheduleId = String(item && item.schedule_id || '')
    if (!scheduleId) return
    if (!byScheduleId[scheduleId]) order.push(scheduleId)
    byScheduleId[scheduleId] = item
  })
  ;(newResults || []).forEach(item => {
    const scheduleId = String(item && item.schedule_id || '')
    if (!scheduleId) return
    if (!byScheduleId[scheduleId]) order.push(scheduleId)
    byScheduleId[scheduleId] = item
  })
  return order.map(scheduleId => byScheduleId[scheduleId])
}

function buildGroupOutcome(options) {
  const groupResults = options.groupResults || []
  const groupCorrect = groupResults.filter(item => item.isCorrect && item.wasSubmitted).length
  const groupWrong = groupResults.filter(item => item.wasSubmitted && !item.isCorrect).length
  const groupSkipped = groupResults.filter(item => !item.wasSubmitted).length
  const groupFailed = groupResults.filter(item => item.submitFailed).length
  const groupRefreshRequired = groupResults.filter(item => item.submitFailed && item.refreshRequired).length
  const groupRetryableFailed = groupResults.filter(item => item.submitFailed && !item.refreshRequired).length
  const failureToast = groupFailed > 0
    ? (groupRefreshRequired > 0 && groupRetryableFailed > 0
      ? `${groupRefreshRequired} 题需刷新，${groupRetryableFailed} 题待重试`
      : (groupRefreshRequired > 0
        ? `${groupRefreshRequired} 题任务已更新，将重新获取`
        : `${groupRetryableFailed} 题提交失败，已保留待重试`))
    : ''

  const allGroupResults = mergeResultsByScheduleId(options.allGroupResults, groupResults)
  const totalCorrect = allGroupResults.filter(item => item.isCorrect && item.wasSubmitted).length
  const totalWrong = allGroupResults.filter(item => item.wasSubmitted && !item.isCorrect).length
  const totalCompleted = allGroupResults.filter(item => item.wasSubmitted).length
  const pendingQuestionIds = new Set(
    groupResults
      .filter(item => !item.wasSubmitted && (!item.submitFailed || !item.refreshRequired))
      .map(item => String(item.schedule_id))
  )
  const pendingQuestions = (options.groupQuestions || [])
    .filter(question => pendingQuestionIds.has(String(question.schedule_id)))
  const groups = pendingQuestions.length > 0
    ? (options.groups || []).concat([pendingQuestions])
    : (options.groups || [])
  const todayTaskTotalCount = Math.max(
    Number(options.sessionTodayTaskTotalCount || 0),
    Number(options.dataTodayDueCount || 0),
    totalCompleted
  )
  const todayCompletedCount = Math.min(
    todayTaskTotalCount,
    Math.max(
      Number(options.dataTodayCompletedCount || 0),
      Number(options.completedBeforeSession || 0) + totalCompleted
    )
  )
  const todayRemainingCount = Math.max(0, todayTaskTotalCount - todayCompletedCount)

  return {
    failureToast,
    session: {
      todayTaskTotalCount,
      allGroupResults,
      totalCorrect,
      totalWrong,
      totalCompleted,
    },
    view: {
      groups,
      groupWrongResults: groupResults.filter(item => item.wasSubmitted && !item.isCorrect),
      groupCorrect,
      groupWrong,
      _groupSkipped: groupSkipped,
      groupAccuracyPercent: Math.round((groupCorrect + groupWrong) > 0 ? groupCorrect / (groupCorrect + groupWrong) * 100 : 0),
      todayDueCount: todayTaskTotalCount,
      todayCompletedCount,
      todayRemainingCount,
      todayProgressPercent: todayTaskTotalCount > 0 ? Math.round(todayCompletedCount / todayTaskTotalCount * 100) : 0,
      _groupProgressStyle: 'width: ' + Math.round((options.currentGroupIdx + 1) / Math.max(1, groups.length) * 100) + '%',
    },
  }
}

module.exports = {
  buildGroupReviews,
  buildGroupResult,
  buildGroupOutcome,
  mergeResultsByScheduleId,
}
