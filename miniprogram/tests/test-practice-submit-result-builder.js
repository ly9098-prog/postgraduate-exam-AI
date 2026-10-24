const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildStoredResults,
  buildLightQuestions,
  computeDisplaySkippedCount,
} = require('../subpackages/study/practice/utils/submit-result-builder')

test('buildStoredResults: reclassifies skipped partials', () => {
  const results = buildStoredResults({
    serverResults: [
      { question_id: 1, status: 'correct', is_correct: true },
      { question_id: 2, status: 'skipped', is_correct: false },
    ],
    partialQuestionIds: [2],
    snapshotAnswerMap: { '1': 'A', '2': 'B' },
    snapshotAnsweredFlags: {},
    questionSource: [],
  })
  assert.equal(results.length, 2)
  assert.equal(results[0].status, 'correct')
  assert.equal(results[1].status, 'partial')
  assert.equal(results[1]._local_partial, true)
  assert.equal(results[1].user_answer, 'B')
})

test('buildStoredResults: keeps non-partial skipped as skipped', () => {
  const results = buildStoredResults({
    serverResults: [
      { question_id: 1, status: 'skipped', is_correct: false },
    ],
    partialQuestionIds: [],
    snapshotAnswerMap: {},
    snapshotAnsweredFlags: {},
    questionSource: [],
  })
  assert.equal(results[0].status, 'skipped')
  assert.equal(results[0]._local_partial, false)
})

test('buildStoredResults: appends missing questions as skipped', () => {
  const results = buildStoredResults({
    serverResults: [
      { question_id: 1, status: 'correct', is_correct: true },
    ],
    partialQuestionIds: [],
    snapshotAnswerMap: { '2': 'C' },
    snapshotAnsweredFlags: {},
    questionSource: [
      { id: 1, question_type: 'single_choice' },
      { id: 2, question_type: 'single_choice' },
    ],
  })
  assert.equal(results.length, 2)
  assert.equal(results[1].question_id, 2)
  assert.equal(results[1].status, 'skipped')
  assert.equal(results[1]._local_skipped, true)
  assert.equal(results[1].user_answer, 'C')
})

test('buildStoredResults: appends missing partial questions as partial', () => {
  const results = buildStoredResults({
    serverResults: [],
    partialQuestionIds: [3],
    snapshotAnswerMap: { '3': 'A,B' },
    snapshotAnsweredFlags: {},
    questionSource: [{ id: 3 }],
  })
  assert.equal(results[0].status, 'partial')
  assert.equal(results[0]._local_partial, true)
})

test('buildStoredResults: skips already-answered questions from snapshot', () => {
  const results = buildStoredResults({
    serverResults: [],
    partialQuestionIds: [],
    snapshotAnswerMap: {},
    snapshotAnsweredFlags: { '1': true },
    questionSource: [{ id: 1 }],
  })
  assert.equal(results.length, 0)
})

test('buildStoredResults: handles empty inputs', () => {
  const results = buildStoredResults({})
  assert.deepEqual(results, [])
})

test('buildLightQuestions: extracts minimal fields', () => {
  const light = buildLightQuestions([
    {
      id: 1,
      question_version_id: 'v1',
      question_version: 2,
      content: { text: 'What is 1+1?' },
      options: ['A', 'B'],
      question_type: 'single_choice',
    },
  ])
  assert.equal(light.length, 1)
  assert.equal(light[0].id, 1)
  assert.equal(light[0].stem, 'What is 1+1?')
  assert.equal(light[0].question_type, 'single_choice')
  assert.deepEqual(light[0].options, ['A', 'B'])
})

test('buildLightQuestions: falls back to stem field', () => {
  const light = buildLightQuestions([
    { id: 1, stem: 'Direct stem' },
  ])
  assert.equal(light[0].stem, 'Direct stem')
})

test('buildLightQuestions: skips entries without id', () => {
  const light = buildLightQuestions([
    { id: 1 },
    { stem: 'no id' },
    null,
  ])
  assert.equal(light.length, 1)
})

test('buildLightQuestions: handles empty array', () => {
  assert.deepEqual(buildLightQuestions([]), [])
})

test('computeDisplaySkippedCount: subtracts partial from server skipped', () => {
  assert.equal(computeDisplaySkippedCount(5, 2), 3)
})

test('computeDisplaySkippedCount: floors at zero', () => {
  assert.equal(computeDisplaySkippedCount(1, 5), 0)
})

test('computeDisplaySkippedCount: handles undefined inputs', () => {
  assert.equal(computeDisplaySkippedCount(undefined, undefined), 0)
})
