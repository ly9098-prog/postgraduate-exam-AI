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
  if (error && (error.code === 'AUTH_REQUIRED' || Number(error.statusCode) === 401)) {
    await options.promptLogin({
      title: '重新登录后交卷',
      content: submission.pendingPersisted
        ? '登录已失效，交卷进度已保存。请重新登录后手动重试交卷，也可以暂不登录。'
        : '登录已失效，未能保存交卷进度。可暂不登录并保留当前页面，重新登录后请手动重试交卷。',
    })
    return false
  }
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
