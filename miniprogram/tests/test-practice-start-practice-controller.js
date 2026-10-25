const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createStartPracticeController,
} = require('../subpackages/study/practice/utils/start-practice-controller')

function createHarness(overrides = {}) {
  const state = {
    loading: false,
    submitting: false,
    pendingSubmission: null,
    selectedSubjectId: 12,
    selectedMode: 'random',
    selectedSubjectHasChildren: false,
    submittedPayload: { old: true },
    views: [],
    toasts: [],
    guards: [],
    traceIds: [],
    sessionReset: false,
    recoveryOffered: 0,
    sheetOpened: 0,
    recentFlushed: 0,
    loads: 0,
  }
  const controller = createStartPracticeController({
    isLoading: () => state.loading,
    isSubmitting: () => state.submitting,
    readPendingSubmission: () => state.pendingSubmission,
    offerPendingSubmissionRecovery: async () => { state.recoveryOffered += 1 },
    getSelectedSubjectId: () => state.selectedSubjectId,
    openSubjectSheet: () => { state.sheetOpened += 1 },
    getSelectedMode: () => state.selectedMode,
    isSelectedSubjectHasChildren: () => state.selectedSubjectHasChildren,
    showToast: options => state.toasts.push(options),
    createTraceId: () => 'trace-new',
    setSubmittedResultPayload: value => { state.submittedPayload = value },
    resetSession: () => { state.sessionReset = true },
    setTraceId: traceId => state.traceIds.push(traceId),
    setData: patch => state.views.push(patch),
    setUnloadGuard: enabled => state.guards.push(enabled),
    flushPendingRecentSubject: () => { state.recentFlushed += 1 },
    loadQuestions: async () => { state.loads += 1 },
    ...overrides,
  })
  return { controller, state }
}

test('starts a new practice and delegates loading', async () => {
  const { controller, state } = createHarness()

  await controller.start()

  assert.equal(state.submittedPayload, null)
  assert.equal(state.sessionReset, true)
  assert.deepEqual(state.traceIds, ['trace-new'])
  assert.deepEqual(state.views, [{
    traceId: 'trace-new',
    loading: true,
    renderCount: 0,
    started: true,
    currentIndex: 0,
    answeredCount: 0,
    results: [],
    submitted: false,
    wrongCount: 0,
    errorText: '',
    sequentialProgress: null,
    feedbackVisible: false,
    feedbackType: '',
    feedbackTitle: '',
    feedbackDetail: '',
    feedbackComboText: '',
  }])
  assert.deepEqual(state.guards, [true])
  assert.equal(state.recentFlushed, 1)
  assert.equal(state.loads, 1)
})

test('does not start while loading or submitting', async () => {
  const loading = createHarness()
  loading.state.loading = true
  await loading.controller.start()
  assert.equal(loading.state.loads, 0)

  const submitting = createHarness()
  submitting.state.submitting = true
  await submitting.controller.start()
  assert.equal(submitting.state.loads, 0)
})

test('offers pending recovery once and stops if it remains unresolved', async () => {
  const { controller, state } = createHarness()
  state.pendingSubmission = { requestId: 'pending' }

  await controller.start()

  assert.equal(state.recoveryOffered, 1)
  assert.equal(state.sessionReset, false)
  assert.equal(state.loads, 0)
})

test('continues after recovery clears the pending submission', async () => {
  const { controller, state } = createHarness({
    offerPendingSubmissionRecovery: async () => { state.pendingSubmission = null },
  })
  state.pendingSubmission = { requestId: 'pending' }

  await controller.start()

  assert.equal(state.recoveryOffered, 0)
  assert.equal(state.loads, 1)
})

test('opens the subject sheet when no subject is selected', async () => {
  const { controller, state } = createHarness()
  state.selectedSubjectId = 0

  await controller.start()

  assert.equal(state.sheetOpened, 1)
  assert.equal(state.loads, 0)
})

test('rejects sequential mode for a parent subject', async () => {
  const { controller, state } = createHarness()
  state.selectedMode = 'sequential'
  state.selectedSubjectHasChildren = true

  await controller.start()

  assert.deepEqual(state.toasts, [{ title: '顺序练习仅支持具体科目', icon: 'none' }])
  assert.equal(state.sessionReset, false)
  assert.equal(state.loads, 0)
})
