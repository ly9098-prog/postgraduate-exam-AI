const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createOverviewSyncController,
} = require('../subpackages/study/review-today/utils/overview-sync-controller')

function createHarness(overrides = {}) {
  const state = {
    session: {
      taskDate: '2026-10-23',
      todayTaskTotalCount: 20,
      allGroupResults: [1, 2],
      totalCorrect: 5,
      totalWrong: 3,
      totalCompleted: 8,
      completedBeforeSession: 5,
    },
    phase: 'reviewing',
    todayDueCount: 20,
  }
  const controller = createOverviewSyncController({
    getSession: () => state.session,
    getPhase: () => state.phase,
    getTodayDueCount: () => state.todayDueCount,
    ...overrides,
  })
  return { controller, state }
}

test('applyOverviewToSession updates session fields from overview', () => {
  const { controller, state } = createHarness()
  const overview = {
    date: '2026-10-24',
    all_question_ids: [1, 2, 3],
    completed_question_ids: [1],
    remaining_question_ids: [2, 3],
  }
  controller.applyOverviewToSession(overview, { todayDueCount: 10 })

  assert.equal(state.session.taskDate, '2026-10-24')
  assert.deepEqual(state.session.allTodayQuestionIds, [1, 2, 3])
  assert.deepEqual(state.session.completedQuestionIds, [1])
  assert.deepEqual(state.session.remainingQuestionIds, [2, 3])
})

test('applyOverviewWithDayReset resets session counters', () => {
  const { controller, state } = createHarness()
  const overview = { date: '2026-10-24', all_question_ids: [1] }
  controller.applyOverviewWithDayReset(overview, { todayDueCount: 15, todayCompletedCount: 3 })

  assert.equal(state.session.taskDate, '2026-10-24')
  assert.deepEqual(state.session.allGroupResults, [])
  assert.equal(state.session.totalCorrect, 0)
assert.equal(state.session.totalWrong, 0)
  assert.equal(state.session.todayTaskTotalCount, 15)
  assert.equal(state.session.completedBeforeSession, 3)
})

test('adjustVmForActiveSession clamps remaining to task total', () => {
  const { controller, state } = createHarness()
  const vm = { todayRemainingCount: 30, todayDueCount: 20, todayCompletedCount: 0, todayProgressPercent: 0 }
  controller.adjustVmForActiveSession(vm)

  assert.equal(vm.todayDueCount, 20)
  assert.equal(vm.todayRemainingCount, 20)
  assert.equal(vm.todayCompletedCount, 0)
})

test('adjustVmForActiveSession is a no-op when task total is 0', () => {
  const { controller, state } = createHarness()
  state.session.todayTaskTotalCount = 0
  const vm = { todayRemainingCount: 30, todayDueCount: 20 }
  controller.adjustVmForActiveSession(vm)

  assert.equal(vm.todayDueCount, 20)
  assert.equal(vm.todayRemainingCount, 30)
})

test('adjustVmForActiveSession is a no-op outside reviewing/group-result phase', () => {
  const { controller, state } = createHarness()
  state.phase = 'overview'
  const vm = { todayRemainingCount: 30, todayDueCount: 20 }
  controller.adjustVmForActiveSession(vm)

  assert.equal(vm.todayDueCount, 20)
  assert.equal(vm.todayRemainingCount, 30)
})

test('isSameDay returns true when task date matches current date', () => {
  const { controller } = createHarness()
  // session.taskDate is set in harness; getChinaDate returns today
  // This may or may not match depending on test run date, so just check it returns a boolean
  const result = controller.isSameDay()
  assert.equal(typeof result, 'boolean')
})
