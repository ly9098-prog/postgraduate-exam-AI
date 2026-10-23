function createNextRemoteBatchController(options) {
  return {
    async next(flowSeq) {
      const batch = await options.postNextBatch({
        batch_size: options.getBatchSize(),
      })
      if (!options.isPageAlive() || !options.isFlowCurrent(flowSeq)) return { status: 'dead' }

      const rawQuestions = batch.questions || []
      if (rawQuestions.length > 0) {
        const questions = []
        rawQuestions.forEach(rawQuestion => {
          const question = options.normalizeQuestion(rawQuestion)
          if (question) questions.push(question)
        })
        const restoredDraft = options.restoreDraft(questions)
        options.getSession().allQuestions = questions
        options.getSession().answers = restoredDraft.answers
        options.setData({
          phase: 'reviewing',
          groups: [questions],
          currentGroupIdx: 0,
          groupQuestions: questions,
          currentIndex: restoredDraft.currentIndex,
          currentBatchNo: batch.batch_no || options.getCurrentBatchNo() + 1,
          totalBatchCount: batch.total_batch_count || options.getTotalBatchCount(),
          todayDueCount: options.getSession().todayTaskTotalCount || options.getTodayDueCount(),
          todayCompletedCount: options.getTodayCompletedCount(),
          todayRemainingCount: options.getTodayRemainingCount(),
          groupResults: [],
          groupWrongResults: [],
          groupCorrect: 0,
          groupWrong: 0,
          groupAccuracyPercent: 0,
          showGroupDetails: false,
          resultTransitioning: false,
        })
        options.syncAnsweredFlags()
        options.showQuestion(restoredDraft.currentIndex)
        options.startReviewTimer()
        if (restoredDraft.restoredCount > 0) {
          options.showToast({ title: `已恢复 ${restoredDraft.restoredCount} 题草稿`, icon: 'none' })
        }
        return { status: 'entered' }
      }

      await options.refreshOverviewStatsSilently()
      if (!options.isPageAlive() || !options.isFlowCurrent(flowSeq)) return { status: 'dead' }
      if (options.getTodayRemainingCount() > 0) {
        options.showToast({ title: '任务状态已更新，请稍后重试', icon: 'none' })
        options.setData({ resultTransitioning: false })
        return { status: 'retry' }
      }
      return { status: 'complete' }
    },
  }
}

module.exports = {
  createNextRemoteBatchController,
}
