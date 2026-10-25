function createExamQuestionTimeController(options) {
  return {
    settle: settleImpl.bind(null, options),
  }
}

function settleImpl(options, settleOptions = {}) {
  const itemId = options.getCurrentItemId()
  if (!itemId || !options.getQuestionEnterAt()) return Promise.resolve()
  const now = options.now()
  const delta = Math.max(0, Math.floor((now - options.getQuestionEnterAt()) / 1000))
  options.setQuestionEnterAt(now)
  if (delta <= 0) return Promise.resolve()
  const answer = options.getAnswer(itemId) || { used_time: 0 }
  answer.used_time = Math.min(6 * 60 * 60, Math.max(0, Number(answer.used_time || 0)) + delta)
  options.setAnswer(itemId, answer)
  options.queueItem(itemId)
  if (settleOptions.sync === false) return Promise.resolve()
  return options.syncItem(itemId).catch(() => {})
}

module.exports = {
  createExamQuestionTimeController,
}
