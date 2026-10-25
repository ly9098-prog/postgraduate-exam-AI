const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamQuestionNavigationController,
} = require('../subpackages/exam/utils/exam-question-navigation-controller')

function createHarness(overrides = {}) {
  const state = {
    expired: false,
    submitting: false,
    navigationLocked: false,
    questions: [
      { _itemId: 101, _answered: true },
      { _itemId: 102, _answered: false },
      { _itemId: 103, _answered: true },
    ],
    answers: {
      101: { selected_answer: 'A', marked_for_review: true },
      102: {},
      103: { selected_answer: 'C' },
    },
    renderViews: {
      101: { id: 'rv101' },
      102: { id: 'rv102' },
      103: { id: 'rv103' },
    },
    now: 123456,
    questionEnterAt: 0,
    currentItemId: '102',
    views: [],
    settles: [],
    syncs: [],
  }
  const controller = createExamQuestionNavigationController({
    getQuestions: () => state.questions,
    getAnswer: itemId => state.answers[itemId],
    getRenderView: itemId => state.renderViews[itemId],
    setQuestionEnterAt: value => { state.questionEnterAt = value },
    now: () => state.now,
    setData: patch => state.views.push(patch),
    buildAnswerState: (renderView, answer) => ({ renderView, answer }),
    isTimeExpired: () => state.expired,
    isSubmitting: () => state.submitting,
    isNavigationLocked: () => state.navigationLocked,
    getCurrentItemId: () => state.currentItemId,
    settleCurrentTime: options => {
      state.settles.push(options)
      return Promise.resolve()
    },
    syncItem: itemId => {
      state.syncs.push(itemId)
      return Promise.resolve()
    },
    ...overrides,
  })
  return { controller, state }
}

test('setCurrent clamps the index and commits the full current-question view', () => {
  const { controller, state } = createHarness()

  controller.setCurrent(99)

  assert.deepEqual(state.views, [{
    currentIndex: 2,
    currentQuestion: state.questions[2],
    currentAnswerState: { renderView: { id: 'rv103' }, answer: 'C' },
    markedForReview: false,
    answeredCount: 2,
    progressPercent: 67,
  }])
  assert.equal(state.questionEnterAt, 123456)
})

test('setCurrent handles invalid indexes and empty question lists', () => {
  const invalid = createHarness()
  invalid.controller.setCurrent(-5)
  assert.equal(invalid.state.views[0].currentIndex, 0)

  const empty = createHarness({ getQuestions: () => [] })
  empty.controller.setCurrent(1)
  assert.deepEqual(empty.state.views, [])
})

test('moveTo settles the previous item, syncs it, then changes the current item', async () => {
  const { controller, state } = createHarness({
    getCurrentItemId: () => '102',
  })
  const order = []
  state.settleOverride = value => {
    state.settles.push(value)
    order.push('settle')
    return Promise.resolve()
  }
  state.syncOverride = itemId => {
    state.syncs.push(itemId)
    order.push(`sync:${itemId}`)
    return Promise.resolve()
  }

  const orderedController = createExamQuestionNavigationController({
    getQuestions: () => state.questions,
    getAnswer: itemId => state.answers[itemId],
    getRenderView: itemId => state.renderViews[itemId],
    setQuestionEnterAt: value => { state.questionEnterAt = value },
    now: () => state.now,
    setData: patch => state.views.push(patch),
    buildAnswerState: (renderView, answer) => ({ renderView, answer }),
    isTimeExpired: () => false,
    isSubmitting: () => false,
    isNavigationLocked: () => false,
    getCurrentItemId: () => '102',
    settleCurrentTime: state.settleOverride,
    syncItem: state.syncOverride,
  })

  await orderedController.moveTo(2)

  assert.deepEqual(order, ['settle', 'sync:102'])
  assert.deepEqual(state.settles, [{ sync: false }])
  assert.equal(state.views[0].currentIndex, 2)
})

test('moveTo is blocked while expired, submitting, or navigation locked', () => {
  for (const update of [
    state => { state.expired = true },
    state => { state.submitting = true },
    state => { state.navigationLocked = true },
  ]) {
    const { controller, state } = createHarness()
    update(state)
    controller.moveTo(2)
    assert.deepEqual(state.settles, [])
    assert.deepEqual(state.syncs, [])
    assert.deepEqual(state.views, [])
  }
})

test('moveTo skips the previous sync when there is no current item', () => {
  const { controller, state } = createHarness()
  state.currentItemId = ''

  controller.moveTo(2)

  assert.deepEqual(state.settles, [{ sync: false }])
  assert.deepEqual(state.syncs, [])
  assert.equal(state.views[0].currentIndex, 2)
})
