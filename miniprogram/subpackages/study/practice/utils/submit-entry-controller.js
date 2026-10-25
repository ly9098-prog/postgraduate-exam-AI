function createSubmitEntryController(options) {
  return {
    prepare: prepareImpl.bind(null, options),
  }
}

async function prepareImpl(options, skipConfirm) {
  const questions = options.getQuestions() || []
  const selectedSubjectId = options.getSelectedSubjectId()
  const selectedSubjectName = options.getSelectedSubjectName()
  const answerMap = options.getAnswerMap()
  const activeStartedMonoMs = options.getActiveStartedMonoMs()
  const comboCount = options.getComboCount()
  const total = questions.length || 0
  const answeredFlags = options.buildAnsweredFlags(questions, answerMap, 'id')
  const classification = options.classifyAnswers({
    questions,
    answerMap,
    answeredFlags,
    isMultiBlank: options.isMultiBlank,
  })

  if (classification.answeredCount === 0 && classification.partialQuestionIds.length === 0) {
    options.showToast({ title: '请至少完成或填写 1 题再提交', icon: 'none' })
    return null
  }

  const confirmed = await confirmSubmission(options, skipConfirm, classification, total)
  if (!confirmed) return null

  const context = buildSubmissionContext(options, questions, classification, total)
  if (!await ensureBatchToken(options)) return null
  const submission = buildSubmission(options, context)
  options.setSubmissionSnapshot(submission)
  submission.pendingPersisted = options.persistPendingSubmission(submission, 'pending', '')
  options.setUnloadGuard(true, '交卷仍在确认中。')
  return submission
}

function buildSubmissionContext(options, questions, classification, total) {
  const answerMap = options.getAnswerMap()
  const activeStartedMonoMs = options.getActiveStartedMonoMs()
  const selectedSubjectId = options.getSelectedSubjectId()
  options.clearTimer()
  options.settleQuestionTime(true)
  const finishedMonoMs = options.monotonicNow()
  const finishedAtMs = options.now()
  const duration = Math.max(0, Math.floor(
    (finishedMonoMs - activeStartedMonoMs - (options.getBackgroundMs() || 0)) / 1000
  ))
  const requestId = options.getRequestId() || options.buildRequestId()
  options.setRequestId(requestId)

  const answers = options.buildSubmitAnswers({
    completedQuestions: classification.completedQuestions,
    answerMap,
    questionTimeMap: options.getQuestionTimeMap(),
    recommendationRequestId: options.getRecommendationRequestId() || null,
  })
  const session = options.buildSubmitSession({
    requestId,
    subjectId: selectedSubjectId,
    mode: options.getBatchMode() || options.getSelectedMode() || 'random',
    startedAtMs: options.getStartedAtMs(),
    finishedAtMs,
    duration,
    total,
    answeredCount: classification.answeredCount,
  })
  const recoveryQuestions = options.buildRecoveryQuestions(questions)
  return {
    questions,
    classification,
    total,
    answerMap,
    requestId,
    finishedAtMs,
    duration,
    answers,
    session,
    recoveryQuestions,
    selectedSubjectId,
    selectedSubjectName: options.getSelectedSubjectName(),
    comboCount: options.getComboCount(),
    answeredFlags: options.buildAnsweredFlags(questions, answerMap, 'id'),
  }
}

function buildSubmission(options, context) {
  const {
    questions,
    classification,
    total,
    answerMap,
    requestId,
    finishedAtMs,
    duration,
    answers,
    session,
    recoveryQuestions,
    selectedSubjectId,
    selectedSubjectName,
    comboCount,
  } = context
  const { answeredFlags } = context
  const submission = options.buildSubmissionSnapshot({
    requestId,
    traceId: options.getTraceId() || '',
    answers,
    skippedQuestionIds: classification.skippedQuestionIds,
    partialQuestionIds: classification.partialQuestionIds,
    session,
    duration,
    total,
    unanswered: classification.unanswered,
    selectedSubjectId,
    selectedSubjectName,
    comboCount,
    answerMap,
    answeredFlags,
    recoveryQuestions,
    batchToken: options.getBatchToken() || '',
    knowledgeScope: options.getKnowledgeScope(),
  })
  return submission
}

async function ensureBatchToken(options) {
  if (options.getBatchToken()) return true
  await options.showConfirm({
    scenario: 'info',
    title: '练习批次已失效',
    message: '请返回后重新获取本组题目。',
    showCancel: false,
    confirmText: '知道了',
    hideEyebrow: true,
  })
  return false
}

async function confirmSubmission(options, skipConfirm, classification, total) {
  if (classification.unanswered > 0) {
    return options.showPausedConfirm({
      scenario: 'unanswered',
      title: `还有 ${classification.unanswered} 题未完成`,
      message: '现在交卷会将未完成题记为跳过。',
      confirmText: '仍然交卷',
      cancelText: '继续答题',
    })
  }
  if (skipConfirm !== true) {
    return options.showPausedConfirm({
      scenario: 'all-done',
      title: '确认交卷？',
      message: `已完成 ${classification.answeredCount} / ${total} 题`,
      confirmText: '确认交卷',
      cancelText: '继续检查',
    })
  }
  return true
}

module.exports = {
  createSubmitEntryController,
}
