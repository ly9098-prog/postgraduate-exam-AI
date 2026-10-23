const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSelfHealController,
} = require('../subpackages/study/practice/utils/self-heal-controller')

function createHarness(overrides = {}) {
  const state = {
    safeMode: false,
    currentIndex: 0,
    questions: [{ id: 1, question_type: 'single_choice', options: { A: 'a' } }],
    cacheCleared: false,
    patches: [],
  }
  const controller = createSelfHealController({
    setSafeModeActive: v => { state.safeMode = v },
    getQuestions: () => state.questions,
    getCurrentIndex: () => state.currentIndex,
    clearRenderCache: () => { state.cacheCleared = true },
    buildViewModel: (q, force) => ({
      question: { ...q, _renderModel: { mode: 'RICH_TEXT' } },
      answerState: {},
      optionKeys: ['A'],
    }),
    setData: patch => { state.patches.push(patch) },
    ...overrides,
  })
  return { controller, state }
}

test('enterSafeMode activates safe mode and re-renders', () => {
  const { controller, state } = createHarness()
  controller.enterSafeMode()

  assert.equal(state.safeMode, true)
  assert.equal(state.cacheCleared, true)
  assert.equal(state.patches.length, 1)
  assert.ok(state.patches[0].currentQuestion !== undefined)
})

test('reRenderCurrentQuestion is a no-op for invalid index', () => {
  const { controller, state } = createHarness()
  state.currentIndex = 99
  controller.reRenderCurrentQuestion()

  assert.equal(state.patches.length, 0)
})

test('reRenderCurrentQuestion is a no-op when buildViewModel returns null', () => {
  const { controller, state } = createHarness()
  const controller2 = createSelfHealController({
    setSafeModeActive: () => {},
    getQuestions: () => state.questions,
    getCurrentIndex: () => 0,
    clearRenderCache: () => {},
    buildViewModel: () => null,
    setData: patch => { state.patches.push(patch) },
  })
  controller2.reRenderCurrentQuestion()

  assert.equal(state.patches.length, 0)
})

test('reRenderCurrentQuestion clears cache and writes view state', () => {
  const { controller, state } = createHarness()
  controller.reRenderCurrentQuestion()

  assert.equal(state.cacheCleared, true)
  assert.equal(state.patches.length, 1)
  assert.ok(state.patches[0].currentQuestion._renderModel)
})
