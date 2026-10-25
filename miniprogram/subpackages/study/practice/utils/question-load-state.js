const EMPTY_VIEW = {
  launchingPreset: false,
  loading: false,
  started: false,
  questions: [],
  totalQuestions: 0,
  currentQuestion: null,
  currentAnswerState: null,
}

function buildResetView(errorText) {
  const view = { ...EMPTY_VIEW }
  if (errorText != null) view.errorText = errorText
  return view
}

function applyBatchCredentials(session, response, fallbackMode) {
  session.comboCount = 0
  session.recommendationRequestId = response.request_id || ''
  session.batchToken = response.batch_token || ''
  session.batchMode = response.mode || fallbackMode
  if (response.submission_request_id) session.requestId = response.submission_request_id
}

function hasMissingBatchCredentials(session, questionCount) {
  return questionCount > 0 && (!session.batchToken || !session.requestId)
}

function buildSequentialRestartView() {
  return { started: true, errorText: '', sequentialProgress: null }
}

function resetSequentialTiming(session) {
  session.activeStartedMonoMs = 0
  session.startedAtMs = 0
  session.backgroundMs = 0
  session._backgroundStartedMonoMs = null
}

function buildLoadedView(questions, viewModelResult) {
  return {
    questions,
    totalQuestions: questions.length,
    currentIndex: 0,
    currentQuestion: viewModelResult ? viewModelResult.question : null,
    currentAnswerState: viewModelResult ? viewModelResult.answerState : null,
    launchingPreset: false,
    loading: false,
  }
}

function applyLoadedBatch(options, response, questions, mode) {
  options.debugAfterApi(response, questions)
  options.applyBatchCredentials(response, mode)
  if (options.hasMissingBatchCredentials(questions.length)) {
    throw new Error('服务器未返回可提交的练习批次凭据')
  }
  if (questions.length > 0) options.warmQuestionImages(questions, 0)
}

function enterLoadedBatch(options, questions, viewModelResult) {
  options.setData(options.buildLoadedView(questions, viewModelResult))
  if (questions.length > 0) {
    options.startLoadedSession(viewModelResult)
    options.checkRenderInvariant(viewModelResult.question._renderModel)
  } else {
    options.showNoQuestions(options.getSubjectId())
  }
}

module.exports = {
  buildResetView,
  applyBatchCredentials,
  hasMissingBatchCredentials,
  buildSequentialRestartView,
  resetSequentialTiming,
  buildLoadedView,
  applyLoadedBatch,
  enterLoadedBatch,
}
