const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createGroupSubmitResultController,
} = require('../subpackages/study/review-today/utils/submit-result-controller')

function createHarness(overrides = {}) {
  const state = {
    data: {
      groups: [],
      todayDueCount: 6,
      todayCompletedCount: 1,
      currentGroupIdx: 0,
    },
    session: {
      allGroupResults: [],
      todayTaskTotalCount: 6,
      completedBeforeSession: 0,
    },
    clearedDrafts: [],
    toasts: [],
    paused: false,
    resultDockShown: false,
    setPatches: [],
  }
  const controller = createGroupSubmitResultController({
    getGroups: () => state.data.groups,
    getSession: () => state.session,
    getTodayDueCount: () => state.data.todayDueCount,
    getTodayCompletedCount: () => state.data.todayCompletedCount,
    getCurrentGroupIdx: () => state.data.currentGroupIdx,
    clearSubmittedDraft: (questions, results) => { state.clearedDrafts.push({ questions, results }) },
    showToast: options => { state.toasts.push(options) },
    pauseTimer: () => { state.paused = true },
    setData: patch => { state.setPatches.push(patch); Object.assign(state.data, patch) },
    showResultDockAndRefreshTimer: () => { state.resultDockShown = true },
    ...overrides,
  })
  return { controller, state }
}

const question = { schedule_id: 1 }
const groupResults = [{
  schedule_id: 1,
  wasSubmitted: true,
  isCorrect: true,
  submitFailed: false,
  refreshRequired: false,
}]

test('clears confirmed drafts, updates session, and writes result view', () => {
  const { controller, state } = createHarness()
  const outcome = controller.apply({ groupQuestions: [question], groupResults })

  assert.deepEqual(state.clearedDrafts, [{ questions: [question], results: groupResults }])
  assert.deepEqual(state.toasts, [])
  assert.equal(state.paused, true)
  assert.equal(state.session.totalCorrect, 1)
  assert.equal(state.session.totalCompleted, 1)
  assert.equal(state.setPatches.length, 1)
  assert.equal(state.data.phase, 'group-result')
  assert.equal(state.data.submittingGroup, false)
  assert.equal(state.data.resultDockVisible, true)
  assert.equal(state.data.todayRemainingCount, 5)
  assert.equal(outcome.view.todayRemainingCount, 5)
  assert.equal(state.resultDockShown, false)
})

test('shows failure toast and completion dock', () => {
  const { controller, state } = createHarness()
  const failed = [{
    schedule_id: 1,
    wasSubmitted: false,
    isCorrect: false,
    submitFailed: true,
    refreshRequired: true,
  }]
  state.data.todayDueCount = 1
  state.data.todayCompletedCount = 0
  state.session.todayTaskTotalCount = 1

  controller.apply({ groupQuestions: [question], groupResults: failed })

  assert.deepEqual(state.toasts, [{ title: '1 题任务已更新，将重新获取', icon: 'none' }])
  assert.equal(state.data.todayRemainingCount, 1)
  assert.equal(state.resultDockShown, false)

  state.data.todayDueCount = 0
  state.session.todayTaskTotalCount = 0
  controller.apply({ groupQuestions: [question], groupResults: [] })
  assert.equal(state.resultDockShown, true)
})
