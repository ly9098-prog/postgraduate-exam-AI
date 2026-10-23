const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createShowCountdownInterruptConfirmController } = require('../pages/pomodoro/utils/show-countdown-interrupt-confirm-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let snapshot = overrides.snapshot ?? { totalSec: 300, phase: 'running' }
  const options = {
    isActionLoading: () => overrides.actionLoading ?? false,
    pauseCountdown: () => { calls.push(['pauseCountdown']); return Promise.resolve(overrides.pauseResult ?? true) },
    getConfirmTimerSnapshot: () => snapshot,
    setData: d => { calls.push(['setData']) },
    nextTick: cb => { calls.push(['nextTick']); cb() },
    initCanvas: f => { calls.push(['initCanvas']) },
    drawRing: (t, b) => { calls.push(['drawRing']) },
  }
  return { options, calls }
}

test('show returns early when actionLoading', () => {
  const h = makeHarness({ actionLoading: true })
  createShowCountdownInterruptConfirmController(h.options).show()
  assert.equal(h.calls.length, 0)
})

test('show sets view and redraws when pause succeeds', async () => {
  const h = makeHarness()
  createShowCountdownInterruptConfirmController(h.options).show()
  await new Promise(r => setTimeout(r, 50))
  assert.ok(h.calls.some(c => c[0] === 'setData'))
  assert.ok(h.calls.some(c => c[0] === 'drawRing'))
})

test('show skips when pause fails', async () => {
  const h = makeHarness({ pauseResult: false })
  createShowCountdownInterruptConfirmController(h.options).show()
  await new Promise(r => setTimeout(r, 50))
  assert.ok(!h.calls.some(c => c[0] === 'setData'))
})
