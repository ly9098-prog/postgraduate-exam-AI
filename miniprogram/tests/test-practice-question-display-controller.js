const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPracticeQuestionDisplayController,
} = require('../subpackages/study/practice/utils/question-display-controller')

function createHarness(overrides = {}) {
  const state = {
    data: {
      questions: [
        { id: 1, question_type: 'single_choice', options: { A: 'opt A', B: 'opt B' } },
        { id: 2, question_type: 'single_choice', options: { A: 'opt A', B: 'opt B' } },
      ],
      currentIndex: 0,
    },
    session: { answerMap: {}, questionRenderCache: Object.create(null) },
    dataPatches: [],
    computedUpdated: false,
    renderChecked: false,
    warmed: false,
    settled: false,
  }

  const controller = createPracticeQuestionDisplayController({
    getSession: () => state.session,
    getAnswerMap: () => state.session.answerMap,
    getQuestions: () => state.data.questions,
    isMathImageEnabled: () => false,
    isDev: () => false,
    setData: (patch, cb) => { state.dataPatches.push(patch); if (cb) cb() },
    updateComputedFields: () => { state.computedUpdated = true },
    checkRenderInvariant: () => { state.renderChecked = true },
    showToast: () => {},
    settleQuestionTime: () => { state.settled = true },
    warmQuestionImages: () => { state.warmed = true },
    setOptionKeys: keys => { state.session.optionKeys = keys },
    setCurrentQuestionStartedMono: () => { state.session.currentQuestionStartedMonoMs = 1 },
    getTraceId: q => 'trace-' + q.id,
    ...overrides,
  })

  return { controller, state }
}

test('getRenderView builds and caches a render view', () => {
  const { controller, state } = createHarness()
  const q = { id: 1, question_type: 'single_choice', options: { A: 'opt A', B: 'opt B' } }
  const view = controller.getRenderView(q)

  assert.ok(view !== null)
  assert.ok(view.question._renderModel !== undefined)
  assert.deepEqual(view.optionKeys, ['A', 'B'])

  // Second call should return cached
  const view2 = controller.getRenderView(q)
  assert.equal(view, view2)
})

test('getRenderView returns null for null question', () => {
  const { controller } = createHarness()
  assert.equal(controller.getRenderView(null), null)
})

test('buildAnswerState produces option list for single choice', () => {
  const { controller } = createHarness()
  const q = { id: 1, question_type: 'single_choice', options: { A: 'opt A', B: 'opt B' } }
  const view = controller.getRenderView(q)
  const state = controller.buildAnswerState(view, 'A')

  assert.equal(state.questionId, '1')
  assert.ok(Array.isArray(state.optionList))
  assert.equal(state.hasBlankOptionGroups, false)
})

test('buildAnswerState returns null for null render view', () => {
  const { controller } = createHarness()
  assert.equal(controller.buildAnswerState(null, 'A'), null)
})

test('buildViewModel combines render view and answer state', () => {
  const { controller, state } = createHarness()
  state.session.answerMap = { 1: 'B' }
  const q = { id: 1, question_type: 'single_choice', options: { A: 'opt A', B: 'opt B' } }
  const vm = controller.buildViewModel(q)

  assert.ok(vm !== null)
  assert.ok(vm.question !== undefined)
  assert.ok(vm.answerState !== null)
  assert.deepEqual(vm.optionKeys, ['A', 'B'])
})

test('showQuestion writes view state and triggers callbacks', () => {
  const { controller, state } = createHarness()
  controller.showQuestion(0)

  assert.equal(state.settled, true)
  assert.equal(state.warmed, true)
  assert.equal(state.computedUpdated, true)
  assert.equal(state.renderChecked, true)
  assert.equal(state.dataPatches.length, 1)
  assert.equal(state.dataPatches[0].currentIndex, 0)
})

test('showQuestion is a no-op for invalid index', () => {
  const { controller, state } = createHarness()
  controller.showQuestion(99)

  assert.equal(state.dataPatches.length, 0)
  assert.equal(state.computedUpdated, false)
})
