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
  const options = {
    getComboCount: () => state.comboCount,
    setComboCount: count => { state.comboCount = count },
    setData: patch => { state.patches.push(patch) },
    clearFeedbackTimer: () => { state.timerCleared = true },
    setFeedbackTimer: (cb, ms) => { state.timerSet = true; state.timerMs = ms; state.timerCb = cb },
    ...overrides,
  }
  const controller = createAnswerFeedbackController(options)
  return { controller, state, options }
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

const correctFeedbackCases = [
  [0, '回答正确', '这题很稳，保持当前节奏', '', '', 0],
  [1, '回答正确', '这题很稳，保持当前节奏', '', '', 0],
  [2, '三连对', '手感正热，保持这个状态', '3 连对', 'warm', 3],
  [3, '三连对', '手感正热，保持这个状态', '4 连对', 'warm', 3],
  [4, '五连斩', '进入心流状态，继续推进', '⚡ 5 连对', 'hot', 5],
  [8, '五连斩', '进入心流状态，继续推进', '⚡ 9 连对', 'hot', 5],
  [9, '学霸连击', '状态火热，无人能挡', '🔥 10 连对', 'fire', 6],
  [10, '学霸连击', '状态火热，无人能挡', '🔥 11 连对', 'fire', 6],
]

for (const [combo, title, detail, text, level, stars] of correctFeedbackCases) {
  test(`preserves the complete feedback and timeout at combo ${combo + 1}`, () => {
    const { controller, state } = createHarness()
    state.comboCount = combo
    controller.show({ question_type: 'single_choice', correct_answer: 'A' }, 'A')
    assert.equal(state.comboCount, combo + 1)
    assert.deepEqual(state.patches, [{
      feedbackVisible: true,
      feedbackType: 'correct',
      feedbackTitle: title,
      feedbackDetail: detail,
      feedbackComboText: text,
      feedbackComboLevel: level,
      feedbackStarCount: stars,
    }])
    assert.equal(state.timerMs, text ? 2000 : 1200)
  })
}

test('feedback writes and timer expiry keep the original port order and receiver', () => {
  const h = createHarness()
  const calls = []
  for (const name of Object.keys(h.options)) {
    const original = h.options[name]
    h.options[name] = function (...args) {
      assert.equal(this, h.options)
      calls.push(name)
      return original(...args)
    }
  }
  h.controller.show({ question_type: 'single_choice', correct_answer: 'A' }, 'B')
  assert.deepEqual(calls, [
    'getComboCount', 'clearFeedbackTimer', 'setComboCount', 'setData', 'setFeedbackTimer',
  ])
  assert.deepEqual(h.state.patches[0], {
    feedbackVisible: true, feedbackType: 'wrong', feedbackTitle: '继续加油',
    feedbackDetail: '先记录选择，交卷后集中复盘',
    feedbackComboText: '', feedbackComboLevel: '', feedbackStarCount: 0,
  })
  assert.equal(h.state.timerMs, 1200)
  h.state.timerCb()
  assert.deepEqual(calls.slice(-2), ['setData', 'clearFeedbackTimer'])
  assert.deepEqual(h.state.patches[1], { feedbackVisible: false })
})

test('empty and indeterminate answers leave existing feedback timers alone', () => {
  for (const [correct, answer, expectedPatches] of [
    ['A', '', [{ feedbackVisible: false }]],
    [null, 'A', []],
  ]) {
    const { controller, state } = createHarness()
    state.comboCount = 4
    controller.show({ question_type: 'single_choice', correct_answer: correct }, answer)
    assert.equal(state.comboCount, 4)
    assert.deepEqual(state.patches, expectedPatches)
    assert.equal(state.timerSet, false)
    assert.equal(state.timerCleared, false)
  }
})
