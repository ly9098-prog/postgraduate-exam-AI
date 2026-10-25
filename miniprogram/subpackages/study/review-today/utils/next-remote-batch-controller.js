const {
  normalizeRemoteQuestions,
  enterRemoteBatch,
  resolveEmptyRemoteBatch,
} = require('./next-remote-batch-state')

function createNextRemoteBatchController(options) {
  return {
    async next(flowSeq) {
      const batch = await options.postNextBatch({
        batch_size: options.getBatchSize(),
      })
      if (!options.isPageAlive() || !options.isFlowCurrent(flowSeq)) return { status: 'dead' }

      const rawQuestions = batch.questions || []
      if (rawQuestions.length > 0) {
        const questions = normalizeRemoteQuestions(rawQuestions, options)
        const restoredDraft = options.restoreDraft(questions)
        enterRemoteBatch(batch, questions, restoredDraft, options)
        return { status: 'entered' }
      }
      return resolveEmptyRemoteBatch(flowSeq, options)
    },
  }
}

module.exports = {
  createNextRemoteBatchController,
}
