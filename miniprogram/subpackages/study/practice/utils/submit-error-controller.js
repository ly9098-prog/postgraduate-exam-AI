function createSubmitErrorController(options) {
  return {
    handle: handleError.bind(null, options),
  }
}

async function handleError(options, submission, error) {
  if (!options.isPageAlive()) return false
  options.logError('提交失败', error)
  options.pauseQuestionTiming()
  options.setData({ submitting: false })

  if (options.isDeterministicReject(error)) {
    submission.retryBlocked = true
    submission.pendingPersisted = options.persistPendingSubmission(
      submission,
      'blocked',
      ''
    ) || submission.pendingPersisted
    options.setUnloadGuard(true, '本次提交未通过。')
    const rejectMessage = options.resolveRejectMessage(String((error && error.code) || ''))
    await options.showConfirm({
      scenario: 'danger',
      title: rejectMessage.title,
      message: rejectMessage.content,
      showCancel: false,
      confirmText: '知道了',
      hideEyebrow: true,
    })
    return false
  }

  const persisted = options.persistPendingSubmission(submission, 'pending', '')
  submission.pendingPersisted = persisted || submission.pendingPersisted
  options.setUnloadGuard(true, '交卷仍在确认中。')
  await options.showConfirm({
    scenario: 'info',
    title: '交卷结果未确认',
    message: submission.pendingPersisted
      ? '已保存交卷进度，可稍后继续确认。'
      : '暂未保存交卷进度，请保持当前页面并重试。',
    showCancel: false,
    confirmText: '知道了',
    hideEyebrow: true,
  })
  return false
}

module.exports = {
  createSubmitErrorController,
}
