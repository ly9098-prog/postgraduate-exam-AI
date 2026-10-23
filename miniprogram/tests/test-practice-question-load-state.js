const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildResetView,
  applyBatchCredentials,
  hasMissingBatchCredentials,
  buildSequentialRestartView,
  resetSequentialTiming,
  buildLoadedView,
} = require('../subpackages/study/practice/utils/question-load-state')

test('builds reset views with an exact base shape and optional error', () => {
  assert.deepEqual(buildResetView(), {
    launchingPreset: false,
    loading: false,
    started: false,
    questions: [],
    totalQuestions: 0,
    currentQuestion: null,
    currentAnswerState: null,
  })
  assert.equal(buildResetView('失败').errorText, '失败')
  assert.equal(Object.hasOwn(buildResetView(), 'errorText'), false)
})

test('applies batch credentials and detects missing submit credentials', () => {
  const session = {}
  applyBatchCredentials(session, {
    request_id: 'request',
    batch_token: 'token',
    mode: 'smart',
    submission_request_id: 'submission',
  }, 'random')
  assert.deepEqual(session, {
    comboCount: 0,
    recommendationRequestId: 'request',
    batchToken: 'token',
    batchMode: 'smart',
    requestId: 'submission',
  })
  assert.equal(hasMissingBatchCredentials(session, 1), false)
  assert.equal(hasMissingBatchCredentials({ batchToken: 'token' }, 1), true)
  assert.equal(hasMissingBatchCredentials({}, 0), false)

})

test('builds sequential restart and successful batch views', () => {
  const session = {
    activeStartedMonoMs: 1,
    startedAtMs: 2,
    backgroundMs: 3,
    _backgroundStartedMonoMs: 4,
  }
  resetSequentialTiming(session)
  assert.deepEqual(session, {
    activeStartedMonoMs: 0,
    startedAtMs: 0,
    backgroundMs: 0,
    _backgroundStartedMonoMs: null,
  })
  assert.deepEqual(buildSequentialRestartView(), {
    started: true,
    errorText: '',
    sequentialProgress: null,
  })

  const question = { id: 1 }
  const viewModel = { question, answerState: { selected: ['A'] } }
  assert.deepEqual(buildLoadedView([question], viewModel), {
    questions: [question],
    totalQuestions: 1,
    currentIndex: 0,
    currentQuestion: question,
    currentAnswerState: viewModel.answerState,
    launchingPreset: false,
    loading: false,
  })
  assert.equal(buildLoadedView([], null).currentQuestion, null)
})
