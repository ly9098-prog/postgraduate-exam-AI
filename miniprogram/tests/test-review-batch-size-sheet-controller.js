const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createBatchSizeSheetController,
} = require('../subpackages/study/review-today/utils/batch-size-sheet-controller')

const OPTIONS = [5, 10, 20, 30]

function createHarness(overrides = {}) {
  const state = {
    phase: 'overview',
    isStarting: false,
    isContinuing: false,
    reviewBatchSize: 10,
    pendingBatchSize: 10,
    showBatchSizeSheet: false,
    userSelected: false,
    patches: [],
  }
  const controller = createBatchSizeSheetController({
    getPhase: () => state.phase,
    isStarting: () => state.isStarting,
    isContinuing: () => state.isContinuing,
    getReviewBatchSize: () => state.reviewBatchSize,
    getPendingBatchSize: () => state.pendingBatchSize,
    getBatchSizeOptions: () => OPTIONS,
    normalizeBatchSize: v => OPTIONS.includes(Number(v)) ? Number(v) : 10,
    markUserSelected: () => { state.userSelected = true },
    setData: patch => { state.patches.push(patch); Object.assign(state, patch) },
    ...overrides,
  })
  return { controller, state }
}

test('show opens sheet in overview phase', () => {
  const { controller, state } = createHarness()
  controller.show()
  assert.equal(state.showBatchSizeSheet, true)
  assert.equal(state.pendingBatchSize, 10)
})

test('show is no-op outside overview phase', () => {
  const { controller, state } = createHarness()
  state.phase = 'reviewing'
  controller.show()
  assert.equal(state.showBatchSizeSheet, false)
})

test('show is no-op while starting', () => {
  const { controller, state } = createHarness()
  state.isStarting = true
  controller.show()
  assert.equal(state.showBatchSizeSheet, false)
})

test('close hides sheet', () => {
  const { controller, state } = createHarness()
  state.showBatchSizeSheet = true
  controller.close()
  assert.equal(state.showBatchSizeSheet, false)
})

test('selectPending sets valid value', () => {
  const { controller, state } = createHarness()
  controller.selectPending({ currentTarget: { dataset: { value: 20 } } })
  assert.equal(state.pendingBatchSize, 20)
})

test('selectPending ignores invalid value', () => {
  const { controller, state } = createHarness()
  controller.selectPending({ currentTarget: { dataset: { value: 7 } } })
  assert.equal(state.pendingBatchSize, 10)
})

test('confirm applies pending size and marks user-selected', () => {
  const { controller, state } = createHarness()
  state.pendingBatchSize = 20
  controller.confirm()
  assert.equal(state.reviewBatchSize, 20)
  assert.equal(state.showBatchSizeSheet, false)
  assert.equal(state.userSelected, true)
})
