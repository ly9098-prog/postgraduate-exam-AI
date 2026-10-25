// Pure controller for the 408 AI teacher from the review dialog.
// Extracted from subpackages/study/practice-result/index.js run408TeacherFromReview.

function createReview408TeacherController(options) {
  return {
    run: runImpl.bind(null, options),
  }
}

async function runImpl(options, action) {
  if (options.getTeacherLoading()) {
    options.setData({ teacherSheetVisible: true })
    return
  }
  const dialog = options.getReviewDialog() || {}
  if (!dialog.questionId) return

  const cacheKey = options.buildCacheKey(dialog, action)
  const cached = options.getCacheEntry(cacheKey)
  options.setActiveCacheKey(cacheKey)
  if (cached) {
    options.setData({
      teacherLoading: false, teacherResult: cached, teacherErrorText: '',
      teacherSheetVisible: true,
      teacherFeedbackSent: options.getFeedbackEntry(cacheKey) || '',
    })
    return
  }
  await performRequest(options, action, dialog, cacheKey)
}

async function performRequest(options, action, dialog, cacheKey) {
  const requestSeq = options.nextRequestSequence()
  const questionId = Number(dialog.questionId)
  const payload = buildPayload(dialog, questionId, action)
  let requestPromise = options.getInflight(cacheKey)
  if (!requestPromise) {
    requestPromise = options.postTeacher(payload)
    options.setInflight(cacheKey, requestPromise)
  }
  options.setData({
    teacherLoading: true, teacherResult: null, teacherErrorText: '',
    teacherSheetVisible: true, teacherFeedbackSent: '',
  })
  try {
    const raw = await requestPromise
    const normalized = options.normalizeResult(raw)
    if (!normalized) throw new Error('AI 返回格式异常')
    options.setCacheEntry(cacheKey, normalized)
    if (requestSeq !== options.getRequestSequence() || !options.isPageAlive()) return
    if (Number((options.getReviewDialog() || {}).questionId) !== questionId) {
      options.setData({ teacherLoading: false })
      return
    }
    options.setActiveCacheKey(cacheKey)
    options.setData({ teacherLoading: false, teacherResult: normalized })
  } catch (error) {
    if (requestSeq !== options.getRequestSequence() || !options.isPageAlive()) return
    options.setData({ teacherLoading: false, teacherErrorText: options.errorMessage(error) })
  } finally {
    if (options.getInflight(cacheKey) === requestPromise) options.deleteInflight(cacheKey)
  }
}

function buildPayload(dialog, questionId, action) {
  const payload = { question_id: questionId, action }
  if (Number(dialog.questionVersionId) > 0) payload.question_version_id = Number(dialog.questionVersionId)
  if (Number(dialog.diagnosisId) > 0) payload.diagnosis_id = Number(dialog.diagnosisId)
  if (dialog.userAnswer && dialog.userAnswer !== '未作答') payload.user_answer = String(dialog.userAnswer)
  return payload
}

module.exports = {
  createReview408TeacherController,
}
