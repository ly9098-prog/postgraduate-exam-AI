const config = require('../../../config')
const adapter = require('../../study/utils/question-runner-adapter')
const { buildRenderModel } = require('../../study/utils/stem-render')

function normalizeQuestion(raw) {
  const q = Object.assign({}, raw || {})
  q.id = q.question_id == null ? q.id : q.question_id
  q.question_type = 'single_choice'
  q.content = q.content || {}
  q.options = q.options || {}
  return q
}

function buildRenderView(raw) {
  const q = normalizeQuestion(raw)
  const opts = adapter.getQuestionOptions(q) || q.options || {}
  const optionKeys = Object.keys(opts)
  const renderModel = buildRenderModel(q, opts, {
    enableMathImage: config.enableMathImage || false,
    DEV: config.DEV,
  })
  return {
    question: Object.assign({}, q, {
      _renderModel: renderModel,
      _opts: opts,
      _optionKeys: optionKeys,
      _hasBlankOptionGroups: false,
    }),
    optionKeys,
  }
}

function buildAnswerState(renderView, answer) {
  if (!renderView || !renderView.question) return null
  const q = renderView.question
  const value = String(answer || '').trim().toUpperCase()
  const flags = {}
  renderView.optionKeys.forEach((key) => { flags[key] = value === key })
  return {
    questionId: String(q.id == null ? '' : q.id),
    optionList: adapter.buildOptionListFromFlags(q._opts, renderView.optionKeys, flags),
    blankOptionGroups: [],
    hasBlankOptionGroups: false,
  }
}

function buildReadonlyState(renderView, correctAnswer, userAnswer) {
  if (!renderView || !renderView.question) return null
  const q = renderView.question
  return {
    questionId: String(q.id == null ? '' : q.id),
    optionList: adapter.buildOptionListReadonly(
      q,
      q._opts,
      renderView.optionKeys,
      correctAnswer,
      userAnswer
    ),
    blankOptionGroups: [],
    hasBlankOptionGroups: false,
  }
}

module.exports = {
  normalizeQuestion,
  buildRenderView,
  buildAnswerState,
  buildReadonlyState,
}
