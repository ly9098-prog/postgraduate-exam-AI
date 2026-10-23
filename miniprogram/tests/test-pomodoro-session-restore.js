const assert = require('node:assert/strict')
const {
  resolvePausedMs,
  computeCountdownRestore,
  computeFreeRestore,
  resolveRestoredSubject,
} = require('../pages/pomodoro/utils/session-restore')

assert.deepEqual(resolvePausedMs({
  serverPausedSec: 10, savedPause: null, pausedAtMs: null, now: 10000, sessionId: 1,
}), { totalPausedMs: 10000, isPaused: false })

assert.deepEqual(resolvePausedMs({
  serverPausedSec: 10,
  savedPause: { sessionId: 1, totalPausedMs: 3000, pauseStartTime: 8000 },
  pausedAtMs: null,
  now: 10000,
  sessionId: 1,
}), { totalPausedMs: 5000, isPaused: true })

assert.deepEqual(resolvePausedMs({
  serverPausedSec: 10,
  savedPause: { sessionId: 2, totalPausedMs: 3000, pauseStartTime: 8000 },
  pausedAtMs: 7000,
  now: 10000,
  sessionId: 1,
}), { totalPausedMs: 13000, isPaused: true })

assert.deepEqual(resolvePausedMs({
  serverPausedSec: 10,
  savedPause: { sessionId: 1, totalPausedMs: 'bad', pauseStartTime: 8000 },
  pausedAtMs: null,
  now: 10000,
  sessionId: 1,
}), { totalPausedMs: 10000, isPaused: true })

assert.deepEqual(resolvePausedMs({
  serverPausedSec: 10, savedPause: null, pausedAtMs: 'bad', now: 10000, sessionId: 1,
}), { totalPausedMs: 10000, isPaused: false })

assert.deepEqual(resolvePausedMs({
  serverPausedSec: 10, savedPause: null, pausedAtMs: 12000, now: 10000, sessionId: 1,
}), { totalPausedMs: 10000, isPaused: true })

assert.deepEqual(computeCountdownRestore({
  serverPausedSec: 0,
  savedPause: null,
  pausedAtMs: null,
  now: 100000,
  startTime: 40000,
  totalSec: 1500,
  totalPausedMs: 0,
}), {
  totalPausedMs: 0,
  isPaused: false,
  elapsed: 60,
  remaining: 1440,
  progress: 0.96,
  completedAt: 100000,
})

assert.deepEqual(computeCountdownRestore({
  serverPausedSec: 0,
  savedPause: null,
  pausedAtMs: null,
  now: 100000,
  startTime: 40000,
  totalSec: 1500,
  totalPausedMs: 17000,
}), {
  totalPausedMs: 17000,
  isPaused: false,
  elapsed: 43,
  remaining: 1457,
  progress: 1457 / 1500,
  completedAt: 100000,
})

assert.deepEqual(computeCountdownRestore({
  serverPausedSec: 0,
  savedPause: { sessionId: 1, totalPausedMs: 0, pauseStartTime: 70000 },
  pausedAtMs: null,
  now: 60000,
  startTime: 30000,
  totalSec: 1500,
  sessionId: 1,
}), {
  totalPausedMs: 0,
  isPaused: true,
  elapsed: 30,
  remaining: 1470,
  progress: 0.98,
  completedAt: 60000,
})

assert.deepEqual(computeCountdownRestore({
  serverPausedSec: 0,
  savedPause: { sessionId: 1, totalPausedMs: 0, pauseStartTime: 70000 },
  pausedAtMs: null,
  now: 60000,
  startTime: 30000,
  totalSec: 1500,
  sessionId: 2,
}), {
  totalPausedMs: 0,
  isPaused: false,
  elapsed: 30,
  remaining: 1470,
  progress: 0.98,
  completedAt: 60000,
})

assert.deepEqual(computeCountdownRestore({
  serverPausedSec: 0,
  savedPause: null,
  pausedAtMs: null,
  now: 2000000,
  startTime: 0,
  totalSec: 1500,
}), {
  totalPausedMs: 0,
  isPaused: false,
  elapsed: 2000,
  remaining: 0,
  progress: 0,
  completedAt: 1500000,
})

assert.deepEqual(computeFreeRestore({
  serverPausedSec: 60,
  savedPause: null,
  pausedAtMs: null,
  now: 200000,
  startTime: 0,
  maxMs: 5 * 60 * 60 * 1000,
}), {
  totalPausedMs: 60000,
  isPaused: false,
  elapsed: 140,
})

assert.deepEqual(computeFreeRestore({
  serverPausedSec: 0,
  savedPause: { sessionId: 1, totalPausedMs: 0, pauseStartTime: 70000 },
  pausedAtMs: null,
  now: 60000,
  startTime: 30000,
  maxMs: 5 * 60 * 60 * 1000,
  sessionId: 1,
}), {
  totalPausedMs: 0,
  isPaused: true,
  elapsed: 30,
})

assert.deepEqual(computeFreeRestore({
  serverPausedSec: 0,
  savedPause: null,
  pausedAtMs: null,
  now: 20000000,
  startTime: 0,
  maxMs: 5 * 60 * 60 * 1000,
}), {
  totalPausedMs: 0,
  isPaused: false,
  elapsed: 18000,
})

assert.deepEqual(computeFreeRestore({
  serverPausedSec: 0,
  savedPause: null,
  pausedAtMs: null,
  now: 60000,
  startTime: 1000,
  maxMs: 5 * 60 * 60 * 1000,
  totalPausedMs: 17000,
}), {
  totalPausedMs: 17000,
  isPaused: false,
  elapsed: 42,
})

assert.deepEqual(resolveRestoredSubject({
  session: { subject_id: 4, subject_code: 'data_structure', subject_name: '数据结构' },
  subjects: [{ id: 4, code: 'data_structure', name: '已缓存' }],
  lookupSubjectIdByCode: () => 99,
}), {
  subjectId: 4,
  subjectCode: 'data_structure',
  subjectName: '数据结构',
  aggregate: false,
  selectedSubject: { id: 4, code: 'data_structure', name: '已缓存' },
})

assert.deepEqual(resolveRestoredSubject({
  session: { subject_code: 'exam408', subject_name: '408', allocation_mode: 'equal_408_core_v1' },
  subjects: [],
  lookupSubjectIdByCode: code => code === 'exam408' ? 408 : null,
}), {
  subjectId: 408,
  subjectCode: 'exam408',
  subjectName: '408',
  aggregate: true,
  selectedSubject: { id: 408, code: 'exam408', name: '408', _isAggregate: true },
})

assert.deepEqual(resolveRestoredSubject({
  session: { subject_code: '', subject_name: '' },
  subjects: [],
}), {
  subjectId: null,
  subjectCode: '',
  subjectName: '未分类',
  aggregate: false,
  selectedSubject: null,
})

console.log('Pomodoro session restore passed: pause math/countdown/free/subject projection')
