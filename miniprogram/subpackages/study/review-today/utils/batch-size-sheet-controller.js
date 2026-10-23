function createBatchSizeSheetController(options) {
  return {
    show() {
      if (options.getPhase() !== 'overview') return
      if (options.isStarting() || options.isContinuing()) return
      options.setData({
        pendingBatchSize: options.getReviewBatchSize(),
        showBatchSizeSheet: true,
      })
    },

    close() {
      options.setData({ showBatchSizeSheet: false })
    },

    selectPending(e) {
      var value = Number(e.currentTarget.dataset.value)
      if (options.getBatchSizeOptions().indexOf(value) === -1) return
      options.setData({ pendingBatchSize: value })
    },

    confirm() {
      var pending = options.normalizeBatchSize(options.getPendingBatchSize())
      options.markUserSelected()
      options.setData({
        reviewBatchSize: pending,
        showBatchSizeSheet: false,
      })
    },
  }
}

module.exports = {
  createBatchSizeSheetController,
}
