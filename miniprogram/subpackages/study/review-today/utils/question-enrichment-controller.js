const {
  buildRenderModel,
  stripLeadingOptionLabel,
  toPlainInlineMathText,
  needsRichRender,
  textToHtml,
} = require('../../utils/stem-render')
const adapter = require('../../utils/question-runner-adapter')

function createQuestionEnrichmentController(options) {
  return {
    splitGroups(questions, size) {
      return splitGroupsImpl(questions, size)
    },

    enrich(q) {
      return enrichImpl(options, q)
    },

    enrichForResult(q) {
      return enrichForResultImpl(options, q)
    },
  }
}

function splitGroupsImpl(questions, size) {
  const groups = []
  for (let i = 0; i < questions.length; i += size) {
    groups.push(questions.slice(i, i + size))
  }
  return groups
}

function enrichImpl(options, q) {
  const stemText = (q.content && (q.content.text || q.content.stem)) || q.stem || ''
  let opts = null
  let optionKeys = []
  if (q.options && Object.keys(q.options).length > 0) {
    opts = q.options
    optionKeys = Object.keys(opts)
  }
  if (options.isTrueFalse(q.question_type)) {
    opts = { A: '正确', B: '错误' }
    optionKeys = ['A', 'B']
  }

  const hasBlankGroups = adapter.isMultiBlankChoice(q) && adapter.getBlankOptionGroups(q).length > 0
  const blankOptionGroups = hasBlankGroups
    ? adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), '')
    : []

  var renderCfg = { enableMathImage: false, DEV: options.isDev() }
  if (options.isSafeModeActive()) renderCfg.SAFE_MODE = true
  const _renderModel = buildRenderModel(q, opts, renderCfg)

  const optText = {}
  const optNeedsRich = {}
  const optHtml = {}
  for (let optionIndex = 0; optionIndex < optionKeys.length; optionIndex++) {
    const key = optionKeys[optionIndex]
    const raw = (opts && opts[key]) || ''
    const text = stripLeadingOptionLabel(key, raw)
    const plain = toPlainInlineMathText(text)
    optText[key] = plain || text
    optNeedsRich[key] = !plain && needsRichRender(text)
    optHtml[key] = optNeedsRich[key] ? textToHtml(text) : ''
  }

  return {
    ...q,
    _opts: opts,
    _optionKeys: optionKeys,
    _optText: optText,
    _optNeedsRich: optNeedsRich,
    _optHtml: optHtml,
    _blankOptionGroups: blankOptionGroups,
    _hasBlankOptionGroups: blankOptionGroups.length > 0,
    _optionList: [],
    _renderModel,
    _stemPreview: stemText.length > 60 ? `${stemText.slice(0, 60)}...` : stemText,
    _subjectLabel: options.subjectLabel(q.subject_name, q.subject_code),
  }
}

function enrichForResultImpl(options, q) {
  if (q._renderModel) return q
  try {
    return enrichImpl(options, q)
  } catch (e) {
    console.error('题目渲染数据生成失败，退化为纯文本预览', e)
    const stemText = (q.content && (q.content.text || q.content.stem)) || q.stem || ''
    return Object.assign({}, q, {
      _renderModel: null,
      _stemPreview: stemText.length > 60 ? `${stemText.slice(0, 60)}...` : stemText,
    })
  }
}

module.exports = {
  createQuestionEnrichmentController,
}
