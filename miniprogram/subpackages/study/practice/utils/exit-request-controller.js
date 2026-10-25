const {
  exitPrompt,
  exitSubmissionState,
} = require('./exit-request-state')

function createExitRequestController(options) {
  return {
    request: requestImpl.bind(null, options),
  }
}

async function requestImpl(options, source) {
  const exitSource = source && source.source ? source.source : ''
  options.setLastExitSource(exitSource)
  if (options.isExitConfirmInFlight()) return
  if (options.isSubmitting()) {
    options.setExitConfirmInFlight(true)
    try {
      await options.showConfirm({
        scenario: 'info',
        title: '正在交卷',
        message: '提交完成前请保持当前页面。',
        confirmText: '知道了',
        hideCancel: true,
        hideEyebrow: true,
      })
    } finally {
      options.setExitConfirmInFlight(false)
    }
    return
  }

  const submission = options.getSubmissionSnapshot()
  if (options.isSubmitted() && options.getPendingResultUrl() && submission) {
    options.openSubmittedResult(options.getPendingResultUrl(), submission)
    return
  }

  const { hasPendingSubmit, retryBlocked } = exitSubmissionState(submission)
  options.setExitConfirmInFlight(true)
  let confirmed = false
  try {
    const showExitConfirm = hasPendingSubmit
      ? options.showConfirm
      : options.showPausedConfirm
    confirmed = await showExitConfirm(exitPrompt(hasPendingSubmit, retryBlocked))
  } finally {
    options.setExitConfirmInFlight(false)
  }
  if (!confirmed) return
  if (!options.isPageAlive()) return
  if (retryBlocked && submission) options.clearPendingSubmission(submission.requestId)
  options.setUnloadGuard(false)
  options.incrementQuestionRequestSeq()
  options.clearTimer()
  options.clearFeedbackTimer()
  options.resetPracticeState()
  options.scrollToSetupTop()
}

module.exports = {
  createExitRequestController,
}
