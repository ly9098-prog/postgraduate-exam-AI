const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  CONFIRM_SNAPSHOT_MAX_AGE_MS,
  isValidConfirmSnapshot,
  buildFreeConfirmSnapshot,
  buildCountdownInterruptSnapshot,
} = require('../pages/pomodoro/utils/end-confirm-snapshot')

test('isValidConfirmSnapshot rejects missing identity and hidden/stale snapshots', () => {
  const now = 100000
  assert.equal(isValidConfirmSnapshot(null, now), false)
  assert.equal(isValidConfirmSnapshot({ mode: 'free-complete', openedAt: 1 }, now), false)
  assert.equal(isValidConfirmSnapshot({ sessionId: 7, openedAt: 1 }, now), false)
  assert.equal(
    isValidConfirmSnapshot({ sessionId: 7, mode: 'free-complete', openedAt: 0 }, now),
    false
  )
  assert.equal(
    isValidConfirmSnapshot(
      { sessionId: 7, mode: 'free-complete', openedAt: 1, confirmVisible: false },
      now
    ),
    false
  )
  assert.equal(
    isValidConfirmSnapshot(
      { sessionId: 7, mode: 'free-complete', openedAt: now - CONFIRM_SNAPSHOT_MAX_AGE_MS - 1 },
      now
    ),
    false
  )
  assert.equal(
    isValidConfirmSnapshot(
      { sessionId: 7, mode: 'free-complete', openedAt: now - 1 },
      now
    ),
    true
  )
})

test('buildFreeConfirmSnapshot assembles the durable free-complete shape', () => {
  const snapshot = buildFreeConfirmSnapshot({
    confirmActionSeq: 3,
    sessionId: 42,
    openedAt: 2000,
    wasPaused: false,
    elapsedSec: 90,
    totalPausedMs: 5000,
    pauseStartTime: 1111,
    sessionStartTime: 900,
  })

  assert.deepEqual(snapshot, {
    mode: 'free-complete',
    confirmActionSeq: 3,
    sessionId: 42,
    openedAt: 2000,
    wasPaused: false,
    pausedByConfirm: true,
    elapsedSec: 90,
    totalPausedMs: 5000,
    pauseStartTime: 1111,
    sessionStartTime: 900,
    backendPauseDone: false,
    confirmVisible: true,
    freeDisplayOffsetMs: 0,
  })
  assert.equal(isValidConfirmSnapshot(snapshot, 2000), true)
})

test('buildFreeConfirmSnapshot keeps pausedByConfirm false when already paused', () => {
  const snapshot = buildFreeConfirmSnapshot({
    confirmActionSeq: 1,
    sessionId: 9,
    openedAt: 10,
    wasPaused: true,
    elapsedSec: 0,
    totalPausedMs: 0,
    pauseStartTime: null,
    sessionStartTime: 5,
  })

  assert.equal(snapshot.pausedByConfirm, false)
  assert.equal(snapshot.wasPaused, true)
  assert.equal(snapshot.pauseStartTime, null)
})

test('buildCountdownInterruptSnapshot assembles the countdown-interrupt shape', () => {
  const snapshot = buildCountdownInterruptSnapshot({
    confirmActionSeq: 5,
    sessionId: 77,
    openedAt: 3000,
    wasPaused: false,
    phase: 'running',
    totalSec: 1500,
    totalMs: 1500000,
    remainingMs: 600000,
    remainingSec: 600,
    progress: 0.4,
    sessionStartTime: 1000,
    countdownEndAt: 1600000,
    totalPausedMs: 0,
    pauseStartTime: null,
  })

  assert.deepEqual(snapshot, {
    mode: 'countdown-interrupt',
    confirmActionSeq: 5,
    sessionId: 77,
    openedAt: 3000,
    wasPaused: false,
    pausedByConfirm: true,
    phase: 'running',
    totalSec: 1500,
    totalMs: 1500000,
    remainingMs: 600000,
    remainingSec: 600,
    progress: 0.4,
    sessionStartTime: 1000,
    countdownEndAt: 1600000,
    totalPausedMs: 0,
    pauseStartTime: null,
    backendPauseDone: false,
    confirmVisible: true,
  })
  assert.equal(isValidConfirmSnapshot(snapshot, 3000), true)
})
