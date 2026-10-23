const { buildRenderModel } = require('../../utils/stem-render')
const adapter = require('../../utils/question-runner-adapter')
const { debugLog, shouldDebugQuestion } = require('../../../../utils/debug')

function createPracticeQuestionDisplayController(options) {
  return {
    getRenderView(q, forceRebuild) {
      return getRenderViewImpl(options, q, forceRebuild)
    },

    buildAnswerState(renderView, answer) {
      return buildAnswerStateImpl(renderView, answer)
    },

    buildViewModel(q, forceRebuild) {
      return buildViewModelImpl(options, q, forceRebuild)
    },

    showQuestion(index) {
      return showQuestionImpl(options, index)
    },
  }
}

function getRenderViewImpl(options, q, forceRebuild) {
  if (!q) return null
  const session = options.getSession()
  if (!session.questionRenderCache) session.questionRenderCache = Object.create(null)
  const questionId = String(q.id == null ? '' : q.id)
  const cacheKey = [
    questionId || 'anonymous',
    String(q.question_version_id || q.question_version || 'version-unknown'),
    session.safeModeActive ? 'safe' : 'normal',
    options.isMathImageEnabled() ? 'math-image' : 'math-native',
  ].join(':')
  if (!forceRebuild && session.questionRenderCache[cacheKey]) {
    return session.questionRenderCache[cacheKey]
  }

  const isBlankChoice = adapter.isMultiBlankChoice(q)
  const rawBlankOptionGroups = isBlankChoice ? adapter.getBlankOptionGroups(q) : []
  const isTrueFalse = q.question_type === 'true_false' || q.question_type === 'judgement'
  const flatOptions = typeof adapter.getQuestionOptions === 'function'
    ? adapter.getQuestionOptions(q)
    : q.options
  const hasFlatOptions = flatOptions && Object.keys(flatOptions).length > 0
  const opts = (!isBlankChoice || rawBlankOptionGroups.length === 0) && hasFlatOptions
    ? flatOptions
    : (!isBlankChoice && isTrueFalse ? { A: '正确', B: '错误' } : null)
  const optionKeys = opts ? Object.keys(opts) : []

  const renderCfg = { enableMathImage: options.isMathImageEnabled() || false, DEV: options.isDev() }
  if (session.safeModeActive) renderCfg.SAFE_MODE = true
  const renderModel = buildRenderModel(q, opts, renderCfg)

  const result = {
    question: Object.assign({}, q, {
      _renderModel: renderModel,
      _opts: opts,
      _optionKeys: optionKeys,
      _hasBlankOptionGroups: rawBlankOptionGroups.length > 0,
    }),
    optionKeys,
    rawBlankOptionGroups,
  }
  session.questionRenderCache[cacheKey] = result
  return result
}

function buildAnswerStateImpl(renderView, answer) {
  if (!renderView || !renderView.question) return null
  const q = renderView.question
  const normalizedAnswer = answer || ''
  const blankOptionGroups = renderView.rawBlankOptionGroups.length > 0
    ? adapter.enrichBlankOptionGroups(renderView.rawBlankOptionGroups, normalizedAnswer)
    : []
  const isMulti = q.question_type === 'multiple_choice'
  const selectedFlags = {}
  for (let optionIndex = 0; optionIndex < renderView.optionKeys.length; optionIndex++) {
    const key = renderView.optionKeys[optionIndex]
    selectedFlags[key] = isMulti
      ? normalizedAnswer.split(',').indexOf(key) >= 0
      : normalizedAnswer === key
  }
  return {
    questionId: String(q.id == null ? '' : q.id),
    optionList: blankOptionGroups.length > 0
      ? []
      : adapter.buildOptionListFromFlags(q._opts, renderView.optionKeys, selectedFlags),
    blankOptionGroups,
    hasBlankOptionGroups: blankOptionGroups.length > 0,
  }
}

function buildViewModelImpl(options, q, forceRebuild) {
  const renderView = getRenderViewImpl(options, q, forceRebuild)
  if (!renderView) return null
  const answer = options.getAnswerMap()[String(q.id)] || ''
  return {
    question: renderView.question,
    answerState: buildAnswerStateImpl(renderView, answer),
    optionKeys: renderView.optionKeys,
    renderView,
  }
}

function showQuestionImpl(options, index) {
  options.settleQuestionTime()
  const q = options.getQuestions()[index]
  if (!q) return
  options.warmQuestionImages(index)

  let viewModelResult
  try {
    viewModelResult = buildViewModelImpl(options, q)
  } catch (renderErr) {
    console.error('切题渲染失败 index=' + index + ' id=' + q.id, renderErr)
    options.showToast({ title: '题目渲染失败，已保留上一题', icon: 'none' })
    return
  }
  if (!viewModelResult) {
    console.error('切题渲染失败 index=' + index + ' id=' + q.id)
    options.showToast({ title: '题目渲染失败，已保留上一题', icon: 'none' })
    return
  }

  const currentQuestion = viewModelResult.question
  const optionKeys = viewModelResult.optionKeys

  if (shouldDebugQuestion(q.id)) {
    debugLog(options.getTraceId(q), 'BEFORE_RENDER', {
      questionId: q.id,
      index,
      optionKeys,
      blankGroupCount: (viewModelResult.answerState.blankOptionGroups || []).length,
      renderMode: (currentQuestion._renderModel || {}).mode,
      sourceLen: ((q.content && (q.content.text || q.content.stem)) || '').length,
    })
  }

  options.setOptionKeys(optionKeys)
  options.setCurrentQuestionStartedMono()
  options.setData({
    currentIndex: index,
    currentQuestion: currentQuestion,
    currentAnswerState: viewModelResult.answerState,
  }, () => {
    options.updateComputedFields()
  })
  options.checkRenderInvariant(currentQuestion._renderModel)
}

module.exports = {
  createPracticeQuestionDisplayController,
}
