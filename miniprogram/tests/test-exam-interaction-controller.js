const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamInteractionController,
} = require('../subpackages/exam/utils/exam-interaction-controller')

function createHarness(overrides = {}) {
  const state = {
    expired: false,
    submitting: false,
    navigationLocked: false,
    itemId: '101',
    answers: {},
    renderViews: { 101: { id: 'render' } },
    queued: [],
    flags: [],
    views: [],
    counts: 0,
    syncs: [],
  }
  const controller = createExamInteractionController({
    isTimeExpired: () => state.expired,
    isSubmitting: () => state.submitting,
    isNavigationLocked: () => state.navigationLocked,
    getCurrentItemId: () => state.itemId,
    getAnswer: itemId => state.answers[itemId],
    setAnswer: (itemId, answer) => { state.answers[itemId] = answer },
    queueItem: itemId => state.queued.push(itemId),
    updateQuestionFlags: itemId => state.flags.push(itemId),
    getRenderView: itemId => state.renderViews[itemId],
    buildAnswerState: (renderView, answer) => ({ renderView, answer }),
    setData: patch => state.views.push(patch),
    setCountsOnly: () => { state.counts += 1 },
    syncItem: itemId => {
      state.syncs.push(itemId)
      return Promise.resolve()
    },
    ...overrides,
  })
  return { controller, state }
}

test('selectOption normalizes and queues an answer', () => {
  const { controller, state } = createHarness()

  controller.selectOption({ detail: { option: ' a ' } })

  assert.deepEqual(state.answers[101], { used_time: 0, selected_answer: 'A' })
  assert.deepEqual(state.queued, ['101'])
  assert.deepEqual(state.flags, ['101'])
  assert.deepEqual(state.views, [{
    currentAnswerState: { renderView: { id: 'render' }, answer: 'A' },
  }])
  assert.equal(state.counts, 1)
  assert.deepEqual(state.syncs, ['101'])
})

test('selectOption clears an empty option and preserves used time', () => {
  const { controller, state } = createHarness()
  state.answers[101] = { used_time: 12, selected_answer: 'A' }

  controller.selectOption({ detail: { option: '' } })

  assert.deepEqual(state.answers[101], { used_time: 12, selected_answer: null })
  assert.deepEqual(state.queued, ['101'])
  assert.deepEqual(state.flags, ['101'])
  assert.deepEqual(state.views, [{
    currentAnswerState: { renderView: { id: 'render' }, answer: null },
  }])
  assert.equal(state.counts, 1)
  assert.deepEqual(state.syncs, ['101'])
})

test('selectOption is blocked while expired, submitting, or navigation locked', () => {
  for (const update of [
    state => { state.expired = true },
    state => { state.submitting = true },
    state => { state.navigationLocked = true },
  ]) {
    const { controller, state } = createHarness()
    update(state)
    controller.selectOption({ detail: { option: 'A' } })
    assert.deepEqual(state.answers, {})
    assert.deepEqual(state.syncs, [])
  }
})

test('selectOption stops without a current item', () => {
  const { controller, state } = createHarness()
  state.itemId = ''

  controller.selectOption({ detail: { option: 'A' } })

  assert.deepEqual(state.queued, [])
  assert.deepEqual(state.views, [])
})

test('toggleMark toggles the current mark and syncs it', () => {
  const { controller, state } = createHarness()

  controller.toggleMark()
  assert.deepEqual(state.answers[101], { used_time: 0, marked_for_review: true })
  assert.deepEqual(state.views, [{ markedForReview: true }])
  assert.deepEqual(state.syncs, ['101'])

  controller.toggleMark()
  assert.equal(state.answers[101].marked_for_review, false)
  assert.deepEqual(state.views[1], { markedForReview: false })
})

test('toggleMark is blocked by the same editing guards', () => {
  for (const update of [
    state => { state.expired = true },
    state => { state.submitting = true },
    state => { state.navigationLocked = true },
  ]) {
    const { controller, state } = createHarness()
    update(state)
    controller.toggleMark()
    assert.deepEqual(state.answers, {})
    assert.deepEqual(state.queued, [])
    assert.deepEqual(state.views, [])
    assert.deepEqual(state.syncs, [])
  }
})
