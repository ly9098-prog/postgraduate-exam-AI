const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildRecoveryQuestions } = require('../subpackages/study/practice/utils/recovery-questions-builder')

test('maps full question to recovery format', () => {
  const result = buildRecoveryQuestions([
    {
      id: 1,
      question_version_id: 'v1',
      question_version: 2,
      subject_id: 12,
      subject_code: 'DS',
      subject_name: '数据结构',
      question_type: 'single_choice',
      content: { text: 'What is 2+2?' },
      options: ['A', 'B', 'C', 'D'],
      image_url: 'http://img.png',
      knowledge_points: [1, 2],
      difficulty: 5,
    },
  ])
  assert.equal(result.length, 1)
  assert.equal(result[0].id, 1)
  assert.equal(result[0].stem, 'What is 2+2?')
  assert.equal(result[0].subject_code, 'DS')
  assert.equal(result[0].difficulty, 5)
  assert.deepEqual(result[0].knowledge_points, [1, 2])
})

test('falls back to stem field when content.text missing', () => {
  const result = buildRecoveryQuestions([
    { id: 1, stem: 'Direct stem' },
  ])
  assert.equal(result[0].stem, 'Direct stem')
})

test('falls back to content.stem when content.text missing', () => {
  const result = buildRecoveryQuestions([
    { id: 1, content: { stem: 'Content stem' } },
  ])
  assert.equal(result[0].stem, 'Content stem')
})

test('filters out entries without id', () => {
  const result = buildRecoveryQuestions([
    { id: 1, stem: 'ok' },
    { stem: 'no id' },
    null,
    { id: 0 },
  ])
  assert.equal(result.length, 1)
  assert.equal(result[0].id, 1)
})

test('defaults missing fields', () => {
  const result = buildRecoveryQuestions([{ id: 1 }])
  assert.equal(result[0].subject_code, '')
  assert.equal(result[0].subject_name, '')
  assert.equal(result[0].question_type, '')
  assert.deepEqual(result[0].content, {})
  assert.equal(result[0].options, null)
  assert.equal(result[0].image_url, null)
  assert.deepEqual(result[0].knowledge_points, [])
  assert.equal(result[0].difficulty, 3)
  assert.equal(result[0].stem, '')
})

test('handles empty array', () => {
  assert.deepEqual(buildRecoveryQuestions([]), [])
})

test('handles null input', () => {
  assert.deepEqual(buildRecoveryQuestions(null), [])
})
