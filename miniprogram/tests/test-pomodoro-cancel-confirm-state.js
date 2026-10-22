const assert = require('node:assert/strict')
const {
  buildCancelEndConfirmPlan,
} = require('../pages/pomodoro/utils/cancel-confirm-state')

const closed = {
  showEndConfirm: false,
  ringCanvasVisible: true,
  endConfirmTheme: '',
  endConfirmTitle: '',
  endConfirmText: '',
  endConfirmLine1: '',
  endConfirmLine2: '',
  endConfirmLine3: '',
}

const countdownPaused = buildCancelEndConfirmPlan({
  mode: 'countdown-interrupt',
  snapshot: {
    sessionId: 1,
    remainingSec: 75,
    progress: 0.5,
    totalPausedMs: 300,
    pauseStartTime: 40,
    totalSec: 150,
    phase: 'running',
    wasPaused: true,
  },
  now: 100,
  isPaused: true,
})
assert.equal(countdownPaused.kind, 'countdown-paused')
assert.deepEqual(countdownPaused.timer, {
  remainingSec: 75,
  progress: 0.5,
  pauseStartTime: 40,
  totalPausedMs: 300,
  endConfirmMode: '',
})
assert.deepEqual(countdownPaused.view, {
  ...closed,
  displayMin: '01',
  displaySec: '15',
  isPaused: true,
})
assert.deepEqual(countdownPaused.redraw, { totalSec: 150, phase: 'running' })
assert.equal(countdownPaused.removeConfirmStorage, true)
assert.equal(countdownPaused.clearSnapshot, true)

const countdownResume = buildCancelEndConfirmPlan({
  mode: 'countdown-interrupt',
  snapshot: {
    sessionId: 2,
    remainingSec: 90,
    remainingMs: 90000,
    progress: 0.6,
    totalPausedMs: 20,
    openedAt: 40,
    totalSec: 150,
    phase: 'break',
    wasPaused: false,
  },
  now: 100,
  isPaused: true,
})
assert.equal(countdownResume.kind, 'countdown-resume')
assert.equal(countdownResume.timer.totalPausedMs, 80)
assert.equal(countdownResume.timer.pauseStartTime, null)
assert.deepEqual(countdownResume.view, {
  ...closed,
  displayMin: '01',
  displaySec: '30',
  isPaused: false,
  actionLoading: false,
})
assert.deepEqual(countdownResume.adjustment, {
  sessionId: 2,
  totalPausedMs: 80,
  savedAt: 100,
  source: 'cancel_end_confirm',
})
assert.deepEqual(countdownResume.startTimer, { totalSec: 150, remainingMs: 90000 })
assert.equal(countdownResume.pendingResume, true)
assert.equal(countdownResume.retryPending, true)

for (const snapshot of [null, { sessionId: 3, mode: 'countdown-interrupt' }]) {
  const freeInvalid = buildCancelEndConfirmPlan({
    mode: 'free-complete',
    snapshot,
    now: 100,
    isPaused: true,
  })
  assert.equal(freeInvalid.kind, 'free-invalid')
  assert.deepEqual(freeInvalid.timer, { endConfirmMode: '' })
  assert.deepEqual(freeInvalid.view, closed)
  assert.equal(freeInvalid.startFreeTimer, false)
  assert.equal(freeInvalid.redrawFree, true)
  assert.equal(freeInvalid.clearSnapshot, false)
}

const freeInvalidRunning = buildCancelEndConfirmPlan({
  mode: 'free-complete',
  snapshot: { sessionId: 3, mode: 'countdown-interrupt' },
  now: 100,
  isPaused: false,
})
assert.equal(freeInvalidRunning.startFreeTimer, true)

const freePaused = buildCancelEndConfirmPlan({
  mode: 'free-complete',
  snapshot: {
    mode: 'free-complete',
    sessionId: 4,
    elapsedSec: 65,
    totalPausedMs: 300,
    pauseStartTime: 50,
    wasPaused: true,
  },
  now: 100,
  isPaused: true,
})
assert.equal(freePaused.kind, 'free-paused')
assert.deepEqual(freePaused.timer, {
  pauseStartTime: 50,
  totalPausedMs: 300,
  elapsedSec: 65,
  freeFriendlyText: '1分05秒',
  endConfirmMode: '',
  freeDisplayOffsetMs: 0,
})
assert.deepEqual(freePaused.view, {
  ...closed,
  isPaused: true,
  freeDisplayTime: '00:01:05',
})
assert.equal(freePaused.redrawFree, true)
assert.equal(freePaused.removeConfirmStorage, true)
assert.equal(freePaused.clearSnapshot, true)

const freeResume = buildCancelEndConfirmPlan({
  mode: 'free-complete',
  snapshot: {
    mode: 'free-complete',
    sessionId: 5,
    elapsedSec: null,
    totalPausedMs: 20,
    openedAt: 40,
    wasPaused: false,
  },
  now: 100,
  freeNow: 120,
  isPaused: true,
})
assert.equal(freeResume.kind, 'free-resume')
assert.equal(freeResume.timer.totalPausedMs, 100)
assert.equal(freeResume.timer.elapsedSec, 0)
assert.equal(freeResume.timer.freeFriendlyText, '')
assert.deepEqual(freeResume.view, {
  ...closed,
  isPaused: false,
  freeDisplayTime: '00:00:00',
})
assert.deepEqual(freeResume.adjustment, {
  sessionId: 5,
  totalPausedMs: 100,
  savedAt: 120,
  source: 'cancel_free_end_confirm',
})
assert.equal(freeResume.pendingResume, true)
assert.equal(freeResume.restartFreeTimer, true)
assert.equal(freeResume.retryPending, true)

const fallback = buildCancelEndConfirmPlan({
  mode: 'unknown',
  snapshot: null,
  now: 100,
  isPaused: true,
})
assert.deepEqual(fallback, {
  kind: 'fallback',
  timer: { endConfirmMode: '' },
  view: closed,
  clearSnapshot: true,
})

const frozen = Object.freeze({
  mode: 'free-complete',
  snapshot: Object.freeze({
    mode: 'free-complete', sessionId: 6, elapsedSec: 10, totalPausedMs: null,
    openedAt: 90, wasPaused: false,
  }),
  now: 100,
  isPaused: true,
})
assert.doesNotThrow(() => buildCancelEndConfirmPlan(frozen))

console.log('Pomodoro cancel confirm state passed: paused/resume/free/fallback')
