/**
 * Runtime-oriented regression checks for Pomodoro long-term stability guards.
 * Executes the real Page methods inside a small WeChat API sandbox instead of
 * only searching source strings.
 * Usage: node scripts/test-pomodoro-stability-runtime.js
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const source = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/pomodoro.js'), 'utf8')
const storage = new Map()
const toasts = []
let failSetStorageKey = ''
let failRemoveStorageKey = ''
let failReadStorageKey = ''
let nowMs = Date.parse('2026-08-23T08:00:00Z')
let scheduledDelay = null
let scheduledTimer = null
const clearedTimers = []
let capturedPage = null

const api = {
  now: () => nowMs,
  get: async () => null,
  post: async () => ({ status: 'running' }),
  createClientStartId: () => 'runtime-test-start-id',
}

const wx = {
  getStorageSync(key) {
    if (key === failReadStorageKey) throw new Error('simulated storage read failure')
    return storage.get(key)
  },
  setStorageSync(key, value) {
    if (key === failSetStorageKey) throw new Error('simulated storage quota failure')
    storage.set(key, value)
  },
  removeStorageSync(key) {
    if (key === failRemoveStorageKey) throw new Error('simulated storage remove failure')
    storage.delete(key)
  },
  showToast(opts) { toasts.push(opts) },
  nextTick(fn) { if (fn) fn() },
  vibrateLong() {},
  onNetworkStatusChange() {},
  offNetworkStatusChange() {},
  setNavigationBarColor() {},
  setBackgroundColor() {},
  setBackgroundTextStyle() {},
}

const sandbox = {
  console,
  wx,
  Page(definition) { capturedPage = definition },
  require(request) {
    if (request === './utils/timer-math') return require('../pages/pomodoro/utils/timer-math')
    if (request === './utils/session-storage') return require('../pages/pomodoro/utils/session-storage')
    if (request === './utils/pending-sync-queue') return require('../pages/pomodoro/utils/pending-sync-queue')
    if (request === './utils/sync-retry-controller') return require('../pages/pomodoro/utils/sync-retry-controller')
    if (request === './utils/active-session-recovery') return require('../pages/pomodoro/utils/active-session-recovery')
    if (request === './utils/completion-recovery') return require('../pages/pomodoro/utils/completion-recovery')
    if (request === './utils/confirm-recovery') return require('../pages/pomodoro/utils/confirm-recovery')
    if (request === './utils/show-recovery') return require('../pages/pomodoro/utils/show-recovery')
    if (request === './utils/hide-storage') return require('../pages/pomodoro/utils/hide-storage')
    if (request === './utils/subject-options') return require('../pages/pomodoro/utils/subject-options')
    if (request === './utils/subject-selection') return require('../pages/pomodoro/utils/subject-selection')
    if (request === './utils/subject-meta') return require('../pages/pomodoro/utils/subject-meta')
    if (request === './utils/countdown-controller') return require('../pages/pomodoro/utils/countdown-controller')
    if (request === './utils/free-timer-controller') return require('../pages/pomodoro/utils/free-timer-controller')
    if (request === './utils/ring-geometry') return require('../pages/pomodoro/utils/ring-geometry')
    if (request === './utils/terminal-conflict-state') return require('../pages/pomodoro/utils/terminal-conflict-state')
    if (request === './utils/canvas-layout') return require('../pages/pomodoro/utils/canvas-layout')
    if (request === './utils/sync-reconciliation') return require('../pages/pomodoro/utils/sync-reconciliation')
    if (request === './utils/session-restore') return require('../pages/pomodoro/utils/session-restore')
    if (request === './utils/countdown-session-restore-controller') {
      return require('../pages/pomodoro/utils/countdown-session-restore-controller')
    }
    if (request === './utils/free-session-restore-controller') {
      return require('../pages/pomodoro/utils/free-session-restore-controller')
    }
    if (request === './utils/start-session-controller') {
      return require('../pages/pomodoro/utils/start-session-controller')
    }
    if (request === './utils/unknown-start-controller') {
      return require('../pages/pomodoro/utils/unknown-start-controller')
    }
    if (request === './utils/pending-sync-controller') {
      return require('../pages/pomodoro/utils/pending-sync-controller')
    }
    if (request === './utils/terminal-conflict-controller') {
      return require('../pages/pomodoro/utils/terminal-conflict-controller')
    }
    if (request === './utils/stats-controller') {
      return require('../pages/pomodoro/utils/stats-controller')
    }
    if (request === './utils/theme-controller') {
      return require('../pages/pomodoro/utils/theme-controller')
    }
    if (request === './utils/end-confirm-snapshot') {
      return require('../pages/pomodoro/utils/end-confirm-snapshot')
    }
    if (request === './utils/active-sync-controller') {
      return require('../pages/pomodoro/utils/active-sync-controller')
    }
    if (request === './utils/pause-toggle-controller') {
      return require('../pages/pomodoro/utils/pause-toggle-controller')
    }
    if (request === './utils/resume-error-controller') {
      return require('../pages/pomodoro/utils/resume-error-controller')
    }
    if (request === './utils/celebration-dismiss-controller') {
      return require('../pages/pomodoro/utils/celebration-dismiss-controller')
    }
    if (request === './utils/break-restore-controller') {
      return require('../pages/pomodoro/utils/break-restore-controller')
    }
    if (request === './utils/completion-celebration-controller') {
      return require('../pages/pomodoro/utils/completion-celebration-controller')
    }
    if (request === './utils/work-complete-controller') {
      return require('../pages/pomodoro/utils/work-complete-controller')
    }
    if (request === './utils/free-timer-begin-controller') {
      return require('../pages/pomodoro/utils/free-timer-begin-controller')
    }
    if (request === './utils/cancel-confirm-state') return require('../pages/pomodoro/utils/cancel-confirm-state')
    if (request === './utils/completion-celebration') return require('../pages/pomodoro/utils/completion-celebration')
    if (request === './utils/terminal-conflict-handler') {
      return require('../pages/pomodoro/utils/terminal-conflict-handler')
    }
    if (request === './utils/pause-adjustment') return require('../pages/pomodoro/utils/pause-adjustment')
    if (request === './utils/celebration-dismiss') return require('../pages/pomodoro/utils/celebration-dismiss')
    if (request === './utils/end-confirm-view-model') return require('../pages/pomodoro/utils/end-confirm-view-model')
    if (request === './utils/unknown-start-helpers') {
      return require('../pages/pomodoro/utils/unknown-start-helpers')
    }
    if (request === './utils/cached-session-builder') {
      return require('../pages/pomodoro/utils/cached-session-builder')
    }
    if (request === '../../utils/api') return api
    if (request === '../../config') return {}
    if (request === '../../utils/route-params') return { safeDecodeURIComponent: v => v }
    if (request === './utils/route-params') return { safeDecodeURIComponent: v => v }
    if (request === './utils/subject-scope') return { filter408SubjectTree: value => value }
    if (request === './utils/subject-cache') {
      return {
        readSubjectCache: () => null,
        writeSubjectCache: () => true,
      }
    }
    if (request === '../../utils/pomodoro-theme' || request === './utils/pomodoro-theme') {
      return {
        getTheme: () => 'light',
        normalizeTheme: v => v || 'light',
        applyNativeTheme() {},
        setTheme() {},
      }
    }
    if (request === '../../utils/china-time') {
      return {
        parseServerUtc: value => Date.parse(value),
        getChinaWallParts: () => ({}),
        getChinaDayStartUtcMs: () => 0,
      }
    }
    if (request === '../../utils/storage') {
      return {
        pomodoroTaskTypes: {
          TYPE_MAP: { new_questions: true, review: true },
          DEFAULT_TYPE: 'new_questions',
          label(type) { return type === 'new_questions' ? '新题' : type },
          getSelected() { return 'new_questions' },
          setSelected(type) { return type },
          recordSession() {},
          typeForSession() { return '' },
          labelForSession() { return '' },
        },
      }
    }
    throw new Error('unexpected require: ' + request)
  },
  setTimeout(fn, delay) {
    scheduledDelay = delay
    scheduledTimer = { fn, delay }
    return scheduledTimer
  },
  clearTimeout(timer) { clearedTimers.push(timer) },
}
vm.runInNewContext(source, sandbox, { filename: 'pomodoro.js' })
assert.ok(capturedPage, 'Page definition was not captured')

function createPage() {
  const page = Object.assign({}, capturedPage)
  page.data = JSON.parse(JSON.stringify(capturedPage.data))
  page._timerState = page._createTimerState()
  page.setData = function setData(patch, callback) {
    Object.assign(this.data, patch)
    if (callback) callback()
  }
  page._clearTimer = () => { page._clearTimerCalls = (page._clearTimerCalls || 0) + 1 }
  page._initCanvas = () => {}
  page.drawRing = () => {}
  page._updateComputedFields = () => {}
  page._startTimer = () => {}
  return page
}

let passed = 0
let failed = 0
async function test(name, fn) {
  try {
    await fn()
    passed++
    console.log('  ✓ ' + name)
  } catch (error) {
    failed++
    console.error('  ✗ ' + name + ' - ' + error.message)
  }
}

;(async () => {
  console.log('\n--- Pomodoro runtime stability ---')

  await test('onHide preserves cancellation and confirmation before running state and timer cleanup', () => {
    storage.clear()
    const page = createPage()
    const unknown = { clientStartId: 'synthetic-hide', payload: { subject_id: 4 } }
    const confirm = { sessionId: 120, mode: 'free-complete' }
    storage.set('pomodoro_unknown_start', unknown)
    page._confirmTimerSnapshot = confirm
    page.data.phase = 'running'
    page.data.showEndConfirm = true
    page.data.isPaused = true
    page.data.allocationMode = 'equal_408_core_v1'
    page.data.selectedTaskType = 'review'
    page._timerState.sessionId = 120
    page._timerState.pauseStartTime = null
    const calls = []
    const write = page._safeSetPomodoroStorage
    page._safeSetPomodoroStorage = function(key, value, context) {
      calls.push(key)
      return write.call(this, key, value, context)
    }
    page._clearTimer = () => calls.push('clear-timer')
    page.onHide()
    assert.deepStrictEqual(calls, [
      'pomodoro_unknown_start', 'pomodoro_confirm_pause', 'pomodoro_running_state', 'clear-timer',
    ])
    assert.strictEqual(storage.get('pomodoro_unknown_start').clientStartId, unknown.clientStartId)
    assert.strictEqual(storage.get('pomodoro_unknown_start').cancelIfFound, true)
    assert.strictEqual(storage.get('pomodoro_unknown_start').cancelAt, nowMs)
    assert.strictEqual(storage.get('pomodoro_confirm_pause'), confirm)
    const running = storage.get('pomodoro_running_state')
    assert.strictEqual(running.sessionId, 120)
    assert.strictEqual(running.allocationMode, 'equal_408_core_v1')
    assert.strictEqual(running.selectedTaskType, 'review')
    assert.strictEqual(running.pauseStartTime, nowMs)
    assert.strictEqual(running.savedAt, nowMs)
    assert.strictEqual(page._pageVisible, false)
  })

  await test('onHide completion read failure never overwrites running snapshot and still clears timer', () => {
    storage.clear()
    const page = createPage()
    const previous = { sessionId: 121 }
    storage.set('pomodoro_running_state', previous)
    page.data.phase = 'running'
    page._timerState.sessionId = 122
    failReadStorageKey = 'pomodoro_completion'
    try {
      page.onHide()
      assert.strictEqual(storage.get('pomodoro_running_state'), previous)
      assert.strictEqual(page._clearTimerCalls, 1)
    } finally {
      failReadStorageKey = ''
    }
  })

  await test('onHide confirmation write failure still saves running state and clears timer', () => {
    storage.clear()
    const page = createPage()
    page.data.phase = 'running'
    page.data.showEndConfirm = true
    page._confirmTimerSnapshot = { sessionId: 123 }
    page._timerState.sessionId = 123
    failSetStorageKey = 'pomodoro_confirm_pause'
    try {
      page.onHide()
      assert.strictEqual(storage.has('pomodoro_confirm_pause'), false)
      assert.strictEqual(storage.get('pomodoro_running_state').sessionId, 123)
      assert.strictEqual(page._clearTimerCalls, 1)
    } finally {
      failSetStorageKey = ''
    }
  })

  await test('onHide cancels ceremony before deciding whether to persist running state', () => {
    storage.clear()
    const page = createPage()
    page.data.phase = 'ceremony'
    page._timerState.sessionId = 124
    page.onHide()
    assert.strictEqual(page.data.phase, 'idle')
    assert.strictEqual(storage.has('pomodoro_running_state'), false)
    assert.strictEqual(page._clearTimerCalls, 1)
  })

  await test('unknown start short-circuits completion and active recovery', async () => {
    for (const resolution of ['storage_error', 'cancelled', 'restored']) {
      storage.clear()
      const page = createPage()
      storage.set('pomodoro_completion', { sessionId: 110 })
      page._syncThemeFromStorage = () => {}
      page._reconcileUnknownStartAttempt = async () => resolution
      let errors = 0
      let completion = 0
      let active = 0
      page._showPomodoroPersistenceError = () => { errors++ }
      page._restoreCompletionView = () => { completion++ }
      page._recoverActiveSession = async () => { active++ }
      await page.onShow()
      assert.strictEqual(errors, resolution === 'storage_error' ? 1 : 0)
      assert.strictEqual(completion, 0)
      assert.strictEqual(active, 0)
    }
  })

  await test('hidden page cannot restore completion after uncertain-start response', async () => {
    storage.clear()
    const page = createPage()
    storage.set('pomodoro_completion', { sessionId: 111 })
    page._syncThemeFromStorage = () => {}
    let resolveStart
    page._reconcileUnknownStartAttempt = () => new Promise(resolve => { resolveStart = resolve })
    let completions = 0
    page._restoreCompletionView = () => { completions++ }
    const showing = page.onShow()
    page.onHide()
    resolveStart('none')
    await showing
    assert.strictEqual(completions, 0)
  })

  await test('returning from stats clears confirmation and passes current generation to active recovery', async () => {
    storage.clear()
    const page = createPage()
    page._navigatingToStats = true
    page._confirmTimerSnapshot = { sessionId: 112 }
    page._timerState.endConfirmMode = 'free-complete'
    page.data.showEndConfirm = true
    storage.set('pomodoro_confirm_pause', { sessionId: 112 })
    page._syncThemeFromStorage = () => {}
    page._reconcileUnknownStartAttempt = async () => 'none'
    let recovered = 0
    page._recoverActiveSession = async (pending, sequence) => {
      recovered++
      assert.strictEqual(pending, null)
      assert.strictEqual(sequence, page._activeSyncSeq)
      assert.strictEqual(page._navigatingToStats, false)
      assert.strictEqual(page._confirmTimerSnapshot, null)
      assert.strictEqual(page._timerState.endConfirmMode, '')
      assert.strictEqual(page.data.showEndConfirm, false)
      assert.strictEqual(storage.has('pomodoro_confirm_pause'), false)
    }
    await page.onShow()
    assert.strictEqual(recovered, 1)
  })

  await test('onShow restores both valid confirmation modes and acknowledges the pause', async () => {
    for (const mode of ['free-complete', 'countdown-interrupt']) {
      storage.clear()
      const page = createPage()
      const snapshot = {
        sessionId: 101, mode, openedAt: nowMs - 1000, sessionStartTime: nowMs - 60000,
        elapsedSec: 65, remainingSec: 75, progress: 0.5, totalSec: 150,
        totalPausedMs: 300, phase: 'break', pausedByConfirm: true,
      }
      storage.set('pomodoro_confirm_pause', snapshot)
      page._syncThemeFromStorage = () => {}
      page._reconcileUnknownStartAttempt = async () => 'none'
      const calls = []
      page._initCanvas = force => calls.push(['canvas', force])
      page.drawRing = (total, isBreak) => calls.push(['ring', total, isBreak])
      page._postPauseWithRetry = async (id, at) => { calls.push(['pause', id, at]) }
      page._fetchActiveSession = async () => { throw new Error('confirmation must skip active fetch') }
      await page.onShow()
      await new Promise(resolve => setImmediate(resolve))
      assert.strictEqual(page._confirmTimerSnapshot, snapshot)
      assert.strictEqual(page._timerState.endConfirmMode, mode)
      assert.strictEqual(page.data.showEndConfirm, true)
      assert.strictEqual(page.data.isPaused, true)
      assert.strictEqual(snapshot.backendPauseDone, true)
      assert.strictEqual(storage.get('pomodoro_confirm_pause'), snapshot)
      assert.strictEqual(scheduledDelay, 200)
      if (mode === 'free-complete') {
        assert.strictEqual(page.data.freeDisplayTime, '00:01:05')
        assert.deepStrictEqual(calls, [['pause', 101, snapshot.openedAt]])
      } else {
        assert.strictEqual(page.data.displayMin, '01')
        assert.strictEqual(page.data.displaySec, '15')
        assert.deepStrictEqual(calls, [
          ['canvas', true], ['ring', 150, true], ['pause', 101, snapshot.openedAt],
        ])
      }
    }
  })

  await test('page confirmation acknowledgement ignores a later action sequence', async () => {
    storage.clear()
    const page = createPage()
    let resolvePause
    page._postPauseWithRetry = () => new Promise(resolve => { resolvePause = resolve })
    const snapshot = { sessionId: 102, mode: 'free-complete', pausedByConfirm: true }
    page._restoreConfirmSnapshot(snapshot)
    page._confirmActionSeq++
    resolvePause()
    await new Promise(resolve => setImmediate(resolve))
    assert.strictEqual(snapshot.backendPauseDone, undefined)
    assert.strictEqual(storage.has('pomodoro_confirm_pause'), false)
  })

  await test('unreadable confirmation storage stops onShow without active fetch', async () => {
    storage.clear()
    const page = createPage()
    page._syncThemeFromStorage = () => {}
    page._reconcileUnknownStartAttempt = async () => 'none'
    let fetched = false
    page._fetchActiveSession = async () => { fetched = true }
    failReadStorageKey = 'pomodoro_confirm_pause'
    try {
      await page.onShow()
      assert.strictEqual(fetched, false)
    } finally {
      failReadStorageKey = ''
    }
  })

  await test('invalid confirmation is removed before normal active recovery', async () => {
    storage.clear()
    const page = createPage()
    storage.set('pomodoro_confirm_pause', {
      sessionId: 103, mode: 'free-complete', openedAt: nowMs - 3600001,
    })
    page._syncThemeFromStorage = () => {}
    page._reconcileUnknownStartAttempt = async () => 'none'
    let recovered = false
    page._recoverActiveSession = async () => {
      recovered = true
      assert.strictEqual(storage.has('pomodoro_confirm_pause'), false)
      assert.strictEqual(page._confirmTimerSnapshot, null)
      assert.strictEqual(page._timerState.endConfirmMode, '')
    }
    await page.onShow()
    assert.strictEqual(recovered, true)
  })

  await test('completion recovery keeps marker authoritative across repeated shows', async () => {
    storage.clear()
    const page = createPage()
    const completion = {
      sessionId: 91, selectedSubjectId: 4, selectedSubjectCode: 'exam408',
      selectedSubjectName: '408', allocationMode: 'equal_408_core_v1',
      selectedTaskType: 'review', workDuration: 50, breakDuration: 10, breakSec: 600,
    }
    storage.set('pomodoro_completion', completion)
    page._syncThemeFromStorage = () => {}
    page._reconcileUnknownStartAttempt = async () => 'none'
    let fetches = 0
    let vibrations = 0
    const oldVibrate = wx.vibrateLong
    wx.vibrateLong = () => { vibrations++ }
    page._fetchActiveSession = async () => { fetches++; return { id: 91 } }
    try {
      await page.onShow()
      await page.onShow()
      assert.strictEqual(page.data.phase, 'idle')
      assert.strictEqual(page.data.showCelebration, true)
      assert.strictEqual(page.data.selectedSubject._isAggregate, true)
      assert.strictEqual(page.data.selectedTaskType, 'review')
      assert.strictEqual(page._completionBreakSec, 600)
      assert.strictEqual(storage.get('pomodoro_completion'), completion)
      assert.strictEqual(fetches, 0)
      assert.strictEqual(vibrations, 1)
      assert.strictEqual(scheduledDelay, 200)
    } finally {
      wx.vibrateLong = oldVibrate
    }
  })

  await test('completion celebration still drains pending actions and handles terminal conflict', async () => {
    storage.clear()
    const page = createPage()
    storage.set('pomodoro_completion', { sessionId: 92 })
    storage.set('pomodoro_pending_sync', [{
      sessionId: 92, action: 'complete', nonce: 'completion-recovery', savedAt: nowMs,
    }])
    page._syncThemeFromStorage = () => {}
    page._reconcileUnknownStartAttempt = async () => 'none'
    const conflict = { sessionId: 92, action: 'complete', actualStatus: 'interrupted' }
    let consumed = 0
    let retries = 0
    let handled = null
    let stats = 0
    page._consumeAnyPomodoroTerminalConflict = () => consumed++ ? conflict : null
    page._retryPendingPomodoroSync = async () => { retries++; return true }
    page._handlePomodoroTerminalConflict = (id, value) => { handled = [id, value] }
    page.loadTodayStats = () => { stats++ }
    await page.onShow()
    await new Promise(resolve => setImmediate(resolve))
    assert.strictEqual(page.data.showCelebration, true)
    assert.strictEqual(retries, 1)
    assert.deepStrictEqual(handled, [92, conflict])
    assert.strictEqual(stats, 0)
  })

  await test('onShow restores the first cached frame before awaiting server response', async () => {
    storage.clear()
    const page = createPage()
    const calls = []
    let resolveFetch
    page._syncThemeFromStorage = () => {}
    page._reconcileUnknownStartAttempt = async () => 'none'
    page._getCachedActiveSession = () => ({ id: 80 })
    page._canLightSyncActive = () => false
    page._restoreSession = session => {
      calls.push(session.id)
      page.data.phase = 'running'
      page._timerState.sessionId = session.id
    }
    page._fetchActiveSession = () => {
      calls.push('fetch')
      return new Promise(resolve => { resolveFetch = resolve })
    }
    const showing = page.onShow()
    await new Promise(resolve => setImmediate(resolve))
    assert.strictEqual(page.data.pageEntered, true)
    assert.deepStrictEqual(calls, [80, 'fetch'])
    page.onHide()
    resolveFetch({ id: 99 })
    await showing
    assert.deepStrictEqual(calls, [80, 'fetch'])
  })

  await test('page restores cached timer before fetch and rejects a hidden-page response', async () => {
    const page = createPage()
    page._pageVisible = true
    page._activeSyncSeq = 10
    const calls = []
    let resolveFetch
    page._getCachedActiveSession = () => ({ id: 81 })
    page._canLightSyncActive = () => false
    page._restoreSession = session => {
      calls.push(session.id)
      page.data.phase = 'running'
      page._timerState.sessionId = session.id
    }
    page._fetchActiveSession = () => {
      calls.push('fetch')
      return new Promise(resolve => { resolveFetch = resolve })
    }
    const recovery = page._recoverActiveSession(null, 10)
    assert.deepStrictEqual(calls, [81, 'fetch'])
    page._pageVisible = false
    resolveFetch({ id: 82 })
    await recovery
    assert.deepStrictEqual(calls, [81, 'fetch'])
  })

  await test('page recovery rejects an older show generation after pending drain', async () => {
    const page = createPage()
    page._pageVisible = true
    page._activeSyncSeq = 20
    page._getCachedActiveSession = () => null
    page._restoreBreak = () => true
    let resolveDrain
    let fetches = 0
    page._retryPendingPomodoroSync = () => new Promise(resolve => { resolveDrain = resolve })
    page._fetchActiveSession = async () => { fetches++; return null }
    const recovery = page._recoverActiveSession({}, 20)
    page._activeSyncSeq = 21
    resolveDrain(true)
    await recovery
    assert.strictEqual(fetches, 0)
  })

  await test('page server-null clears an optimistically restored running session', async () => {
    const page = createPage()
    page._pageVisible = true
    page._activeSyncSeq = 30
    const calls = []
    page._getCachedActiveSession = () => ({ id: 83 })
    page._canLightSyncActive = () => false
    page._restoreSession = session => {
      page.data.phase = 'running'
      page._timerState.sessionId = session.id
    }
    page._fetchActiveSession = async () => null
    page._resetToIdle = () => { calls.push('idle'); page.data.phase = 'idle' }
    page._restoreBreak = () => { calls.push('break'); return false }
    await page._recoverActiveSession(null, 30)
    assert.deepStrictEqual(calls, ['idle', 'break'])
    assert.strictEqual(scheduledDelay, 200)
  })

  await test('retry controllers are lazy, per-page, and teardown does not create one', () => {
    const first = createPage()
    const second = createPage()
    first._unregisterNetworkStatusListener()
    first._clearPendingPomodoroSyncRetryTimer(true)
    assert.strictEqual(first._syncRetryController, null)
    assert.notStrictEqual(first._getSyncRetryController(), second._getSyncRetryController())
    assert.strictEqual(first._getSyncRetryController(), first._getSyncRetryController())
  })

  await test('real page reconnect checks pending work, consumes conflicts and refreshes stats', async () => {
    storage.clear()
    const page = createPage()
    const oldOn = wx.onNetworkStatusChange
    const oldOff = wx.offNetworkStatusChange
    let callback
    let removed
    let registrations = 0
    let retries = 0
    let stats = 0
    let handled = null
    let conflict = { sessionId: 71 }
    wx.onNetworkStatusChange = fn => { callback = fn; registrations++ }
    wx.offNetworkStatusChange = fn => { removed = fn }
    page._retryPendingPomodoroSync = async () => { retries++; return true }
    page._consumeAnyPomodoroTerminalConflict = () => conflict
    page._handlePomodoroTerminalConflict = (id, value) => { handled = [id, value] }
    page.loadTodayStats = () => { stats++ }
    try {
      page._registerNetworkStatusListener()
      page._registerNetworkStatusListener()
      assert.strictEqual(registrations, 1)
      callback({ isConnected: true })
      page._pageVisible = true
      callback({ isConnected: true })
      assert.strictEqual(retries, 0)
      storage.set('pomodoro_pending_sync', [{
        action: 'pause', sessionId: 71, savedAt: nowMs, nonce: 'reconnect-test',
      }])
      page._schedulePendingPomodoroSyncRetry({ statusCode: 503 })
      const timer = scheduledTimer
      callback({ isConnected: true })
      await new Promise(resolve => setImmediate(resolve))
      assert.ok(clearedTimers.includes(timer))
      assert.deepStrictEqual(handled, [71, conflict])
      assert.strictEqual(stats, 0)
      conflict = null
      callback({ isConnected: true })
      await new Promise(resolve => setImmediate(resolve))
      assert.strictEqual(stats, 1)
      page.onUnload()
      assert.strictEqual(removed, callback)
      callback({ isConnected: true })
      assert.strictEqual(retries, 2)
    } finally {
      wx.onNetworkStatusChange = oldOn
      wx.offNetworkStatusChange = oldOff
    }
  })

  await test('onHide cancels delayed retry and preserves backoff; unload resets it', () => {
    storage.clear()
    const page = createPage()
    page._pageVisible = true
    storage.set('pomodoro_pending_sync', [{
      action: 'pause', sessionId: 72, savedAt: nowMs, nonce: 'hide-test',
    }])
    page._schedulePendingPomodoroSyncRetry({})
    const timer = scheduledTimer
    page.onHide()
    assert.ok(clearedTimers.includes(timer))
    page._pageVisible = true
    page._schedulePendingPomodoroSyncRetry({})
    assert.strictEqual(scheduledDelay, 5000)
    page.onUnload()
    page._pageVisible = true
    page._schedulePendingPomodoroSyncRetry({})
    assert.strictEqual(scheduledDelay, 2000)
    page._clearPendingPomodoroSyncRetryTimer(true)
  })

  await test('page network adapter requires both listener APIs and tolerates disappearing off', () => {
    const page = createPage()
    const oldOn = wx.onNetworkStatusChange
    const oldOff = wx.offNetworkStatusChange
    let registrations = 0
    wx.onNetworkStatusChange = () => { registrations++ }
    wx.offNetworkStatusChange = undefined
    try {
      page._registerNetworkStatusListener()
      assert.strictEqual(registrations, 0)
      wx.offNetworkStatusChange = oldOff
      page._registerNetworkStatusListener()
      assert.strictEqual(registrations, 1)
      wx.offNetworkStatusChange = undefined
      page._unregisterNetworkStatusListener()
    } finally {
      wx.onNetworkStatusChange = oldOn
      wx.offNetworkStatusChange = oldOff
    }
  })

  await test('repeated reconnect callbacks share the actual queue drain in flight', async () => {
    storage.clear()
    const page = createPage()
    page._pageVisible = true
    storage.set('pomodoro_pending_sync', [{
      action: 'pause', sessionId: 73, savedAt: nowMs,
      clientActionAt: nowMs, nonce: 'single-flight-test',
    }])
    const oldOn = wx.onNetworkStatusChange
    const oldPost = api.post
    let callback
    let resolvePost
    let posts = 0
    wx.onNetworkStatusChange = fn => { callback = fn }
    api.post = () => {
      posts++
      return new Promise(resolve => { resolvePost = resolve })
    }
    page.loadTodayStats = () => {}
    try {
      page._registerNetworkStatusListener()
      callback({ isConnected: true })
      callback({ isConnected: true })
      assert.strictEqual(posts, 1)
      resolvePost({ status: 'paused' })
      await new Promise(resolve => setImmediate(resolve))
      await new Promise(resolve => setImmediate(resolve))
      assert.strictEqual(page._getPendingPomodoroSyncQueue().length, 0)
      assert.strictEqual(posts, 1)
    } finally {
      page._unregisterNetworkStatusListener()
      wx.onNetworkStatusChange = oldOn
      api.post = oldPost
    }
  })

  await test('pending queue adapters belong to their Page instance and observe live storage', () => {
    storage.clear()
    const first = createPage()
    const second = createPage()
    assert.notStrictEqual(first._getPendingSyncStore(), second._getPendingSyncStore())
    assert.strictEqual(first._getPendingSyncStore(), first._getPendingSyncStore())
    const pending = first._setPendingPomodoroSync('pause', 91, nowMs - 10)
    assert.strictEqual(second._getPendingPomodoroSync().nonce, pending.nonce)
    assert.strictEqual(second._clearPendingPomodoroSync(pending), true)
    assert.strictEqual(first._getPendingPomodoroSync(), null)
    first._safeGetPomodoroStorage = () => ({ ok: false, value: null })
    assert.strictEqual(first._getPendingPomodoroSync().storageUnreadable, true)
    assert.strictEqual(second._getPendingPomodoroSync(), null)
  })

  await test('pending queue wrappers retain timestamps, updates and acknowledgements', () => {
    storage.clear()
    const page = createPage()
    const pending = page._setPendingPomodoroSync('pause', 92, nowMs - 50)
    assert.strictEqual(pending.clientActionAt, nowMs - 50)
    assert.strictEqual(page._hasPendingPomodoroAction(92, 'pause'), true)
    assert.strictEqual(page._updatePendingPomodoroSync(pending, { attempts: 2 }).attempts, 2)
    assert.strictEqual(page._getPendingPomodoroSyncQueue().length, 1)
    assert.strictEqual(page._clearPendingPomodoroSync(pending), true)
    assert.strictEqual(page._hasPendingPomodoroAction(92, 'pause'), false)
  })

  await test('timer wrappers keep the API clock and local pause adjustment', () => {
    storage.clear()
    const page = createPage()
    page._timerState.sessionId = 'timer-math-session'
    page._timerState.sessionStartTime = nowMs - 10000
    page._timerState.totalPausedMs = 1000
    storage.set('pomodoro_pause_adjustment', {
      sessionId: 'timer-math-session', totalPausedMs: 3000,
    })
    assert.strictEqual(page._getFreeElapsedMs(), 9000)
    assert.strictEqual(page._getEffectiveFreeElapsedMs(), 7000)
    assert.strictEqual(page._getFreeElapsedMs(nowMs + 1000), 10000)
    assert.strictEqual(page._getFreeElapsedMs(0), 0)
    const display = page._formatCountdownDisplay(61)
    assert.strictEqual(display.min, '01')
    assert.strictEqual(display.sec, '01')
    storage.clear()
  })

  await test('invalid session starts do not read pause storage', () => {
    const page = createPage()
    page._timerState.sessionStartTime = 'invalid'
    page._mergeLocalPauseAdjustment = () => { throw new Error('unexpected storage read') }
    assert.strictEqual(page._getFreeElapsedMs(nowMs), 0)
    assert.strictEqual(page._getEffectiveFreeElapsedMs(nowMs), 0)
  })

  await test('invalid merged pauses retain the original NaN result', () => {
    const page = createPage()
    page._timerState.sessionStartTime = nowMs - 10000
    page._timerState.totalPausedMs = 'invalid'
    page._mergeLocalPauseAdjustment = (_sessionId, pause) => pause
    assert.ok(Number.isNaN(page._getEffectiveFreeElapsedMs(nowMs)))
  })

  await test('current single subject icons replace stale cached paths in both themes', () => {
    const subjects = [
      { id: 10, code: 'exam408', name: '计算机', _isAggregate: true, _disabled: false, _icon: '', _iconDark: '' },
      { id: 11, code: 'data_structure', name: '数据结构', _icon: '/assets/icons/diagnosis-subject/data-structure.svg', _iconDark: '/assets/icons/diagnosis-subject/data-structure-dark.svg' },
      { id: 12, code: 'computer_organization', name: '计算机组成原理' },
      { id: 13, code: 'operating_system', name: '操作系统' },
      { id: 14, code: 'computer_network', name: '计算机网络' },
    ]
    const page = createPage()
    page._applySubjects(subjects)
    assert.strictEqual(page.data.aggregateAvailable, true)
    assert.strictEqual(page.data.coreSubjects.length, 4)
    for (const [code, icon] of [['exam408', 'monitor'], ['data_structure', 'list-tree']]) {
      const subject = page.data.subjects.find(item => item.code === code)
      for (const [field, suffix] of [['_icon', ''], ['_iconDark', '-dark']]) {
        const expected = `/assets/icons/pomodoro-subject/${icon}${suffix}.svg`
        assert.strictEqual(subject[field], expected)
        const svg = fs.readFileSync(path.resolve(__dirname, '..', expected.slice(1)), 'utf8')
        assert.ok(svg.includes('fill="none"') && svg.includes('stroke-width="2"'))
        assert.ok(svg.includes(suffix ? '#A5CBA8' : '#27634B'))
      }
      page.data.selectedSubject = subject
      capturedPage._updateComputedFields.call(page)
      assert.strictEqual(page.data.selectedSubjectIcon, subject._icon)
    }
    assert.strictEqual(subjects[0]._icon, '', 'cached input is not mutated')
    assert.strictEqual(subjects[1]._icon, '/assets/icons/diagnosis-subject/data-structure.svg')
    const wxml = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/pomodoro.wxml'), 'utf8')
    assert.ok(!wxml.includes('aggregate-icon'))
    assert.ok(!wxml.includes('wx:for="{{coreSubjects}}"'))
    assert.ok(wxml.includes("themeMode === 'dark' ? item._iconDark : item._icon"))
  })

  await test('fresh subject loading supplies independent aggregate and data-structure icons', async () => {
    const previousGet = api.get
    api.get = async () => [{
      subject_id: 10, subject_code: 'exam408', subject_name: '计算机',
      children: ['data_structure', 'computer_organization', 'operating_system', 'computer_network']
        .map((code, index) => ({ subject_id: 11 + index, subject_code: code, subject_name: code })),
    }]
    try {
      const page = createPage()
      await page._loadSubjects()
      assert.strictEqual(page.data.subjects[0]._icon, '/assets/icons/pomodoro-subject/monitor.svg')
      assert.strictEqual(page.data.subjects[1]._icon, '/assets/icons/pomodoro-subject/list-tree.svg')
      assert.strictEqual(page.data.subjects[0]._disabled, false)
      assert.strictEqual(page.data.aggregateAvailable, true)
    } finally {
      api.get = previousGet
    }
  })

  await test('408 parent route selects the enabled four-subject allocation', async () => {
    const subjects = [
      { id: 10, code: 'exam408', name: '计算机', _isAggregate: true, _disabled: false },
      { id: 11, code: 'data_structure', name: '数据结构' },
      { id: 12, code: 'computer_organization', name: '计算机组成原理' },
      { id: 13, code: 'operating_system', name: '操作系统' },
      { id: 14, code: 'computer_network', name: '计算机网络' },
    ]
    for (const route of [{ fromSubjectCode: 'exam408' }, { fromSubjectId: 10 }]) {
      const page = createPage()
      Object.assign(page.data, route)
      page._applySubjects(subjects)
      assert.strictEqual(page.data.selectedSubjectId, 10)
      assert.strictEqual(page.data.selectedSubject._isAggregate, true)
      assert.strictEqual(page.data.allocationMode, 'equal_408_core_v1')
    }
  })

  await test('cached and server-restored sessions retain the 408 allocation mode', async () => {
    const page = createPage()
    page.data.subjects = [
      { id: 10, code: 'exam408', name: '计算机', _isAggregate: true },
    ]
    page._mergeLocalPauseAdjustment = (_id, value) => value
    page._startTimer = () => {}
    page._pageVisible = true
    const cached = page._buildCachedActiveSession({
      sessionId: 88,
      sessionStartTime: nowMs - 60_000,
      workDuration: 25,
      breakDuration: 5,
      selectedPreset: 'standard',
      selectedSubjectId: 10,
      selectedSubjectCode: 'exam408',
      selectedSubjectName: '计算机',
      allocationMode: 'equal_408_core_v1',
    })
    assert.strictEqual(cached.allocation_mode, 'equal_408_core_v1')
    page._restoreSession(cached)
    assert.strictEqual(page.data.allocationMode, 'equal_408_core_v1')
    assert.strictEqual(page.data.selectedSubject._isAggregate, true)

    page.data.allocationMode = 'single'
    page.data.selectedSubject._isAggregate = false
    page._syncActiveSessionLight({
      ...cached,
      allocation_mode: 'equal_408_core_v1',
    })
    assert.strictEqual(page.data.allocationMode, 'equal_408_core_v1')
    assert.strictEqual(page.data.selectedSubject._isAggregate, true)
  })

  await test('pause stays fail-closed when pending intent cannot be persisted', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page.data.phase = 'running'
    page.data.isPaused = false
    page.data.actionLoading = false
    page._timerState.sessionId = 11
    page._timerState.sessionStartTime = nowMs - 30_000
    failSetStorageKey = 'pomodoro_pending_sync'
    await page._pauseSession()
    failSetStorageKey = ''
    assert.strictEqual(page.data.isPaused, false)
    assert.strictEqual(page._clearTimerCalls || 0, 0)
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('resume stays paused when pending intent cannot be persisted', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page.data.phase = 'running'
    page.data.isPaused = true
    page.data.actionLoading = false
    page.data.workDuration = 25
    page.data.selectedPreset = 'standard'
    page._timerState.sessionId = 12
    page._timerState.sessionStartTime = nowMs - 60_000
    page._timerState.pauseStartTime = nowMs - 5_000
    storage.set('pomodoro_pause', { sessionId: 12, totalPausedMs: 0, pauseStartTime: nowMs - 5_000 })
    failSetStorageKey = 'pomodoro_pending_sync'
    await page._resumeSession()
    failSetStorageKey = ''
    assert.strictEqual(page.data.isPaused, true)
    assert.ok(storage.get('pomodoro_pause'))
  })

  await test('queue safety valve rejects toggles but preserves terminal capacity', async () => {
    storage.clear()
    const page = createPage()
    const queue = []
    for (let i = 0; i < 196; i++) {
      queue.push({
        action: i % 2 ? 'resume' : 'pause',
        sessionId: 21,
        savedAt: nowMs + i + 1,
        clientActionAt: nowMs + i + 1,
        nonce: 'n' + i,
      })
    }
    storage.set('pomodoro_pending_sync', queue)
    assert.strictEqual(page._setPendingPomodoroSync('pause', 21, nowMs + 500), null)
    const terminal = page._setPendingPomodoroSync('complete', 21, nowMs + 501)
    assert.ok(terminal)
    assert.strictEqual(storage.get('pomodoro_pending_sync').length, 197)
  })

  await test('503 schedules the first bounded retry at 2 seconds', async () => {
    storage.clear(); scheduledDelay = null
    const page = createPage()
    page._pageVisible = true
    storage.set('pomodoro_pending_sync', [{
      action: 'pause', sessionId: 31, savedAt: nowMs, clientActionAt: nowMs, nonce: 'retry-1',
    }])
    page._schedulePendingPomodoroSyncRetry({ statusCode: 503 })
    assert.strictEqual(scheduledDelay, 2000)
    let retries = 0
    page._retryPendingPomodoroSync = async () => { retries++; return true }
    scheduledTimer.fn()
    await Promise.resolve()
    assert.strictEqual(retries, 1)
    page._schedulePendingPomodoroSyncRetry({ statusCode: 503 })
    assert.strictEqual(scheduledDelay, 5000)
    page._clearPendingPomodoroSyncRetryTimer(true)
  })

  await test('cold restore remains paused across device-clock rollback', async () => {
    storage.clear()
    const page = createPage()
    storage.set('pomodoro_pause', {
      sessionId: 41,
      totalPausedMs: 0,
      pauseStartTime: nowMs + 60_000,
    })
    page._restoreSession({
      id: 41,
      preset: 'standard',
      work_duration: 25,
      break_duration: 5,
      start_time: new Date(nowMs - 30_000).toISOString(),
      total_paused_sec: 0,
      subject_id: null,
      subject_code: '',
      subject_name: '未分类',
    })
    assert.strictEqual(page.data.isPaused, true)
    assert.ok(page._timerState.totalPausedMs >= 0)
  })

  await test('pending storage read failure is not treated as an empty queue', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    const original = [{
      action: 'pause', sessionId: 51, savedAt: nowMs, clientActionAt: nowMs, nonce: 'keep-me',
    }]
    storage.set('pomodoro_pending_sync', original)
    failReadStorageKey = 'pomodoro_pending_sync'
    assert.strictEqual(page._getPendingPomodoroSyncQueue(), null)
    assert.strictEqual(page._setPendingPomodoroSync('resume', 51, nowMs + 1000), null)
    failReadStorageKey = ''
    assert.deepStrictEqual(storage.get('pomodoro_pending_sync'), original)
  })

  await test('onShow stops reconciliation while pending storage is unreadable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._syncThemeFromStorage = () => {}
    page._pageVisible = false
    let reconcileCalls = 0
    page._reconcileUnknownStartAttempt = async () => { reconcileCalls++; return 'none' }
    failReadStorageKey = 'pomodoro_pending_sync'
    await page.onShow()
    failReadStorageKey = ''
    assert.strictEqual(reconcileCalls, 0)
    assert.strictEqual(page.data.pageEntered, true)
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('active-session recovery fails closed before any server fetch when local snapshot is unreadable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    let getCount = 0
    api.get = async () => { getCount++; return null }
    failReadStorageKey = 'pomodoro_running_state'
    const cached = page._getCachedActiveSession()
    const active = await page._fetchActiveSession()
    failReadStorageKey = ''
    api.get = async () => null
    assert.ok(cached && cached.storageUnreadable)
    assert.ok(active && active.storageUnreadable)
    assert.strictEqual(getCount, 0)
  })

  await test('cold restore does not treat unreadable pause adjustment as zero', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    storage.set('pomodoro_pause', {
      sessionId: 52,
      totalPausedMs: 1000,
      pauseStartTime: nowMs - 1000,
    })
    failReadStorageKey = 'pomodoro_pause_adjustment'
    const restored = page._restoreSession({
      id: 52,
      preset: 'standard',
      work_duration: 25,
      break_duration: 5,
      start_time: new Date(nowMs - 30_000).toISOString(),
      total_paused_sec: 0,
      subject_id: null,
      subject_code: '',
      subject_name: '未分类',
    })
    failReadStorageKey = ''
    assert.strictEqual(restored, false)
    assert.strictEqual(page.data.phase, 'idle')
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('terminal conflict storage failure keeps the pending terminal mutation durable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._pageVisible = true
    storage.set('pomodoro_pending_sync', [{
      action: 'complete', sessionId: 53, savedAt: nowMs, clientActionAt: nowMs, nonce: 'terminal-keep',
    }])
    api.post = async () => ({ status: 'interrupted' })
    failSetStorageKey = 'pomodoro_terminal_conflict'
    const synced = await page._retryPendingPomodoroSync()
    failSetStorageKey = ''
    api.post = async () => ({ status: 'running' })
    assert.strictEqual(synced, false)
    const queue = storage.get('pomodoro_pending_sync')
    assert.ok(Array.isArray(queue) && queue.length === 1)
    assert.strictEqual(queue[0].nonce, 'terminal-keep')
    assert.strictEqual(storage.has('pomodoro_terminal_conflict'), false)
  })

  await test('terminal conflict is not acknowledged when durable cleanup cannot finish', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page.data.showCelebration = true
    const conflict = { sessionId: 54, requestedAction: 'complete', serverStatus: 'interrupted', savedAt: nowMs }
    storage.set('pomodoro_terminal_conflict', conflict)
    storage.set('pomodoro_completion', { sessionId: 54, breakSec: 300 })
    const peeked = page._consumePomodoroTerminalConflict(54, 'complete')
    assert.strictEqual(peeked.sessionId, 54)
    failRemoveStorageKey = 'pomodoro_terminal_conflict'
    const handled = page._handlePomodoroTerminalConflict(54, peeked)
    failRemoveStorageKey = ''
    assert.strictEqual(handled, false)
    assert.ok(storage.get('pomodoro_terminal_conflict'))
    assert.strictEqual(page.data.showCelebration, true)
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('start is never POSTed before unknown-start recovery data is durable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._pageVisible = true
    page._startRequestSeq = 1
    let postCount = 0
    api.post = async () => { postCount++; return { id: 61, status: 'running', client_start_id: 'runtime-test-start-id' } }
    failSetStorageKey = 'pomodoro_unknown_start'
    const result = await page._postPomodoroStartWithReconciliation({
      subject_id: 1, chapter_id: null, preset: 'standard', work_duration: 25, break_duration: 5,
    }, 1)
    failSetStorageKey = ''
    assert.strictEqual(result.handled, true)
    assert.strictEqual(postCount, 0)
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('late start response keeps a cancel credential when pending storage is unavailable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._pageVisible = false
    page._startRequestSeq = 2
    api.post = async (url, body) => ({
      id: 62,
      status: 'running',
      client_start_id: body.client_start_id,
      start_time: new Date(nowMs - 1000).toISOString(),
    })
    failSetStorageKey = 'pomodoro_pending_sync'
    const result = await page._postPomodoroStartWithReconciliation({
      subject_id: 1, chapter_id: null, preset: 'standard', work_duration: 25, break_duration: 5,
    }, 1)
    failSetStorageKey = ''
    assert.strictEqual(result.handled, true)
    const marker = storage.get('pomodoro_unknown_start')
    assert.ok(marker && marker.cancelIfFound)
    assert.ok(Number(marker.cancelAt) > 0)
    assert.strictEqual(storage.has('pomodoro_pending_sync'), false)
  })

  await test('successful start is not accepted while unknown-start cleanup cannot be persisted', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._pageVisible = true
    page._startRequestSeq = 3
    page.data.phase = 'ceremony'
    api.post = async (url, body) => ({
      id: 63,
      status: 'running',
      client_start_id: body.client_start_id,
      start_time: new Date(nowMs).toISOString(),
    })
    failRemoveStorageKey = 'pomodoro_unknown_start'
    const result = await page._postPomodoroStartWithReconciliation({
      subject_id: 1, chapter_id: null, preset: 'standard', work_duration: 25, break_duration: 5,
    }, 3)
    failRemoveStorageKey = ''
    assert.strictEqual(result.handled, true)
    assert.strictEqual(page.data.phase, 'idle')
    assert.ok(storage.get('pomodoro_unknown_start'))
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('slower older stats response cannot overwrite newer totals', async () => {
    storage.clear()
    const page = createPage()
    const pending = []
    api.get = () => new Promise(resolve => pending.push(resolve))
    const first = page.loadTodayStats()
    const second = page.loadTodayStats()
    pending[1]({ today_sessions: 8, today_duration_sec: 3600 })
    await second
    pending[0]({ today_sessions: 7, today_duration_sec: 3000 })
    await first
    assert.strictEqual(page.data.todaySessions, 8)
    assert.strictEqual(page.data.todayDurationText, '1时0分')
    api.get = async () => null
  })

  console.log('\n==============================')
  console.log('Passed:', passed, ' Failed:', failed)
  console.log('==============================\n')
  if (failed) process.exit(1)
})()
