// Pure controller for the 408 AI teacher panel on the exam result page.
// Extracted from subpackages/exam/result/index.js run408Teacher.

function createExam408TeacherController(options) {
  return {
    run: runImpl.bind(null, options),
  }
}

async function runImpl(options, action, questionId) {
  if (options.getTeacherLoading()) {
    options.setData({ teacherSheetVisible: true })
    return
  }
  if (!options.getAttemptId() || !questionId) return

  const cacheKey = buildCacheKey(options.getAttemptId(), questionId, action)
  const cached = options.getCacheEntry(cacheKey)
  options.setActiveCacheKey(cacheKey)
  if (cached) {
    options.setData({
      teacherLoading: false,
      teacherResult: cached,
      teacherErrorText: '',
      teacherSheetVisible: true,
      teacherFeedbackSent: options.getFeedbackEntry(cacheKey) || '',
    })
    return
  }
  await performTeacherRequest(options, action, questionId, cacheKey)
}

function buildCacheKey(attemptId, questionId, action) {
  return [Number(attemptId || 0), Number(questionId || 0), String(action || '')].join('|')
}

async function performTeacherRequest(options, action, questionId, cacheKey) {
  const requestSeq = options.nextRequestSequence()
  const payload = {
    question_id: Number(questionId),
    action,
    exam_attempt_id: Number(options.getAttemptId()),
  }
  let requestPromise = options.getInflight(cacheKey)
  if (!requestPromise) {
    requestPromise = options.postTeacher(payload)
    options.setInflight(cacheKey, requestPromise)
  }
  options.setData({
    teacherLoading: true,
    teacherResult: null,
    teacherErrorText: '',
    teacherSheetVisible: true,
    teacherFeedbackSent: '',
  })
  try {
    const raw = await requestPromise
    const normalized = options.normalizeResult(raw)
    if (!normalized) throw new Error('AI 返回格式异常')
    options.setCacheEntry(cacheKey, normalized)
    if (requestSeq !== options.getRequestSequence() || !options.isPageAlive()) return
    options.setActiveCacheKey(cacheKey)
    options.setData({ teacherLoading: false, teacherResult: normalized })
  } catch (error) {
    if (requestSeq !== options.getRequestSequence() || !options.isPageAlive()) return
    options.setData({ teacherLoading: false, teacherErrorText: options.errorMessage(error) })
  } finally {
    if (options.getInflight(cacheKey) === requestPromise) options.deleteInflight(cacheKey)
  }
}

module.exports = {
  createExam408TeacherController,
}
