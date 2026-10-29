const { REVIEW_DRAFT_PREFIX } = require('./review-runner-support')
const { getChinaDate } = require('../../../../utils/china-time')
const { createReviewDraftController } = require('./draft-controller')

function buildReviewDraftPageCapabilities(page, deps) {
  const { storage } = deps
  return {
      getDraftKey: () => {
        const session = page._reviewSession || (page._reviewSession = page._createReviewSession())
        const user = storage.get(storage.KEYS.USER) || {}
        const userId = user.id != null ? user.id : (user.user_id != null ? user.user_id : 'current')
        const taskDate = String(session.taskDate || getChinaDate(0))
        return REVIEW_DRAFT_PREFIX + ':' + String(userId) + ':' + taskDate
      },
      readStorage: key => storage.get(key),
      writeStorage: (key, value) => storage.set(key, value),
      removeStorage: key => storage.remove(key),
      getSession: () => page._reviewSession,
      getCurrentDate: () => getChinaDate(0),
      getPhase: () => page.data.phase,
      getGroupQuestions: () => page.data.groupQuestions,
      getCurrentQuestion: () => page.data.currentQuestion,
      now: () => Date.now(),
  }
}

module.exports = {
  buildReviewDraftPageCapabilities,
}