const assert = require('node:assert/strict')
const { test } = require('node:test')

const {
  buildExamPendingCachePageCapabilities,
  isPendingItemKey,
} = require('../subpackages/exam/utils/exam-runner-pending-cache-page-adapter')
const {
  buildExamTimerPageCapabilities,
} = require('../subpackages/exam/utils/exam-runner-timer-page-adapter')
const {
  buildExamInteractionPageCapabilities,
  buildExamQuestionTimePageCapabilities,
  buildExamAnswerSyncPageCapabilities,
  buildExamAttemptReconcilePageCapabilities,
} = require('../subpackages/exam/utils/exam-runner-answer-page-adapter')
const {
  buildExamQuestionNavigationPageCapabilities,
  buildExamExitRequestPageCapabilities,
} = require('../subpackages/exam/utils/exam-runner-navigation-page-adapter')
const {
  buildExamSubmitRetryPageCapabilities,
  buildExamSubmitEntryPageCapabilities,
  buildExamSubmitPreparationPageCapabilities,
  buildExamSubmitOutcomePageCapabilities,
} = require('../subpackages/exam/utils/exam-runner-submit-page-adapter')
const {
  buildExamReconnectPageCapabilities,
} = require('../subpackages/exam/utils/exam-runner-reconnect-page-adapter')
const { isRetryableSubmitError } = require('../subpackages/exam/utils/submit-helpers')

function recordingPage() {
  const calls = []
  const page = {
    data: {
      attemptId: 12,
      questions: [{ _itemId: 1 }],
      currentQuestion: { _itemId: 1 },
      timeExpired: false,
      submitting: false,
      totalCount: 3,
      answeredCount: 1,
      remainingText: '--:--',
    },
    _pageAlive: true,
    _terminalNavigation: false,
    _attemptTerminal: false,
    _attemptLoaded: true,
    _attemptAbandoned: false,
    _navigationLocked: false,
    _reconnectSyncing: false,
    _retainPendingForSubmit: false,
    _answers: { 1: { selected_answer: 'A' } },
    _renderCache: { 1: { question: {} } },
    _pending: { 1: { selected_answer: 'A' } },
    _questionEnterAt: 7,
    _timerBaseRemaining: 30,
    _timerStartedAt: 3,
    _timer: null,
    _submitPromise: null,
    _confirmingSubmit: false,
    setData: (...args) => calls.push(['setData', ...args]),
    _persistPending: (...args) => calls.push(['persistPending', ...args]),
    _pendingItemIds: () => Object.keys(page._pending),
    _currentItemId: () => String(page.data.currentQuestion._itemId),
    _queueItem: (...args) => calls.push(['queueItem', ...args]),
    _updateQuestionFlags: (...args) => calls.push(['updateQuestionFlags', ...args]),
    _setCountsOnly: (...args) => calls.push(['setCountsOnly', ...args]),
    _syncItem: (...args) => {
      calls.push(['syncItem', ...args])
      return Promise.resolve(true)
    },
    _settleCurrentTime: (...args) => calls.push(['settleCurrentTime', ...args]),
    _navigateToResult: (...args) => calls.push(['navigateToResult', ...args]),
    _navigateToPaperList: (...args) => calls.push(['navigateToPaperList', ...args]),
    _clearPendingStorage: (...args) => calls.push(['clearPendingStorage', ...args]),
    _reconcileAttemptState: () => {
      calls.push(['reconcileAttemptState'])
      return Promise.resolve(true)
    },
    // Mirrors the page rule: only a 409 conflict is reconciled locally.
    _resolveTerminalSyncConflict: error => {
      calls.push(['resolveTerminalSyncConflict', error])
      return Promise.resolve(Number(error && error.statusCode) === 409)
    },
    _setCurrent: index => calls.push(['setCurrent', index]),
    _clearTimer: () => calls.push(['clearTimer']),
    _currentRemainingSec: () => 42,
    _buildFinalSubmitAnswers: () => ({ 1: { selected_answer: 'A' } }),
    _performSubmit: auto => {
      calls.push(['performSubmit', auto])
      return Promise.resolve()
    },
    _tickTimer: () => calls.push(['tickTimer']),
    _showAppDialog: options => {
      calls.push(['showAppDialog', options])
      return Promise.resolve(true)
    },
    submitExam: options => {
      calls.push(['submitExam', options])
      return Promise.resolve(true)
    },
    _flushAllPending: options => {
      calls.push(['flushAllPending', options])
      return Promise.resolve(true)
    },
  }
  return { page, calls }
}

const EXPECTED_PORTS = {
  ExamPendingCache: ['cacheKey', 'clearPendingAttempt', 'getDraftTtlMs', 'getSchemaVersion',
    'getSubmitPendingTtlMs', 'isPendingItemKey', 'legacyCacheKey', 'now', 'readStorage',
    'removeStorage', 'sanitizePendingItems', 'setRetainPendingForSubmit', 'v2CacheKey',
    'writeStorage'],
  ExamTimer: ['clearInterval', 'formatClock', 'getBaseRemaining', 'getRemainingText',
    'getStartedAt', 'getTimer', 'isAttemptTerminal', 'isPageAlive', 'isTerminalNavigation',
    'isTimeExpired', 'now', 'onExpired', 'setBaseRemaining', 'setData', 'setInterval',
    'setStartedAt', 'setTimer'],
  ExamInteraction: ['buildAnswerState', 'getAnswer', 'getCurrentItemId', 'getRenderView',
    'isNavigationLocked', 'isSubmitting', 'isTimeExpired', 'queueItem', 'setAnswer',
    'setCountsOnly', 'setData', 'syncItem', 'updateQuestionFlags'],
  ExamQuestionTime: ['getAnswer', 'getCurrentItemId', 'getQuestionEnterAt', 'now', 'queueItem',
    'setAnswer', 'setQuestionEnterAt', 'syncItem'],
  ExamAnswerSync: ['getMaxSyncPasses', 'getPendingItem', 'getPendingItemIds',
    'isPendingItemUnchanged', 'onTerminalSync', 'patchAnswer', 'persistPending',
    'removePendingItem', 'resolveTerminalSyncConflict', 'showFlushError'],
  ExamAttemptReconcile: ['clearPending', 'getAttempt', 'isPageAlive', 'onAbandoned', 'onTerminal',
    'setAttemptAbandoned', 'setAttemptTerminal'],
  ExamSubmitRetry: ['getPageClosedMessage', 'getRetryDelays', 'getSubmitFailedMessage',
    'isPageAlive', 'isRetryableSubmitError', 'isTerminalNavigation', 'postSubmit',
    'reconcileAttemptState', 'sleep'],
  ExamReconnect: ['flushAllPending', 'isAttemptLoaded', 'isAttemptTerminal', 'isPageAlive',
    'isReconnectSyncing', 'isSubmitting', 'isTerminalNavigation', 'isTimeExpired',
    'setReconnectSyncing', 'submitExam', 'tickTimer'],
  ExamQuestionNavigation: ['buildAnswerState', 'getAnswer', 'getCurrentItemId', 'getQuestions',
    'getRenderView', 'isNavigationLocked', 'isSubmitting', 'isTimeExpired', 'now', 'setCurrent',
    'setData', 'setQuestionEnterAt', 'settleCurrentTime', 'syncItem'],
  ExamExitRequest: ['isNavigationLocked', 'isSubmitting', 'navigateBack', 'settleCurrentTime',
    'showExitDialog'],
  ExamSubmitEntry: ['buildConfirmDialog', 'clearSubmitPromise', 'getSubmitPromise',
    'isAttemptTerminal', 'isConfirmingSubmit', 'isNavigationLocked', 'isSubmitting',
    'isTimeExpired', 'performSubmit', 'setConfirmingSubmit', 'setSubmitPromise',
    'showConfirmDialog'],
  ExamSubmitPreparation: ['buildFinalSubmitAnswers', 'clearTimer', 'getCurrentRemainingSec',
    'isTimeExpired', 'onAutoResolved', 'persistPending', 'setRetainPendingForSubmit',
    'setSubmitting', 'settleCurrentTime'],
  ExamSubmitOutcome: ['clearPending', 'isPageAlive', 'navigateReconciled', 'navigateToResult',
    'reconcileAttemptState', 'setAttemptTerminal', 'setSubmitting', 'showAutoSubmitPending',
    'showManualSubmitError'],
}

const BUILDERS = {
  ExamPendingCache: buildExamPendingCachePageCapabilities,
  ExamTimer: buildExamTimerPageCapabilities,
  ExamInteraction: buildExamInteractionPageCapabilities,
  ExamQuestionTime: buildExamQuestionTimePageCapabilities,
  ExamAnswerSync: buildExamAnswerSyncPageCapabilities,
  ExamAttemptReconcile: buildExamAttemptReconcilePageCapabilities,
  ExamSubmitRetry: buildExamSubmitRetryPageCapabilities,
  ExamReconnect: buildExamReconnectPageCapabilities,
  ExamQuestionNavigation: buildExamQuestionNavigationPageCapabilities,
  ExamExitRequest: buildExamExitRequestPageCapabilities,
  ExamSubmitEntry: buildExamSubmitEntryPageCapabilities,
  ExamSubmitPreparation: buildExamSubmitPreparationPageCapabilities,
  ExamSubmitOutcome: buildExamSubmitOutcomePageCapabilities,
}

function withWx(storage, run) {
  const previous = global.wx
  global.wx = storage
  try {
    return run()
  } finally {
    global.wx = previous
  }
}

test('every page adapter exposes the frozen controller port set', () => {
  for (const [name, build] of Object.entries(BUILDERS)) {
    const { page } = recordingPage()
    const capabilities = build(page)
    assert.deepEqual(Object.keys(capabilities).sort(), EXPECTED_PORTS[name], name)
  }
})

test('pending cache ports read, write and sanitize through the page and wx storage', () => {
  const { page } = recordingPage()
  const storage = { values: { k: 'v' }, writes: [], removed: [] }
  withWx({
    getStorageSync: key => storage.values[key],
    setStorageSync: (key, value) => storage.writes.push([key, value]),
    removeStorageSync: key => storage.removed.push(key),
  }, () => {
    const capabilities = buildExamPendingCachePageCapabilities(page)
    assert.equal(capabilities.readStorage('k'), 'v')
    capabilities.writeStorage('k', 'w')
    capabilities.removeStorage('k')
    assert.deepEqual(storage.writes, [['k', 'w']])
    assert.deepEqual(storage.removed, ['k'])
    assert.equal(capabilities.getSchemaVersion(), 3)
    assert.equal(capabilities.getDraftTtlMs(), 3600000)
    assert.equal(capabilities.getSubmitPendingTtlMs(), 604800000)
    assert.equal(capabilities.isPendingItemKey('12'), true)
    assert.equal(capabilities.isPendingItemKey('12a'), false)
    const sanitized = capabilities.sanitizePendingItems({
      1: { selected_answer: ' a ', marked_for_review: 1, used_time: 10 },
      bad: { selected_answer: 'B' },
      2: 'not-an-object',
    })
    assert.equal(Object.getPrototypeOf(sanitized), null)
    assert.deepEqual(Object.assign({}, sanitized), {
      1: { selected_answer: 'A', marked_for_review: true, used_time: 10 },
    })
    capabilities.setRetainPendingForSubmit(true)
    assert.equal(page._retainPendingForSubmit, true)
  })
  assert.equal(isPendingItemKey('7'), true)
})

test('timer ports format the clock and hand expiry back to the page exactly once', () => {
  const { page, calls } = recordingPage()
  const capabilities = buildExamTimerPageCapabilities(page)
  assert.equal(capabilities.formatClock(3661), '01:01:01')
  assert.equal(capabilities.formatClock(61), '01:01')
  assert.equal(capabilities.isPageAlive(), true)
  assert.equal(capabilities.getBaseRemaining(), 30)
  capabilities.setBaseRemaining(15)
  capabilities.setStartedAt(9)
  capabilities.setTimer('timer-ref')
  assert.equal(page._timerBaseRemaining, 15)
  assert.equal(page._timerStartedAt, 9)
  assert.equal(page._timer, 'timer-ref')
  capabilities.onExpired()
  assert.equal(page._retainPendingForSubmit, true)
  assert.ok(calls.some(call => call[0] === 'persistPending'))
  assert.ok(calls.some(call => call[0] === 'submitExam' && call[1].auto === true))
})

test('answer interaction and question time ports keep the page state authoritative', () => {
  const { page, calls } = recordingPage()
  const interaction = buildExamInteractionPageCapabilities(page)
  assert.equal(interaction.isTimeExpired(), false)
  assert.equal(interaction.getCurrentItemId(), '1')
  assert.deepEqual(interaction.getAnswer('1'), { selected_answer: 'A' })
  interaction.setAnswer('1', { selected_answer: 'B' })
  interaction.queueItem('1')
  interaction.updateQuestionFlags('1')
  interaction.setCountsOnly()
  interaction.setData({ loading: false })
  assert.deepEqual(page._answers['1'], { selected_answer: 'B' })
  for (const expected of ['queueItem', 'updateQuestionFlags', 'setCountsOnly', 'setData']) {
    assert.ok(calls.some(call => call[0] === expected), expected)
  }

  const questionTime = buildExamQuestionTimePageCapabilities(page)
  assert.equal(questionTime.getQuestionEnterAt(), 7)
  assert.equal(typeof questionTime.now(), 'number')
  questionTime.setQuestionEnterAt(11)
  assert.equal(page._questionEnterAt, 11)
})

test('answer sync and reconcile ports keep pending snapshots and terminal callbacks', async () => {
  const { page, calls } = recordingPage()
  const sync = buildExamAnswerSyncPageCapabilities(page)
  assert.equal(sync.getMaxSyncPasses(), 2)
  assert.deepEqual(sync.getPendingItem('1'), { selected_answer: 'A' })
  assert.deepEqual(sync.getPendingItemIds(), ['1'])
  assert.equal(sync.isPendingItemUnchanged('1', { selected_answer: 'A' }), true)
  assert.equal(sync.isPendingItemUnchanged('1', { selected_answer: 'B' }), false)
  assert.equal(sync.isPendingItemUnchanged('missing', { selected_answer: 'B' }), false)
  sync.removePendingItem('1')
  assert.equal(Object.keys(page._pending).length, 0)
  sync.onTerminalSync()
  assert.equal(page._attemptTerminal, true)
  assert.ok(calls.some(call => call[0] === 'navigateToResult'))
  await sync.resolveTerminalSyncConflict({ statusCode: 409 })
  assert.equal(await sync.resolveTerminalSyncConflict({ statusCode: 500 }), false)

  const reconcile = buildExamAttemptReconcilePageCapabilities(page)
  assert.equal(reconcile.isPageAlive(), true)
  reconcile.setAttemptTerminal(false)
  reconcile.setAttemptAbandoned(true)
  assert.equal(page._attemptTerminal, false)
  assert.equal(page._attemptAbandoned, true)
  calls.length = 0
  reconcile.onAbandoned()
  assert.ok(calls.some(call => call[0] === 'navigateToPaperList'))
  calls.length = 0
  page.data.submitting = true
  reconcile.onTerminal()
  assert.deepEqual(calls, [])
})

test('navigation and exit ports leave dialogs and navigation to the page', async () => {
  const { page, calls } = recordingPage()
  const navigation = buildExamQuestionNavigationPageCapabilities(page)
  assert.deepEqual(navigation.getQuestions(), page.data.questions)
  assert.equal(navigation.isNavigationLocked(), false)
  navigation.settleCurrentTime({ sync: false })
  navigation.setCurrent(2)
  assert.ok(calls.some(call => call[0] === 'settleCurrentTime'))
  assert.ok(calls.some(call => call[0] === 'setCurrent' && call[1] === 2))

  const exit = buildExamExitRequestPageCapabilities(page)
  calls.length = 0
  await exit.showExitDialog()
  const dialog = calls.find(call => call[0] === 'showAppDialog')
  assert.ok(dialog, 'exit dialog must be rendered by the page dialog component')
  assert.equal(dialog[1].title, '暂时退出考试？')
  assert.ok(dialog[1].message.includes('60 分钟'))
  withWx({ navigateBack: options => calls.push(['navigateBack', options]) }, () => {
    exit.navigateBack({ delta: 1 })
  })
  assert.ok(calls.some(call => call[0] === 'navigateBack'))
})

test('submit ports keep retry, confirm and outcome wiring on the page', async () => {
  const { page, calls } = recordingPage()
  const retry = buildExamSubmitRetryPageCapabilities(page)
  assert.deepEqual(retry.getRetryDelays(), [0, 450, 1200])
  assert.equal(retry.getPageClosedMessage(), '页面已关闭')
  assert.equal(retry.getSubmitFailedMessage(), '交卷失败')
  assert.equal(retry.isRetryableSubmitError, isRetryableSubmitError)

  const entry = buildExamSubmitEntryPageCapabilities(page)
  entry.setConfirmingSubmit(true)
  assert.equal(page._confirmingSubmit, true)
  entry.setSubmitPromise('task')
  assert.equal(page._submitPromise, 'task')
  entry.clearSubmitPromise('other')
  assert.equal(page._submitPromise, 'task')
  entry.clearSubmitPromise('task')
  assert.equal(page._submitPromise, null)
  const dialog = entry.buildConfirmDialog()
  assert.equal(dialog.title, '确认交卷')
  assert.ok(dialog.message.includes('还有 2 题未作答'))
  await entry.showConfirmDialog(dialog)
  assert.ok(calls.some(call => call[0] === 'showAppDialog' && call[1] === dialog))

  const preparation = buildExamSubmitPreparationPageCapabilities(page)
  assert.equal(preparation.getCurrentRemainingSec(), 42)
  assert.deepEqual(preparation.buildFinalSubmitAnswers(), { 1: { selected_answer: 'A' } })
  preparation.setRetainPendingForSubmit(true)
  assert.equal(page._retainPendingForSubmit, true)
  preparation.setSubmitting(true)
  assert.ok(calls.some(call => call[0] === 'setData' && call[1].submitting === true))

  const outcome = buildExamSubmitOutcomePageCapabilities(page)
  assert.equal(outcome.isPageAlive(), true)
  calls.length = 0
  outcome.clearPending()
  assert.equal(page._retainPendingForSubmit, false)
  assert.equal(Object.getPrototypeOf(page._pending), null)
  assert.equal(Object.keys(page._pending).length, 0)
  assert.ok(calls.some(call => call[0] === 'clearPendingStorage'))
  outcome.navigateReconciled()
  assert.ok(calls.some(call => call[0] === 'navigateToResult'))
})

test('reconnect ports delegate recovery to the page and its controllers', async () => {
  const { page, calls } = recordingPage()
  const reconnect = buildExamReconnectPageCapabilities(page)
  assert.equal(reconnect.isAttemptLoaded(), true)
  assert.equal(reconnect.isReconnectSyncing(), false)
  reconnect.setReconnectSyncing(true)
  assert.equal(page._reconnectSyncing, true)
  reconnect.tickTimer()
  await reconnect.submitExam({ auto: true })
  await reconnect.flushAllPending({ quiet: true })
  assert.ok(calls.some(call => call[0] === 'tickTimer'))
  assert.ok(calls.some(call => call[0] === 'submitExam' && call[1].auto === true))
  assert.ok(calls.some(call => call[0] === 'flushAllPending' && call[1].quiet === true))
})
