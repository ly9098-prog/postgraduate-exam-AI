const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamResultLoadController,
} = require('../subpackages/exam/utils/exam-result-load-controller')

function harness(overrides = {}) {
  const calls = { fetches: [], setsData: [], errorMessages: [] }
  const state = {
    pageAlive: true,
    attemptId: 42,
    inflight: null,
    sequence: 0,
    wrongIds: [],
    wrongIdsLength: 0,
    diagnosisIndex: null,
    firstQuestionId: 0,
    response: {
      accuracy: 0.8,
      choice_score: 18,
      total_choice_score: 20,
      correct_count: 8,
      wrong_count: 2,
      unanswered_count: 0,
      duration_sec: 600,
      questions: [
        { question_id: 101, status: 'wrong', wrong_question_id: 201, error_diagnosis: { id: 301 } },
        { question_id: 102, status: 'correct' },
      ],
    },
    fetchError: null,
  }
  const options = {
    getInflight: () => state.inflight,
    setInflight: value => { state.inflight = value },
    nextSequence: () => ++state.sequence,
    getSequence: () => state.sequence,
    isPageAlive: () => state.pageAlive,
    setData: patch => calls.setsData.push(patch),
    fetchResult: async () => {
      calls.fetches.push(true)
      if (state.fetchError) throw state.fetchError
      return state.response
    },
    getErrorMessage: error => `msg:${error && error.message}`,
    percentNumber: v => Math.round(Number(v) * 100),
    clamp: (v, min, max) => Math.min(max, Math.max(min, v)),
    compactScore: v => String(Math.round(v)),
    compactDuration: () => '10:00',
    encouragement: () => '继续保持！',
    encouragementTail: () => '，继续保持！',
    buildKnowledgeMetrics: () => [{ name: 'kp', accuracyPct: 80, source: 'knowledge' }],
    buildScoreRing: rate => ({ showScoreRingCaps: true, scoreRingEndStyle: `rate:${rate}` }),
    buildRadar: () => ({ radarItems: [], radarEdges: [], radarPolygonStyle: 'poly' }),
    buildTopItems: () => [],
    collectWrongIds: () => [201],
    firstWrongIdByQuestion: q => Number(q && q.wrong_question_id) || 0,
    setWrongIds: ids => { state.wrongIds = ids; state.wrongIdsLength = ids.length },
    getWrongIdsLength: () => state.wrongIdsLength,
    resetDiagnosisIndex: () => { state.diagnosisIndex = Object.create(null) },
    setDiagnosisId: (wrongId, id) => { state.diagnosisIndex[wrongId] = id },
    setFirstQuestionId: id => { state.firstQuestionId = id },
    ...overrides.options,
  }
  return { state, options, calls, get controller() { return createExamResultLoadController(options) } }
}

test('happy path fetches, maps and commits the result patch', async () => {
  const h = harness()
  await h.controller.load()
  assert.deepEqual(h.calls.fetches, [true])
  assert.equal(h.state.firstQuestionId, 101)
  assert.deepEqual(h.state.wrongIds, [201])
  assert.equal(h.state.diagnosisIndex[201], 301)
  const patch = h.calls.setsData[h.calls.setsData.length - 1]
  assert.equal(patch.loading, false)
  assert.equal(patch.result.scoreRatePct, 90)
  assert.equal(patch.result.accuracyPct, 80)
  assert.equal(patch.result.correctCount, 8)
  assert.equal(patch.result.wrongCount, 2)
  assert.equal(patch.radarPolygonStyle, 'poly')
  assert.equal(patch.weakCount, 0)
  assert.equal(patch.wrongDetailCount, 1)
})

test('skipLoadingState avoids the loading=true patch', async () => {
  const h = harness()
  await h.controller.load({ skipLoadingState: true })
  assert.ok(!h.calls.setsData.some(p => p.loading === true && p.errorText === ''))
})

test('without skipLoadingState sets loading=true first', async () => {
  const h = harness()
  await h.controller.load()
  assert.deepEqual(h.calls.setsData[0], { loading: true, errorText: '' })
})

test('inflight request is reused and not duplicated', async () => {
  const h = harness()
  const p1 = h.controller.load()
  const p2 = h.controller.load()
  await Promise.all([p1, p2])
  assert.deepEqual(h.calls.fetches, [true])
})

test('stale sequence response is discarded', async () => {
  const h = harness()
  h.options.fetchResult = async () => {
    // Bump the sequence from outside (e.g. onUnload) while in-flight.
    h.state.sequence += 1
    return h.state.response
  }
  await h.controller.load()
  // No loading=false commit because the response was stale.
  assert.ok(!h.calls.setsData.some(p => p.loading === false && p.result))
})

test('dead page response is discarded', async () => {
  const h = harness()
  h.options.fetchResult = async () => {
    h.state.pageAlive = false
    return h.state.response
  }
  await h.controller.load()
  assert.ok(!h.calls.setsData.some(p => p.loading === false && p.result))
})

test('fetch error writes loading=false and errorText', async () => {
  const h = harness()
  h.state.fetchError = new Error('network')
  await h.controller.load()
  const patch = h.calls.setsData[h.calls.setsData.length - 1]
  assert.deepEqual(patch, { loading: false, errorText: 'msg:network' })
})

test('stale error is discarded', async () => {
  const h = harness()
  h.options.fetchResult = async () => {
    h.state.sequence += 1
    throw new Error('network')
  }
  await h.controller.load()
  assert.ok(!h.calls.setsData.some(p => p.errorText))
})

test('inflight is cleared after completion', async () => {
  const h = harness()
  await h.controller.load()
  assert.equal(h.state.inflight, null)
})
