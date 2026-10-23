const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createReviewMasterController,
} = require('../subpackages/study/review-today/utils/master-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    data: {
      masterSubmitting: false,
      submittingGroup: false,
      masterConfirmId: 2,
      currentGroupIdx: 0,
      currentIndex: 0,
      groupQuestions: [
        { schedule_id: 1, question_version_id: 11, occurrence_seq: 1 },
        { schedule_id: 2, question_version_id: 12, occurrence_seq: 1 },
      ],
      groups: [],
      masterUndoVisible: false,
      todayRemainingCount: 1,
    },
    session: { answers: { 2: 'B' }, allQuestions: [] },
    pendingMasterUndo: null,
    masterUndoInFlight: false,
    masterUndoTimer: null,
    masteredCount: 0,
    masterResult: { active: true, changed: true },
    unmasterResult: { active: true, occurrence_seq: 2 },
    daySyncSucceeds: true,
    toasts: [],
    logs: [],
    callbacks: [],
    timerCleared: false,
    timerStarted: false,
  }
  const controller = createReviewMasterController({
    getData: () => state.data,
    getSession: () => state.session,
    setData: patch => { Object.assign(state.data, patch) },
    isPageAlive: () => state.alive,
    isMasterSubmitting: () => state.data.masterSubmitting,
    isSubmittingGroup: () => state.data.submittingGroup,
    isMasterUndoInFlight: () => state.masterUndoInFlight,
    getPendingMasterUndo: () => state.pendingMasterUndo,
    setPendingMasterUndo: value => { state.pendingMasterUndo = value },
    setMasterUndoInFlight: value => { state.masterUndoInFlight = value },
    getMasterUndoTimer: () => state.masterUndoTimer,
    setMasterUndoTimer: timer => { state.masterUndoTimer = timer },
    incrementMasteredCount: () => { state.masteredCount++ },
    decrementMasteredCount: () => { state.masteredCount = Math.max(0, state.masteredCount - 1) },
    syncReviewSessionDay: async () => state.daySyncSucceeds,
    postMaster: async scheduleId => {
      state.masterRequest = scheduleId
      return state.masterResult
    },
    postUnmaster: async scheduleId => {
      state.unmasterRequest = scheduleId
      return state.unmasterResult
    },
    refreshOverviewStatsSilently: async () => { state.callbacks.push('refresh') },
    clearUndo: () => controller.clearUndo(),
    armUndoExpiry: ms => controller.armUndoExpiry(ms),
    clearReviewTimer: () => { state.timerCleared = true },
    getTodayRemainingCount: () => state.data.todayRemainingCount,
    syncAnsweredFlags: () => { state.callbacks.push('sync') },
    showQuestion: index => { state.callbacks.push(['show', index]) },
    startReviewTimer: () => { state.timerStarted = true },
    showToast: options => { state.toasts.push(options) },
    logError: (message, error) => { state.logs.push([message, error]) },
    setTimeout: callback => {
      state.timerCallback = callback
      return 'timer'
    },
    clearTimeout: timer => { state.clearedTimers = [...(state.clearedTimers || []), timer] },
    ...overrides,
  })
  return { controller, state }
}

test('guards and sets the master confirmation target', async () => {
  const { controller, state } = createHarness()
  state.data.masterSubmitting = true
  await controller.tap({ detail: { question: { schedule_id: 3 } } })
  assert.equal(state.data.masterConfirmId, 2)

  state.data.masterSubmitting = false
  state.data.submittingGroup = true
  await controller.tap({ detail: { question: { schedule_id: 3 } } })
  assert.equal(state.data.masterConfirmId, 2)

  state.data.submittingGroup = false
  await controller.tap({ detail: { question: { schedule_id: 3 } } })
  assert.equal(state.data.masterConfirmId, 3)
  await controller.tap({ detail: {} })
  assert.equal(state.data.masterConfirmId, 3)

  state.data.masterSubmitting = true
  await controller.cancel()
  assert.equal(state.data.masterConfirmId, 3)
  state.data.masterSubmitting = false
  await controller.cancel()
  assert.equal(state.data.masterConfirmId, null)
})

test('marks a question as mastered and keeps a five second undo window', async () => {
  const { controller, state } = createHarness()
  await controller.confirm()

  assert.equal(state.masterRequest, 2)
  assert.deepEqual(state.session.answers, {})
  assert.deepEqual(state.data.groupQuestions, [
    { schedule_id: 1, question_version_id: 11, occurrence_seq: 1 },
  ])
  assert.equal(state.data.masterSubmitting, false)
  assert.equal(state.data.masterUndoVisible, true)
  assert.equal(state.masterUndoTimer, 'timer')
  assert.equal(state.masteredCount, 1)
  assert.deepEqual(state.callbacks, ['refresh', 'sync', ['show', 0]])
  assert.equal(state.timerStarted, false)

  state.timerCallback()
  assert.equal(state.pendingMasterUndo, null)
  assert.equal(state.masterUndoTimer, null)
  assert.equal(state.data.masterUndoVisible, false)
})

test('master sync and request failures preserve page state safely', async () => {
  const dayFails = createHarness({ syncReviewSessionDay: async () => false })
  await dayFails.controller.confirm()
  assert.equal(dayFails.state.masterRequest, undefined)
  assert.equal(dayFails.state.data.masterSubmitting, false)
  assert.equal(dayFails.state.data.masterConfirmId, null)

  const failed = createHarness({ postMaster: async () => { throw new Error('network') } })
  await failed.controller.confirm()
  assert.deepEqual(failed.state.logs, [['标记掌握失败', new Error('network')]])
  assert.equal(failed.state.data.masterSubmitting, false)
  assert.equal(failed.state.data.masterConfirmId, null)
  assert.deepEqual(failed.state.toasts, [{ title: '操作失败，请重试', icon: 'none' }])

  const dead = createHarness({ isPageAlive: () => false })
  await dead.controller.confirm()
  assert.equal(dead.state.data.masterSubmitting, true)
})

test('restores the original question and answer on undo', async () => {
  const { controller, state } = createHarness()
  await controller.confirm()
  await controller.undo()

  assert.equal(state.unmasterRequest, 2)
  assert.deepEqual(state.session.allQuestions, [
    { schedule_id: 1, question_version_id: 11, occurrence_seq: 1 },
    { schedule_id: 2, question_version_id: 12, occurrence_seq: 2 },
  ])
  assert.equal(state.session.answers[2], 'B')
  assert.equal(state.masteredCount, 0)
  assert.equal(state.data.masterUndoVisible, false)
  assert.equal(state.data.phase, 'reviewing')
  assert.equal(state.data.currentIndex, 1)
  assert.equal(state.timerStarted, true)
  assert.deepEqual(state.toasts, [{ title: '已撤销掌握', icon: 'none' }])
})

test('handles undo day-sync, inactive task, and request failures', async () => {
  const dayFails = createHarness()
  dayFails.state.data.masterUndoVisible = true
  dayFails.controller.armUndoExpiry(5000)
  dayFails.state.masterUndoInFlight = true
  dayFails.state.pendingMasterUndo = { scheduleId: 2 }
  await dayFails.controller.undo()
  assert.equal(dayFails.state.data.masterUndoVisible, true)
  assert.equal(dayFails.state.masterUndoInFlight, true)

  const inactive = createHarness()
  await inactive.controller.confirm()
  inactive.state.unmasterResult = { active: false }
  await inactive.controller.undo()
  assert.equal(inactive.state.pendingMasterUndo, null)
  assert.deepEqual(inactive.state.toasts, [{ title: '该题已移出复习计划，无法撤销', icon: 'none' }])

  const failed = createHarness()
  await failed.controller.confirm()
  failed.state.unmasterResult = null
  failed.controller = createHarness({
    postUnmaster: async () => { throw new Error('network') },
    getData: () => failed.state.data,
    getSession: () => failed.state.session,
    setData: patch => Object.assign(failed.state.data, patch),
    isPageAlive: () => failed.state.alive,
    isMasterSubmitting: () => failed.state.data.masterSubmitting,
    isSubmittingGroup: () => failed.state.data.submittingGroup,
    isMasterUndoInFlight: () => failed.state.masterUndoInFlight,
    getPendingMasterUndo: () => failed.state.pendingMasterUndo,
    setPendingMasterUndo: value => { failed.state.pendingMasterUndo = value },
    setMasterUndoInFlight: value => { failed.state.masterUndoInFlight = value },
    getMasterUndoTimer: () => failed.state.masterUndoTimer,
    setMasterUndoTimer: timer => { failed.state.masterUndoTimer = timer },
    syncReviewSessionDay: async () => true,
    refreshOverviewStatsSilently: async () => {},
    clearUndo: () => failed.controller.clearUndo(),
    armUndoExpiry: ms => failed.controller.armUndoExpiry(ms),
    clearReviewTimer: () => {},
    getTodayRemainingCount: () => 1,
    syncAnsweredFlags: () => {},
    showQuestion: () => {},
    startReviewTimer: () => {},
    showToast: options => failed.state.toasts.push(options),
    logError: (message, error) => failed.state.logs.push([message, error]),
    setTimeout: callback => {
      failed.state.timerCallback = callback
      return 'timer'
    },
    clearTimeout: () => {},
  }).controller
  await failed.controller.undo()
  assert.equal(failed.state.logs.length, 1)
  assert.equal(failed.state.logs[0][0], '撤销掌握失败')
  assert.equal(failed.state.data.masterUndoVisible, true)
})
