function createSelfHealController(options) {
  return {
    enterSafeMode() {
      console.warn('[SELF_HEAL] CODE render violation detected — entering SAFE_MODE')
      options.setSafeModeActive(true)
      this.reRenderCurrentQuestion()
    },

    reRenderCurrentQuestion() {
      reRenderImpl(options)
    },
  }
}

function reRenderImpl(options) {
  const q = options.getQuestions()[options.getCurrentIndex()]
  if (!q) return
  options.clearRenderCache()
  const viewModelResult = options.buildViewModel(q, true)
  if (!viewModelResult) return
  options.setData({
    currentQuestion: viewModelResult.question,
    currentAnswerState: viewModelResult.answerState,
  })
  console.warn('[SELF_HEAL] Re-rendered q' + q.id + ' in SAFE_MODE, mode=' + viewModelResult.question._renderModel.mode)
}

module.exports = {
  createSelfHealController,
}
