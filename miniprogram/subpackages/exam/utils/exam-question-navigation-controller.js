function createExamQuestionNavigationController(options) {
  return {
    setCurrent: setCurrentImpl.bind(null, options),
    moveTo: moveToImpl.bind(null, options),
  }
}

function setCurrentImpl(options, index) {
  const questions = options.getQuestions()
  if (!questions.length) return
  index = Math.max(0, Math.min(Number(index) || 0, questions.length - 1))
  const question = questions[index]
  const itemId = String(question._itemId)
  const answer = options.getAnswer(itemId) || {}
  const renderView = options.getRenderView(itemId)
  options.setQuestionEnterAt(options.now())
  const answeredCount = questions.reduce((count, item) => count + (item._answered ? 1 : 0), 0)
  options.setData({
    currentIndex: index,
    currentQuestion: question,
    currentAnswerState: options.buildAnswerState(renderView, answer.selected_answer),
    markedForReview: !!answer.marked_for_review,
    answeredCount,
    progressPercent: questions.length ? Math.round((answeredCount / questions.length) * 100) : 0,
  })
}

function moveToImpl(options, index) {
  if (options.isTimeExpired() || options.isSubmitting() || options.isNavigationLocked()) return
  const previousItemId = options.getCurrentItemId()
  options.settleCurrentTime({ sync: false })
  if (previousItemId) options.syncItem(previousItemId).catch(() => {})
  setCurrentImpl(options, index)
}

module.exports = {
  createExamQuestionNavigationController,
}
