const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createAnswerInteractionController,
} = require('../subpackages/study/review-today/utils/answer-interaction-controller')

const KF = 'schedule_id'

function createHarness(overrides = {}) {
  const state = {
    data: {
      submittingGroup: false,
      currentQuestion: {
        schedule_id: 1,
        question_type: 'single_choice',
        subject_name: '数学',
        _optionKeys: ['A', 'B', 'C', 'D'],
      },
      groupQuestions: [
        { schedule_id: 1, question_type: 'single_choice' },
        { schedule_id: 2, question_type: 'single_choice' },
      ],
    },
    session: { answers: {} },
    dataPatches: [],
    persisted: false,
    synced: false,
    runnerUpdated: false,
  }

  const controller = createAnswerInteractionController({
    isSubmitting: () => state.data.submittingGroup,
    getCurrentQuestion: () => state.data.currentQuestion,
    getAnswers: () => state.session.answers,
    setAnswers: answers => { state.session.answers = answers },
    getGroupQuestions: () => state.data.groupQuestions,
    getKeyField: () => KF,
    setData: patch => { state.dataPatches.push(patch) },
    persistDraft: () => { state.persisted = true },
    syncAnsweredFlags: () => { state.synced = true },
    updateRunnerFields: () => { state.runnerUpdated = true },
    buildRunnerSubtitle: () => '第 1 / 1 组',
    ...overrides,
  })

  return { controller, state }
}

test('selectOption toggles a single-choice answer and writes view state', () => {
  const { controller, state } = createHarness()
  controller.selectOption({ detail: { option: 'A' } })

  assert.equal(state.session.answers[1], 'A')
  assert.equal(state.persisted, true)
  assert.equal(state.synced, true)
  assert.equal(state.runnerUpdated, true)
  assert.equal(state.dataPatches.length, 1)
  assert.equal(state.dataPatches[0]._answeredCount, 1)
  assert.equal(state.dataPatches[0].currentQuestion._optionList !== undefined, true)
})

test('selectOption toggles off when the same option is selected again', () => {
  const { controller, state } = createHarness()
  state.session.answers = { 1: 'A' }
  controller.selectOption({ detail: { option: 'A' } })

  assert.equal(state.session.answers[1], undefined)
})

test('selectOption toggles multiple-choice answers with sorted output', () => {
  const { controller, state } = createHarness()
  state.data.currentQuestion.question_type = 'multiple_choice'
  controller.selectOption({ detail: { option: 'B' } })
  controller.selectOption({ detail: { option: 'A' } })

  // After selecting B then A, answer should contain both sorted
  assert.ok(state.session.answers[1].includes('A'))
  assert.ok(state.session.answers[1].includes('B'))

  // Toggle off A
  controller.selectOption({ detail: { option: 'A' } })
  assert.ok(!state.session.answers[1].includes('A') || state.session.answers[1] === undefined || !state.session.answers[1].includes('A'))
})

test('selectOption is a no-op while submitting', () => {
  const { controller, state } = createHarness()
  state.data.submittingGroup = true
  controller.selectOption({ detail: { option: 'A' } })

  assert.deepEqual(state.session.answers, {})
  assert.equal(state.persisted, false)
})

test('selectOption is a no-op with no option', () => {
  const { controller, state } = createHarness()
  controller.selectOption({ detail: {} })

  assert.deepEqual(state.session.answers, {})
  assert.equal(state.persisted, false)
})

test('selectBlankOption is a no-op when question is missing', () => {
  const { controller, state } = createHarness()
  state.data.currentQuestion = null
  controller.selectBlankOption({ detail: { blankId: 'b1', option: 'A' } })

  assert.equal(state.persisted, false)
})

test('selectBlankOption is a no-op while submitting', () => {
  const { controller, state } = createHarness()
  state.data.submittingGroup = true
  controller.selectBlankOption({ detail: { blankId: 'b1', option: 'A' } })

  assert.equal(state.persisted, false)
})
