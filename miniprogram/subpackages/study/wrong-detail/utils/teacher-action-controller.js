// Pure controller for run408TeacherAction. Extracted from
// subpackages/study/wrong-detail/wrong-detail.js.

function createTeacherActionController(options) {
  return {
    run: runImpl.bind(null, options),
  }
}

async function runImpl(options, event) {
  const action = String(event.currentTarget.dataset.action || '')
  if (!action) return
  if (options.getAiLoading() || options.getAiRegenerating()) {
    options.showToast({ title: 'AI 复盘生成中，请稍后', icon: 'none' })
    return
  }
  if (options.getTeacherLoadingAction()) {
    options.setData({ teacherSheetVisible: true })
    return
  }
  const wq = options.getWq() || {}
  const diagnosis = options.getErrorDiagnosis() || {}
  const questionId = Number(wq.question_id || wq.questionId || 0)
  if (!questionId) {
    options.showToast({ title: '缺少题目ID', icon: 'none' })
    return
  }
  const ctx = buildRequestContext(options, wq, diagnosis, action, questionId)
  const cached = options.getCacheEntry(ctx.cacheKey)
  options.setActiveCacheKey(ctx.cacheKey)
  if (cached) {
    options.setData(buildCachedPatch(action, ctx.cacheKey, cached, options))
    return
  }
  await performTeacherRequest(options, action, ctx)
}

function buildRequestContext(options, wq, diagnosis, action, questionId) {
  const versionId = Number(
    diagnosis.question_version_id || diagnosis.questionVersionId ||
    wq.question_version_id || wq.questionVersionId || 0
  )
  const diagnosisId = Number(diagnosis.id || 0)
  const cacheKey = options.buildCacheKey(wq, diagnosis, action)
  const payload = { question_id: questionId, action }
  if (versionId > 0) payload.question_version_id = versionId
  if (diagnosisId > 0) payload.diagnosis_id = diagnosisId
  if (wq.wrong_answer) payload.user_answer = String(wq.wrong_answer)
  return { cacheKey, payload, sourceWqId: String(wq.id || '') }
}

function buildCachedPatch(action, cacheKey, cached, options) {
  return {
    teacherLoadingAction: '', teacherLastAction: action, teacherErrorText: '',
    teacherResult: cached, teacherSheetVisible: true,
    teacherFeedbackSent: options.getFeedbackEntry(cacheKey) || '',
  }
}

async function performTeacherRequest(options, action, ctx) {
  const requestSeq = options.nextRequestSequence()
  let requestPromise = options.getInflight(ctx.cacheKey)
  if (!requestPromise) {
    requestPromise = options.postTeacher(ctx.payload)
    options.setInflight(ctx.cacheKey, requestPromise)
  }
  options.setData({
    teacherLoadingAction: action, teacherLastAction: action, teacherErrorText: '',
    teacherResult: null, teacherSheetVisible: true, teacherFeedbackSent: '',
  })
  try {
    const raw = await requestPromise
    const normalized = options.normalizeResult(raw)
    if (!normalized) throw new Error('AI 返回格式异常')
    const presented = options.presentResult(normalized)
    options.setCacheEntry(ctx.cacheKey, presented)
    if (requestSeq !== options.getRequestSequence() || !options.isAlive()) return
    if (String((options.getWq() && options.getWq().id) || '') !== ctx.sourceWqId) {
      options.setData({ teacherLoadingAction: '' })
      return
    }
    options.setActiveCacheKey(ctx.cacheKey)
    options.setData({ teacherLoadingAction: '', teacherResult: presented })
  } catch (error) {
    if (requestSeq !== options.getRequestSequence() || !options.isAlive()) return
    options.setData({ teacherLoadingAction: '', teacherErrorText: options.errorMessage(error) })
  } finally {
    if (options.getInflight(ctx.cacheKey) === requestPromise) options.deleteInflight(ctx.cacheKey)
  }
}

module.exports = {
  createTeacherActionController,
}
