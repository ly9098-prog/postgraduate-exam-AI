const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamSubmitPreparationController,
} = require('../subpackages/exam/utils/exam-submit-preparation-controller')

function harness(overrides = {}) {
  const state = {
    remaining: 30,
    timeExpired: false,
    retained: false,
    persisted: 0,
    submitting: false,
    timerCleared: 0,
    settled: [],
    finalAnswers: [{ item_id: 101 }],
    resolvedAuto: null,
  }
  const options = {
    getCurrentRemainingSec: () => state.remaining,
    isTimeExpired: () => state.timeExpired,
    setRetainPendingForSubmit: value => { state.retained = value },
    persistPending: () => { state.persisted += 1 },
    setSubmitting: value => { state.submitting = value },
    clearTimer: () => { state.timerCleared += 1 },
    settleCurrentTime: async options => { state.settled.push(options) },
    buildFinalSubmitAnswers: () => state.finalAnswers,
    onAutoResolved: value => { state.resolvedAuto = value },
    ...overrides,
  }
  return { options, state, get controller() { return createExamSubmitPreparationController(options) } }
}

test('manual submission keeps normal draft retention', async () => {
  const h = harness()
  const result = await h.controller.prepare(false)

  assert.deepEqual(result, { auto: false, finalAnswers: [{ item_id: 101 }] })
  assert.equal(h.state.retained, false)
  assert.equal(h.state.persisted, 0)
  assert.equal(h.state.submitting, true)
  assert.equal(h.state.timerCleared, 1)
  assert.deepEqual(h.state.settled, [{ sync: false }])
  assert.equal(h.state.resolvedAuto, false)
})

test('requested auto submission persists submit-pending state', async () => {
  const h = harness()
  const result = await h.controller.prepare(true)

  assert.equal(result.auto, true)
  assert.equal(h.state.retained, true)
  assert.equal(h.state.persisted, 1)
  assert.equal(h.state.submitting, true)
  assert.equal(h.state.resolvedAuto, true)
})

test('expired page state forces auto submission', async () => {
  const h = harness()
  h.state.timeExpired = true
  const result = await h.controller.prepare(false)

  assert.equal(result.auto, true)
  assert.equal(h.state.retained, true)
  assert.equal(h.state.persisted, 1)
})

test('zero remaining time forces auto submission', async () => {
  const h = harness()
  h.state.remaining = 0
  const result = await h.controller.prepare(false)

  assert.equal(result.auto, true)
  assert.equal(h.state.retained, true)
})

test('settle failures prevent payload construction and propagate', async () => {
  const failure = new Error('settle failed')
  const h = harness({
    settleCurrentTime: async options => { h.state.settled.push(options); throw failure },
  })
  await assert.rejects(() => h.controller.prepare(false), failure)
  assert.equal(h.state.submitting, true)
  assert.equal(h.state.timerCleared, 1)
  assert.deepEqual(h.state.settled, [{ sync: false }])
  assert.equal(h.state.resolvedAuto, null)
})
