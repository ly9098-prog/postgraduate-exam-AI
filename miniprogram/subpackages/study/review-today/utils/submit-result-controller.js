const { buildGroupOutcome } = require('./group-submission')

function createGroupSubmitResultController(options) {
  return {
    apply(input) {
      // Drafts are removed only after the server confirms the immutable occurrence.
      options.clearSubmittedDraft(input.groupQuestions, input.groupResults)
      const outcome = buildGroupOutcome({
        groupResults: input.groupResults,
        groupQuestions: input.groupQuestions,
        groups: options.getGroups(),
        allGroupResults: options.getSession().allGroupResults,
        sessionTodayTaskTotalCount: options.getSession().todayTaskTotalCount,
        dataTodayDueCount: options.getTodayDueCount(),
        dataTodayCompletedCount: options.getTodayCompletedCount(),
        completedBeforeSession: options.getSession().completedBeforeSession,
        currentGroupIdx: options.getCurrentGroupIdx(),
      })
      if (outcome.failureToast) options.showToast({ title: outcome.failureToast, icon: 'none' })
      Object.assign(options.getSession(), outcome.session)
      options.pauseTimer()
      options.setData({
        phase: 'group-result',
        ...outcome.view,
        groupResults: input.groupResults,
        showGroupDetails: false,
        submittingGroup: false,
        resultDockVisible: true,
      })
      if (outcome.view.todayRemainingCount <= 0) options.showResultDockAndRefreshTimer()
      return outcome
    },
  }
}

module.exports = {
  createGroupSubmitResultController,
}
