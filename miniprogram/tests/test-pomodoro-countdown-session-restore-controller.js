const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createCountdownSessionRestoreController,
} = require('../pages/pomodoro/utils/countdown-session-restore-controller')
const {
  resolvePausedMs,
  computeCountdownRestore,
  resolveRestoredSubject,
} = require('../pages/pomodoro/utils/session-restore')
const { formatCountdownDisplay } = require('../pages/pomodoro/utils/timer-math')

function createHarness(overrides = {}) {
  const calls = {
    now: 0,
    nowValues: Array.isArray(overrides.nowValues) ? [...overrides.nowValues] : null,
    remove: [],
    writes: [],
    errors: 0,
    resets: 0,
    toast: [],
    records: [],
    merged: [],
    starts: [],
    draws: [],
    nextTicks: 0,
    stats: 0,
    completions: [],
    conflicts: [],
    handled: [],
    celebrations: [],
    vibrations: 0,
  }
  const page = {
    data: {
      showEndConfirm: false,
      subjects: [{ id: 4, code: 'data_structure', name: '数据结构' }],
    },
    _confirmTimerSnapshot: overrides.confirmSnapshot || null,
    _timerState: {
      sessionId: null,
      sessionStartTime: null,
      remainingSec: 0,
      totalPausedMs: 0,
      pauseStartTime: null,
      progress: 0,
    },
    _safeGetPomodoroStorage(key) {
      if (key === 'pomodoro_confirm_pause') {
        return overrides.confirmStorage || { ok: true, value: null }
      }
      if (key === 'pomodoro_pause') {
        return overrides.pauseStorage || { ok: true, value: null }
      }
      throw new Error(`unexpected storage read: ${key}`)
    },
    _safeRemovePomodoroStorage(key) {
      calls.remove.push(key)
      return true
    },
    _safeSetPomodoroStorage(key, value) {
      calls.writes.push([key, value])
      return true
    },
    _showPomodoroPersistenceError() {
      calls.errors += 1
    },
    _resetToIdle() {
      calls.resets += 1
    },
    _mergeLocalPauseAdjustment(sessionId, totalPausedMs, failClosed) {
      calls.merged.push([sessionId, totalPausedMs, failClosed])
      return overrides.mergedPausedMs === undefined
        ? totalPausedMs
        : overrides.mergedPausedMs
    },
    _lookupSubjectIdByCode(code) {
      return code === 'data_structure' ? 4 : null
    },
    _completePomodoroWithRetry(sessionId, completedAt) {
      calls.completions.push([sessionId, completedAt])
      return Promise.resolve(overrides.completedSynced !== false)
    },
    _consumePomodoroTerminalConflict(sessionId, action) {
      calls.conflicts.push([sessionId, action])
      return overrides.terminalConflict || null
    },
    _handlePomodoroTerminalConflict(sessionId, conflict) {
      calls.handled.push([sessionId, conflict])
    },
    _showCompletionCelebration(sessionId, options) {
      calls.celebrations.push([sessionId, options])
    },
    loadTodayStats() {
      calls.stats += 1
    },
    _updateComputedFields() {},
    _startTimer(totalSec) {
      calls.starts.push(totalSec)
    },
    _initCanvas(force) {
      calls.draws.push(['init', force])
    },
    drawRing(totalSec, isBreak) {
      calls.draws.push(['ring', totalSec, isBreak])
    },
    setData(update) {
      page.data = { ...page.data, ...update }
    },
  }
  const options = {
    page,
    now: () => {
      calls.now += 1
      if (calls.nowValues && calls.nowValues.length) return calls.nowValues.shift()
      return overrides.now || 60000
    },
    parseServerTime: value => overrides.parseServerTime
      ? overrides.parseServerTime(value)
      : Number(value),
    resolvePausedMs,
    computeCountdownRestore,
    resolveRestoredSubject,
    formatCountdownDisplay,
    runningPhase: 'running',
    pomodoroTaskTypes: {
      typeForSession: () => overrides.taskType || '',
      label: type => type === 'study' ? '学习' : '未分类',
      recordSession(session, type) {
        calls.records.push([session.id, type])
      },
    },
    nextTick(callback) {
      calls.nextTicks += 1
      callback()
    },
    vibrateLong() {
      calls.vibrations += 1
    },
    showToast(payload) {
      calls.toast.push(payload)
    },
  }
  return {
    controller: createCountdownSessionRestoreController(options),
    page,
    calls,
  }
}

function activeSession(overrides = {}) {
  return {
    id: 7,
    preset: 'standard',
    start_time: 1000,
    work_duration: 2,
    break_duration: 5,
    total_paused_sec: 0,
    subject_id: 4,
    ...overrides,
  }
}

test('restores a running countdown from the server clock and starts its timer', () => {
  const { controller, page, calls } = createHarness({ taskType: 'study' })

  assert.equal(controller.restore(activeSession()), true)
  assert.equal(calls.now, 1)
  assert.deepEqual(calls.merged, [[7, 0, true]])
  assert.deepEqual(calls.records, [[7, 'study']])
  assert.deepEqual(calls.starts, [120])
  assert.equal(page._timerState.sessionId, 7)
  assert.equal(page._timerState.remainingSec, 61)
  assert.equal(page._timerState.totalPausedMs, 0)
  assert.equal(page._timerState.pauseStartTime, null)
  assert.equal(page.data.phase, 'running')
  assert.equal(page.data.displayMin, '01')
  assert.equal(page.data.displaySec, '01')
  assert.equal(page.data.isPaused, false)
  assert.equal(page.data.selectedTaskTypeLabel, '学习')
  assert.equal(calls.nextTicks, 0)
})

test('restores a paused countdown without starting the timer and redraws once', () => {
  const savedPause = { sessionId: 7, totalPausedMs: 0, pauseStartTime: 50000 }
  const { controller, page, calls } = createHarness({
    nowValues: [60000, 70000],
    pauseStorage: { ok: true, value: savedPause },
  })

  assert.equal(controller.restore(activeSession()), true)
  assert.equal(calls.now, 1)
  assert.deepEqual(calls.merged, [[7, 10000, true]])
  assert.deepEqual(calls.starts, [])
  assert.deepEqual(calls.draws, [['init', true], ['ring', 120, false]])
  assert.equal(calls.nextTicks, 1)
  assert.equal(page._timerState.remainingSec, 71)
  assert.equal(page._timerState.totalPausedMs, 10000)
  assert.equal(page._timerState.pauseStartTime, 60000)
  assert.deepEqual(calls.writes, [[
    'pomodoro_pause',
    { totalPausedMs: 10000, pauseStartTime: 60000, sessionId: 7 },
  ]])
})

test('uses the merged local pause adjustment in countdown timing', () => {
  const { controller, page } = createHarness({ mergedPausedMs: 17000 })

  assert.equal(controller.restore(activeSession()), true)
  assert.equal(page._timerState.totalPausedMs, 17000)
  assert.equal(page._timerState.remainingSec, 78)
  assert.equal(page.data.displayMin, '01')
  assert.equal(page.data.displaySec, '18')
})

test('keeps an active matching confirmation snapshot authoritative', () => {
  const { controller, page, calls } = createHarness({
    confirmSnapshot: { sessionId: 7, mode: 'countdown-interrupt' },
  })
  page.data.showEndConfirm = true

  assert.equal(controller.restore(activeSession()), true)
  assert.equal(calls.now, 0)
  assert.equal(calls.resets, 0)
  assert.deepEqual(calls.writes, [])
})

test('confirmation storage failure blocks countdown restoration', () => {
  const { controller, calls } = createHarness({
    confirmStorage: { ok: false, value: null },
  })

  assert.equal(controller.restore(activeSession()), false)
  assert.equal(calls.errors, 1)
  assert.equal(calls.now, 0)
})

test('invalid countdown state clears snapshots, resets and shows the legacy toast', () => {
  const { controller, calls } = createHarness({
    parseServerTime: () => Number.NaN,
  })

  assert.equal(controller.restore(activeSession()), true)
  assert.deepEqual(calls.remove, ['pomodoro_pause', 'pomodoro_running_state'])
  assert.equal(calls.resets, 1)
  assert.deepEqual(calls.toast, [{ title: '番茄钟状态异常，已重置', icon: 'none' }])
  assert.equal(calls.now, 0)
})

test('pause snapshot and local adjustment failures block restoration', () => {
  const pauseFailure = createHarness({
    pauseStorage: { ok: false, value: null },
  })
  assert.equal(pauseFailure.controller.restore(activeSession()), false)
  assert.equal(pauseFailure.calls.errors, 1)

  const adjustmentFailure = createHarness({ mergedPausedMs: null })
  assert.equal(adjustmentFailure.controller.restore(activeSession()), false)
  assert.equal(adjustmentFailure.calls.errors, 1)
  assert.deepEqual(adjustmentFailure.calls.merged, [[7, 0, true]])
})

test('expired countdown completes once, updates projections and shows celebration', async () => {
  const { controller, page, calls } = createHarness({ now: 120000, taskType: 'study' })
  const session = activeSession({ work_duration: 1 })

  assert.equal(controller.restore(session), true)
  assert.deepEqual(calls.completions, [[7, 61000]])
  assert.deepEqual(calls.starts, [])
  assert.equal(page._timerState.totalPausedMs, 0)
  assert.equal(page.data.selectedSubjectId, 4)
  assert.equal(page.data.isPaused, false)
  assert.equal(calls.vibrations, 1)
  assert.equal(calls.stats, 1)
  assert.equal(calls.celebrations.length, 1)
  assert.deepEqual(calls.celebrations[0][0], 7)
  assert.equal(calls.celebrations[0][1].selectedTaskType, 'study')

  await Promise.resolve()
  await Promise.resolve()
  assert.equal(calls.stats, 2)
  assert.deepEqual(calls.conflicts, [[7, 'complete']])
})

test('expired countdown handles a terminal conflict before refreshing stats', async () => {
  const conflict = { sessionId: 7, requestedAction: 'complete' }
  const { controller, calls } = createHarness({
    now: 120000,
    terminalConflict: conflict,
  })

  assert.equal(controller.restore(activeSession({ work_duration: 1 })), true)
  await Promise.resolve()
  await Promise.resolve()
  assert.deepEqual(calls.handled, [[7, conflict]])
  assert.equal(calls.stats, 1)
})
