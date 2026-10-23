const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildGroupReviews,
  buildGroupResult,
  buildGroupOutcome,
  mergeResultsByScheduleId,
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

test('merges result history by schedule id in first-seen order', () => {
  const previous = [
    { schedule_id: 1, wasSubmitted: true, isCorrect: false },
    { schedule_id: 2, wasSubmitted: true, isCorrect: true },
  ]
  const current = [
    { schedule_id: 2, wasSubmitted: true, isCorrect: false },
    { schedule_id: 3, wasSubmitted: true, isCorrect: true },
  ]
  assert.deepEqual(mergeResultsByScheduleId(previous, current), [
    { schedule_id: 1, wasSubmitted: true, isCorrect: false },
    { schedule_id: 2, wasSubmitted: true, isCorrect: false },
    { schedule_id: 3, wasSubmitted: true, isCorrect: true },
  ])
})

test('builds retry groups, progress, and session state from group results', () => {
  const submitted = {
    schedule_id: 1,
    wasSubmitted: true,
    isCorrect: true,
  }
  const failed = {
    schedule_id: 2,
    wasSubmitted: false,
    submitFailed: true,
    refreshRequired: false,
  }
  const refreshed = {
    schedule_id: 3,
    wasSubmitted: false,
    submitFailed: true,
    refreshRequired: true,
  }
  const skipped = {
    schedule_id: 4,
    wasSubmitted: false,
    submitFailed: false,
  }
  const outcome = buildGroupOutcome({
    groupResults: [submitted, failed, refreshed, skipped],
    groupQuestions: [
      { schedule_id: 1 }, { schedule_id: 2 }, { schedule_id: 3 }, { schedule_id: 4 },
    ],
    groups: [{ schedule_id: 1 }, { schedule_id: 2 }, { schedule_id: 3 }, { schedule_id: 4 }],
    allGroupResults: [{ schedule_id: 1, wasSubmitted: false }],
    sessionTodayTaskTotalCount: 6,
    dataTodayDueCount: 5,
    dataTodayCompletedCount: 1,
    completedBeforeSession: 0,
    currentGroupIdx: 0,
  })

  assert.equal(outcome.failureToast, '1 题需刷新，1 题待重试')
  assert.deepEqual(outcome.view.groups, [
    { schedule_id: 1 }, { schedule_id: 2 }, { schedule_id: 3 }, { schedule_id: 4 },
    [{ schedule_id: 2 }, { schedule_id: 4 }],
  ])
  assert.deepEqual(outcome.session, {
    todayTaskTotalCount: 6,
    allGroupResults: [submitted, failed, refreshed, skipped],
    totalCorrect: 1,
    totalWrong: 0,
    totalCompleted: 1,
  })
  assert.equal(outcome.view.groupCorrect, 1)
  assert.equal(outcome.view.groupWrong, 0)
  assert.equal(outcome.view._groupSkipped, 3)
  assert.equal(outcome.view.groupAccuracyPercent, 100)
  assert.equal(outcome.view.todayDueCount, 6)
  assert.equal(outcome.view.todayCompletedCount, 1)
  assert.equal(outcome.view.todayRemainingCount, 5)
  assert.equal(outcome.view.todayProgressPercent, 17)
  assert.equal(outcome.view._groupProgressStyle, 'width: 20%')
  assert.deepEqual(outcome.view.groupWrongResults, [])
})
