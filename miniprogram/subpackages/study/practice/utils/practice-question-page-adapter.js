const coldResume = require('./cold-resume-controller')

function _startPracticeController(page, dependencies) {
const { api, createStartPracticeController, getPlatform } = dependencies
return page._startPracticeControllerInstance || (
page._startPracticeControllerInstance = createStartPracticeController({
isLoading: () => page.data.loading,
isSubmitting: () => page.data.submitting,
readPendingSubmission: () => page._readPendingSubmission(),
offerPendingSubmissionRecovery: () => page._offerPendingSubmissionRecovery(),
getSelectedSubjectId: () => page.data.selectedSubjectId,
openSubjectSheet: () => page.openSubjectSheet(),
getSelectedMode: () => page.data.selectedMode,
isSelectedSubjectHasChildren: () => page.data.selectedSubjectHasChildren,
showToast: options => getPlatform().showToast(options),
createTraceId: () => api.createTraceId(),
setSubmittedResultPayload: value => { page._submittedResultPayload = value },
resetSession: () => page._resetSession(),
setTraceId: traceId => { page._practiceSession.traceId = traceId },
setData: patch => page.setData(patch),
setUnloadGuard: enabled => page._setPracticeUnloadGuard(enabled),
flushPendingRecentSubject: () => page._flushPendingRecentSubject(),
loadQuestions: () => page._loadQuestions(),
})
)
}

function _imageWarmController(page, dependencies) {
const { adapter, config, createImageWarmController, getConsole, questionImageCache } = dependencies
return page._imageWarmControllerInstance || (
page._imageWarmControllerInstance = createImageWarmController({
isPageAlive: () => page._pageAlive,
getCurrentIndex: () => page.data.currentIndex,
getQuestions: () => page.data.questions,
getQuestionPrefetchUrls: adapter.getQuestionPrefetchUrls,
preloadMany: (urls, concurrency) => questionImageCache.preloadMany(urls, concurrency),
buildQuestionViewModel: (question, force) => page._buildQuestionViewModel(question, force),
setOptionKeys: keys => { page._practiceSession.optionKeys = keys },
setData: patch => page.setData(patch),
isDev: () => config.DEV,
logWarn: (...args) => getConsole().warn(...args),
})
)
}

function _questionDisplayController(page, dependencies) {
const { config, createPracticeQuestionDisplayController, getPlatform, monotonicNow } = dependencies
return page._questionDisplay || (
page._questionDisplay = createPracticeQuestionDisplayController({
getSession: () => page._practiceSession,
getAnswerMap: () => page._practiceSession.answerMap,
getQuestions: () => page.data.questions,
isMathImageEnabled: () => config.enableMathImage,
isDev: () => config.DEV,
setData: (patch, cb) => { page.setData(patch, cb); coldResume.persist(page) },
updateComputedFields: () => page._updateComputedFields(),
checkRenderInvariant: model => page._checkRenderInvariant(model),
showToast: options => getPlatform().showToast(options),
settleQuestionTime: () => page._settleQuestionTime(),
warmQuestionImages: index => page._warmQuestionImages(page.data.questions, index),
setOptionKeys: keys => { page._practiceSession.optionKeys = keys },
setCurrentQuestionStartedMono: () => { page._practiceSession.currentQuestionStartedMonoMs = monotonicNow() },
getTraceId: q => page._practiceSession.traceId || q.trace_id,
})
)
}

function _computedFieldsController(page, dependencies) {
const { createComputedFieldsController } = dependencies
return page._computedFields || (
page._computedFields = createComputedFieldsController({
getSelectedMode: () => page.data.selectedMode,
getCount: () => page.data.count,
getTotalQuestions: () => page.data.totalQuestions,
getAnsweredCount: () => page.data.answeredCount,
setData: patch => page.setData(patch),
})
)
}

function _answerFeedbackController(page, dependencies) {
const { createAnswerFeedbackController, getClearTimeout, getSetTimeout } = dependencies
return page._answerFeedback || (
page._answerFeedback = createAnswerFeedbackController({
getComboCount: () => page._practiceSession.comboCount,
setComboCount: count => { page._practiceSession.comboCount = count },
setData: patch => page.setData(patch),
clearFeedbackTimer: () => { if (page._feedbackTimer) { getClearTimeout()(page._feedbackTimer); page._feedbackTimer = null } },
setFeedbackTimer: (cb, ms) => { page._feedbackTimer = getSetTimeout()(cb, ms) },
})
)
}

function _renderInvariantController(page, dependencies) {
const { createRenderInvariantController } = dependencies
return page._renderInvariant || (
page._renderInvariant = createRenderInvariantController({
isSafeModeActive: () => page._practiceSession.safeModeActive,
enterSafeMode: () => page._enterSafeMode(),
})
)
}

function _questionTimerController(page, dependencies) {
const { createQuestionTimerController, monotonicNow } = dependencies
return page._questionTimer || (
page._questionTimer = createQuestionTimerController({
getCurrentIndex: () => page.data.currentIndex,
getQuestions: () => page.data.questions,
getCurrentQuestionStartedMonoMs: () => page._practiceSession.currentQuestionStartedMonoMs,
getQuestionTimeMap: () => page._practiceSession.questionTimeMap,
setQuestionTimeMap: map => { page._practiceSession.questionTimeMap = map },
setCurrentQuestionStartedMonoMs: ms => { page._practiceSession.currentQuestionStartedMonoMs = ms },
monotonicNow: () => monotonicNow(),
})
)
}

function _sequentialRestartController(page, dependencies) {
const { api, buildResetView, buildSequentialRestartView, createSequentialRestartController, getConsole, getPlatform, resetSequentialTiming } = dependencies
return page._sequentialRestart || (
page._sequentialRestart = createSequentialRestartController({
clearTimer: () => page._clearTimer(),
setUnloadGuard: value => page._setPracticeUnloadGuard(value),
setData: data => page.setData(data),
buildResetView: () => buildResetView(),
showRestartConfirm: options => page._showSubmitConfirm(options),
isPageAlive: () => page._pageAlive,
getRequestSeq: () => page._questionsRequestSeq,
getTraceId: () => page._practiceSession.traceId,
resetSequentialProgress: payload => api.post('/practice/sequential/reset', payload),
logError: (...args) => getConsole().error(...args),
showToast: options => getPlatform().showToast(options),
getSession: () => page._practiceSession,
resetSequentialTiming: session => resetSequentialTiming(session),
buildSequentialRestartView: () => buildSequentialRestartView(),
reloadQuestions: () => page._loadQuestions(),
})
)
}

function _selfHealController(page, dependencies) {
const { createSelfHealController } = dependencies
return page._selfHeal || (
page._selfHeal = createSelfHealController({
setSafeModeActive: v => { page._practiceSession.safeModeActive = v },
getQuestions: () => page.data.questions,
getCurrentIndex: () => page.data.currentIndex,
clearRenderCache: () => { page._practiceSession.questionRenderCache = Object.create(null) },
buildViewModel: (q, force) => page._buildQuestionViewModel(q, force),
setData: patch => page.setData(patch),
})
)
}

function _answerInteractionController(page, dependencies) {
const { createPracticeAnswerInteractionController, debugLog, saveDebugSnapshot, shouldDebugQuestion } = dependencies
return page._answerInteraction || (
page._answerInteraction = createPracticeAnswerInteractionController({
isSubmitted: () => page.data.submitted,
isSubmissionLocked: () => page._isSubmissionLocked(),
getCurrentQuestion: () => page.data.currentQuestion,
getAnswerMap: () => page._practiceSession.answerMap,
setAnswerMap: map => { page._practiceSession.answerMap = map },
getAnsweredFlags: () => page._practiceSession.answeredFlags,
setAnsweredFlags: flags => { page._practiceSession.answeredFlags = flags; coldResume.persist(page) },
getQuestions: () => page.data.questions,
getCurrentIndex: () => page.data.currentIndex,
getTotalQuestions: () => page.data.totalQuestions,
getQuestionRenderView: q => page._getQuestionRenderView(q),
buildQuestionAnswerState: (renderView, answer) => page._buildQuestionAnswerState(renderView, answer),
setData: (patch, cb) => page.setData(patch, cb),
updateComputedFields: () => page._updateComputedFields(),
debugStateChange: (q, prev, next, count) => {
if (shouldDebugQuestion(q.id)) {
debugLog(page._practiceSession.traceId || q.trace_id, 'STATE_CHANGE', {
questionId: q.id, previousAnswer: prev, nextAnswer: next, answeredCount: count,
})
saveDebugSnapshot(page._practiceSession.traceId || q.trace_id, 'state_change', {
questionId: q.id, previousAnswer: prev, nextAnswer: next, answeredCount: count,
})
}
},
})
)
}

function _submissionLockController(page, dependencies) {
const { createSubmissionLockController, getPlatform } = dependencies
return page._submissionLockControllerInstance || (
page._submissionLockControllerInstance = createSubmissionLockController({
getSubmissionSnapshot: () => page._practiceSession && page._practiceSession.submissionSnapshot,
showToast: options => getPlatform().showToast(options),
})
)
}

function goQuestion(page, e) {
const idx = e.detail.index
if (idx >= 0 && idx < page.data.totalQuestions) {
page._showQuestion(idx)
}
}

function _questionLoadController(page, dependencies) {
  if (!page._questionLoad) {
    const { getPlatform, ...ports } = dependencies
    const { createQuestionLoadController, createQuestionLoadWiring, ...wiring } = ports
    page._questionLoad = createQuestionLoadController(createQuestionLoadWiring(page, {
      ...wiring,
      wx: getPlatform(),
    }))
  }
  return page._questionLoad
}

module.exports = { _startPracticeController, _imageWarmController, _questionDisplayController, _computedFieldsController, _answerFeedbackController, _renderInvariantController, _questionTimerController, _sequentialRestartController, _selfHealController, _answerInteractionController, _submissionLockController, goQuestion, _questionLoadController }
