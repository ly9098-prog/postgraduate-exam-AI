const {
  createPracticeLifecycleController,
} = require('./practice-lifecycle-controller')
const coldResume = require('./cold-resume-controller')

function createPracticeLifecyclePageController(page, monotonicNow) {
  page._coldResumeCreatedAt = Date.now()
  const controller = createPracticeLifecycleController({
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
  return {
    show: () => controller.show(),
    hide: () => { controller.hide(); coldResume.persist(page, monotonicNow) },
  }
}

module.exports = {
  createPracticeLifecyclePageController,
}
