function createQuestionTimerController(options) {
  return {
    settle(pause) {
      settleImpl(options, pause)
    },
  }
}

function settleImpl(options, pause) {
  const currentIndex = options.getCurrentIndex()
  const questions = options.getQuestions()
  const currentQuestionStartedMonoMs = options.getCurrentQuestionStartedMonoMs()
  const questionTimeMap = options.getQuestionTimeMap()

  if (!currentQuestionStartedMonoMs || !questions.length) return
  const q = questions[currentIndex]
  if (!q) return

  const elapsed = Math.max(0, Math.floor((options.monotonicNow() - currentQuestionStartedMonoMs) / 1000))
  const key = String(q.id)
  const map = { ...questionTimeMap }
  map[key] = (map[key] || 0) + elapsed
  options.setQuestionTimeMap(map)
  options.setCurrentQuestionStartedMonoMs(pause ? 0 : options.monotonicNow())
}

module.exports = {
  createQuestionTimerController,
}
