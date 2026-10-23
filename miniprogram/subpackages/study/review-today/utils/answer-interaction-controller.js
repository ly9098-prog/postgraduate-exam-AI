const {
  isMultipleChoiceType,
  normalizeChoiceAnswer,
  serializeChoiceAnswer,
  serializeBlankAnswer,
} = require('../../utils/answer')
const adapter = require('../../utils/question-runner-adapter')

function createAnswerInteractionController(options) {
  return {
    selectOption(e) {
      return selectOptionImpl(options, e)
    },

    selectBlankOption(e) {
      return selectBlankOptionImpl(options, e)
    },
  }
}

function selectOptionImpl(options, e) {
  if (options.isSubmitting()) return
  const opt = e.detail.option
  if (!opt) return
  const q = options.getCurrentQuestion()
  const answers = { ...options.getAnswers() }

  if (isMultipleChoiceType(q.question_type)) {
    toggleMultipleChoice(answers, q.schedule_id, opt)
  } else {
    toggleSingleChoice(answers, q.schedule_id, opt)
  }

  options.setAnswers(answers)
  options.persistDraft()

  const optionList = adapter.buildOptionList(q, answers, options.getKeyField())
  const currentQuestion = Object.assign({}, q, { _optionList: optionList })
  const answeredCount = adapter.computeAnsweredCount(options.getGroupQuestions(), answers, options.getKeyField())
  options.setData({ currentQuestion, _answeredCount: answeredCount })
  options.syncAnsweredFlags()
  options.updateRunnerFields()
}

function toggleMultipleChoice(answers, scheduleId, opt) {
  const prev = answers[scheduleId] || ''
  const sel = normalizeChoiceAnswer(prev)
  const idx = sel.indexOf(opt)
  if (idx >= 0) sel.splice(idx, 1)
  else sel.push(opt)
  sel.sort()
  const newAnswer = serializeChoiceAnswer(sel.join(','))
  if (newAnswer) answers[scheduleId] = newAnswer
  else delete answers[scheduleId]
}

function toggleSingleChoice(answers, scheduleId, opt) {
  if (answers[scheduleId] === opt) {
    delete answers[scheduleId]
  } else {
    answers[scheduleId] = opt
  }
}

function selectBlankOptionImpl(options, e) {
  if (options.isSubmitting()) return
  const blankId = String(e.detail.blankId || '').trim()
  const opt = String(e.detail.option || '').trim().toUpperCase()
  const q = options.getCurrentQuestion()
  if (!q || !adapter.isMultiBlankChoice(q) || !blankId || !opt) return

  const answer = options.getAnswers()[q.schedule_id] || ''
  const blankAnswers = adapter.normalizeBlankAnswer(answer)

  if (typeof adapter.isMultiBlankMultipleChoice === 'function' && adapter.isMultiBlankMultipleChoice(q)) {
    toggleBlankMultipleChoice(blankAnswers, blankId, opt)
  } else if (blankAnswers[blankId] === opt) {
    delete blankAnswers[blankId]
  } else {
    blankAnswers[blankId] = opt
  }

  const rawGroups = adapter.getBlankOptionGroups(q)
  const newAnswer = serializeBlankAnswer(rawGroups, blankAnswers)
  const answers = { ...options.getAnswers() }
  if (newAnswer) answers[q.schedule_id] = newAnswer
  else delete answers[q.schedule_id]

  const enrichedGroups = adapter.enrichBlankOptionGroups(rawGroups, newAnswer)
  options.setAnswers(answers)
  options.persistDraft()

  const answeredCount = adapter.computeAnsweredCount(options.getGroupQuestions(), answers, options.getKeyField())
  const enrichedQuestions = adapter.applyAnsweredFlags(
    options.getGroupQuestions(),
    adapter.buildAnsweredFlags(options.getGroupQuestions(), answers, options.getKeyField()),
    options.getKeyField()
  )
  options.setData({
    _answeredCount: answeredCount,
    runnerProgressPercent: Math.round(answeredCount / (enrichedQuestions.length || 1) * 100),
    runnerSubtitle: options.buildRunnerSubtitle(),
    runnerSubjectName: q ? (q.subject_name || q._subjectLabel || '') : '',
    'currentQuestion._blankOptionGroups': enrichedGroups,
    'currentQuestion._hasBlankOptionGroups': enrichedGroups.length > 0,
    groupQuestions: enrichedQuestions,
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
  createAnswerInteractionController,
}
