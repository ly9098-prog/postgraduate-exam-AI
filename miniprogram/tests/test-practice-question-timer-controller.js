const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createQuestionTimerController,
} = require('../subpackages/study/practice/utils/question-timer-controller')

function createHarness(overrides = {}) {
  const state = {
    currentIndex: 0,
    questions: [{ id: 1 }, { id: 2 }],
    startedMonoMs: 1000,
    timeMap: {},
    now: 5000,
  }
  const controller = createQuestionTimerController({
    getCurrentIndex: () => state.currentIndex,
    getQuestions: () => state.questions,
    getCurrentQuestionStartedMonoMs: () => state.startedMonoMs,
    getQuestionTimeMap: () => state.timeMap,
    setQuestionTimeMap: map => { state.timeMap = map },
    setCurrentQuestionStartedMonoMs: ms => { state.startedMonoMs = ms },
    monotonicNow: () => state.now,
    ...overrides,
  })
  return { controller, state }
}

test('settle accumulates elapsed time for current question', () => {
  const { controller, state } = createHarness()
  controller.settle(false)

  assert.equal(state.timeMap[1], 4)
  assert.equal(state.startedMonoMs, 5000)
})

test('settle with pause resets started mono to 0', () => {
  const { controller, state } = createHarness()
  controller.settle(true)

  assert.equal(state.timeMap[1], 4)
  assert.equal(state.startedMonoMs, 0)
})

test('settle is a no-op when no started time', () => {
  const { controller, state } = createHarness()
  state.startedMonoMs = 0
  controller.settle(false)

  assert.deepEqual(state.timeMap, {})
})

test('settle is a no-op with no questions', () => {
  const { controller, state } = createHarness()
  state.questions = []
  controller.settle(false)

  assert.deepEqual(state.timeMap, {})
})

test('settle is a no-op for invalid index', () => {
  const { controller, state } = createHarness()
  state.currentIndex = 99
  controller.settle(false)

  assert.deepEqual(state.timeMap, {})
})

test('settle accumulates across multiple calls', () => {
  const { controller, state } = createHarness()
  controller.settle(false)
  state.now = 9000
  controller.settle(false)

  assert.equal(state.timeMap[1], 8)
})
