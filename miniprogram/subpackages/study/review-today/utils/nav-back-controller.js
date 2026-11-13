function exitPrompt(submittingGroup) {
  return {
    layout: 'minimal',
    title: '退出本组复习？',
    message: submittingGroup
      ? '本组提交仍在进行中，退出后本次提交结果将不再展示，确定退出吗？'
      : '本组尚未提交的答案不会计入复习结果，确定退出吗？',
    confirmText: '退出',
    cancelText: submittingGroup ? '继续等待' : '继续复习',
  }
}

function createNavBackController(options) {
  return {
    async onNavBack() {
      if (options.getPhase() !== 'reviewing') {
        navigateBack(options)
        return
      }
      if (options.isExitConfirmPending()) return
      options.setExitConfirmPending(true)
      let confirmed = false
      try {
        confirmed = await options.showConfirm(exitPrompt(options.isSubmittingGroup()))
      } catch (error) {
        options.logWarn('退出确认弹窗异常', error)
        confirmed = false
      } finally {
        options.setExitConfirmPending(false)
      }
      if (!confirmed || options.getPhase() !== 'reviewing') return
      options.clearMasterUndo()
      options.clearReviewActivity()
      options.clearReviewTimer()
      navigateBack(options)
    },
  }
}

function navigateBack(options) {
  options.closeBackGuard(() => {
    const pages = options.getCurrentPages()
    if (pages.length > 1) options.navigateBack()
    else options.reLaunch({ url: '/pages/home/home' })
  })
}

module.exports = {
  createNavBackController,
}
