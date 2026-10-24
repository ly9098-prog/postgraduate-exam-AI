const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildSubmitResultPayload,
} = require('../subpackages/study/practice/utils/submit-result-payload')

const submission = {
  answerMap: { 1: 'A', 2: '' },
  answeredFlags: { 1: true, 2: false },
  partialQuestionIds: [2],
  total: 3,
  unanswered: 1,
  selectedSubjectId: 12,
  selectedSubjectName: '数据结构',
  duration: 120,
  traceId: 'trace-submission',
  comboCount: 2,
  recoveryQuestions: [{ id: 3, stem: 'Q3' }],
  knowledgeScope: { root_id: 34 },
  requestId: 'request-1',
}

const submitResult = {
  results: [
    { question_id: 1, status: 'correct' },
    { question_id: 2, status: 'skipped' },
  ],
  total_correct: 1,
  total_wrong: 1,
  total_skipped: 1,
  trace_id: 'trace-server',
  knowledge_session: { root_id: 34 },
}

function build(options) {
  return buildSubmitResultPayload({
    ...options,
    buildStoredResults: opts => opts.serverResults.map(result => ({
      ...result,
      user_answer: (opts.snapshotAnswerMap || {})[String(result.question_id)] || '',
    })),
    buildLightQuestions: questions => questions.map(q => ({ id: q.id, stem: q.stem })),
    computeDisplaySkippedCount: (skipped, partial) => Math.max(0, skipped - partial),
  })
}

test('builds the local result payload from snapshot and server result', () => {
  const payload = build({
    submission,
    submitResult,
    questions: [{ id: 1 }, { id: 2 }],
    traceId: 'trace-page',
    cacheKey: 'cache-1',
    userId: 'user-1',
    createdAt: 123,
  })

  assert.deepEqual(payload, {
    correct: 1,
    wrong: 1,
    skipped: 0,
    partial: 1,
    total: 3,
    subject_id: 12,
    subject_name: '数据结构',
    duration: 120,
    traceId: 'trace-server',
    results: [
      { question_id: 1, status: 'correct', user_answer: 'A' },
      { question_id: 2, status: 'skipped', user_answer: '' },
    ],
    questions: [
      { id: 1, stem: undefined },
      { id: 2, stem: undefined },
    ],
    comboCount: 2,
    knowledge_session: { root_id: 34 },
    request_id: 'request-1',
    _cacheKey: 'cache-1',
    _userId: 'user-1',
    _createdAt: 123,
  })
})

test('falls back to recovery questions, page trace and snapshot counts', () => {
  const payload = build({
    submission: {
      ...submission,
      selectedSubjectId: null,
      selectedSubjectName: '',
      duration: null,
      traceId: '',
    },
    submitResult: { results: [] },
    questions: [],
    traceId: 'trace-page',
    cacheKey: 'cache-2',
    userId: 'user-2',
    createdAt: 456,
  })

  assert.equal(payload.total, 3)
  assert.equal(payload.skipped, 0)
  assert.equal(payload.subject_id, null)
  assert.equal(payload.subject_name, '')
  assert.equal(payload.duration, 0)
  assert.equal(payload.traceId, 'trace-page')
  assert.deepEqual(payload.questions, [{ id: 3, stem: 'Q3' }])
})
