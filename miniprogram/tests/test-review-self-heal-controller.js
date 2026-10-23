const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createReviewSelfHealController,
} = require('../subpackages/study/review-today/utils/self-heal-controller')

function createHarness(overrides = {}) {
  const state = {
    safeMode: false,
    currentIndex: 0,
    currentQuestion: { id: 1 },
    groupQuestions: [{ id: 1, question_type: 'single_choice' }],
    patches: [],
    questionShown: false,
    enriched: null,
  }
  const controller = createReviewSelfHealController({
    setSafeModeActive: v => { state.safeMode = v },
    getCurrentQuestion: () => state.currentQuestion,
    getCurrentIndex: () => state.currentIndex,
    getGroupQuestions: () => state.groupQuestions,
    enrichQuestion: q => { state.enriched = { ...q, _renderModel: { mode: 'RICH_TEXT' } }; return state.enriched },
    setData: patch => { state.patches.push(patch); Object.assign(state, patch) },
    showQuestion: idx => { state.questionShown = idx },
    ...overrides,
  })
  return { controller, state }
}

test('enterSafeMode activates safe mode and re-renders current question', () => {
  const { controller, state } = createHarness()
  controller.enterSafeMode()

  assert.equal(state.safeMode, true)
  assert.equal(state.questionShown, 0)
  assert.ok(state.patches.some(p => p.groupQuestions))
})

test('enterSafeMode is a no-op when no current question', () => {
  const { controller, state } = createHarness()
  state.currentQuestion = null
  controller.enterSafeMode()

  assert.equal(state.safeMode, true)
  assert.equal(state.questionShown, false)
})

test('enterSafeMode skips re-render when question at index is missing', () => {
  const { controller, state } = createHarness()
  state.currentIndex = 99
  controller.enterSafeMode()

  assert.equal(state.safeMode, true)
  assert.equal(state.questionShown, false)
})
