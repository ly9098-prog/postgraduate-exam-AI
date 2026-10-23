const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createFreeSessionRestoreController,
} = require('../pages/pomodoro/utils/free-session-restore-controller')
const {
  resolvePausedMs,
  computeFreeRestore,
  resolveRestoredSubject,
} = require('../pages/pomodoro/utils/session-restore')
const { formatElapsedSec } = require('../pages/pomodoro/utils/timer-math')

const MAX_MS = 5 * 60 * 60 * 1000

function createHarness(overrides = {}) {
  const calls = {
    remove: [],
    errors: 0,
    resets: 0,
    records: [],
    merged: [],
    intervals: 0,
    limits: 0,
    draws: [],
    nextTick: 0,
    now: 0,
  }
  const page = {
    data: { subjects: [{ id: 4, code: 'data_structure', name: '数据结构' }] },
    _timerState: {
      sessionId: null,
      sessionStartTime: null,
      totalPausedMs: 0,
      pauseStartTime: null,
      elapsedSec: 0,
      freeFriendlyText: '',
      freeDisplayOffsetMs: 99,
      progress: 0,
    },
    _safeGetPomodoroStorage: overrides.readStorage || (() => ({ ok: true, value: null })),
    _safeRemovePomodoroStorage(key) {
      calls.remove.push(key)
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
    _clearTimer() {},
    _initCanvas(force) {
      calls.draws.push(['init', force])
    },
    drawRing(totalSec, isBreak) {
      calls.draws.push(['ring', totalSec, isBreak])
    },
    _startFreeTimerInterval() {
      calls.intervals += 1
    },
    _checkFreeTimerLimitAndAutoEnd() {
      calls.limits += 1
    },
    _updateComputedFields() {},
    setData(update) {
      page.data = { ...page.data, ...update }
    },
  }
  const options = {
    page,
    now: () => {
      calls.now += 1
      return overrides.now || 60000
    },
    parseServerTime: value => overrides.parseServerTime
      ? overrides.parseServerTime(value)
      : Number(value),
    resolvePausedMs,
    computeFreeRestore,
    resolveRestoredSubject,
    formatElapsedSec,
    maxMs: MAX_MS,
    runningPhase: 'running',
    pomodoroTaskTypes: {
      typeForSession: () => overrides.taskType || '',
      label: type => type === 'study' ? '学习' : '未分类',
      recordSession(session, type) {
        calls.records.push([session.id, type])
      },
    },
    nextTick(callback) {
      calls.nextTick += 1
      callback()
    },
  }
  return { controller: createFreeSessionRestoreController(options), page, calls }
}

test('restores a running free session and restarts its interval', () => {
  const { controller, page, calls } = createHarness({ taskType: 'study' })
  const result = controller.restore({
    id: 7,
    preset: 'free',
    start_time: 1000,
    total_paused_sec: 0,
    subject_id: 4,
    subject_code: 'data_structure',
  })

  assert.equal(result, true)
  assert.deepEqual(calls.merged, [[7, 0, true]])
  assert.deepEqual(calls.records, [[7, 'study']])
  assert.equal(page._timerState.sessionId, 7)
  assert.equal(page._timerState.sessionStartTime, 1000)
  assert.equal(page._timerState.freeDisplayOffsetMs, 0)
  assert.equal(page._timerState.elapsedSec, 59)
  assert.equal(page._timerState.freeFriendlyText, '59秒')
  assert.equal(page._timerState.pauseStartTime, null)
  assert.equal(page.data.phase, 'running')
  assert.equal(page.data.isFreeTimer, true)
  assert.equal(page.data.isPaused, false)
  assert.equal(page.data.selectedTaskType, 'study')
  assert.equal(page.data.selectedTaskTypeLabel, '学习')
  assert.equal(page.data.freeDisplayTime, '00:00:59')
  assert.deepEqual(calls.draws, [['init', true], ['ring', 0, false]])
  assert.equal(calls.intervals, 1)
  assert.equal(calls.limits, 1)
  assert.equal(calls.now, 1)
})

test('restores a paused free session without restarting the interval', () => {
  const savedPause = { sessionId: 7, totalPausedMs: 1000, pauseStartTime: 50000 }
  const { controller, page, calls } = createHarness({
    readStorage: () => ({ ok: true, value: savedPause }),
    now: 60000,
  })

  const result = controller.restore({
    id: 7,
    preset: 'free',
    start_time: 1000,
    total_paused_sec: 0,
    subject_id: 4,
  })

  assert.equal(result, true)
  assert.deepEqual(calls.merged, [[7, 11000, true]])
  assert.equal(page._timerState.totalPausedMs, 11000)
  assert.equal(page._timerState.pauseStartTime, 60000)
  assert.equal(page._timerState.elapsedSec, 48)
  assert.equal(page.data.isPaused, true)
  assert.equal(calls.intervals, 0)
  assert.equal(calls.limits, 0)
  assert.equal(calls.now, 1)
})

test('uses the merged local pause snapshot for the restored elapsed time', () => {
  const { controller, page } = createHarness({ mergedPausedMs: 17000 })

  assert.equal(controller.restore({
    id: 7,
    preset: 'free',
    start_time: 1000,
    total_paused_sec: 0,
    subject_id: 4,
  }), true)

  assert.equal(page._timerState.totalPausedMs, 17000)
  assert.equal(page._timerState.elapsedSec, 42)
  assert.equal(page.data.freeDisplayTime, '00:00:42')
})

test('invalid start time removes free caches and resets to idle', () => {
  const { controller, calls } = createHarness({
    parseServerTime: () => Number.NaN,
  })

  assert.equal(controller.restore({ id: 7, preset: 'free' }), true)
  assert.deepEqual(calls.remove, ['pomodoro_free_pause', 'pomodoro_running_state'])
  assert.equal(calls.resets, 1)
  assert.equal(calls.now, 0)
})

test('pause storage failure blocks restoration and reports persistence error', () => {
  const { controller, calls } = createHarness({
    readStorage: () => ({ ok: false, value: null }),
  })

  assert.equal(controller.restore({ id: 7, start_time: 1000 }), false)
  assert.equal(calls.errors, 1)
  assert.equal(calls.resets, 0)
  assert.equal(calls.now, 0)
})

test('local pause adjustment failure blocks restoration', () => {
  const { controller, calls } = createHarness({ mergedPausedMs: null })

  assert.equal(controller.restore({ id: 7, start_time: 1000 }), false)
  assert.equal(calls.errors, 1)
  assert.deepEqual(calls.merged, [[7, 0, true]])
})
