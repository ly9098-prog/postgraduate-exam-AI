const assert = require('node:assert/strict')
const { test } = require('node:test')
const adapters = require('../subpackages/study/practice/utils/practice-submit-page-adapter')
const { createSubmitEntryController } = require('../subpackages/study/practice/utils/submit-entry-controller')
const { createSubmitFlowController } = require('../subpackages/study/practice/utils/submit-flow-controller')
const { createSubmitErrorController } = require('../subpackages/study/practice/utils/submit-error-controller')
const { buildSubmitAnswers, buildSubmitSession } = require('../subpackages/study/practice/utils/submit-session-builder')
const { buildSubmitPayload, isDeterministicReject, resolveRejectMessage } = require('../subpackages/study/practice/utils/submit-payload-builder')
const { buildSubmissionSnapshot } = require('../subpackages/study/practice/utils/submission-snapshot-builder')
const { buildRecoveryQuestions } = require('../subpackages/study/practice/utils/recovery-questions-builder')
const { classifyAnswers } = require('../subpackages/study/practice/utils/answer-classification')

async function verifySubmitRetry(firstError, loginDecision) {
  let wallMs = 200000
  let monoMs = 16000
  const calls = []
  const posted = []
  const loginPrompts = []
  const page = {
    _pageAlive: true,
    _practiceSession: {
      answerMap: { 1: 'A', 2: '' }, questionTimeMap: { 1: 13 },
      activeStartedMonoMs: 1000, backgroundMs: 2000, startedAtMs: 185000,
      requestId: 'fixed-request', batchToken: 'fixed-batch', batchMode: 'random',
    },
    data: {
      questions: [{ id: 1 }, { id: 2 }], selectedSubjectId: 7,
      selectedSubjectName: 'Test subject', submitting: false,
    },
    setData(patch) { Object.assign(this.data, patch) },
    _clearTimer() {},
    _settleQuestionTime() {},
    _setPracticeUnloadGuard() {},
    _showSubmitConfirmPaused: async () => true,
    _showSubmitConfirm: async () => {},
    _persistPendingSubmission(submission, status) {
      calls.push({ status, requestId: submission.requestId })
      return true
    },
    _submitSuccessController() {
      return { complete: submission => {
        submission.serverAccepted = true
        this.setData({ submitted: true, submitting: false })
      } }
    },
  }
  const api = {
    now: () => wallMs,
    async post(url, payload) {
      assert.equal(url, '/practice/batch-submit')
      assert.deepEqual(calls.at(-1), { status: 'pending', requestId: 'fixed-request' })
      assert.equal(page._practiceSession.submissionSnapshot.pendingPersisted, true)
      posted.push(JSON.parse(JSON.stringify(payload)))
      if (posted.length === 1) {
        wallMs += 3600000
        monoMs += 60000
        page._practiceSession.answerMap[1] = 'B'
        throw firstError
      }
      return { results: [] }
    },
  }
  const dependencies = {
    api, buildSubmitPayload, createSubmitEntryController, createSubmitFlowController,
    createSubmitErrorController, buildSubmitAnswers, buildSubmitSession,
    buildSubmissionSnapshot, buildRecoveryQuestions, classifyAnswers,
    isDeterministicReject, resolveRejectMessage,
    promptLogin: async options => { loginPrompts.push(options); return loginDecision },
    adapter: {
      buildAnsweredFlags: () => ({ 1: true, 2: false }),
      isMultiBlankChoice: () => false,
    },
    getDate: () => Date, getMath: () => Math,
    getPlatform: () => ({}), getConsole: () => ({ error() {} }),
    monotonicNow: () => monoMs,
  }
  page._submitEntryController = () => adapters._submitEntryController(page, dependencies)
  page._submitErrorController = () => adapters._submitErrorController(page, dependencies)
  const flow = adapters._submitFlowController(page, dependencies)
  await flow.submit(true)
  assert.equal(page.data.submitting, false)
  assert.equal(page.data.submitted, undefined)
  assert.equal(posted[0].session.duration_sec, 13)
  assert.equal(posted[0].session.finished_at, new Date(200000).toISOString())
  assert.equal(posted[0].session.subject_id, 7)
  assert.equal(posted[0].session.request_id, 'fixed-request')
  assert.equal(posted[0].batch_token, 'fixed-batch')
  assert.equal(posted[0].answers[0].user_answer, 'A')
  assert.deepEqual(posted[0].skipped_question_ids, [2])
  assert.equal(loginPrompts.length, firstError.code === 'AUTH_REQUIRED' ? 1 : 0)
  assert.equal(posted.length, 1)
  assert.equal(page._practiceSession.submissionSnapshot.retryBlocked, false)
  await flow.submit(true)
  assert.equal(posted.length, 2)
  assert.deepEqual(posted[1], posted[0])
  assert.equal(page.data.submitted, true)
}

test('real submit adapters persist before POST and reuse frozen timing and answers after network failure', async () => {
  await verifySubmitRetry(new Error('response lost'))
})

for (const decision of [true, false]) {
  test(`formal submit offers login without replay and retains frozen retry after choice ${decision}`, async () => {
    await verifySubmitRetry({ code: 'AUTH_REQUIRED', statusCode: 401 }, decision)
  })
}
