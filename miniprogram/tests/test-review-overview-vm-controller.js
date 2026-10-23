const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createOverviewVMController,
} = require('../subpackages/study/review-today/utils/overview-vm-controller')

const BATCH_SIZE_OPTIONS = [5, 10, 20, 30]

function createHarness(overrides = {}) {
  const state = {
    userSelectedBatchSize: false,
    currentBatchSize: 10,
  }
  const controller = createOverviewVMController({
    getBatchSizeOptions: () => BATCH_SIZE_OPTIONS,
    getDefaultBatchSize: () => 10,
    isUserBatchSizeSelected: () => state.userSelectedBatchSize,
    getCurrentUserBatchSize: () => state.currentBatchSize,
    ...overrides,
  })
  return { controller, state }
}

test('builds VM from a full overview', () => {
  const { controller } = createHarness()
  const vm = controller.buildVM({
    today_due_count: 20,
    today_completed_count: 5,
    today_remaining_count: 15,
    today_overdue_count: 0,
    today_new_due_count: 8,
    estimated_minutes: 30,
    batch_size: 10,
    current_batch_no: 1,
    total_batch_count: 4,
    remaining_batch_count: 3,
  })

  assert.equal(vm.todayDueCount, 20)
  assert.equal(vm.todayCompletedCount, 5)
  assert.equal(vm.todayRemainingCount, 15)
  assert.equal(vm.todayProgressPercent, 25)
  assert.equal(vm.reviewBatchSize, 10)
  assert.equal(vm.currentBatchNo, 1)
  assert.equal(vm.totalBatchCount, 4)
  assert.ok(vm.todayAdviceText.length > 0)
})

test('advice text reflects overdue questions', () => {
  const { controller } = createHarness()
  const vm = controller.buildVM({ today_overdue_count: 3, today_remaining_count: 10 })
  assert.ok(vm.todayAdviceText.includes('逾期'))
})

test('advice text reflects few remaining questions', () => {
  const { controller } = createHarness()
  const vm = controller.buildVM({ today_overdue_count: 0, today_remaining_count: 3 })
  assert.ok(vm.todayAdviceText.includes('只剩'))
})

test('advice text reflects progress when questions completed', () => {
  const { controller } = createHarness()
  const vm = controller.buildVM({
    today_overdue_count: 0,
    today_remaining_count: 10,
    today_completed_count: 5,
  })
  assert.ok(vm.todayAdviceText.includes('已经完成'))
})

test('respects user-selected batch size over server value', () => {
  const { controller, state } = createHarness()
  state.userSelectedBatchSize = true
  state.currentBatchSize = 20
  const vm = controller.buildVM({ batch_size: 5 })
  assert.equal(vm.reviewBatchSize, 20)
})

test('normalizes invalid batch size to default', () => {
  const { controller } = createHarness()
  const vm = controller.buildVM({ batch_size: 7 })
  assert.equal(vm.reviewBatchSize, 10)
})

test('handles empty overview gracefully', () => {
  const { controller } = createHarness()
  const vm = controller.buildVM({})

  assert.equal(vm.todayDueCount, 0)
  assert.equal(vm.todayCompletedCount, 0)
  assert.equal(vm.todayRemainingCount, 0)
  assert.equal(vm.todayProgressPercent, 0)
  assert.equal(vm.reviewBatchSize, 10)
})
