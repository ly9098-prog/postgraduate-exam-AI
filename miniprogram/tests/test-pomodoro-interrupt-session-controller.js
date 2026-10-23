const assert = require('node:assert/strict')
const { test } = require('node:test')
const { createInterruptSessionController } = require('../pages/pomodoro/utils/interrupt-session-controller')

function makeHarness(overrides = {}) {
  const calls = []
  const options = {
    getSessionId: () => overrides.sessionId ?? 's1',
    isFreeTimer: () => overrides.isFreeTimer ?? false,
    showEndFreeConfirm: () => { calls.push(['showEndFreeConfirm']) },
    showCountdownInterruptConfirm: () => { calls.push(['showCountdownInterruptConfirm']) },
  }
  return { options, calls }
}

test('interrupt returns early when no session', () => {
  const h = makeHarness()
  h.options.getSessionId = () => null
  createInterruptSessionController(h.options).interrupt()
  assert.equal(h.calls.length, 0)
})

test('interrupt dispatches to free confirm when free timer', () => {
  const h = makeHarness({ isFreeTimer: true })
  createInterruptSessionController(h.options).interrupt()
  assert.ok(h.calls.some(c => c[0] === 'showEndFreeConfirm'))
})

test('interrupt dispatches to countdown confirm when countdown timer', () => {
  const h = makeHarness({ isFreeTimer: false })
  createInterruptSessionController(h.options).interrupt()
  assert.ok(h.calls.some(c => c[0] === 'showCountdownInterruptConfirm'))
})
