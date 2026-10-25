const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamQuestionTimeController,
} = require('../subpackages/exam/utils/exam-question-time-controller')

function createHarness(overrides = {}) {
  const state = {
    itemId: '101',
    questionEnterAt: 1000000,
    now: 1260000,
    answers: { 101: { used_time: 10 } },
    queued: [],
    syncs: [],
  }
  const controller = createExamQuestionTimeController({
    getCurrentItemId: () => state.itemId,
    getQuestionEnterAt: () => state.questionEnterAt,
    setQuestionEnterAt: value => { state.questionEnterAt = value },
    now: () => state.now,
    getAnswer: itemId => state.answers[itemId],
    setAnswer: (itemId, answer) => { state.answers[itemId] = answer },
    queueItem: itemId => state.queued.push(itemId),
    syncItem: itemId => {
      state.syncs.push(itemId)
      if (state.syncThrows) return Promise.reject(new Error('sync failed'))
      return Promise.resolve()
    },
    ...overrides,
  })
  return { controller, state }
}

test('settles elapsed time, queues it, and syncs by default', async () => {
  const { controller, state } = createHarness()

  await controller.settle()

  assert.deepEqual(state.answers[101], { used_time: 270 })
  assert.equal(state.questionEnterAt, 1260000)
  assert.deepEqual(state.queued, ['101'])
  assert.deepEqual(state.syncs, ['101'])
})

test('settles without syncing when sync is false', async () => {
  const { controller, state } = createHarness()

  await controller.settle({ sync: false })

  assert.deepEqual(state.answers[101], { used_time: 270 })
  assert.deepEqual(state.queued, ['101'])
  assert.deepEqual(state.syncs, [])
})

test('stops without mutation when the item or entry time is missing', async () => {
  const missingItem = createHarness()
  missingItem.state.itemId = ''
  await missingItem.controller.settle()
  assert.deepEqual(missingItem.state.answers, { 101: { used_time: 10 } })
  assert.deepEqual(missingItem.state.queued, [])

  const missingTime = createHarness()
  missingTime.state.questionEnterAt = 0
  await missingTime.controller.settle()
  assert.deepEqual(missingTime.state.answers, { 101: { used_time: 10 } })
  assert.deepEqual(missingTime.state.queued, [])
})

test('ignores zero elapsed time but still advances the entry timestamp', async () => {
  const { controller, state } = createHarness()
  state.now = 1000000

  await controller.settle()

  assert.deepEqual(state.answers[101], { used_time: 10 })
  assert.equal(state.questionEnterAt, 1000000)
  assert.deepEqual(state.queued, [])
  assert.deepEqual(state.syncs, [])
})

test('creates a default answer and caps used time at six hours', async () => {
  const { controller, state } = createHarness()
  state.answers = {}
  state.now = 1000000 + 8 * 60 * 60 * 1000

  await controller.settle({ sync: false })

  assert.deepEqual(state.answers[101], { used_time: 6 * 60 * 60 })
})

test('swallows sync failures and still resolves', async () => {
  const { controller, state } = createHarness()
  state.syncThrows = true

  await controller.settle()

  assert.deepEqual(state.answers[101], { used_time: 270 })
  assert.deepEqual(state.syncs, ['101'])
})
