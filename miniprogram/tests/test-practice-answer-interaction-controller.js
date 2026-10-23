const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPracticeAnswerInteractionController,
} = require('../subpackages/study/practice/utils/answer-interaction-controller')

function createHarness(overrides = {}) {
  const state = {
    data: {
      submitted: false,
      currentQuestion: { id: 1, question_type: 'single_choice' },
      questions: [{ id: 1, question_type: 'single_choice' }, { id: 2, question_type: 'single_choice' }],
      currentIndex: 0,
      totalQuestions: 2,
    },
    session: { answerMap: {}, answeredFlags: [] },
    submissionLocked: false,
    dataPatches: [],
    computedUpdated: false,
    debugCalled: false,
  }

  const controller = createPracticeAnswerInteractionController({
    isSubmitted: () => state.data.submitted,
    isSubmissionLocked: () => state.submissionLocked,
    getCurrentQuestion: () => state.data.currentQuestion,
    getAnswerMap: () => state.session.answerMap,
    setAnswerMap: map => { state.session.answerMap = map },
    getAnsweredFlags: () => state.session.answeredFlags,
    setAnsweredFlags: flags => { state.session.answeredFlags = flags },
    getQuestions: () => state.data.questions,
    getCurrentIndex: () => state.data.currentIndex,
    getTotalQuestions: () => state.data.totalQuestions,
    getQuestionRenderView: () => null,
    buildQuestionAnswerState: () => ({}),
    setData: (patch, cb) => { state.dataPatches.push(patch); if (cb) cb() },
    updateComputedFields: () => { state.computedUpdated = true },
    debugStateChange: () => { state.debugCalled = true },
    ...overrides,
  })

  return { controller, state }
}

test('selectOption toggles single-choice answer', () => {
  const { controller, state } = createHarness()
  controller.selectOption({ detail: { option: 'A' } })

  assert.equal(state.session.answerMap[1], 'A')
  assert.equal(state.debugCalled, true)
  assert.equal(state.computedUpdated, true)
})

test('selectOption toggles off when same option selected', () => {
  const { controller, state } = createHarness()
  state.session.answerMap = { 1: 'A' }
  controller.selectOption({ detail: { option: 'A' } })

  assert.equal(state.session.answerMap[1], undefined)
})

test('selectOption toggles multiple-choice with sorted output', () => {
  const { controller, state } = createHarness()
  state.data.currentQuestion.question_type = 'multiple_choice'
  controller.selectOption({ detail: { option: 'B' } })
  controller.selectOption({ detail: { option: 'A' } })

  assert.ok(state.session.answerMap[1].includes('A'))
  assert.ok(state.session.answerMap[1].includes('B'))
})

test('selectOption is a no-op while submitted', () => {
  const { controller, state } = createHarness()
  state.data.submitted = true
  controller.selectOption({ detail: { option: 'A' } })

  assert.deepEqual(state.session.answerMap, {})
})

test('selectOption is a no-op while submission locked', () => {
  const { controller, state } = createHarness()
  state.submissionLocked = true
  controller.selectOption({ detail: { option: 'A' } })

  assert.deepEqual(state.session.answerMap, {})
})

test('selectOption is a no-op with no current question', () => {
  const { controller, state } = createHarness()
  state.data.currentQuestion = null
  controller.selectOption({ detail: { option: 'A' } })

  assert.deepEqual(state.session.answerMap, {})
})

test('selectBlankOption is a no-op when question is missing', () => {
  const { controller, state } = createHarness()
  state.data.currentQuestion = null
  controller.selectBlankOption({ detail: { blankId: 'b1', option: 'A' } })

  assert.equal(state.debugCalled, false)
})

test('selectBlankOption is a no-op while submitted', () => {
  const { controller, state } = createHarness()
  state.data.submitted = true
  controller.selectBlankOption({ detail: { blankId: 'b1', option: 'A' } })

  assert.equal(state.debugCalled, false)
})
