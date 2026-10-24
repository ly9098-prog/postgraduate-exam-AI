const assert = require('node:assert/strict')
const { test } = require('node:test')
const { classifyAnswers } = require('../subpackages/study/practice/utils/answer-classification')

const isMultiBlank = (q) => q.question_type === 'multi_blank_choice'

test('classifies all answered questions', () => {
  const result = classifyAnswers({
    questions: [
      { id: 1, question_type: 'single_choice' },
      { id: 2, question_type: 'single_choice' },
    ],
    answerMap: { '1': 'A', '2': 'B' },
    answeredFlags: { '1': true, '2': true },
    isMultiBlank,
  })
  assert.equal(result.answeredCount, 2)
  assert.equal(result.unanswered, 0)
  assert.equal(result.completedQuestions.length, 2)
  assert.deepEqual(result.partialQuestionIds, [])
  assert.deepEqual(result.skippedQuestionIds, [])
})

test('classifies skipped questions', () => {
  const result = classifyAnswers({
    questions: [
      { id: 1, question_type: 'single_choice' },
      { id: 2, question_type: 'single_choice' },
    ],
    answerMap: {},
    answeredFlags: { '1': true },
    isMultiBlank,
  })
  assert.equal(result.answeredCount, 1)
  assert.equal(result.unanswered, 1)
  assert.deepEqual(result.skippedQuestionIds, [2])
})

test('classifies partial multi-blank questions', () => {
  const result = classifyAnswers({
    questions: [
      { id: 1, question_type: 'multi_blank_choice' },
      { id: 2, question_type: 'single_choice' },
    ],
    answerMap: { '1': 'A,' },
    answeredFlags: {},
    isMultiBlank,
  })
  assert.deepEqual(result.partialQuestionIds, [1])
  assert.deepEqual(result.skippedQuestionIds, [1, 2])
})

test('does not classify single_choice with answer as partial', () => {
  const result = classifyAnswers({
    questions: [{ id: 1, question_type: 'single_choice' }],
    answerMap: { '1': 'A' },
    answeredFlags: {},
    isMultiBlank,
  })
  assert.deepEqual(result.partialQuestionIds, [])
})

test('handles empty questions', () => {
  const result = classifyAnswers({
    questions: [],
    answerMap: {},
    answeredFlags: {},
    isMultiBlank,
  })
  assert.equal(result.total, 0)
  assert.equal(result.answeredCount, 0)
  assert.equal(result.unanswered, 0)
})

test('handles missing optional fields', () => {
  const result = classifyAnswers({})
  assert.equal(result.total, 0)
  assert.equal(result.answeredCount, 0)
})
