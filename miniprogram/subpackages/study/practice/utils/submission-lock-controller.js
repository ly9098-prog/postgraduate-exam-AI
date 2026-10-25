function createSubmissionLockController(options) {
  return {
    isLocked: isLockedImpl.bind(null, options),
  }
}

function isLockedImpl(options) {
  const submission = options.getSubmissionSnapshot()
  if (!submission) return false
  options.showToast({
    title: submission.serverAccepted
      ? '本次已交卷，请查看结果'
      : (submission.retryBlocked ? '提交已被拒绝，请退出后重试' : '交卷内容已锁定，请确认提交'),
    icon: 'none',
  })
  return true
}

module.exports = {
  createSubmissionLockController,
}
