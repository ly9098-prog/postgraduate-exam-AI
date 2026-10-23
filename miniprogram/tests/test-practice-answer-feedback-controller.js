const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createAnswerFeedbackController,
} = require('../subpackages/study/practice/utils/answer-feedback-controller')

function createHarness(overrides = {}) {
  const state = {
    comboCount: 0,
    patches: [],
    timerSet: false,
    timerCleared: false,
  }
  const controller = createAnswerFeedbackController({
    getComboCount: () => state.comboCount,
    setComboCount: count => { state.comboCount = count },
    setData: patch => { state.patches.push(patch) },
    clearFeedbackTimer: () => { state.timerCleared = true },
    setFeedbackTimer: (cb, ms) => { state.timerSet = true; state.timerMs = ms; state.timerCb = cb },
    ...overrides,
  })
  return { controller, state }
}

test('shows correct feedback with combo for 3+ streak', () => {
  const { controller, state } = createHarness()
  state.comboCount = 2
  // Use a question that isAnswerCorrect returns true for answer 'A'
  controller.show({ id: 1, question_type: 'single_choice', correct_answer: 'A' }, 'A')

  assert.equal(state.comboCount, 3)
  const patch = state.patches.find(p => p.feedbackVisible === true)
  assert.ok(patch)
  assert.equal(patch.feedbackTitle, '三连对')
  assert.equal(patch.feedbackComboLevel, 'warm')
})

test('shows fire feedback for 10+ streak', () => {
  const { controller, state } = createHarness()
  state.comboCount = 9
  controller.show({ id: 1, question_type: 'single_choice', correct_answer: 'A' }, 'A')

  const patch = state.patches.find(p => p.feedbackVisible === true)
  assert.ok(patch)
  assert.equal(patch.feedbackTitle, '学霸连击')
  assert.equal(patch.feedbackComboLevel, 'fire')
  assert.equal(state.timerMs, 2000)
})

test('shows wrong feedback and resets combo', () => {
  const { controller, state } = createHarness()
  state.comboCount = 5
  controller.show({ id: 1, question_type: 'single_choice', correct_answer: 'A' }, 'B')

  assert.equal(state.comboCount, 0)
  const patch = state.patches.find(p => p.feedbackVisible === true)
  assert.ok(patch)
  assert.equal(patch.feedbackType, 'wrong')
  assert.equal(patch.feedbackTitle, '继续加油')
})

test('hides feedback when no answer', () => {
  const { controller, state } = createHarness()
  state.comboCount = 3
  controller.show({ id: 1, question_type: 'single_choice', correct_answer: 'A' }, '')

  assert.equal(state.comboCount, 3)
  const patch = state.patches[state.patches.length - 1]
  assert.equal(patch.feedbackVisible, false)
})

test('does not show feedback for indeterminate correctness', () => {
  const { controller, state } = createHarness()
  state.comboCount = 2
  // null answer with hasAnswer=true but isCorrect indeterminate
  controller.show({ id: 1, question_type: 'single_choice', correct_answer: null }, 'A')

  // Should not show visible feedback
  const visiblePatch = state.patches.find(p => p.feedbackVisible === true)
  assert.equal(visiblePatch, undefined)
})
