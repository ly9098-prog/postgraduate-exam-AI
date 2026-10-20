const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildRunningSnapshot, cancelUnknownStartOnHide, persistSessionOnHide,
} = require('../pages/pomodoro/utils/hide-storage')

function fixture() {
  const calls = []
  const view = { phase: 'running', isPaused: false, selectedSubject: null }
  const timer = { sessionId: 1, sessionStartTime: 100, totalPausedMs: 0, elapsedSec: 10 }
  const values = new Map()
  let time = 1000
  const options = {
    readStorage: (key, context) => { calls.push(['read', key, context]); return { ok: true, value: values.get(key) } },
    writeStorage: (key, value, context) => { calls.push(['write', key, context]); values.set(key, value); return true },
    view: () => view,
    timer: () => timer,
    confirmSnapshot: () => null,
    now: () => time++,
  }
  return { calls, view, timer, values, options }
}

test('running snapshot preserves stored fields, allocation and task classification', () => {
  const view = Object.freeze({
    phase: 'running', selectedSubjectId: 4, selectedSubject: Object.freeze({ code: 'exam408', name: '408' }),
    allocationMode: 'equal_408_core_v1', selectedTaskType: 'review',
    selectedPreset: 'long', workDuration: 50, breakDuration: 10, isPaused: true, isFreeTimer: false,
  })
  const timer = Object.freeze({
    sessionId: 1, sessionStartTime: 100, totalPausedMs: 300, pauseStartTime: 800, elapsedSec: 65,
    freeDisplayOffsetMs: 999,
  })
  assert.deepEqual(buildRunningSnapshot(view, timer, () => 1000), {
    sessionStartTime: 100, workDuration: 50, breakDuration: 10, selectedPreset: 'long',
    selectedSubjectId: 4, selectedSubjectCode: 'exam408', selectedSubjectName: '408',
    allocationMode: 'equal_408_core_v1', selectedTaskType: 'review', isPaused: true,
    totalPausedMs: 300, pauseStartTime: 800, sessionId: 1, isFreeTimer: false, elapsedSec: 65,
    freeDisplayOffsetMs: 0, savedAt: 1000,
  })
})

test('clock is sampled separately for missing pause start and savedAt', () => {
  const f = fixture()
  f.view.isPaused = true
  const snapshot = buildRunningSnapshot(f.view, f.timer, f.options.now)
  assert.equal(snapshot.pauseStartTime, 1000)
  assert.equal(snapshot.savedAt, 1001)
  f.view.isPaused = false
  const running = buildRunningSnapshot(f.view, f.timer, f.options.now)
  assert.equal(running.pauseStartTime, null)
  assert.equal(running.savedAt, 1002)
  assert.equal(running.selectedSubjectCode, '')
  assert.equal(running.selectedSubjectName, '')
})

test('unknown start cancellation retains exact idempotency fields without mutating source', () => {
  const f = fixture()
  const attempt = Object.freeze({ clientStartId: 'synthetic-key', payload: { subject_id: 4 }, cancelAt: 20 })
  f.values.set('pomodoro_unknown_start', attempt)
  cancelUnknownStartOnHide(f.options)
  assert.deepEqual(f.values.get('pomodoro_unknown_start'), {
    ...attempt, cancelIfFound: true, cancelAt: 1000,
  })
  assert.equal(attempt.cancelIfFound, undefined)
  assert.equal(f.values.get('pomodoro_unknown_start').payload, attempt.payload)
})

test('missing or unreadable unknown start never writes or samples the clock', () => {
  for (const stored of [{ ok: true }, { ok: false, value: { clientStartId: 'synthetic-key' } }]) {
    const f = fixture()
    f.options.readStorage = () => stored
    f.options.now = () => { throw new Error('unexpected clock read') }
    cancelUnknownStartOnHide(f.options)
    assert.deepEqual(f.calls, [])
  }
})

test('confirmation persists first and running state follows completion check', () => {
  const f = fixture()
  const confirm = { sessionId: 1, mode: 'free-complete' }
  f.view.showEndConfirm = true
  f.options.confirmSnapshot = () => confirm
  persistSessionOnHide(f.options)
  assert.equal(f.values.get('pomodoro_confirm_pause'), confirm)
  assert.deepEqual(f.calls, [
    ['write', 'pomodoro_confirm_pause', 'onHide confirm snapshot'],
    ['read', 'pomodoro_completion', 'onHide completion'],
    ['write', 'pomodoro_running_state', 'onHide running snapshot'],
  ])
})

test('completion marker or read failure prevents writing running snapshot', () => {
  for (const stored of [{ ok: true, value: { sessionId: 1 } }, { ok: false }]) {
    const f = fixture()
    f.options.readStorage = () => stored
    persistSessionOnHide(f.options)
    assert.equal(f.values.has('pomodoro_running_state'), false)
  }
})

test('idle, break, ceremony, missing session and celebration never overwrite running snapshot', () => {
  for (const mode of ['idle', 'break', 'ceremony', 'missing-session', 'celebration']) {
    const f = fixture()
    if (mode === 'missing-session') f.timer.sessionId = null
    else if (mode === 'celebration') f.view.showCelebration = true
    else f.view.phase = mode
    persistSessionOnHide(f.options)
    assert.equal(f.values.has('pomodoro_running_state'), false)
  }
})

test('failed confirmation write does not skip independent running snapshot persistence', () => {
  const f = fixture()
  f.view.showEndConfirm = true
  f.options.confirmSnapshot = () => ({ sessionId: 1 })
  const write = f.options.writeStorage
  f.options.writeStorage = (key, ...args) => key === 'pomodoro_confirm_pause' ? false : write(key, ...args)
  persistSessionOnHide(f.options)
  assert.equal(f.values.has('pomodoro_confirm_pause'), false)
  assert.equal(f.values.get('pomodoro_running_state').sessionId, 1)
})
