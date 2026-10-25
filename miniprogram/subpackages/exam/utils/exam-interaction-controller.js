function createExamInteractionController(options) {
  return {
    selectOption: selectOptionImpl.bind(null, options),
    toggleMark: toggleMarkImpl.bind(null, options),
  }
}

function isEditingBlocked(options) {
  return options.isTimeExpired() || options.isSubmitting() || options.isNavigationLocked()
}

function selectOptionImpl(options, e) {
  if (isEditingBlocked(options)) return
  const itemId = options.getCurrentItemId()
  if (!itemId) return
  const answer = options.getAnswer(itemId) || { used_time: 0 }
  answer.selected_answer = String(e.detail.option || '').trim().toUpperCase() || null
  options.setAnswer(itemId, answer)
  options.queueItem(itemId)
  options.updateQuestionFlags(itemId)
  const renderView = options.getRenderView(itemId)
  options.setData({
    currentAnswerState: options.buildAnswerState(renderView, answer.selected_answer),
  })
  options.setCountsOnly()
  options.syncItem(itemId).catch(() => {})
}

function toggleMarkImpl(options) {
  if (isEditingBlocked(options)) return
  const itemId = options.getCurrentItemId()
  if (!itemId) return
  const answer = options.getAnswer(itemId) || { used_time: 0 }
  answer.marked_for_review = !answer.marked_for_review
  options.setAnswer(itemId, answer)
  options.queueItem(itemId)
  options.updateQuestionFlags(itemId)
  options.setData({ markedForReview: !!answer.marked_for_review })
  options.syncItem(itemId).catch(() => {})
}

module.exports = {
  createExamInteractionController,
}
