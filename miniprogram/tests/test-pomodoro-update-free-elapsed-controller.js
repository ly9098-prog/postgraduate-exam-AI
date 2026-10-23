/**
 * Independent regression for the update-free-elapsed controller.
 * Run: node --test miniprogram/tests/test-pomodoro-update-free-elapsed-controller.js
 */
const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createUpdateFreeElapsedController } = require('../pages/pomodoro/utils/update-free-elapsed-controller')

function makeHarness(overrides = {}) {
  const calls = []
  let elapsedSec = overrides.elapsedSec ?? 120
  let freeFriendlyText = overrides.freeFriendlyText ?? null
  const data = { isFreeTimer: overrides.isFreeTimer ?? true, showEndConfirm: false, isPaused: overrides.isPaused ?? false }
  const options = {
    isFreeTimer: () => data.isFreeTimer,
    showEndConfirm: () => data.showEndConfirm,
    isPaused: () => data.isPaused,
    getElapsedSec: () => elapsedSec,
    setData: d => { calls.push(['setData', d]) },
    setFreeFriendlyText: v => { freeFriendlyText = v },
    getEffectiveFreeElapsedMs: () => overrides.effectiveMs ?? 130000,
    maxMs: () => overrides.maxMs ?? 18000000,
    setElapsedSec: v => { elapsedSec = v; calls.push(['setElapsedSec', v]) },
  }
  return { options, calls, get elapsedSec() { return elapsedSec }, get freeFriendlyText() { return freeFriendlyText } }
}

test('update returns early when not free timer', () => {
  const h = makeHarness({ isFreeTimer: false })
  createUpdateFreeElapsedController(h.options).update()
  assert.equal(h.calls.length, 0)
})

test('update shows paused elapsed without recomputing', () => {
  const h = makeHarness({ isPaused: true, elapsedSec: 60 })
  createUpdateFreeElapsedController(h.options).update()
  assert.ok(h.calls.some(c => c[0] === 'setData'))
})

test('update computes and sets new elapsed when changed', () => {
  const h = makeHarness({ elapsedSec: 120, effectiveMs: 130000 })
  createUpdateFreeElapsedController(h.options).update()
  // 130000ms / 1000 = 130 seconds, !== 120 so should update
  assert.equal(h.elapsedSec, 130)
  assert.ok(h.calls.some(c => c[0] === 'setData'))
})

test('update skips when elapsed unchanged', () => {
  const h = makeHarness({ elapsedSec: 130, effectiveMs: 130000 })
  createUpdateFreeElapsedController(h.options).update()
  assert.ok(!h.calls.some(c => c[0] === 'setData'))
})
