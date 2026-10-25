const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExam408TeacherController,
} = require('../subpackages/exam/utils/exam-408-teacher-controller')

function harness(overrides = {}) {
  const calls = { posts: [], setsData: [], normalizes: [], errors: [] }
  const state = {
    pageAlive: true,
    attemptId: 42,
    teacherLoading: false,
    requestSequence: 0,
    activeCacheKey: '',
    cache: Object.create(null),
    feedback: Object.create(null),
    inflight: Object.create(null),
    postResult: { action: 'core_concept' },
    postError: null,
    normalizeResult: raw => raw,
  }
  const options = {
    getAttemptId: () => state.attemptId,
    getTeacherLoading: () => state.teacherLoading,
    isPageAlive: () => state.pageAlive,
    setData: patch => calls.setsData.push(patch),
    getCacheEntry: key => state.cache[key],
    setCacheEntry: (key, value) => { state.cache[key] = value },
    getFeedbackEntry: key => state.feedback[key],
    setActiveCacheKey: key => { state.activeCacheKey = key },
    getInflight: key => state.inflight[key],
    setInflight: (key, p) => { state.inflight[key] = p },
    deleteInflight: key => { delete state.inflight[key] },
    nextRequestSequence: () => ++state.requestSequence,
    getRequestSequence: () => state.requestSequence,
    postTeacher: async payload => {
      calls.posts.push(payload)
      if (state.postError) throw state.postError
      return state.postResult
    },
    normalizeResult: raw => {
      calls.normalizes.push(raw)
      return state.normalizeResult(raw)
    },
    errorMessage: error => {
      calls.errors.push(error)
      return `msg:${error && error.message}`
    },
    ...overrides.options,
  }
  return { state, options, calls, get controller() { return createExam408TeacherController(options) } }
}

test('busy teacher loading just shows the sheet', async () => {
  const h = harness()
  h.state.teacherLoading = true
  await h.controller.run('core_concept', 101)
  assert.deepEqual(h.calls.setsData, [{ teacherSheetVisible: true }])
  assert.deepEqual(h.calls.posts, [])
})

test('missing attemptId or questionId is a no-op', async () => {
  const h = harness()
  h.state.attemptId = 0
  await h.controller.run('core_concept', 101)
  h.state.attemptId = 42
  await h.controller.run('core_concept', 0)
  assert.deepEqual(h.calls.posts, [])
})

test('cached result is shown without posting', async () => {
  const h = harness()
  h.state.cache['42|101|core_concept'] = { action: 'core_concept', cached: true }
  h.state.feedback['42|101|core_concept'] = 'like'
  await h.controller.run('core_concept', 101)
  assert.deepEqual(h.calls.posts, [])
  const patch = h.calls.setsData[h.calls.setsData.length - 1]
  assert.equal(patch.teacherLoading, false)
  assert.deepEqual(patch.teacherResult, { action: 'core_concept', cached: true })
  assert.equal(patch.teacherFeedbackSent, 'like')
  assert.equal(h.state.activeCacheKey, '42|101|core_concept')
})

test('happy path posts, normalizes, caches and commits', async () => {
  const h = harness()
  await h.controller.run('core_concept', 101)
  assert.deepEqual(h.calls.posts, [{
    question_id: 101, action: 'core_concept', exam_attempt_id: 42,
  }])
  assert.deepEqual(h.calls.normalizes, [h.state.postResult])
  assert.deepEqual(h.state.cache['42|101|core_concept'], h.state.postResult)
  const patch = h.calls.setsData[h.calls.setsData.length - 1]
  assert.equal(patch.teacherLoading, false)
  assert.deepEqual(patch.teacherResult, h.state.postResult)
})

test('invalid normalized result throws and shows error', async () => {
  const h = harness()
  h.state.normalizeResult = () => null
  await h.controller.run('core_concept', 101)
  const patch = h.calls.setsData[h.calls.setsData.length - 1]
  assert.equal(patch.teacherLoading, false)
  assert.equal(patch.teacherErrorText, 'msg:AI 返回格式异常')
})

test('stale sequence after post discards commit', async () => {
  const h = harness()
  h.options.postTeacher = async () => {
    h.state.requestSequence += 1
    return h.state.postResult
  }
  await h.controller.run('core_concept', 101)
  assert.ok(!h.calls.setsData.some(p => p.teacherResult))
})

test('dead page after post discards commit', async () => {
  const h = harness()
  h.options.postTeacher = async () => {
    h.state.pageAlive = false
    return h.state.postResult
  }
  await h.controller.run('core_concept', 101)
  assert.ok(!h.calls.setsData.some(p => p.teacherResult))
})

test('post error shows error message', async () => {
  const h = harness()
  h.state.postError = new Error('timeout')
  await h.controller.run('core_concept', 101)
  const patch = h.calls.setsData[h.calls.setsData.length - 1]
  assert.equal(patch.teacherErrorText, 'msg:timeout')
})

test('inflight request is reused and cleared in finally', async () => {
  const h = harness()
  const p1 = h.controller.run('core_concept', 101)
  const p2 = h.controller.run('core_concept', 101)
  await Promise.all([p1, p2])
  assert.deepEqual(h.calls.posts, [h.calls.posts[0]])
  assert.equal(h.state.inflight['42|101|core_concept'], undefined)
})
