const assert = require('node:assert/strict')
const { buildCachedActiveSession } = require('../pages/pomodoro/utils/cached-session-builder')

const toISO = (ms) => new Date(ms).toISOString()

// null/invalid inputs
assert.equal(buildCachedActiveSession(null, toISO), null)
assert.equal(buildCachedActiveSession({}, toISO), null)
assert.equal(buildCachedActiveSession({ sessionStartTime: 'bad' }, toISO), null)
assert.equal(buildCachedActiveSession({ sessionStartTime: -1 }, toISO), null)
assert.equal(buildCachedActiveSession({ sessionStartTime: 1000 }, toISO), null) // no sessionId

// valid running session
const running = buildCachedActiveSession({
  sessionStartTime: 1700000000000,
  sessionId: 42,
  workDuration: 25,
  breakDuration: 5,
  selectedPreset: 'standard',
  isPaused: false,
  totalPausedMs: 30000,
  selectedSubjectId: 3,
  selectedSubjectCode: 'CS',
  selectedSubjectName: '计算机',
  allocationMode: 'single',
  selectedTaskType: 'lecture',
  isFreeTimer: false,
}, toISO)
assert.equal(running.id, 42)
assert.equal(running.status, 'running')
assert.equal(running.preset, 'standard')
assert.equal(running.total_paused_sec, 30)
assert.equal(running.paused_at, null)
assert.equal(running._local_elapsed_sec, undefined)

// paused free-timer session
const paused = buildCachedActiveSession({
  sessionStartTime: 1700000000000,
  sessionId: 7,
  workDuration: 0,
  breakDuration: 0,
  selectedPreset: 'free',
  isPaused: true,
  pauseStartTime: 1700000010000,
  totalPausedMs: 5000,
  selectedSubjectId: null,
  selectedSubjectCode: '',
  selectedSubjectName: '',
  allocationMode: 'equal_408_core_v1',
  selectedTaskType: 'exam',
  isFreeTimer: true,
  elapsedSec: 120,
}, toISO)
assert.equal(paused.status, 'paused')
assert.ok(paused.paused_at.includes('T'))
assert.equal(paused._local_elapsed_sec, 120)
assert.equal(paused.allocation_mode, 'equal_408_core_v1')
assert.equal(paused.task_type, 'exam')

// defaults for missing fields
const defaults = buildCachedActiveSession({
  sessionStartTime: 1700000000000,
  sessionId: 1,
}, toISO)
assert.equal(defaults.preset, 'standard')
assert.equal(defaults.allocation_mode, 'single')
assert.equal(defaults.subject_code, '')
assert.equal(defaults.work_duration, 0)

console.log('Pomodoro cached session builder passed: null/running/paused/defaults')
