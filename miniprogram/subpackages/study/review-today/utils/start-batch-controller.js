function createStartBatchController(options) {
  return {
    async start() {
      if (options.getTodayRemainingCount() <= 0) return
      if (options.isStarting() || options.isContinuing()) return
      const flowSeq = options.nextFlowSeq()
      options.setData({
        isStarting: true,
        batchLoading: true,
        phase: 'loading',
      })
      try {
        const batch = await options.postNextBatch({
          batch_size: options.getBatchSize(),
        })
        if (!options.isPageAlive() || !options.isFlowCurrent(flowSeq)) return
        const rawQuestions = batch.questions || []
        if (!rawQuestions.length) {
          options.showToast({ title: '今日没有待复习题目', icon: 'none' })
          await options.loadOverview()
          return
        }
        const questions = normalizeQuestions(rawQuestions, options)
        if (!questions.length) throw new Error('所有题目标准化后为空')
        const prepared = prepareQuestions(questions, batch, options)
        applyPreparedBatch(prepared, batch, options)
      } catch (error) {
        handleStartError(options, flowSeq, error)
      }
    },
  }
}

function normalizeQuestions(rawQuestions, options) {
  const questions = []
  rawQuestions.forEach(rawQuestion => {
    const question = options.normalizeQuestion(rawQuestion)
    if (question) questions.push(question)
  })
  return questions
}

function prepareQuestions(questions, batch, options) {
  const session = options.getSession()
  const restoredDraft = options.restoreDraft(questions)
  resetSessionForBatch(session, restoredDraft, questions, batch)

  const firstEnriched = options.enrichQuestion(questions[0])
  const preparedQuestions = questions.slice()
  preparedQuestions[0] = firstEnriched
  const currentIndex = Math.min(
    Math.max(0, restoredDraft.currentIndex || 0),
    preparedQuestions.length - 1
  )
  if (currentIndex > 0) {
    preparedQuestions[currentIndex] = options.enrichQuestion(preparedQuestions[currentIndex])
  }
  const currentEnriched = preparedQuestions[currentIndex]
  const currentOptionList = options.buildOptionList(currentEnriched, restoredDraft.answers)
  let currentBlankOptionGroups = currentEnriched._blankOptionGroups || []
  if (currentEnriched._hasBlankOptionGroups) {
    const restoredAnswer = restoredDraft.answers[currentEnriched.schedule_id] || ''
    currentBlankOptionGroups = options.enrichBlankOptionGroups(
      options.getBlankOptionGroups(currentEnriched),
      restoredAnswer
    )
  }
  const currentQuestion = Object.assign({}, currentEnriched, {
    _optionList: currentOptionList,
    _blankOptionGroups: currentBlankOptionGroups,
    _hasBlankOptionGroups: currentBlankOptionGroups.length > 0,
  })
  session.optionKeys = currentEnriched._optionKeys
  session.allQuestions = preparedQuestions
  return {
    preparedQuestions,
    currentIndex,
    currentEnriched,
    currentQuestion,
    restoredDraft,
  }
}

function resetSessionForBatch(session, restoredDraft, questions, batch) {
  session.answers = restoredDraft.answers
  session.sessionId = batch.session_id || ''
  session.currentGroupId = batch.group_id || ''
  session.allGroupResults = []
  session.totalCorrect = 0
  session.totalWrong = 0
  session.totalCompleted = 0
  session.safeModeActive = false
  session.renderTraces = []
  session.allQuestions = questions
}

function applyPreparedBatch(prepared, batch, options) {
  const data = options.getData()
  const session = options.getSession()
  const taskTotalCount = Math.max(
    Number(session.todayTaskTotalCount || 0),
    Number(data.todayDueCount || 0),
    Number(batch.today_due_count || 0),
    prepared.preparedQuestions.length
  )
  const completedBeforeSession = Math.max(
    Number(session.completedBeforeSession || 0),
    Number(data.todayCompletedCount || 0),
    Number(batch.today_completed_count || 0)
  )
  session.todayTaskTotalCount = taskTotalCount
  session.completedBeforeSession = completedBeforeSession
  const viewPatch = buildBatchView(prepared, batch, options, {
    taskTotalCount,
    completedBeforeSession,
  })
  options.checkSetDataSize({
    phase: 'reviewing',
    currentQuestion: prepared.currentQuestion,
  })
  options.setData(viewPatch)
  options.syncAnsweredFlags()
  options.updateRunnerFields()
  options.checkRenderInvariant(prepared.currentEnriched._renderModel)
  options.recordRenderTrace(
    prepared.currentEnriched._renderModel
    && prepared.currentEnriched._renderModel.renderTrace
  )
  options.startReviewTimer()
  if (prepared.restoredDraft.restoredCount > 0) {
    options.showToast({ title: `已恢复 ${prepared.restoredDraft.restoredCount} 题草稿`, icon: 'none' })
  }
}

function buildBatchView(prepared, batch, options, counts) {
  return {
    phase: 'reviewing',
    groups: [prepared.preparedQuestions],
    currentGroupIdx: 0,
    groupQuestions: prepared.preparedQuestions,
    currentIndex: prepared.currentIndex,
    currentQuestion: prepared.currentQuestion,
    _answeredCount: options.computeAnsweredCount(
      prepared.preparedQuestions,
      prepared.restoredDraft.answers
    ),
    currentBatchNo: batch.batch_no || 1,
    totalBatchCount: batch.total_batch_count || options.getTotalBatchCount(),
    todayDueCount: counts.taskTotalCount,
    todayCompletedCount: counts.completedBeforeSession,
    todayRemainingCount: Math.max(0, counts.taskTotalCount - counts.completedBeforeSession),
    groupResults: [],
    groupWrongResults: [],
    groupCorrect: 0,
    groupWrong: 0,
    _groupSkipped: 0,
    groupAccuracyPercent: 0,
    showGroupDetails: false,
    masterConfirmId: null,
    submittingGroup: false,
    resultTransitioning: false,
    batchLoading: false,
    isStarting: false,
    isContinuing: false,
  }
}

function handleStartError(options, flowSeq, error) {
  if (!options.isPageAlive() || !options.isFlowCurrent(flowSeq)) return
  options.logError('[REVIEW_ERROR] startTodayReview failed',
    'batchSize=' + options.getBatchSize(),
    'statusCode=' + (error.statusCode || 'N/A'),
    'detail=' + (error.detail || error.message || 'unknown'))
  options.setData({
    isStarting: false,
    isContinuing: false,
    batchLoading: false,
    phase: 'error',
    errorText: '获取复习题失败，请检查网络后重试',
  })
  options.showToast({ title: '获取复习题失败，请重试', icon: 'none' })
}

module.exports = {
  createStartBatchController,
}
