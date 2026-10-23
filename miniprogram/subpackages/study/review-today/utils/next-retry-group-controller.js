function createNextRetryGroupController(options) {
  return {
    enter(nextGroupIdx) {
      const currentGroups = options.getGroups()
      const retryQuestions = currentGroups[nextGroupIdx]
      if (
        nextGroupIdx >= currentGroups.length ||
        !retryQuestions ||
        retryQuestions.length === 0
      ) return null

      const previousAnswers = options.getSession().answers || {}
      const retryAnswers = {}
      retryQuestions.forEach(question => {
        const scheduleId = String(question.schedule_id)
        if (Object.prototype.hasOwnProperty.call(previousAnswers, scheduleId)) {
          retryAnswers[scheduleId] = previousAnswers[scheduleId]
        } else if (Object.prototype.hasOwnProperty.call(previousAnswers, question.schedule_id)) {
          retryAnswers[question.schedule_id] = previousAnswers[question.schedule_id]
        }
      })
      options.getSession().answers = retryAnswers
      options.getSession().allQuestions = retryQuestions.slice()
      options.setData({
        phase: 'reviewing',
        currentGroupIdx: nextGroupIdx,
        groupQuestions: retryQuestions,
        currentIndex: 0,
        groupResults: [],
        groupWrongResults: [],
        groupCorrect: 0,
        groupWrong: 0,
        groupAccuracyPercent: 0,
        showGroupDetails: false,
        resultTransitioning: false,
      })
      options.syncAnsweredFlags()
      options.showQuestion(0)
      options.startReviewTimer()
      return retryQuestions
    },
  }
}

module.exports = {
  createNextRetryGroupController,
}
