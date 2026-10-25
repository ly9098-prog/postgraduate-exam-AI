function createSubmittedResultController(options) {
  return {
    open: openImpl.bind(null, options),
  }
}

function openImpl(options, resultUrl, submission) {
  if (!resultUrl || !options.isPageAlive()) return
  if (submission && submission.keepPendingUntilResult && !submission.pendingPersisted) {
    try {
      if (!options.getSubmittedResultPayload()) throw new Error('missing in-memory result payload')
      options.writeResultCache(options.getSubmittedResultPayload())
      submission.keepPendingUntilResult = false
    } catch (storageError) {
      options.logWarn('结果缓存与待确认快照均不可持久化', storageError)
      options.showConfirm({
        scenario: 'info',
        title: '复盘数据暂未保存',
        message: '成绩已保存。请保持当前页面，释放设备存储后再次打开复盘。',
        showCancel: false,
        confirmText: '知道了',
        hideEyebrow: true,
      })
      return
    }
  }
  options.setPendingResultUrl(resultUrl)
  options.redirectTo({
    url: resultUrl,
    success: () => {
      const session = options.getSession()
      if (session && session.submissionSnapshot === submission) {
        session.submissionSnapshot = null
      }
      options.setPendingResultUrl('')
    },
    fail: (err) => {
      options.logError('结果页打开失败', err)
      if (!options.isPageAlive()) return
      options.setData({ submitting: false, submitted: true })
      options.setUnloadGuard(false)
      options.showConfirm({
        scenario: 'info',
        title: '结果页打开失败',
        message: submission && submission.pendingPersisted
          ? '成绩已保存，可稍后再次打开复盘。'
          : '成绩已保存，请保持当前页面后再次打开复盘。',
        showCancel: false,
        confirmText: '知道了',
        hideEyebrow: true,
      })
    },
  })
}

module.exports = {
  createSubmittedResultController,
}
