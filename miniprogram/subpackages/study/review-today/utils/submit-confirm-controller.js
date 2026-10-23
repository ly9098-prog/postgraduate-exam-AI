function createGroupSubmitConfirmController(options) {
  return {
    async confirm(totalCount, unansweredCount) {
      const confirmDialog = options.getConfirm()
      if (!confirmDialog) return false
      options.setPending(true)
      try {
        if (unansweredCount > 0) {
          const continueReview = await confirmDialog.show({
            scenario: 'unanswered',
            layout: 'minimal',
            title: '请先完成本组复习',
            message: `还有 ${unansweredCount} 题未完成作答。请填写全部题目后再提交，多空题需要填写每一空。`,
            confirmText: '继续作答',
            showCancel: false,
          })
          if (continueReview && options.isPageAlive() && options.getPhase() === 'reviewing') {
            const index = options.findUnansweredIndex()
            if (index >= 0) options.showQuestion(index)
          }
          return false
        }

        const confirmed = await confirmDialog.show({
          scenario: 'all-done',
          layout: 'minimal',
          title: '提交本组复习？',
          message: `本组 ${totalCount} 题已全部作答，提交后查看复盘结果。`,
          confirmText: '提交复习',
          cancelText: '继续检查',
        })
        return Boolean(confirmed && options.isPageAlive() && options.getPhase() === 'reviewing')
      } catch (_) {
        return false
      } finally {
        options.setPending(false)
      }
    },
  }
}

module.exports = {
  createGroupSubmitConfirmController,
}
