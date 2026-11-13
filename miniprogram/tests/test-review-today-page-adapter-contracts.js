const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')

const root = path.resolve(__dirname, '..')

const {
  buildReviewDraftPageCapabilities,
} = require('../subpackages/study/review-today/utils/review-draft-page-adapter')
const {
  buildAnswerInteractionPageCapabilities,
  buildQuestionDisplayPageCapabilities,
  buildQuestionEnrichmentPageCapabilities,
  buildRenderSafetyPageCapabilities,
} = require('../subpackages/study/review-today/utils/review-answer-page-adapter')
const {
  buildOverviewVMPageCapabilities,
  buildBatchSizeSheetPageCapabilities,
  buildOverviewLoadPageCapabilities,
  buildReviewDaySyncPageCapabilities,
  buildOverviewSyncPageCapabilities,
} = require('../subpackages/study/review-today/utils/review-overview-page-adapter')
const {
  buildReviewSessionPageCapabilities,
  buildStartBatchPageCapabilities,
  buildNavBackPageCapabilities,
  buildReviewSelfHealPageCapabilities,
} = require('../subpackages/study/review-today/utils/review-session-page-adapter')
const {
  buildGroupSubmitFlowPageCapabilities,
  buildGroupSubmitEntryPageCapabilities,
  buildGroupSubmitRequestPageCapabilities,
  buildGroupSubmitResultPageCapabilities,
  buildResultDockPageCapabilities,
} = require('../subpackages/study/review-today/utils/review-submit-page-adapter')
const {
  buildReviewMasterPageCapabilities,
  buildNextGroupPageCapabilities,
  buildNextRetryGroupPageCapabilities,
  buildNextRemoteBatchPageCapabilities,
  buildReviewTimerPageCapabilities,
} = require('../subpackages/study/review-today/utils/review-progress-page-adapter')

const EXPECTED_PORTS = {
  AnswerInteraction: ['buildRunnerSubtitle', 'getAnswers', 'getCurrentQuestion', 'getGroupQuestions', 'getKeyField', 'isSubmitting', 'persistDraft', 'setAnswers', 'setData', 'syncAnsweredFlags', 'updateRunnerFields'],
  QuestionDisplay: ['buildRunnerSubtitle', 'checkRenderInvariant', 'checkSetDataSize', 'enrichQuestion', 'getAnsweredCount', 'getAnswers', 'getCurrentQuestion', 'getGroupQuestions', 'getKeyField', 'recordRenderTrace', 'setData', 'setOptionKeys'],
  QuestionEnrichment: ['isDev', 'isSafeModeActive', 'isTrueFalse', 'subjectLabel'],
  RenderSafety: ['enterSafeMode', 'getRenderTraces', 'isDev', 'isSafeModeActive', 'setRenderTraces'],
  ReviewDraft: ['getCurrentDate', 'getCurrentQuestion', 'getDraftKey', 'getGroupQuestions', 'getPhase', 'getSession', 'now', 'readStorage', 'removeStorage', 'writeStorage'],
  OverviewVM: ['getBatchSizeOptions', 'getCurrentUserBatchSize', 'getDefaultBatchSize', 'isUserBatchSizeSelected'],
  BatchSizeSheet: ['getBatchSizeOptions', 'getPendingBatchSize', 'getPhase', 'getReviewBatchSize', 'isContinuing', 'isStarting', 'markUserSelected', 'normalizeBatchSize', 'setData'],
  OverviewLoad: ['adjustVmForActiveSession', 'applyOverviewToSession', 'buildOverviewVM', 'getOverview', 'isAutoStartPending', 'isPageAlive', 'isRequestCurrent', 'logError', 'nextRequestSeq', 'setAutoStartPending', 'setData', 'setOverviewLoading', 'startReview'],
  ReviewDaySync: ['applyOverviewWithDayReset', 'buildOverviewVM', 'getOverview', 'isPageAlive', 'isSameDay', 'logError', 'setData', 'setDateStr', 'showFailureToast', 'showSuccessToast'],
  OverviewSync: ['getPhase', 'getSession', 'getTodayDueCount'],
  ReviewMaster: ['armUndoExpiry', 'clearReviewActivity', 'clearReviewTimer', 'clearTimeout', 'clearUndo', 'decrementMasteredCount', 'getData', 'getMasterUndoTimer', 'getPendingMasterUndo', 'getSession', 'getTodayRemainingCount', 'incrementMasteredCount', 'isMasterSubmitting', 'isMasterUndoInFlight', 'isPageAlive', 'isSubmittingGroup', 'logError', 'postMaster', 'postUnmaster', 'refreshOverviewStatsSilently', 'setData', 'setMasterUndoInFlight', 'setMasterUndoTimer', 'setPendingMasterUndo', 'setTimeout', 'showQuestion', 'showToast', 'startReviewTimer', 'syncAnsweredFlags', 'syncReviewSessionDay'],
  NextGroup: ['clearMasterUndo', 'clearResultDockFadeTimer', 'getCurrentGroupIdx', 'getData', 'getTodayRemainingCount', 'isFlowCurrent', 'isPageAlive', 'logError', 'nextFlowSeq', 'remoteBatchController', 'retryGroupController', 'setData', 'showResultDockAndRefreshTimer', 'showToast', 'syncReviewSessionDay'],
  NextRetryGroup: ['getGroups', 'getSession', 'setData', 'showQuestion', 'startReviewTimer', 'syncAnsweredFlags'],
  NextRemoteBatch: ['getBatchSize', 'getCurrentBatchNo', 'getSession', 'getTodayCompletedCount', 'getTodayDueCount', 'getTodayRemainingCount', 'getTotalBatchCount', 'isFlowCurrent', 'isPageAlive', 'normalizeQuestion', 'postNextBatch', 'refreshOverviewStatsSilently', 'restoreDraft', 'setData', 'showQuestion', 'showToast', 'startReviewTimer', 'syncAnsweredFlags'],
  ReviewTimer: ['clearInterval', 'createRequestId', 'formatElapsed', 'getSession', 'getTimerId', 'isPageAlive', 'monotonicNow', 'serverNow', 'setData', 'setInterval', 'setTimerId'],
  ReviewSession: ['getSession', 'setData'],
  StartBatch: ['buildOptionList', 'checkRenderInvariant', 'checkSetDataSize', 'computeAnsweredCount', 'enrichBlankOptionGroups', 'enrichQuestion', 'getBatchSize', 'getBlankOptionGroups', 'getCurrentFlowSeq', 'getData', 'getSession', 'getTodayRemainingCount', 'getTotalBatchCount', 'isContinuing', 'isFlowCurrent', 'isPageAlive', 'isStarting', 'loadOverview', 'logError', 'nextFlowSeq', 'normalizeQuestion', 'postNextBatch', 'recordRenderTrace', 'restoreDraft', 'setData', 'showToast', 'startReviewTimer', 'syncAnsweredFlags', 'updateRunnerFields'],
  NavBack: ['clearMasterUndo', 'clearReviewActivity', 'clearReviewTimer', 'getCurrentPages', 'getPhase', 'isExitConfirmPending', 'isSubmittingGroup', 'logWarn', 'navigateBack', 'reLaunch', 'setExitConfirmPending', 'showConfirm'],
  ReviewSelfHeal: ['enrichQuestion', 'getCurrentIndex', 'getCurrentQuestion', 'getGroupQuestions', 'setData', 'setSafeModeActive', 'showQuestion'],
  GroupSubmitFlow: ['applyResult', 'begin', 'buildTimingSession', 'confirm', 'enrichForResult', 'failureNeedsRefresh', 'getGroupQuestions', 'getRequestId', 'isPageAlive', 'isQuestionAnswered', 'logError', 'request', 'setSubmitting', 'showResultFailureToast'],
  GroupSubmitEntry: ['clearMasterUndo', 'computeAnsweredCount', 'confirmController', 'getData', 'getSession', 'isConfirmPending', 'isMasterUndoInFlight', 'isPageAlive', 'setSubmitting', 'showToast', 'syncReviewSessionDay'],
  GroupSubmitRequest: ['isPageAlive', 'postGrade', 'setSubmitting', 'showToast'],
  GroupSubmitResult: ['clearSubmittedDraft', 'getCurrentGroupIdx', 'getGroups', 'getSession', 'getTodayCompletedCount', 'getTodayDueCount', 'pauseTimer', 'setData', 'showResultDockAndRefreshTimer', 'showToast'],
  ResultDock: ['clearFadeTimer', 'clearTimeout', 'getFadeDelay', 'getPhase', 'getResultDockVisible', 'getTodayRemainingCount', 'isPageAlive', 'setData', 'setFadeTimer', 'setTimeout'],
}

const BUILDERS = {
  ReviewDraft: buildReviewDraftPageCapabilities,
  AnswerInteraction: buildAnswerInteractionPageCapabilities,
  QuestionDisplay: buildQuestionDisplayPageCapabilities,
  QuestionEnrichment: buildQuestionEnrichmentPageCapabilities,
  RenderSafety: buildRenderSafetyPageCapabilities,
  OverviewVM: buildOverviewVMPageCapabilities,
  BatchSizeSheet: buildBatchSizeSheetPageCapabilities,
  OverviewLoad: buildOverviewLoadPageCapabilities,
  ReviewDaySync: buildReviewDaySyncPageCapabilities,
  OverviewSync: buildOverviewSyncPageCapabilities,
  ReviewSession: buildReviewSessionPageCapabilities,
  StartBatch: buildStartBatchPageCapabilities,
  NavBack: buildNavBackPageCapabilities,
  ReviewSelfHeal: buildReviewSelfHealPageCapabilities,
  GroupSubmitFlow: buildGroupSubmitFlowPageCapabilities,
  GroupSubmitEntry: buildGroupSubmitEntryPageCapabilities,
  GroupSubmitRequest: buildGroupSubmitRequestPageCapabilities,
  GroupSubmitResult: buildGroupSubmitResultPageCapabilities,
  ResultDock: buildResultDockPageCapabilities,
  ReviewMaster: buildReviewMasterPageCapabilities,
  NextGroup: buildNextGroupPageCapabilities,
  NextRetryGroup: buildNextRetryGroupPageCapabilities,
  NextRemoteBatch: buildNextRemoteBatchPageCapabilities,
  ReviewTimer: buildReviewTimerPageCapabilities,
}

function recordingPage() {
  const calls = []
  const page = {
    data: {
      phase: 'reviewing',
      groupQuestions: [{ schedule_id: 1 }],
      currentQuestion: { schedule_id: 1 },
      currentGroupIdx: 0,
      groups: [],
      todayRemainingCount: 3,
      todayDueCount: 5,
      todayCompletedCount: 2,
      totalBatchCount: 1,
      currentBatchNo: 0,
      reviewBatchSize: 10,
      pendingBatchSize: 10,
      resultDockVisible: true,
      isStarting: false,
      isContinuing: false,
      submittingGroup: false,
    },
    _alive: true,
    _reviewSession: { answers: {}, allQuestions: [], taskDate: '2026-10-29' },
    setData: (...args) => calls.push(['setData', ...args]),
    _createReviewSession: () => ({ taskDate: '2026-10-29', answers: {} }),
    _clearMasterUndo: (...args) => calls.push(['clearMasterUndo', ...args]),
    _clearResultDockFadeTimer: (...args) => calls.push(['clearResultDockFadeTimer', ...args]),
    _syncReviewSessionDayIfNeeded: (...args) => calls.push(['syncDay', ...args]),
    _syncAnsweredFlags: (...args) => calls.push(['syncAnsweredFlags', ...args]),
    _showQuestion: (...args) => calls.push(['showQuestion', ...args]),
    _reviewMonotonicNow: () => 1234,
    _reviewServerNow: () => 4321,
    _nextRetryGroupController: () => ({ retry: () => 'retry' }),
    _nextRemoteBatchController: () => ({ next: () => 'next-remote' }),
  }
  return { page, calls }
}

function deps(extra = {}) {
  return {
    api: {
      post: async () => ({ results: [] }),
      createRequestId: () => 'req_1',
    },
    storage: {
      KEYS: { USER: 'user' },
      get: key => `stored:${key}`,
      set: () => {},
      remove: () => {},
    },
    config: { DEV: false },
    ...extra,
  }
}

test('every review-today page adapter exposes the frozen controller port set', () => {
  for (const [name, build] of Object.entries(BUILDERS)) {
    const { page } = recordingPage()
    const capabilities = build(page, deps())
    assert.deepEqual(Object.keys(capabilities).sort(), EXPECTED_PORTS[name], name)
  }
})

test('draft adapter reads and writes through the injected storage module', () => {
  const { page } = recordingPage()
  const writes = []
  const capabilities = buildReviewDraftPageCapabilities(page, {
    storage: {
      KEYS: { USER: 'user' },
      get: key => (key === 'user' ? { id: 7 } : null),
      set: (key, value) => writes.push([key, value]),
      remove: key => writes.push(['remove', key]),
    },
  })
  assert.equal(capabilities.getDraftKey(), 'review_today_draft_v1:7:2026-10-29')
  capabilities.writeStorage('k', { a: 1 })
  capabilities.removeStorage('k')
  assert.deepEqual(writes, [['k', { a: 1 }], ['remove', 'k']])
  assert.equal(capabilities.getSession(), page._reviewSession)
  assert.equal(capabilities.getPhase(), 'reviewing')
})

test('api-backed ports use the page-injected api module, not a module-level import', async () => {
  const { page, calls } = recordingPage()
  const posted = []
  const requestAdapter = buildGroupSubmitRequestPageCapabilities(page, {
    api: { post: async (url, payload) => { posted.push([url, payload]); return { results: [] } } },
  })
  await requestAdapter.postGrade({ reviews: [] })
  assert.deepEqual(posted, [['/review/grade-batch', { reviews: [] }]])

  const timerAdapter = buildReviewTimerPageCapabilities(page, {
    api: { createRequestId: () => 'req_9' },
    _reviewMonotonicNow: () => 55,
    _reviewServerNow: () => 66,
  })
  assert.equal(timerAdapter.monotonicNow(), 55)
  assert.equal(timerAdapter.serverNow(), 66)
  assert.equal(timerAdapter.createRequestId(), 'req_9')
  assert.equal(timerAdapter.formatElapsed(65), '01:05')
  assert.ok(calls.length >= 0)
})

test('controller ports stay delegated to the page helpers', () => {
  const { page, calls } = recordingPage()
  const flow = buildGroupSubmitFlowPageCapabilities(page, deps())
  assert.equal(flow.failureNeedsRefresh({ success: false, refresh_required: true }), true)
  assert.equal(flow.failureNeedsRefresh({ success: true }), false)
  assert.equal(flow.getGroupQuestions(), page.data.groupQuestions)

  const resultDock = buildResultDockPageCapabilities(page, deps())
  resultDock.clearFadeTimer()
  resultDock.setFadeTimer('timer')
  assert.ok(calls.some(call => call[0] === 'clearResultDockFadeTimer'))
  assert.equal(page._resultDockFadeTimer, 'timer')

  const overviewSync = buildOverviewSyncPageCapabilities(page, deps())
  assert.equal(overviewSync.getTodayDueCount(), 5)
  assert.equal(overviewSync.getPhase(), 'reviewing')
})

test('nav-back exit confirm uses the shared dialog selector and degrades to a toast', async () => {
  const { page } = recordingPage()
  const selectors = []
  const dialogs = []
  page.selectComponent = selector => {
    selectors.push(selector)
    return { show: options => { dialogs.push(options); return Promise.resolve(true) } }
  }
  const navBack = buildNavBackPageCapabilities(page, deps())
  assert.equal(await navBack.showConfirm({ title: 'x' }), true)
  assert.deepEqual(selectors, ['#submitConfirm'])
  assert.deepEqual(dialogs, [{ title: 'x' }])
  assert.equal(navBack.isExitConfirmPending(), false)
  navBack.setExitConfirmPending(true)
  assert.equal(navBack.isExitConfirmPending(), true)
  navBack.setExitConfirmPending(false)

  const { page: missingPage } = recordingPage()
  const toasts = []
  global.wx = { showToast: options => toasts.push(options) }
  try {
    missingPage.selectComponent = () => null
    const missing = buildNavBackPageCapabilities(missingPage, deps())
    assert.equal(await missing.showConfirm({}), false)
    assert.equal(toasts.length, 1)
  } finally {
    delete global.wx
  }
})

test('review-today registers the confirm component the exit prompt selects', () => {
  const config = JSON.parse(fs.readFileSync(
    path.join(root, 'subpackages/study/review-today/review-today.json'), 'utf8'))
  assert.equal(
    config.usingComponents['submit-confirm'],
    '/subpackages/study/components/submit-confirm/submit-confirm'
  )
})
