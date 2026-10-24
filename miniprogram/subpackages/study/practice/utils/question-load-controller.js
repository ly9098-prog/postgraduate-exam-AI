function createQuestionLoadController(options) {
  return {
    load: loadImpl.bind(null, options),
  }
}

async function loadImpl(options) {
  const loadSeq = options.nextRequestSeq()
  if (!options.isLoading()) options.setData({ loading: true })
  try {
    const result = await loadQuestions(options, loadSeq)
    return result
  } catch (error) {
    if (!options.isPageAlive() || loadSeq !== options.getRequestSeq()) return false
    if (error.renderFailure) {
      options.logError('首题渲染失败', error)
      options.resetToSetup('题目解析失败，可重试或返回选题')
      return false
    }
    options.logError('加载题目失败', error)
    options.resetToSetup('加载题目失败，请重试或返回重新选择科目')
    options.showToast({ title: '加载题目失败', icon: 'none' })
    return false
  }
}

async function loadQuestions(options, loadSeq) {
  const subjectId = options.getSubjectId()
  if (!subjectId) {
    options.resetToSetup()
    options.showToast({ title: '请选择科目', icon: 'none' })
    return false
  }

  const mode = options.getSelectedMode() || 'random'
  const params = options.buildRequestParams()
  const response = await options.requestQuestions(params)
  if (!options.isPageAlive() || loadSeq !== options.getRequestSeq()) return false

  const scopeError = options.validateKnowledgeScope(response)
  if (scopeError) {
    options.logError(scopeError.logTag, scopeError.logDetail)
    options.resetToSetup(scopeError.resetMessage)
    options.showToast({ title: scopeError.toastTitle, icon: 'none' })
    return false
  }

  options.applyKnowledgeScope(response)
  const batchError = options.findBatchError(response)
  const recovery = options.resolveBatchErrorRecovery(batchError, response)
  if (recovery) {
    options.logError(recovery.logTag, recovery.logDetail)
    options.resetToSetup(recovery.resetMessage)
    options.showToast({ title: recovery.toastTitle, icon: 'none' })
    return false
  }

  const questions = options.applyAnsweredFlags(response)
  const sequentialProgress = mode === 'sequential'
    ? (response.sequential_progress || null)
    : null
  options.setData({ sequentialProgress })

  if (
    mode === 'sequential' &&
    questions.length === 0 &&
    sequentialProgress &&
    sequentialProgress.cycle_completed
  ) {
    await options.restartSequential(sequentialProgress, subjectId, loadSeq)
    return false
  }

  options.debugAfterApi(response, questions)
  options.applyBatchCredentials(response, mode)
  if (options.hasMissingBatchCredentials(questions.length)) {
    throw new Error('服务器未返回可提交的练习批次凭据')
  }

  if (questions.length > 0) options.warmQuestionImages(questions, 0)
  const viewModelResult = renderFirstQuestion(options, questions)

  options.setData(options.buildLoadedView(questions, viewModelResult))
  if (questions.length > 0) {
    options.startLoadedSession(viewModelResult)
    options.checkRenderInvariant(viewModelResult.question._renderModel)
  } else {
    options.showNoQuestions(subjectId)
  }
  return true
}

function renderFirstQuestion(options, questions) {
  const viewModel = questions.length > 0 ? options.buildFirstViewModel(questions[0]) : null
  if (questions.length > 0 && !viewModel) {
    const error = new Error('_buildQuestionViewModel returned null')
    error.renderFailure = true
    throw error
  }
  return viewModel
}

module.exports = {
  createQuestionLoadController,
}
