const assert = require('node:assert/strict')
const { test } = require('node:test')

const {
  buildSubjectLoadPageCapabilities,
  buildStartSessionPageCapabilities,
  buildFreeTimerBeginPageCapabilities,
  buildBeginCountdownPageCapabilities,
  buildPauseTogglePageCapabilities,
  buildStartTimerPageCapabilities,
  buildStartBreakPageCapabilities,
  buildSkipBreakPageCapabilities,
} = require('../pages/pomodoro/utils/pomodoro-session-page-adapter')
const {
  buildPauseSessionPageCapabilities,
  buildResumeSessionPageCapabilities,
  buildPauseFreeTimerPageCapabilities,
  buildResumeFreeTimerPageCapabilities,
  buildInterruptSessionPageCapabilities,
  buildEndSessionPageCapabilities,
  buildResetToIdlePageCapabilities,
  buildUpdateFreeElapsedPageCapabilities,
  buildFreeTimerPageCapabilities,
  buildFreeTimerLimitPageCapabilities,
  buildFreeElapsedPageCapabilities,
  buildPomodoroPauseSyncPageCapabilities,
} = require('../pages/pomodoro/utils/pomodoro-session-control-page-adapter')
const {
  buildCancelEndConfirmPageCapabilities,
  buildShowEndFreeConfirmPageCapabilities,
  buildPauseCountdownEndConfirmPageCapabilities,
  buildConfirmInterruptCountdownPageCapabilities,
  buildShowCountdownInterruptConfirmPageCapabilities,
  buildConfirmEndTimerPageCapabilities,
  buildConfirmEndFreeTimerPageCapabilities,
} = require('../pages/pomodoro/utils/pomodoro-confirm-page-adapter')
const {
  buildCompletionCelebrationPageCapabilities,
  buildWorkCompletePageCapabilities,
  buildCelebrationDismissPageCapabilities,
  buildBreakRestorePageCapabilities,
  buildCelebrationTypePageCapabilities,
} = require('../pages/pomodoro/utils/pomodoro-celebration-page-adapter')
const {
  buildSyncRetryPageCapabilities,
  buildUnknownStartPageCapabilities,
  buildResumeErrorPageCapabilities,
  buildPendingSyncQueuePageCapabilities,
  buildPomodoroSessionActionDropperPageCapabilities,
  buildTerminalConflictPageCapabilities,
  buildPendingSyncPageCapabilities,
  buildActiveSyncPageCapabilities,
  buildPomodoroActiveSessionReconcilerPageCapabilities,
  buildPomodoroRunningStateMigratorPageCapabilities,
} = require('../pages/pomodoro/utils/pomodoro-recovery-page-adapter')
const {
  buildCanvasInitPageCapabilities,
  buildDrawRingPageCapabilities,
  buildStatsPageCapabilities,
  buildThemePageCapabilities,
  buildFontSizePageCapabilities,
  buildSubjectViewPageCapabilities,
  buildPresetViewPageCapabilities,
  buildDateExamPageCapabilities,
} = require('../pages/pomodoro/utils/pomodoro-view-page-adapter')
const {
  buildCountdownSessionRestorePageCapabilities,
  buildFreeSessionRestorePageCapabilities,
} = require('../pages/pomodoro/utils/pomodoro-restore-page-adapter')

function recordingPage() {
  const calls = []
  const methods = {
    _applySubjects: (...args) => calls.push(['applySubjects', ...args]),
    _updateComputedFields: () => calls.push(['updateComputed']),
    _autoFinishFreeTimer: () => calls.push(['autoFinishFree']),
    _startFreeTimerInterval: () => calls.push(['startFreeInterval']),
    _initCanvas: (...args) => calls.push(['initCanvas', ...args]),
    drawRing: (...args) => calls.push(['drawRing', ...args]),
    _clearTimer: () => calls.push(['clearTimer']),
    _startTimer: (...args) => calls.push(['startTimer', ...args]),
    _getCurrentTotalSec: () => 42,
    _getCurrentTotalSecOriginal: undefined,
    _getEffectiveFreeElapsedMs: () => 1000,
    _resetToIdle: () => calls.push(['resetIdle']),
    _createTimerState: () => ({ created: true }),
    _safeGetPomodoroStorage: (...args) => calls.push(['getStorage', ...args]),
    _safeSetPomodoroStorage: (...args) => calls.push(['setStorage', ...args]),
    _safeRemovePomodoroStorage: (...args) => calls.push(['removeStorage', ...args]),
    _showPomodoroPersistenceError: () => calls.push(['persistenceError']),
    _setPendingPomodoroSync: (...args) => calls.push(['setPending', ...args]),
    _retryPendingPomodoroSync: () => calls.push(['retryPending']),
    _completePomodoroWithRetry: (...args) => calls.push(['complete', ...args]),
    _consumePomodoroTerminalConflict: (...args) => calls.push(['consumeConflict', ...args]),
    _handlePomodoroTerminalConflict: (...args) => calls.push(['handleConflict', ...args]),
    loadTodayStats: () => calls.push(['loadStats']),
    _getPendingPomodoroSync: () => calls.push(['getPending']) || null,
    _getPendingPomodoroSyncQueue: () => calls.push(['getQueue']) || [],
    _writePendingPomodoroSyncQueue: queue => calls.push(['writeQueue', queue]),
    _dropPendingPomodoroSessionActions: sessionId => calls.push(['dropActions', sessionId]),
    _recordPomodoroTerminalConflict: (...args) => calls.push(['recordConflict', ...args]),
    _readPomodoroTerminalConflict: () => calls.push(['readConflict']) || null,
    _isPomodoroStorageError: value => calls.push(['storageError', value]),
    _clearPendingPomodoroSyncRetryTimer: (...args) => calls.push(['clearRetry', ...args]),
    _schedulePendingPomodoroSyncRetry: (...args) => calls.push(['scheduleRetry', ...args]),
    _reconcileUnknownStartAttempt: attempt => calls.push(['reconcile', attempt]),
    _mergeLocalPauseAdjustment: (...args) => calls.push(['mergeAdjustment', ...args]),
    _updateFreeElapsed: () => calls.push(['updateFreeElapsed']),
    _clearFreeTimerInterval: () => calls.push(['clearFreeInterval']),
    _restartFreeTimerInterval: () => calls.push(['restartFreeInterval']),
    _redrawFreeRingAfterOverlay: () => calls.push(['redrawFreeRing']),
    _postPauseWithRetry: (...args) => calls.push(['postPause', ...args]),
    _formatCountdownDisplay: value => `formatted:${value}`,
    _buildRingCache: isBreak => ({ isBreak }),
    _onWorkComplete: () => calls.push(['workComplete']),
    _nextCelebrationType: () => 'standard',
    _pauseFreeTimer: () => calls.push(['pauseFree']),
    _resumeFreeTimer: () => calls.push(['resumeFree']),
    _pauseSession: () => calls.push(['pauseSession']),
    _resumeSession: () => calls.push(['resumeSession']),
    _showEndFreeConfirm: () => calls.push(['showEndFreeConfirm']),
    _showCountdownInterruptConfirm: () => calls.push(['showCountdownInterrupt']),
    _confirmEndFreeTimer: () => calls.push(['confirmEndFree']),
    _confirmInterruptCountdown: () => calls.push(['confirmInterrupt']),
    _pauseCountdownForEndConfirm: () => calls.push(['pauseCountdownForEndConfirm']),
    _restoreSession: active => calls.push(['restoreSession', active]),
    _maybeClearLocalPauseAdjustment: sessionId => calls.push(['clearAdjustment', sessionId]),
    setData: (...args) => calls.push(['setData', ...args]),
  }
  return {
    page: {
      data: {
        phase: 'running',
        actionLoading: false,
        showEndConfirm: false,
        isFreeTimer: false,
        isPaused: false,
        selectedPreset: 'debug',
        workDuration: 10,
        ringCanvasVisible: false,
        ringCanvasPaintReady: true,
        themeMode: 'light',
        fontSizeLevel: 2,
        subjects: [{ subject_id: 1, subject_name: 'subject', _isAggregate: true }],
      },
      _timerState: {
        sessionId: 99,
        elapsedSec: 7,
        remainingSec: 8,
        progress: 0.5,
        totalPausedMs: 11,
        pauseStartTime: 12,
        sessionStartTime: 100,
        todayDurationSec: 0,
        endConfirmMode: 'countdown',
      },
      _confirmTimerSnapshot: { mode: 'countdown', confirmActionSeq: 3 },
      _confirmActionSeq: 3,
      _countdownTotalSec: 42,
      _countdownEndAt: 50,
      _canvasReady: true,
      _ctx: { name: 'ctx' },
      _canvasInitPending: false,
      _canvasInitSeq: 4,
      _canvasSize: { width: 10 },
      _dpr: 2,
      _pendingDraw: null,
      _ringCache: { cached: true },
      _lastDrawnProgress: 0,
      _lastDrawnIsBreak: false,
      _lastDrawnAt: 10,
      _freeTimerFinalizing: false,
      _completionBreakSec: 5,
      _timerController: { name: 'timer' },
      _pageVisible: true,
      _clearTimer: () => calls.push(['clearTimer']) || null,
      ...methods,
    },
    calls,
  }
}

function fakeApi(calls = []) {
  return {
    get: (...args) => calls.push(['api', 'get', ...args]) || {},
    post: (...args) => calls.push(['api', 'post', ...args]) || {},
    now: () => calls.push(['api', 'now']) || 12345,
    createClientStartId: () => calls.push(['api', 'createClientStartId']) || 'start-1',
  }
}

test('session adapters use injected API and keep delegating ports to the page', () => {
  const { page, calls } = recordingPage()
  const api = fakeApi(calls)
  const capabilities = [
    buildSubjectLoadPageCapabilities(page, { api }),
    buildFreeTimerBeginPageCapabilities(page, { api }),
    buildBeginCountdownPageCapabilities(page, { api }),
    buildStartTimerPageCapabilities(page, { api }),
    buildStartBreakPageCapabilities(page, { api }),
  ]
  for (const ports of capabilities) assert.ok(Object.keys(ports).length >= 7)

  const subjectLoad = capabilities[0]
  subjectLoad.fetchSubjects()
  assert.deepEqual(calls.at(-1), ['api', 'get', '/practice/subjects'])
  assert.equal(subjectLoad.filterSubjectTree, require('../pages/pomodoro/utils/subject-scope').filter408SubjectTree)
  subjectLoad.applySubjects([1])
  assert.deepEqual(calls.at(-1), ['applySubjects', [1]])

  const beginCountdown = capabilities[2]
  beginCountdown.setTimerFields({ remainingSec: 6 })
  assert.equal(page._timerState.remainingSec, 6)
  beginCountdown.onWorkComplete()
  assert.equal(calls.at(-1)[0], 'workComplete')

  const pauseToggle = buildPauseTogglePageCapabilities(page, {})
  assert.equal(pauseToggle.cooldownMs, 500)
  assert.equal(pauseToggle.runningPhase, 'running')
  pauseToggle.pauseCountdown()
  pauseToggle.resumeCountdown()
  assert.deepEqual(calls.slice(-2).map(call => call[0]), ['pauseSession', 'resumeSession'])

  const startSession = buildStartSessionPageCapabilities(page, {})
  assert.equal(startSession.page, page)
  assert.equal(startSession.phases.RUNNING, 'running')
  assert.equal(startSession.pomodoroTaskTypes, require('../utils/storage').pomodoroTaskTypes)

  const skipBreak = buildSkipBreakPageCapabilities(page, {})
  skipBreak.clearTimer()
  skipBreak.removeStorage('k', 'context')
  skipBreak.resetIdle()
  assert.deepEqual(calls.slice(-3).map(call => call[0]), ['clearTimer', 'removeStorage', 'resetIdle'])
})

test('session control adapters preserve terminal and timer behavior ports', () => {
  const { page, calls } = recordingPage()
  const api = fakeApi(calls)
  const ports = [
    buildPauseSessionPageCapabilities(page, { api }),
    buildResumeSessionPageCapabilities(page, { api }),
    buildPauseFreeTimerPageCapabilities(page, { api }),
    buildResumeFreeTimerPageCapabilities(page, { api }),
    buildInterruptSessionPageCapabilities(page, {}),
    buildEndSessionPageCapabilities(page, { api }),
    buildResetToIdlePageCapabilities(page, {}),
    buildUpdateFreeElapsedPageCapabilities(page, {}),
    buildFreeTimerPageCapabilities(page, {}),
    buildFreeTimerLimitPageCapabilities(page, { api }),
    buildFreeElapsedPageCapabilities(page, { api }),
    buildPomodoroPauseSyncPageCapabilities(page, {}),
  ]
  assert.equal(ports.length, 12)

  const endSession = ports[5]
  endSession.completeWithRetry(1, 2)
  endSession.consumeTerminalConflict(1, 'complete')
  assert.deepEqual(calls.slice(-2).map(call => call[0]), ['complete', 'consumeConflict'])

  const reset = ports[6]
  reset.resetTimerState()
  assert.deepEqual(page._timerState, { created: true })
  reset.setConfirmTimerSnapshot(null)
  assert.equal(page._confirmTimerSnapshot, null)

  const freeTimer = ports[8]
  assert.equal(freeTimer.getElapsedMs(), 1000)
  assert.equal(freeTimer.isBlocked(), false)

  const freeLimit = ports[9]
  assert.equal(freeLimit.maxMs, 5 * 60 * 60 * 1000)
  freeLimit.setElapsedSec(12)
  assert.equal(page._timerState.elapsedSec, 12)

  const pauseSync = ports[11]
  pauseSync.setPendingPomodoroSync('complete', 1, 2)
  pauseSync.retryPendingPomodoroSync()
  assert.deepEqual(calls.slice(-2).map(call => call[0]), ['setPending', 'retryPending'])
})

test('confirm adapters route API through deps and preserve page snapshots', () => {
  const { page, calls } = recordingPage()
  const api = fakeApi(calls)
  const ports = [
    buildCancelEndConfirmPageCapabilities(page, { api }),
    buildShowEndFreeConfirmPageCapabilities(page, { api }),
    buildPauseCountdownEndConfirmPageCapabilities(page, { api }),
    buildConfirmInterruptCountdownPageCapabilities(page, { api }),
    buildShowCountdownInterruptConfirmPageCapabilities(page, {}),
    buildConfirmEndTimerPageCapabilities(page, {}),
    buildConfirmEndFreeTimerPageCapabilities(page, {}),
  ]
  for (const capabilities of ports) assert.ok(Object.keys(capabilities).length >= 6)

  const cancel = ports[0]
  cancel.incrementConfirmActionSeq()
  assert.equal(page._confirmActionSeq, 4)
  cancel.setCountdownTotalSec(55)
  assert.equal(page._countdownTotalSec, 55)

  const pause = ports[2]
  pause.setCountdownEndAt(66)
  assert.equal(page._countdownEndAt, 66)

  const interrupt = ports[3]
  assert.equal(interrupt.getConfirmTimerSnapshot(), page._confirmTimerSnapshot)
  interrupt.setTotalPausedMs(17)
  assert.equal(page._timerState.totalPausedMs, 17)

  const endTimer = ports[5]
  assert.equal(endTimer.getSnapshotMode(), 'countdown')
  assert.equal(endTimer.getSessionId(), 99)
})

test('celebration and recovery adapters keep ports stable without static API access', async () => {
  const { page, calls } = recordingPage()
  const api = fakeApi(calls)

  const celebration = buildCompletionCelebrationPageCapabilities(page, {})
  assert.equal(celebration.nextCelebrationType(), 'standard')
  celebration.setCompletionBreakSec(9)
  assert.equal(page._completionBreakSec, 9)
  celebration.invalidateCanvas()
  assert.equal(page._canvasReady, false)
  assert.equal(page._ctx, null)

  const dismiss = buildCelebrationDismissPageCapabilities(page, {})
  assert.equal(dismiss.getCompletionBreakSec(), 9)
  dismiss.setData({ phase: 'idle' })
  assert.deepEqual(calls.at(-1), ['setData', { phase: 'idle' }])

  const syncRetry = buildSyncRetryPageCapabilities(page, {})
  assert.equal(syncRetry.isVisible(), true)
  syncRetry.retry()
  assert.equal(calls.at(-1)[0], 'retryPending')

  const unknown = buildUnknownStartPageCapabilities(page, { api })
  assert.equal(unknown.storageKey, 'pomodoro_unknown_start')
  assert.equal(unknown.page, page)
  unknown.post('/pomodoro/start', { a: 1 })
  assert.deepEqual(calls.at(-1), ['api', 'post', '/pomodoro/start', { a: 1 }])

  const queue = buildPendingSyncQueuePageCapabilities(page, { api })
  queue.storage.write('k', 1, 'ctx')
  queue.storage.read('k', 'ctx')
  queue.storage.remove('k', 'ctx')
  assert.deepEqual(calls.slice(-3).map(call => call[0]), ['setStorage', 'getStorage', 'removeStorage'])

  const terminal = buildTerminalConflictPageCapabilities(page, { api })
  assert.equal(terminal.storageKey, 'pomodoro_terminal_conflict')
  assert.equal(terminal.getCompletionBreakSec(), 9)

  const pending = buildPendingSyncPageCapabilities(page, { api })
  assert.equal(pending.post, pending.post)
  pending.getActive()
  assert.deepEqual(calls.at(-1), ['api', 'get', '/pomodoro/active'])
  assert.equal(
    pending.formatClientActionAt(new Date(0).toISOString()),
    '1970-01-01T00:00:00.000Z',
  )

  const activeSync = buildActiveSyncPageCapabilities(page, { api })
  assert.equal(activeSync.maxMs, 5 * 60 * 60 * 1000)
  assert.equal(activeSync.runningPhase, 'running')

  const migrator = buildPomodoroRunningStateMigratorPageCapabilities(page, {})
  migrator.safeGetPomodoroStorage('k', 'ctx')
  assert.equal(calls.at(-1)[0], 'getStorage')
  await Promise.resolve()
})

test('view and restore adapters preserve pure and page-bound ports', () => {
  const { page, calls } = recordingPage()
  const api = fakeApi(calls)
  const canvas = buildCanvasInitPageCapabilities(page, {})
  canvas.setDpr(3)
  canvas.setCanvasSize({ width: 12 })
  assert.equal(page._dpr, 3)
  assert.deepEqual(page._canvasSize, { width: 12 })
  assert.equal(canvas.maxRetries(), require('../pages/pomodoro/utils/canvas-layout').CANVAS_INIT_MAX_RETRIES)

  const draw = buildDrawRingPageCapabilities(page, { api })
  draw.now()
  assert.deepEqual(calls.at(-1), ['api', 'now'])
  assert.equal(draw.getRingCache(), page._ringCache)

  const stats = buildStatsPageCapabilities(page, { api })
  stats.setTodayDurationSec(30)
  assert.equal(page._timerState.todayDurationSec, 30)

  const subjectView = buildSubjectViewPageCapabilities(page, {})
  assert.equal(subjectView.getSubjects(), page.data.subjects)
  const presetView = buildPresetViewPageCapabilities(page, {})
  assert.equal(presetView.getPresets()[0].key, 'standard')

  const dateExam = buildDateExamPageCapabilities(page, { api })
  assert.equal(dateExam.utc({ year: 2026, month: 1, day: 1 }), Date.UTC(2026, 1, 1))

  const restore = buildCountdownSessionRestorePageCapabilities(page, { api })
  assert.equal(restore.page, page)
  assert.equal(restore.runningPhase, 'running')
  const freeRestore = buildFreeSessionRestorePageCapabilities(page, { api })
  assert.equal(freeRestore.page, page)
  assert.equal(freeRestore.maxMs, 5 * 60 * 60 * 1000)
})

test('all page adapters construct from a page and capability deps object', () => {
  const { page } = recordingPage()
  const cases = [
    [buildSubjectLoadPageCapabilities, true],
    [buildStartSessionPageCapabilities, false],
    [buildFreeTimerBeginPageCapabilities, true],
    [buildBeginCountdownPageCapabilities, true],
    [buildPauseTogglePageCapabilities, false],
    [buildStartTimerPageCapabilities, true],
    [buildStartBreakPageCapabilities, true],
    [buildSkipBreakPageCapabilities, false],
    [buildPauseSessionPageCapabilities, true],
    [buildResumeSessionPageCapabilities, true],
    [buildPauseFreeTimerPageCapabilities, true],
    [buildResumeFreeTimerPageCapabilities, true],
    [buildInterruptSessionPageCapabilities, false],
    [buildEndSessionPageCapabilities, true],
    [buildResetToIdlePageCapabilities, false],
    [buildUpdateFreeElapsedPageCapabilities, false],
    [buildFreeTimerPageCapabilities, false],
    [buildFreeTimerLimitPageCapabilities, true],
    [buildFreeElapsedPageCapabilities, true],
    [buildPomodoroPauseSyncPageCapabilities, false],
    [buildCancelEndConfirmPageCapabilities, true],
    [buildShowEndFreeConfirmPageCapabilities, true],
    [buildPauseCountdownEndConfirmPageCapabilities, true],
    [buildConfirmInterruptCountdownPageCapabilities, true],
    [buildShowCountdownInterruptConfirmPageCapabilities, false],
    [buildConfirmEndTimerPageCapabilities, false],
    [buildConfirmEndFreeTimerPageCapabilities, false],
    [buildCompletionCelebrationPageCapabilities, false],
    [buildWorkCompletePageCapabilities, true],
    [buildCelebrationDismissPageCapabilities, false],
    [buildBreakRestorePageCapabilities, true],
    [buildCelebrationTypePageCapabilities, false],
    [buildSyncRetryPageCapabilities, false],
    [buildUnknownStartPageCapabilities, true],
    [buildResumeErrorPageCapabilities, true],
    [buildPendingSyncQueuePageCapabilities, true],
    [buildPomodoroSessionActionDropperPageCapabilities, false],
    [buildTerminalConflictPageCapabilities, true],
    [buildPendingSyncPageCapabilities, true],
    [buildActiveSyncPageCapabilities, true],
    [buildPomodoroActiveSessionReconcilerPageCapabilities, true],
    [buildPomodoroRunningStateMigratorPageCapabilities, false],
    [buildCanvasInitPageCapabilities, false],
    [buildDrawRingPageCapabilities, true],
    [buildStatsPageCapabilities, true],
    [buildThemePageCapabilities, false],
    [buildFontSizePageCapabilities, false],
    [buildSubjectViewPageCapabilities, false],
    [buildPresetViewPageCapabilities, false],
    [buildDateExamPageCapabilities, true],
    [buildCountdownSessionRestorePageCapabilities, true],
    [buildFreeSessionRestorePageCapabilities, true],
  ]
  const api = fakeApi()
  for (const [builder, usesApi] of cases) {
    const ports = builder(page, usesApi ? { api } : {})
    assert.equal(typeof ports, 'object')
    assert.notEqual(ports, null)
    assert.ok(Object.keys(ports).length > 0)
  }
})
