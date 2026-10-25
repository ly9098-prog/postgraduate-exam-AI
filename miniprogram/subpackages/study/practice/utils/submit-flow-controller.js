function createSubmitFlowController(options) {
  return {
    submit: submitImpl.bind(null, options),
  }
}

async function submitImpl(options, skipConfirm) {
  if (options.isSubmitting()) return
  let submission = options.getSubmissionSnapshot()
  if (options.isSubmitted() && options.getPendingResultUrl() && submission) {
    options.openSubmittedResult(options.getPendingResultUrl(), submission)
    return
  }
  if (submission && submission.retryBlocked) {
    await options.showConfirm({
      scenario: 'danger',
      title: '本次提交无法继续重试',
      message: '请退出本组练习后重新开始。',
      showCancel: false,
      confirmText: '知道了',
      hideEyebrow: true,
    })
    return
  }
  const questions = options.getQuestions()
  if (!submission) {
    submission = await options.prepareSubmission(skipConfirm)
    if (!submission) return
  } else {
    options.clearTimer()
    submission.pendingPersisted = options.persistPendingSubmission(
      submission,
      'pending',
      ''
    ) || submission.pendingPersisted
  }
  options.setData({ submitting: true })
  let submitResult
  try {
    const submitPayload = options.buildSubmitPayload(submission, options.getTraceId())
    submitResult = await options.requestSubmit(submitPayload)
    if (!options.isPageAlive()) return
  } catch (error) {
    await options.handleSubmitError(submission, error)
    return
  }
  options.completeSubmit(submission, submitResult, questions)
}

module.exports = {
  createSubmitFlowController,
}
