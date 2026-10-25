function createQuestionLoadWiring(page, deps) {
  return Object.assign(
    createRequestPorts(page, deps),
    createScopePorts(page, deps),
    createBatchPorts(page, deps),
    createSessionPorts(page, deps),
    createRecoveryPorts(page, deps)
  )
}

function createRequestPorts(page, deps) {
  return {
    nextRequestSeq: () => ++page._questionsRequestSeq,
    getRequestSeq: () => page._questionsRequestSeq,
    isPageAlive: () => page._pageAlive,
    isLoading: () => page.data.loading,
    setData: (data, callback) => page.setData(data, callback),
    getSubjectId: () => page.data.selectedSubjectId,
    getSelectedMode: () => page.data.selectedMode,
    buildRequestParams: () => page._buildQuestionRequestParams(),
    requestQuestions: params => deps.api.get('/practice/questions', params),
    logError: (...args) => console.error(...args),
    showToast: options => deps.wx.showToast(options),
  }
}

function createScopePorts(page, deps) {
  return {
    validateKnowledgeScope: response => {
      if (!page._launchIncludeDescendants) return null
      const scope = response && response.knowledge_scope
      if (deps.validateKnowledgeScope(scope, page._launchKnowledgePointId)) return null
      return {
        logTag: '[PRACTICE_KNOWLEDGE_SCOPE_MISMATCH]',
        logDetail: {
          requestedRootId: page._launchKnowledgePointId,
          requestedIncludeDescendants: true,
          receivedScope: scope || null,
          traceId: response && (response.trace_id || page._practiceSession.traceId),
        },
        resetMessage: '章节专项范围校验失败，请更新后端服务后重试。',
        toastTitle: '章节专项暂不可用',
      }
    },
    applyKnowledgeScope: response => {
      page._practiceSession.knowledgeScope = response && response.knowledge_scope
        ? Object.assign({}, response.knowledge_scope)
        : null
    },
  }
}

function createBatchPorts(page, deps) {
  return {
    findBatchError: response => deps.findQuestionBatchError(
      Array.isArray(response.questions) ? response.questions : [],
      {
        answerableTypes: deps.practiceAnswerableTypes,
        allowedScopeIds: new Set(
          page._getPracticeSubjectScopeIds(
            page.data.selectedSubjectId,
            page._buildQuestionRequestParams().include_children
          ).map(Number)
        ),
      }
    ),
    resolveBatchErrorRecovery: (batchError, response) => deps.resolveBatchErrorRecovery(
      batchError,
      {
        subjectId: page.data.selectedSubjectId,
        includeChildren: page._buildQuestionRequestParams().include_children,
        traceId: response.trace_id || page._practiceSession.traceId,
      }
    ),
    applyAnsweredFlags: response => deps.adapter.applyAnsweredFlags(
      Array.isArray(response.questions) ? response.questions : [],
      {},
      'id'
    ),
    applyBatchCredentials: (response, mode) => (
      deps.applyBatchCredentials(page._practiceSession, response, mode)
    ),
    hasMissingBatchCredentials: count => (
      deps.hasMissingBatchCredentials(page._practiceSession, count)
    ),
  }
}

function createSessionPorts(page, deps) {
  return {
    restartSequential: (progress, subjectId, loadSeq) => (
      page._sequentialRestartController().restart(
        progress,
        subjectId,
        page.data.selectedSubjectName,
        loadSeq
      )
    ),
    debugAfterApi: (response, questions) => {
      deps.debugLog(page._practiceSession.traceId, 'STATE_AFTER_API', {
        total: questions.length,
        responseTraceId: response.trace_id,
      })
      deps.saveDebugSnapshot(page._practiceSession.traceId, 'state_after_api', {
        total: questions.length,
        questionIds: questions.map(question => question.id),
      })
    },
    warmQuestionImages: (questions, index) => page._warmQuestionImages(questions, index),
    buildFirstViewModel: question => page._buildQuestionViewModel(question),
    buildLoadedView: (questions, viewModel) => deps.buildLoadedView(questions, viewModel),
    startLoadedSession: viewModel => {
      if (!page._practiceSession.activeStartedMonoMs) {
        page._practiceSession.activeStartedMonoMs = deps.monotonicNow()
        page._practiceSession.startedAtMs = deps.api.now()
        page._practiceSession.backgroundMs = 0
        page._practiceSession._backgroundStartedMonoMs = null
        page._practiceSession.elapsedSec = 0
      }
      page._practiceSession.optionKeys = viewModel.optionKeys
      page._practiceSession.currentQuestionStartedMonoMs = deps.monotonicNow()
      page._setPracticeUnloadGuard(true)
      page._startTimer()
      page._updateComputedFields()
    },
    checkRenderInvariant: model => page._checkRenderInvariant(model),
  }
}

function createRecoveryPorts(page, deps) {
  return {
    showNoQuestions: subjectId => {
      page._clearTimer()
      page._setPracticeUnloadGuard(false)
      const name = page.data.selectedSubjectName || String(subjectId)
      page.setData(deps.buildResetView())
      page._showSubmitConfirm({
        scenario: 'info',
        eyebrow: 'NO QUESTIONS',
        title: '该科目暂无可练题目',
        message: `「${name}」目前没有可在本页作答的已发布题目。\n可检查导入审核状态、题型与科目分类，或选择其他科目。`,
        confirmText: '返回选择科目',
        hideCancel: true,
      })
    },
    resetToSetup: errorText => {
      page._clearTimer()
      page._setPracticeUnloadGuard(false)
      page.setData(deps.buildResetView(errorText))
    },
  }
}

module.exports = {
  createQuestionLoadWiring,
}
