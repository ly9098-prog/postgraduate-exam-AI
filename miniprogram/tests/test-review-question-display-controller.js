const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createQuestionDisplayController,
} = require('../subpackages/study/review-today/utils/question-display-controller')

const KF = 'schedule_id'

function createHarness(overrides = {}) {
  const state = {
    data: {
      groupQuestions: [
        { schedule_id: 1, question_type: 'single_choice', _renderModel: { renderTrace: [] } },
        { schedule_id: 2, question_type: 'single_choice', _renderModel: { renderTrace: [] } },
      ],
      currentQuestion: null,
      currentIndex: 0,
      _answeredCount: 0,
      currentBatchNo: 1,
      totalBatchCount: 3,
      currentGroupIdx: 0,
    },
    session: { answers: {}, optionKeys: [] },
    dataPatches: [],
    renderChecked: false,
    traceRecorded: null,
    sizeChecked: null,
  }

  const controller = createQuestionDisplayController({
    getGroupQuestions: () => state.data.groupQuestions,
    setGroupQuestions: qs => { state.data.groupQuestions = qs },
    getAnswers: () => state.session.answers,
    setOptionKeys: keys => { state.session.optionKeys = keys },
    getKeyField: () => KF,
    getAnsweredCount: () => state.data._answeredCount,
    getCurrentQuestion: () => state.data.currentQuestion,
    enrichQuestion: q => Object.assign({ _optionKeys: ['A', 'B', 'C', 'D'] }, q),
    setData: patch => {
      state.dataPatches.push(patch)
      Object.assign(state.data, patch)
    },
    checkSetDataSize: data => { state.sizeChecked = data },
    checkRenderInvariant: () => { state.renderChecked = true },
    recordRenderTrace: trace => { state.traceRecorded = trace },
    buildRunnerSubtitle: () => '第 1 / 3 组',
    ...overrides,
  })

  return { controller, state }
}

test('showQuestion assembles current question and writes view state', () => {
  const { controller, state } = createHarness()
  controller.showQuestion(0)

  assert.equal(state.data.currentIndex, 0)
  assert.ok(state.data.currentQuestion !== null)
  assert.equal(state.renderChecked, true)
  assert.equal(state.sizeChecked !== null, true)
})

test('showQuestion is a no-op for an invalid index', () => {
  const { controller, state } = createHarness()
  controller.showQuestion(99)

  assert.equal(state.data.currentQuestion, null)
  assert.equal(state.dataPatches.length, 0)
})

test('updateRunnerFields writes progress percent and subtitle', () => {
  const { controller, state } = createHarness()
  state.data._answeredCount = 1
  state.data.currentQuestion = { subject_name: '数学' }
  controller.updateRunnerFields()

  const lastPatch = state.dataPatches[state.dataPatches.length - 1]
  assert.equal(lastPatch.runnerProgressPercent, 50)
  assert.equal(lastPatch.runnerSubtitle, '第 1 / 3 组')
  assert.equal(lastPatch.runnerSubjectName, '数学')
})

test('updateRunnerFields handles empty group questions', () => {
  const { controller, state } = createHarness()
  state.data.groupQuestions = []
  state.data._answeredCount = 0
  state.data.currentQuestion = null
  controller.updateRunnerFields()

  const lastPatch = state.dataPatches[state.dataPatches.length - 1]
  assert.equal(lastPatch.runnerProgressPercent, 0)
  assert.equal(lastPatch.runnerSubjectName, '')
})

test('syncAnsweredFlags writes enriched questions', () => {
  const { controller, state } = createHarness()
  state.session.answers = { 1: 'A' }
  controller.syncAnsweredFlags()

  assert.ok(state.dataPatches.length > 0)
  const lastPatch = state.dataPatches[state.dataPatches.length - 1]
  assert.ok(Array.isArray(lastPatch.groupQuestions))
})
