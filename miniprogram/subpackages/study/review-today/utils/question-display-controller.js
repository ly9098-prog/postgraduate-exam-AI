const adapter = require('../../utils/question-runner-adapter')

function createQuestionDisplayController(options) {
  return {
    showQuestion(index) {
      return showQuestionImpl(options, index)
    },

    updateRunnerFields() {
      updateRunnerFieldsImpl(options)
    },

    syncAnsweredFlags() {
      syncAnsweredFlagsImpl(options)
    },
  }
}

function showQuestionImpl(options, index) {
  const questions = options.getGroupQuestions()
  const q = questions[index]
  if (!q) return

  const enriched = q._renderModel ? q : options.enrichQuestion(q)
  const answers = options.getAnswers()
  const keyField = options.getKeyField()

  const answeredCount = adapter.computeAnsweredCount(questions, answers, keyField)
  const optionList = adapter.buildOptionList(enriched, answers, keyField)
  let blankOptionGroups = enriched._blankOptionGroups || []
  let hasBlankOptionGroups = enriched._hasBlankOptionGroups || false
  if (hasBlankOptionGroups) {
    const answer = answers[enriched.schedule_id] || ''
    blankOptionGroups = adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(enriched), answer)
  }

  const currentQuestion = Object.assign({}, enriched, {
    _optionList: optionList,
    _blankOptionGroups: blankOptionGroups,
    _hasBlankOptionGroups: blankOptionGroups.length > 0,
  })

  options.setOptionKeys(enriched._optionKeys)

  if (!q._renderModel) {
    const gq = questions.slice()
    gq[index] = enriched
    options.setData({ groupQuestions: gq })
  }

  options.checkSetDataSize({ currentIndex: index, currentQuestion: currentQuestion })
  options.setData({
    currentIndex: index,
    currentQuestion: currentQuestion,
    _answeredCount: answeredCount,
  })
  updateRunnerFieldsImpl(options)
  options.checkRenderInvariant(enriched._renderModel)
  options.recordRenderTrace(enriched._renderModel && enriched._renderModel.renderTrace)
}

function updateRunnerFieldsImpl(options) {
  const grp = options.getGroupQuestions() || []
  const total = grp.length || 1
  const answered = options.getAnsweredCount() || 0
  options.setData({
    runnerProgressPercent: Math.round(answered / total * 100),
    runnerSubtitle: options.buildRunnerSubtitle(),
    runnerSubjectName: options.getCurrentQuestion()
      ? (options.getCurrentQuestion().subject_name || options.getCurrentQuestion()._subjectLabel || '')
      : '',
  })
}

function syncAnsweredFlagsImpl(options) {
  const questions = options.getGroupQuestions()
  const enriched = adapter.applyAnsweredFlags(
    questions,
    adapter.buildAnsweredFlags(questions, options.getAnswers(), options.getKeyField()),
    options.getKeyField()
  )
  options.setData({ groupQuestions: enriched })
}

module.exports = {
  createQuestionDisplayController,
}
