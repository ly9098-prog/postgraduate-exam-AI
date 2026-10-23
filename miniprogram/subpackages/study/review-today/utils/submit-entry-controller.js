function createGroupSubmitEntryController(options) {
  return {
    async confirm(groupQuestions) {
      const data = options.getData()
      if (
        data.submittingGroup ||
        options.isConfirmPending() ||
        data.masterSubmitting ||
        options.isMasterUndoInFlight() ||
        !groupQuestions.length
      ) return false

      const totalCount = groupQuestions.length
      const answeredCount = options.computeAnsweredCount(
        groupQuestions,
        options.getSession().answers
      )
      return options.confirmController.confirm(totalCount, totalCount - answeredCount)
    },

    async begin(groupQuestions) {
      const data = options.getData()
      if (data.submittingGroup || data.groupQuestions !== groupQuestions) return null
      const answers = { ...options.getSession().answers }
      if (options.computeAnsweredCount(groupQuestions, answers) !== groupQuestions.length) {
        options.showToast({ title: '请完成全部题目后再提交', icon: 'none' })
        return null
      }

      options.clearMasterUndo()
      options.setSubmitting(true)
      if (!await options.syncReviewSessionDay()) {
        if (options.isPageAlive()) options.setSubmitting(false)
        return null
      }
      return answers
    },
  }
}

module.exports = {
  createGroupSubmitEntryController,
}
