function createNavBackController(options) {
  return {
    onNavBack() {
      if (options.getPhase() === 'reviewing') {
        options.setData({ exitConfirmVisible: true })
        return
      }
      navigateBack(options)
    },

    closeExitConfirm() {
      options.setData({ exitConfirmVisible: false })
    },

    confirmExitReview() {
      options.clearMasterUndo()
      options.clearReviewTimer()
      options.setData({ exitConfirmVisible: false })
      navigateBack(options)
    },
  }
}

function navigateBack(options) {
  const pages = options.getCurrentPages()
  if (pages.length > 1) options.navigateBack()
  else options.reLaunch({ url: '/pages/home/home' })
}

module.exports = {
  createNavBackController,
}
