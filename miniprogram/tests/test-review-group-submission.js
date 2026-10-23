const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildGroupReviews,
  buildGroupResult,
} = require('../subpackages/study/review-today/utils/group-submission')

const questions = [
  { schedule_id: 1, question_id: 11, question_version_id: 21, occurrence_seq: 1 },
  { schedule_id: 2, question_id: 12, question_version_id: 22, occurrence_seq: 1 },
]
const answers = { 1: 'A', 2: 'B' }
const answered = () => true
const requestId = question => `request-${question.schedule_id}`

test('builds immutable review submissions in group order', () => {
  assert.deepEqual(buildGroupReviews({
    groupQuestions: questions,
    answers,
    isQuestionAnswered: answered,
    getRequestId: requestId,
  }), {
    reviews: [
      { schedule_id: 1, question_id: 11, question_version_id: 21, occurrence_seq: 1, request_id: 'request-1', user_answer: 'A' },
      { schedule_id: 2, question_id: 12, question_version_id: 22, occurrence_seq: 1, request_id: 'request-2', user_answer: 'B' },
    ],
  })
  assert.deepEqual(buildGroupReviews({
    groupQuestions: questions,
    answers: { 1: 'A' },
    isQuestionAnswered: () => false,
    getRequestId: requestId,
  }), { error: 'incomplete', index: 0 })
  assert.deepEqual(buildGroupReviews({
    groupQuestions: [{ ...questions[0], question_version_id: null }],
    answers,
    isQuestionAnswered: answered,
    getRequestId: requestId,
  }), { error: 'version', index: 0 })
  assert.deepEqual(buildGroupReviews({
    groupQuestions: [],
    answers,
    isQuestionAnswered: answered,
    getRequestId: requestId,
  }), { error: 'empty' })
})

test('skips invalid schedule matches and falls back to question id', () => {
  const base = {
    results: [
      { schedule_id: 2, question_version_id: 22, occurrence_seq: 1, success: true, is_correct: true, correct_answer: 'B', mastery_percent: 80, mastered: true },
      { schedule_id: 1, question_version_id: 99, occurrence_seq: 1, success: false, error: 'version changed', error_code: 'VERSION' },
      { question_id: 11, success: true, is_correct: false, correct_answer: 'A' },
    ],
    reviews: questions.map(question => ({ schedule_id: question.schedule_id })),
    answers,
    isQuestionAnswered: answered,
    enrichForResult: question => ({ ...question, enriched: true }),
    failureNeedsRefresh: result => result.error === 'version changed',
  }
  const second = buildGroupResult({ ...base, question: questions[1] })
  assert.equal(second.wasSubmitted, true)
  assert.equal(second.isCorrect, true)
  assert.equal(second.masteryPercent, 80)
  assert.equal(second.mastered, true)

  const first = buildGroupResult({ ...base, question: questions[0] })
  assert.equal(first.wasSubmitted, true)
  assert.equal(first.isCorrect, false)
  assert.equal(first.submitFailed, false)
  assert.equal(first.refreshRequired, false)
  assert.equal(first.retryable, false)
  assert.equal(first.submitError, '')
  assert.equal(first.submitErrorCode, '')
})

test('marks missing submitted results and unsubmitted skipped questions', () => {
  const question = questions[0]
  const missing = buildGroupResult({
    question,
    results: [],
    reviews: [{ schedule_id: 1 }],
    answers,
    isQuestionAnswered: answered,
    enrichForResult: q => q,
    failureNeedsRefresh: () => false,
  })
  assert.equal(missing.submitFailed, true)
  assert.equal(missing.retryable, true)
  assert.equal(missing.submitError, '批改结果缺失，已保留待重试')

  const skipped = buildGroupResult({
    question,
    results: [],
    reviews: [],
    answers,
    isQuestionAnswered: () => false,
    enrichForResult: q => q,
    failureNeedsRefresh: () => false,
  })
  assert.equal(skipped.wasSkipped, true)
  assert.equal(skipped.submitFailed, false)
  assert.equal(skipped.correctAnswer, '')
})

test('uses result order and may select a question id fallback', () => {
  const exact = buildGroupResult({
    question: questions[0],
    results: [
      { question_id: 11, success: true, is_correct: false, correct_answer: 'wrong' },
      { schedule_id: 1, question_version_id: 21, occurrence_seq: 1, success: true, is_correct: true, correct_answer: 'A' },
    ],
    reviews: [{ schedule_id: 1 }],
    answers,
    isQuestionAnswered: answered,
    enrichForResult: q => q,
    failureNeedsRefresh: () => false,
  })
  assert.equal(exact.wasSubmitted, true)
  assert.equal(exact.isCorrect, false)
  assert.equal(exact.correctAnswer, 'wrong')
})
