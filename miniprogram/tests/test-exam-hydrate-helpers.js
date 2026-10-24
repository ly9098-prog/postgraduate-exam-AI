const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildServerAnswersMap, mergeAnswerState, buildExamResultUrl } = require('../subpackages/exam/utils/hydrate-helpers')

test('buildServerAnswersMap: builds map from answers array', () => {
  const map = buildServerAnswersMap([
    { item_id: 1, selected_answer: 'A', marked_for_review: true, used_time: 30 },
    { item_id: 2, selected_answer: null, marked_for_review: false, used_time: 0 },
  ])
  assert.equal(map['1'].selected_answer, 'A')
  assert.equal(map['1'].marked_for_review, true)
  assert.equal(map['1'].used_time, 30)
  assert.equal(map['2'].selected_answer, null)
})

test('buildServerAnswersMap: defaults missing fields', () => {
  const map = buildServerAnswersMap([{ item_id: 1 }])
  assert.equal(map['1'].selected_answer, null)
  assert.equal(map['1'].marked_for_review, false)
  assert.equal(map['1'].used_time, 0)
})

test('buildServerAnswersMap: clamps negative used_time', () => {
  const map = buildServerAnswersMap([{ item_id: 1, used_time: -10 }])
  assert.equal(map['1'].used_time, 0)
})

test('buildServerAnswersMap: handles empty array', () => {
  const map = buildServerAnswersMap([])
  assert.equal(Object.keys(map).length, 0)
})

test('buildServerAnswersMap: handles null', () => {
  const map = buildServerAnswersMap(null)
  assert.equal(Object.keys(map).length, 0)
})

test('mergeAnswerState: pending overrides server', () => {
  const merged = mergeAnswerState(
    { selected_answer: 'A', used_time: 10 },
    { selected_answer: 'B', used_time: 20 }
  )
  assert.equal(merged.selected_answer, 'B')
  assert.equal(merged.used_time, 20)
})

test('mergeAnswerState: server used when pending empty', () => {
  const merged = mergeAnswerState({ selected_answer: 'A' }, {})
  assert.equal(merged.selected_answer, 'A')
})

test('mergeAnswerState: empty when both null', () => {
  const merged = mergeAnswerState(null, null)
  assert.deepEqual(merged, {})
})

test('buildExamResultUrl: builds correct URL', () => {
  assert.equal(
    buildExamResultUrl(123),
    '/subpackages/exam/result/index?attempt_id=123'
  )
})
