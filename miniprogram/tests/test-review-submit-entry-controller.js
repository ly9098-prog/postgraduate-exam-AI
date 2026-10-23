const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createGroupSubmitEntryController,
} = require('../subpackages/study/review-today/utils/submit-entry-controller')

const questions = [{ schedule_id: 1 }, { schedule_id: 2 }]

function createHarness(overrides = {}) {
  const state = {
    data: {
      groupQuestions: questions,
      submittingGroup: false,
      masterSubmitting: false,
    },
    session: { answers: { 1: 'A', 2: 'B' } },
    confirmPending: false,
    masterUndoInFlight: false,
    alive: true,
    confirmed: true,
    syncDay: true,
    toasts: [],
    submitting: false,
    undoCleared: 0,
    syncCalls: 0,
  }
  const controller = createGroupSubmitEntryController({
    getData: () => state.data,
    getSession: () => state.session,
    isConfirmPending: () => state.confirmPending,
    isMasterUndoInFlight: () => state.masterUndoInFlight,
    isPageAlive: () => state.alive,
    computeAnsweredCount: (items, answers) => items.filter(
      item => Boolean(answers[item.schedule_id])
    ).length,
    confirmController: {
      async confirm(totalCount, unansweredCount) {
        state.confirmArgs = { totalCount, unansweredCount }
        return state.confirmed
      },
    },
    showToast: options => { state.toasts.push(options) },
    clearMasterUndo: () => { state.undoCleared++ },
    setSubmitting: value => { state.submitting = value },
    syncReviewSessionDay: async () => {
      state.syncCalls++
      return state.syncDay
    },
    ...overrides,
  })
  return { controller, state }
}

test('blocks duplicate and busy submissions before confirmation', async () => {
  for (const key of ['submittingGroup', 'masterSubmitting']) {
    const { controller, state } = createHarness()
    state.data[key] = true
    assert.equal(await controller.confirm(questions), false)
  }

  const pending = createHarness()
  pending.state.confirmPending = true
  assert.equal(await pending.controller.confirm(questions), false)

  const undo = createHarness()
  undo.state.masterUndoInFlight = true
  assert.equal(await undo.controller.confirm(questions), false)

  assert.equal(await createHarness().controller.confirm([]), false)
})

test('delegates answered counts to the submit confirmation controller', async () => {
  const { controller, state } = createHarness()
  state.session.answers = { 1: 'A' }
  assert.equal(await controller.confirm(questions), true)
  assert.deepEqual(state.confirmArgs, { totalCount: 2, unansweredCount: 1 })
})

test('revalidates group identity and answers after confirmation', async () => {
  const changed = createHarness()
  changed.state.data.groupQuestions = []
  assert.equal(await changed.controller.begin(questions), null)
  assert.equal(changed.state.undoCleared, 0)
  assert.equal(changed.state.submitting, false)

  const incomplete = createHarness()
  incomplete.state.session.answers = { 1: 'A' }
  assert.equal(await incomplete.controller.begin(questions), null)
  assert.deepEqual(incomplete.state.toasts, [{ title: '请完成全部题目后再提交', icon: 'none' }])
  assert.equal(incomplete.state.syncCalls, 0)
})

test('starts submission and returns copied answers after day sync', async () => {
  const { controller, state } = createHarness()
  const answers = await controller.begin(questions)

  assert.deepEqual(answers, { 1: 'A', 2: 'B' })
  assert.notEqual(answers, state.session.answers)
  assert.equal(state.undoCleared, 1)
  assert.equal(state.submitting, true)
  assert.equal(state.syncCalls, 1)
})

test('rolls back submitting state when day sync fails on a live page', async () => {
  const { controller, state } = createHarness()
  state.syncDay = false
  assert.equal(await controller.begin(questions), null)
  assert.equal(state.submitting, false)
  assert.equal(state.syncCalls, 1)

  const dead = createHarness()
  dead.state.syncDay = false
  dead.state.alive = false
  dead.state.submitting = true
  assert.equal(await dead.controller.begin(questions), null)
  assert.equal(dead.state.submitting, true)
})
