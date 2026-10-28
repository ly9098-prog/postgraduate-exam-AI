const {
  createPracticeLifecycleController,
} = require('./practice-lifecycle-controller')

function createPracticeLifecyclePageController(page, monotonicNow) {
  return createPracticeLifecycleController({
    getSession: () => page._practiceSession,
    monotonicNow,
    isQuestionActive: session => Boolean(
      page.data.started &&
      !page.data.loading &&
      !page.data.submitting &&
      !session.submissionSnapshot
    ),
    settleQuestionTime: pause => page._settleQuestionTime(pause),
  })
}

module.exports = {
  createPracticeLifecyclePageController,
}
