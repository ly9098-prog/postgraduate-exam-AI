const assert = require('node:assert/strict')
const {
  buildUnknownStartPayload,
  matchesUnknownStartAttempt,
  buildUnknownStartAttempt,
} = require('../pages/pomodoro/utils/unknown-start-helpers')

const data = {
  selectedSubjectId: 5,
  fromChapterId: 'ch1',
  selectedPreset: 'standard',
  workDuration: 25,
  breakDuration: 5,
  allocationMode: 'single',
  selectedTaskType: 'lecture',
}

// ── buildUnknownStartPayload ──

assert.equal(buildUnknownStartPayload(null), null)
assert.equal(buildUnknownStartPayload({}), null)
assert.equal(buildUnknownStartPayload({ clientStartId: '' }), null)

const payload = buildUnknownStartPayload({
  subjectId: 3, allocationMode: 'equal_408_core_v1', chapterId: 'ch2',
  preset: 'long', workDuration: 50, breakDuration: 10,
  notificationEnabled: true, clientStartId: 'abc',
})
assert.deepEqual(payload, {
  subject_id: 3, allocation_mode: 'equal_408_core_v1', chapter_id: 'ch2',
  preset: 'long', work_duration: 50, break_duration: 10,
  notification_enabled: true, client_start_id: 'abc',
})

// defaults
const defaults = buildUnknownStartPayload({ clientStartId: 'x' })
assert.equal(defaults.allocation_mode, 'single')
assert.equal(defaults.chapter_id, null)
assert.equal(defaults.notification_enabled, false)

// ── matchesUnknownStartAttempt ──

assert.equal(matchesUnknownStartAttempt(null, {}), false)
assert.equal(matchesUnknownStartAttempt({}, {}), false)
assert.equal(matchesUnknownStartAttempt({ id: 1, client_start_id: 'abc' }, { clientStartId: 'abc' }), true)
assert.equal(matchesUnknownStartAttempt({ id: 1, client_start_id: 'abc' }, { clientStartId: 'xyz' }), false)
assert.equal(matchesUnknownStartAttempt({ id: 1, client_start_id: 'abc' }, null), false)
assert.equal(matchesUnknownStartAttempt(null, { clientStartId: 'abc' }), false)
assert.equal(matchesUnknownStartAttempt({ client_start_id: 'abc' }, { clientStartId: 'abc' }), false) // no session.id

// ── buildUnknownStartAttempt ──

const attempt = buildUnknownStartAttempt(data, {}, () => 'client123', 1000)
assert.equal(attempt.requestedAt, 1000)
assert.equal(attempt.cancelIfFound, false)
assert.equal(attempt.cancelAt, null)
assert.equal(attempt.clientStartId, 'client123')
assert.equal(attempt.subjectId, 5)
assert.equal(attempt.chapterId, 'ch1')
assert.equal(attempt.preset, 'standard')
assert.equal(attempt.workDuration, 25)
assert.equal(attempt.breakDuration, 5)
assert.equal(attempt.allocationMode, 'single')
assert.equal(attempt.notificationEnabled, false)
assert.equal(attempt.taskType, 'lecture')

// debug preset
const debugAttempt = buildUnknownStartAttempt(
  { ...data, selectedPreset: 'debug' }, {}, () => 'dbg', 2000
)
assert.equal(debugAttempt.workDuration, 1)
assert.equal(debugAttempt.breakDuration, 1)

// overrides
const overridden = buildUnknownStartAttempt(data, {
  clientStartId: 'override', subjectId: 99, taskType: 'exam'
}, () => 'unused', 3000)
assert.equal(overridden.clientStartId, 'override')
assert.equal(overridden.subjectId, 99)
assert.equal(overridden.taskType, 'exam')
assert.equal(overridden.requestedAt, 3000)

console.log('Pomodoro unknown start helpers passed: payload/match/build')

// ── startCancellationAt ──
const { startCancellationAt } = require('../pages/pomodoro/utils/unknown-start-helpers')
const parse = (s) => new Date(s).getTime()

// with valid server start_time
assert.equal(startCancellationAt({ start_time: '2023-01-01T00:00:00Z' }, 1700000001000, 1700000002000, parse), 1700000001000)
// cancelAt=0 → fallback to now, which is after server start
assert.equal(startCancellationAt({ start_time: '2023-01-01T00:00:00Z' }, 0, 1700000002000, parse), 1700000002000)
// no session → fallback to now
assert.equal(startCancellationAt(null, 0, 1700000003000, parse), 1700000003000)
// invalid cancelAt → fallback to now
assert.equal(startCancellationAt(null, NaN, 1700000004000, parse), 1700000004000)
// valid cancelAt → use it
assert.equal(startCancellationAt(null, 1700000005000, 1700000006000, parse), 1700000005000)

console.log('Pomodoro unknown start helpers passed: payload/match/build/cancellation')
