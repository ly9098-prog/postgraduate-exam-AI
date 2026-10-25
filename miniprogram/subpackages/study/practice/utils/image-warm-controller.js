function createImageWarmController(options) {
  return {
    warm: warmImpl.bind(null, options),
  }
}

function warmImpl(options, questions, index) {
  if (!Array.isArray(questions) || !questions.length) return
  const current = questions[index]
  if (!current || typeof options.getQuestionPrefetchUrls !== 'function') return
  const currentId = String(current.id == null ? '' : current.id)
  const currentUrls = options.getQuestionPrefetchUrls(current)
  if (currentUrls.length) {
    options.preloadMany(currentUrls, 3).then(() => {
      if (!options.isPageAlive() || options.getCurrentIndex() !== index) return
      const visible = options.getQuestions()[index]
      if (!visible || String(visible.id == null ? '' : visible.id) !== currentId) return
      try {
        const refreshed = options.buildQuestionViewModel(visible, true)
        if (!refreshed) return
        options.setOptionKeys(refreshed.optionKeys)
        options.setData({
          currentQuestion: refreshed.question,
          currentAnswerState: refreshed.answerState,
        })
      } catch (err) {
        if (options.isDev()) options.logWarn('[practice] image cache refresh failed', err)
      }
    })
  }
  const neighborIndexes = [index + 1, index + 2, index - 1]
  const neighborUrls = []
  for (let i = 0; i < neighborIndexes.length; i++) {
    const q = questions[neighborIndexes[i]]
    if (!q) continue
    const urls = options.getQuestionPrefetchUrls(q)
    for (let j = 0; j < urls.length; j++) neighborUrls.push(urls[j])
  }
  if (neighborUrls.length) options.preloadMany(neighborUrls, 2)
}

module.exports = {
  createImageWarmController,
}
