function createReviewSelfHealController(options) {
  return {
    enterSafeMode() {
      console.warn('[SELF_HEAL] review-today CODE render violation — entering SAFE_MODE')
      options.setSafeModeActive(true)
      if (options.getCurrentQuestion()) {
        const idx = options.getCurrentIndex()
        const q = options.getGroupQuestions()[idx]
        if (q) {
          const enriched = options.enrichQuestion(q)
          const groupQuestions = (options.getGroupQuestions() || []).slice()
          groupQuestions[idx] = enriched
          options.setData({ groupQuestions })
          options.showQuestion(idx)
        }
        console.warn('[SELF_HEAL] review-today re-rendered at index ' + idx + ' in SAFE_MODE')
      }
    },
  }
}

module.exports = {
  createReviewSelfHealController,
}
