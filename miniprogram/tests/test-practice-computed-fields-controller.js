const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createComputedFieldsController,
  modeLabel,
} = require('../subpackages/study/practice/utils/computed-fields-controller')

function createHarness(overrides = {}) {
  const state = {
    data: { selectedMode: 'random', count: 5, totalQuestions: 10, answeredCount: 3 },
    patches: [],
  }
  const controller = createComputedFieldsController({
    getSelectedMode: () => state.data.selectedMode,
    getCount: () => state.data.count,
    getTotalQuestions: () => state.data.totalQuestions,
    getAnsweredCount: () => state.data.answeredCount,
    setData: patch => { state.patches.push(patch) },
    ...overrides,
  })
  return { controller, state }
}

test('modeLabel maps known modes', () => {
  assert.equal(modeLabel('random'), '随机挑战')
  assert.equal(modeLabel('sequential'), '顺序推进')
  assert.equal(modeLabel('smart'), '智能推荐')
})

test('modeLabel returns input for unknown mode', () => {
  assert.equal(modeLabel('custom'), 'custom')
  assert.equal(modeLabel(''), '')
  assert.equal(modeLabel(undefined), '')
})

test('update writes computed fields', () => {
  const { controller, state } = createHarness()
  controller.update()

  assert.equal(state.patches.length, 1)
  const patch = state.patches[0]
  assert.equal(patch.selectedModeLabel, '随机挑战')
  assert.equal(patch.countDisplay, '05')
  assert.equal(patch.estimatedMinutes, 10)
  assert.equal(patch.progressPercent, 30)
})

test('update handles large count without leading zero', () => {
  const { controller, state } = createHarness()
  state.data.count = 20
  controller.update()

  assert.equal(state.patches[0].countDisplay, '20')
  assert.equal(state.patches[0].estimatedMinutes, 40)
})

test('update handles zero total questions', () => {
  const { controller, state } = createHarness()
  state.data.totalQuestions = 0
  controller.update()

  assert.equal(state.patches[0].progressPercent, 0)
})

test('update merges extras', () => {
  const { controller, state } = createHarness()
  controller.update({ customField: 'value' })

  assert.equal(state.patches[0].customField, 'value')
  assert.equal(state.patches[0].selectedModeLabel, '随机挑战')
})
