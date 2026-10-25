function createGroupSubmitFlowController(options) {
  return {
    submit: () => submitImpl(options),
  }
}

async function submitImpl(options) {
  const groupQuestions = options.getGroupQuestions()
  if (!await options.confirm(groupQuestions)) return false
  const answers = await options.begin(groupQuestions)
  if (!answers) return false

  const submission = await options.request({
    groupQuestions,
    answers,
    isQuestionAnswered: options.isQuestionAnswered,
    getRequestId: options.getRequestId,
    buildTimingSession: options.buildTimingSession,
    enrichForResult: options.enrichForResult,
    failureNeedsRefresh: options.failureNeedsRefresh,
  })
  if (submission.status !== 'submitted') return false

  try {
    options.applyResult({
      groupQuestions,
      groupResults: submission.groupResults,
    })
    return true
  } catch (error) {
    if (!options.isPageAlive()) return false
    options.logError('提交失败', error)
    options.showResultFailureToast()
    options.setSubmitting(false)
    return false
  }
}

module.exports = {
  createGroupSubmitFlowController,
}
