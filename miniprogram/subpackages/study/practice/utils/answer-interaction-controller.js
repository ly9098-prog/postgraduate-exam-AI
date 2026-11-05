const adapter = require('../../utils/question-runner-adapter')

function createPracticeAnswerInteractionController(options) {
  return {
    selectOption(e) {
      return selectOptionImpl(options, e)
    },

    selectBlankOption(e) {
      return selectBlankOptionImpl(options, e)
    },
    inputText(e) {
      if (options.isSubmitted() || options.isSubmissionLocked()) return
      const question = options.getCurrentQuestion()
      if (!question || !['fill_blank', 'subjective'].includes(question.question_type)) return
      const value = String(e.detail.value || '').slice(0, 4096)
      const map = { ...options.getAnswerMap(), [question.id]: value }
      const flags = adapter.buildAnsweredFlags(options.getQuestions(), map, 'id')
      options.setAnswerMap(map)
      options.setAnsweredFlags(flags)
      options.setData({
        textAnswer: value,
        [`questions[${options.getCurrentIndex()}]._answered`]: Boolean(flags[question.id]),
        answeredCount: adapter.countAnswered(flags),
      })
      options.updateComputedFields()
    },
  }
}

function selectOptionImpl(options, e) {
  if (options.isSubmitted() || options.isSubmissionLocked()) return
  const opt = e.detail.option
  const q = options.getCurrentQuestion()
  if (!q) return

  const isMulti = q.question_type === 'multiple_choice'
  const key = String(q.id)
  const prev = options.getAnswerMap()[key] || ''
  let newAnswer

  if (isMulti) {
    const sel = prev ? prev.split(',') : []
    const idx = sel.indexOf(opt)
    if (idx >= 0) sel.splice(idx, 1)
    else sel.push(opt)
    sel.sort()
    newAnswer = sel.join(',')
  } else {
    newAnswer = prev === opt ? '' : opt
  }

  const answerMap = { ...options.getAnswerMap() }
  if (newAnswer) {
    answerMap[key] = newAnswer
  } else {
    delete answerMap[key]
  }

  const answeredFlags = adapter.buildAnsweredFlags(options.getQuestions(), answerMap, 'id')
  const answeredCount = adapter.countAnswered(answeredFlags)
  const currentIdx = options.getCurrentIndex()
  const answered = !!answeredFlags[key]

  options.debugStateChange(q, prev, newAnswer, answeredCount)

  const renderView = options.getQuestionRenderView(q)
  const answerState = options.buildQuestionAnswerState(renderView, newAnswer)

  options.setAnswerMap(answerMap)
  options.setAnsweredFlags(answeredFlags)
  options.setData({
    [`questions[${currentIdx}]._answered`]: answered,
    answeredCount,
    currentAnswerState: answerState,
  }, () => {
    options.updateComputedFields()
  })
}

function selectBlankOptionImpl(options, e) {
  if (options.isSubmitted() || options.isSubmissionLocked()) return
  const blankId = String(e.detail.blankId || '').trim()
  const opt = String(e.detail.option || '').trim().toUpperCase()
  const q = options.getCurrentQuestion()
  if (!q || !adapter.isMultiBlankChoice(q) || !blankId || !opt) return

  const key = String(q.id)
  const prev = options.getAnswerMap()[key] || ''
  const blankAnswers = adapter.normalizeBlankAnswer(prev)

  if (typeof adapter.isMultiBlankMultipleChoice === 'function' && adapter.isMultiBlankMultipleChoice(q)) {
    toggleBlankMultipleChoice(blankAnswers, blankId, opt)
  } else if (blankAnswers[blankId] === opt) {
    delete blankAnswers[blankId]
  } else {
    blankAnswers[blankId] = opt
  }

  const renderView = options.getQuestionRenderView(q)
  const rawGroups = renderView ? renderView.rawBlankOptionGroups : adapter.getBlankOptionGroups(q)
  const newAnswer = adapter.serializeBlankAnswer(rawGroups, blankAnswers)
  const answerMap = { ...options.getAnswerMap() }
  if (newAnswer) {
    answerMap[key] = newAnswer
  } else {
    delete answerMap[key]
  }

  const answeredFlags = adapter.buildAnsweredFlags(options.getQuestions(), answerMap, 'id')
  const answeredCount = adapter.countAnswered(answeredFlags)
  const answerState = options.buildQuestionAnswerState(renderView, newAnswer)

  options.debugStateChange(q, prev, newAnswer, answeredCount)

  options.setAnswerMap(answerMap)
  options.setAnsweredFlags(answeredFlags)

  const currentIdx = options.getCurrentIndex()
  const answered = !!answeredFlags[key]
  const totalQuestions = options.getTotalQuestions() || 0
  options.setData({
    [`questions[${currentIdx}]._answered`]: answered,
    answeredCount,
    progressPercent: totalQuestions > 0 ? Math.round(answeredCount / totalQuestions * 100) : 0,
    currentAnswerState: answerState,
  })
}

function toggleBlankMultipleChoice(blankAnswers, blankId, opt) {
  const current = String(blankAnswers[blankId] || '').split(',').filter(Boolean)
  const next = current.indexOf(opt) >= 0
    ? current.filter(function (k) { return k !== opt })
    : current.concat([opt]).sort()
  if (next.length > 0) blankAnswers[blankId] = next.join(',')
  else delete blankAnswers[blankId]
}

module.exports = {
  createPracticeAnswerInteractionController,
}
