const api = require('../../../utils/api')
const config = require('../../../config')
const {
buildRenderModel, resetRenderGuard, setRenderGuardPage
} = require('../utils/stem-render')
const { isTrueFalseType } = require('../utils/answer')
const adapter = require('../utils/question-runner-adapter')
const { normalizeAiAnalysisPayload, hasAiAnalysisContent } = require('../utils/ai-analysis-normalizer')
const { buildAiRichText } = require('../utils/ai-math-render')
const errorDiagnosis = require('../utils/error-diagnosis')
const aiTeacher408 = require('../utils/ai-teacher-408')
const AI_REQUEST_TIMEOUT_MS = 55000
const AI_CACHE_POLL_ATTEMPTS = 44
const QUESTION_SWITCH_OUT_MS = 150
const QUESTION_SWITCH_IN_MS = 170
const QUESTION_SWITCH_WATCHDOG_MS = 35000
const QUESTION_SWITCH_ANIM_WATCHDOG_MS = 5000
function _sleep(ms) {
return new Promise(resolve => setTimeout(resolve, ms))
}
function _aiPollDelayMs(attempt) {
if (attempt <= 5) return 2000
if (attempt <= 15) return 3000
return 5000
}
function _isTimeoutError(err) {
const message = [
err && err.message,
err && err.raw && err.raw.errMsg,
].filter(Boolean).join(' ').toLowerCase()
return message.includes('timeout') || message.includes('timed out')
}
function _generationMarker(wq) {
return String((wq && wq.ai_analysis_generated_at) || '')
}
function _fallbackMessage(model, errorCode, retryable) {
if (errorCode === 'ai_provider_auth_failed') return 'AI 分析服务鉴权失败，请联系管理员检查模型 API Key'
if (errorCode === 'ai_model_unconfigured') return 'AI 分析模型尚未正确配置，请联系管理员检查模型设置'
if (errorCode === 'ai_provider_rate_limited') return 'AI 服务当前繁忙，请稍后重试'
if (errorCode === 'ai_provider_timeout') return 'AI 分析生成超时，请稍后重试'
if (errorCode === 'ai_provider_transient') return 'AI 服务暂时不可用，请稍后重试'
if (errorCode === 'ai_response_parse_failed') return 'AI 返回格式异常，请重新生成'
if (model === 'timeout') return 'AI 分析生成超时，请稍后重试'
if (model === 'parse_failed') return 'AI 返回格式异常，请重新生成'
if (model === 'vision_input_missing') return '题目图片缺失或无法读取，AI 解析失败'
if (model === 'vision_unavailable') return '当前 AI 分析模型暂不支持图片理解，请稍后重试或联系管理员检查分析模型配置'
if (model === 'vision_parse_failed') return 'AI 未能正确读取题目图片，解析失败，请稍后重试'
if (retryable === false) return 'AI 服务配置异常，请联系管理员检查模型设置'
return 'AI 服务暂时不可用，请稍后重试'
}
function _subjectLabel(s) {
const { getSubjectName } = require('../utils/subject-meta')
return getSubjectName(s)
}
function _errorTypeLabel(t) {
const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他' }
return map[t] || t
}
function _processWqData(wq, safeMode) {
const questionType = wq.question_type || wq.type || ''
let opts = wq.options || null
if ((!opts || Object.keys(opts).length === 0) && isTrueFalseType(questionType)) {
opts = { A: '正确', B: '错误' }
}
const optionKeys = opts ? Object.keys(opts) : []
var renderCfg = { enableMathImage: false, DEV: config.DEV }
if (safeMode) renderCfg.SAFE_MODE = true
const _renderModel = buildRenderModel(wq, opts, renderCfg)
const _optionList = adapter.buildOptionListReadonly(wq, opts, optionKeys, wq.answer, wq.wrong_answer)
const blankOptionGroups = adapter.enrichBlankOptionGroupsReadonly(
adapter.getBlankOptionGroups(wq), wq.answer, wq.wrong_answer
)
return {
wq,
_optionList,
_optionKeys: optionKeys,
_opts: opts,
_blankOptionGroups: blankOptionGroups,
_hasBlankOptionGroups: blankOptionGroups.length > 0,
_renderModel,
subjectLabelText: wq.subject_name || _subjectLabel(wq.subject_code),
errorTypeLabelText: _errorTypeLabel(wq.error_type),
}
}
function _buildAiRichText(value) {
return buildAiRichText(value)
}
function _normalizeAiResult(content) {
const diagnosis = content.mistake_diagnosis || content.error_analysis || ''
const knowledge = content.knowledge_patch || content.knowledge_weakness || ''
const task = content.review_task || content.suggestion || ''
return {
mistakeDiagnosis: _buildAiRichText(String(diagnosis).replace(/^错因诊断[：:]\s*/, '')),
knowledgePatch: _buildAiRichText(String(knowledge).replace(/^补漏重点[：:]\s*/, '')),
reviewTask: _buildAiRichText(String(task).replace(/^复练任务[：:]\s*/, '')),
formatError: !!(content && content.formatError),
}
}
function _normalizeAiPayload(result) {
if (!result) return null
return normalizeAiAnalysisPayload(result)
}
function _hasAiContent(content) {
return hasAiAnalysisContent(content)
}
function _hasStoredAnalysisValue(raw) {
if (raw === null || raw === undefined) return false
if (typeof raw === 'string') {
const t = raw.trim()
if (!t) return false
if (/^(null|true|false|undefined|\[\]|\{\}|-?\d+(?:\.\d+)?)$/i.test(t)) return false
return true
}
if (Array.isArray(raw)) return raw.length > 0
if (typeof raw === 'object') {
if (Object.keys(raw).length === 0) return false
return hasAiAnalysisContent(normalizeAiAnalysisPayload(raw))
}
return true
}
function _detectAiCache(wq) {
if (!wq) return false
if (wq.ai_analysis_status && wq.ai_analysis_status !== 'ready') return false
return _hasStoredAnalysisValue(wq.ai_analysis)
}
function _resolvePreferredAnalysis(wq) {
if (!wq) return null
if ((!wq.ai_analysis_status || wq.ai_analysis_status === 'ready') && _hasStoredAnalysisValue(wq.ai_analysis)) {
return {
normalized: _normalizeAiPayload(wq.ai_analysis),
source: 'ai',
}
}
if (_hasStoredAnalysisValue(wq.analysis)) {
return {
normalized: _normalizeAiPayload(wq.analysis),
source: 'question',
}
}
return null
}
function _isWqMastered(wq) {
if (!wq) return false
return wq.is_mastered === true ||
wq.mastered === true ||
wq.review_status === 'mastered' ||
wq.status === 'mastered'
}
Page({
data: {
wq: null,
aiLoading: false,
aiFallback: false,
aiErrorText: '',
aiRetryable: true,
aiRequested: false,
aiFromCache: false,
loading: true,
errorText: '',
questionIds: [],
currentIdx: 0,
totalQuestions: 0,
safeModeActive: false,
aiCards: null,
aiFromQuestionAnalysis: false,
aiRegenerating: false,
aiSkeletonVisible: false,
aiInlineNotice: '',
aiReviewExpanded: false,
contentTransitionClass: '',
showSwitchMask: false,
renderTraces: [],
masterConfirmVisible: false,
unmasterConfirmVisible: false,
masterSubmitting: false,
isCurrentMastered: false,
masterUndoVisible: false,
moreMenuVisible: false,
removeConfirmVisible: false,
removeSubmitting: false,
errorDiagnosis: null,
diagnosisOptions: errorDiagnosis.TAXONOMY.filter(item => item.type !== 'unknown'),
diagnosisSheetVisible: false,
diagnosisPrimary: 'unknown',
diagnosisSecondaryMap: {},
diagnosisSaving: false,
diagnosisAiQueuing: false,
diagnosisAiEnabled: false,
teacherPrimaryActions: aiTeacher408.PRIMARY_ACTIONS,
teacherMoreActions: aiTeacher408.MORE_ACTIONS,
teacherActionsExpanded: false,
teacherLoadingAction: '',
teacherLastAction: '',
teacherResult: null,
teacherSheetVisible: false,
teacherErrorText: '',
teacherFeedbackSent: '',
bottomActionsVisible: true,
currentQuestion: null,
wrongQuestions: [],
runnerProgressPercent: 0,
skeletonOptions: [1, 2, 3, 4],
aiSkeletonSections: [1, 2, 3],
},
_alive: false,
_aiRequestId: 0,
_currentWqId: null,
_switching: false,
_navigationSeq: 0,
_aiResult: null,
_errorTypeLabelText: '',
_aiSwipeStart: null,
_contentTransitionStartedAt: 0,
_contentTransitionDirection: '',
_teacherRequestSeq: 0,
_diagnosisAiRequestSeq: 0,
_bottomActionsTimer: null,
_bottomActionsLastActiveAt: 0,
onLoad(options) {
setRenderGuardPage('wrong-detail')
this._alive = true
this._aiRequestId = 0
this._currentWqId = null
this._aiGenerationMarker = ''
this._switching = false
this._navigationSeq = 0
this._aiSwipeStart = null
this._contentTransitionStartedAt = 0
this._contentTransitionDirection = ''
this._teacherRequestSeq = 0
this._diagnosisAiRequestSeq = 0
this._teacherCache = Object.create(null)
this._teacherInflight = Object.create(null)
this._teacherFeedbackCache = Object.create(null)
this._activeTeacherCacheKey = ''
this._wqCache = {}
this._switchMaskTimer = null
this._contentTransitionTimer = null
this._switchWatchdogTimer = null
this._masterUndoTimer = null
this._masterAdvanceTimer = null
this._removeBackTimer = null
this._bottomActionsTimer = null
this._bottomActionsLastActiveAt = 0
this._masterUndoInFlight = false
this._pendingMasterUndo = null
const currentId = Number(options.id)
if (!Number.isFinite(currentId) || currentId <= 0) {
this.setData({ loading: false, errorText: '错题ID无效', wq: null })
return
}
let questionIds = []
try {
if (options.source === 'wrong-book' || options.source === 'practice-result') {
const nav = wx.getStorageSync('wrong_detail_nav')
if (nav && Array.isArray(nav.ids) && Date.now() - Number(nav.ts || 0) < 30 * 60 * 1000) {
const normalized = nav.ids.map(Number).filter(Number.isFinite)
const sourceMatches = !nav.source || nav.source === options.source
if (sourceMatches && normalized.includes(currentId)) questionIds = normalized
}
}
} catch (_) {}
if (!questionIds.length) questionIds = [currentId]
const currentIdx = questionIds.indexOf(currentId)
this.setData({
questionIds,
currentIdx: currentIdx >= 0 ? currentIdx : 0,
totalQuestions: questionIds.length,
})
this.loadData(currentId)
this._showBottomActions()
},
onShow() {
if (this._alive && this.data.wq) this._showBottomActions()
},
onHide() {
this._clearBottomActionsTimer()
},
onPageScroll() {
this._showBottomActions()
},
onPageInteraction() {
this._showBottomActions()
},
_clearBottomActionsTimer() {
if (!this._bottomActionsTimer) return
clearTimeout(this._bottomActionsTimer)
this._bottomActionsTimer = null
},
_scheduleBottomActionsAutoHide() {
if (!this._alive || this._bottomActionsTimer) return
const tick = () => {
this._bottomActionsTimer = null
if (!this._alive) return
const idleFor = Date.now() - Number(this._bottomActionsLastActiveAt || 0)
const wait = Math.max(0, 3000 - idleFor)
if (wait > 0) {
this._bottomActionsTimer = setTimeout(tick, wait)
return
}
if (this.data.bottomActionsVisible) this.setData({ bottomActionsVisible: false })
}
this._bottomActionsTimer = setTimeout(tick, 3000)
},
_showBottomActions() {
if (!this._alive) return
this._bottomActionsLastActiveAt = Date.now()
if (!this.data.bottomActionsVisible) this.setData({ bottomActionsVisible: true })
this._scheduleBottomActionsAutoHide()
},
onUnload() {
this._alive = false
this._aiRequestId++
this._teacherRequestSeq++
this._diagnosisAiRequestSeq++
if (this._switchMaskTimer) {
clearTimeout(this._switchMaskTimer)
this._switchMaskTimer = null
}
if (this._contentTransitionTimer) {
clearTimeout(this._contentTransitionTimer)
this._contentTransitionTimer = null
}
if (this._switchWatchdogTimer) {
clearTimeout(this._switchWatchdogTimer)
this._switchWatchdogTimer = null
}
if (this._removeBackTimer) {
clearTimeout(this._removeBackTimer)
this._removeBackTimer = null
}
this._clearBottomActionsTimer()
this._clearMasterUndo()
this._wqCache = null
this._teacherCache = null
this._teacherInflight = null
this._teacherFeedbackCache = null
this._activeTeacherCacheKey = ''
this._aiGenerationMarker = ''
resetRenderGuard()
},
async loadData(wqId) {
var loadSeq = ++this._aiRequestId
this._resetAiLoadingState()
this._aiResult = null
this.setData({
loading: true,
errorText: '',
aiFallback: false,
aiErrorText: '',
aiRetryable: true,
aiRequested: false,
aiFromCache: false,
aiFromQuestionAnalysis: false,
masterConfirmVisible: false,
unmasterConfirmVisible: false,
moreMenuVisible: false,
removeConfirmVisible: false,
masterSubmitting: false,
removeSubmitting: false,
diagnosisSheetVisible: false,
diagnosisSaving: false,
diagnosisAiQueuing: false,
diagnosisAiEnabled: false,
})
this._diagnosisAiRequestSeq++
this._teacherRequestSeq++
try {
const wq = await api.get(`/wrong-questions/${wqId}`)
if (loadSeq !== this._aiRequestId || !this._alive) return
if (!wq) throw new Error('not found')
if (this._wqCache) this._wqCache[wqId] = { data: wq, ts: Date.now() }
const raw = _processWqData(wq, this.data.safeModeActive)
const currentQuestion = Object.assign({}, wq, {
_optionList: raw._optionList,
_optionKeys: raw._optionKeys,
_opts: raw._opts,
_blankOptionGroups: raw._blankOptionGroups,
_hasBlankOptionGroups: raw._hasBlankOptionGroups,
_renderModel: raw._renderModel,
})
var totalQ = this.data.totalQuestions || 1
var wrongQuestions = []
for (var wi = 0; wi < totalQ; wi++) {
wrongQuestions.push({ _answered: true })
}
this._currentWqId = wqId
this._diagnosisAiRequestSeq++
this._teacherRequestSeq++
this._errorTypeLabelText = raw.errorTypeLabelText
this._aiGenerationMarker = _generationMarker(wq)
this._aiResult = null
var data = {
wq,
currentQuestion,
wrongQuestions,
runnerProgressPercent: totalQ > 0 ? Math.round((this.data.currentIdx + 1) / totalQ * 100) : 0,
subjectLabelText: raw.subjectLabelText,
loading: false,
aiLoading: false,
errorText: '',
aiCards: null,
aiRequested: false,
aiFromCache: false,
aiFromQuestionAnalysis: false,
aiFallback: false,
aiErrorText: '',
aiRetryable: true,
aiReviewExpanded: false,
isCurrentMastered: _isWqMastered(wq),
masterSubmitting: false,
removeSubmitting: false,
errorDiagnosis: errorDiagnosis.normalizeDiagnosis(wq.error_diagnosis),
diagnosisAiEnabled: false,
teacherLoadingAction: '',
teacherLastAction: '',
teacherResult: null,
teacherSheetVisible: false,
teacherErrorText: '',
teacherFeedbackSent: '',
teacherActionsExpanded: false,
}
var preferredAnalysis = _resolvePreferredAnalysis(wq)
if (preferredAnalysis) {
var preferredNormalized = preferredAnalysis.normalized
data.aiRequested = true
if (_hasAiContent(preferredNormalized)) {
this._aiResult = preferredNormalized
data.aiCards = _normalizeAiResult(this._aiResult)
data.aiFromCache = preferredAnalysis.source === 'ai'
data.aiFromQuestionAnalysis = preferredAnalysis.source === 'question'
data.aiFallback = false
data.aiErrorText = ''
} else {
this._aiResult = null
data.aiCards = null
data.aiFromCache = false
data.aiFromQuestionAnalysis = false
data.aiFallback = true
data.aiErrorText = preferredNormalized && preferredNormalized.formatError
? 'AI 返回格式异常，请重新生成'
: 'AI 分析结果为空，请重新生成'
}
}
if (loadSeq !== this._aiRequestId || !this._alive) return
this.setData(data)
const checkModel = data.currentQuestion && data.currentQuestion._renderModel
if (checkModel) {
this._checkRenderInvariant(checkModel)
this._recordRenderTrace(checkModel.renderTrace)
}
} catch (e) {
if (loadSeq !== this._aiRequestId || !this._alive) return
console.error('加载错题详情失败', e)
this._aiResult = null
this.setData({
loading: false,
errorText: '错题不存在或已被移除',
wq: null,
aiLoading: false,
aiFallback: false,
aiErrorText: '',
aiRequested: false,
aiFromCache: false,
aiFromQuestionAnalysis: false,
})
}
},
_resetAiLoadingState() {
this.setData({
aiLoading: false,
aiRegenerating: false,
aiSkeletonVisible: false,
aiInlineNotice: '',
})
},
_syncWqCacheAi(wqId, normalized, generatedAt) {
if (!this._wqCache || !wqId || !normalized) return
const entry = this._wqCache[wqId]
if (!entry) return
const patch = { ai_analysis: normalized }
if (generatedAt !== undefined) patch.ai_analysis_generated_at = String(generatedAt || '')
entry.data = Object.assign({}, entry.data, patch)
},
async _requestAiAnalysis(wqId, forceRegenerate) {
return api.post('/ai/error-analysis', {
wrong_question_id: wqId,
force_regenerate: !!forceRegenerate,
}, {
timeout: AI_REQUEST_TIMEOUT_MS,
suppressNetworkToast: true,
})
},
async _enqueueAiRecovery(wqId, forceRegenerate, baselineGeneratedAt) {
try {
const payload = {
wrong_question_id: wqId,
force_regenerate: !!forceRegenerate,
}
if (forceRegenerate) payload.baseline_generated_at = String(baselineGeneratedAt || '')
const result = await api.post('/ai/error-analysis/recover', payload, {
timeout: 10000,
suppressNetworkToast: true,
})
return !!(result && result.queued)
} catch (e) {
console.warn('AI 恢复任务入队失败，将继续轮询原请求结果', e)
return false
}
},
_analysisFailureState(model, result) {
return {
aiErrorText: _fallbackMessage(
model,
result && result.error_code,
result && result.retryable
),
aiRetryable: !(result && result.retryable === false),
}
},
onTapAiAnalysis() {
if (this.data.aiLoading || this.data.aiRegenerating) return
const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
if (!wqId) {
wx.showToast({ title: '缺少错题ID', icon: 'none' })
return
}
this.loadAiAnalysis(wqId)
},
toggleAiReview() {
if (!this.data.aiCards || this.data.aiRegenerating) return
this.setData({ aiReviewExpanded: !this.data.aiReviewExpanded })
},
toggleTeacherActions() {
if (this.data.teacherLoadingAction) return
this.setData({ teacherActionsExpanded: !this.data.teacherActionsExpanded })
},
_teacherCacheKeyForWrong(wq, diagnosis, action) {
const item = wq || {}
const d = diagnosis || {}
return [
Number(item.id || 0),
Number(item.question_id || item.questionId || 0),
Number(d.question_version_id || d.questionVersionId || item.question_version_id || item.questionVersionId || 0),
Number(d.id || 0),
String(action || ''),
String(item.wrong_answer || ''),
].join('|')
},
async run408TeacherAction(e) {
const action = String(e.currentTarget.dataset.action || '')
if (!action) return
if (this.data.aiLoading || this.data.aiRegenerating) {
wx.showToast({ title: 'AI 复盘生成中，请稍后', icon: 'none' })
return
}
if (this.data.teacherLoadingAction) {
this.setData({ teacherSheetVisible: true })
return
}
const wq = this.data.wq || {}
const diagnosis = this.data.errorDiagnosis || {}
const questionId = Number(wq.question_id || wq.questionId || 0)
if (!questionId) {
wx.showToast({ title: '缺少题目ID', icon: 'none' })
return
}
const versionId = Number(
diagnosis.question_version_id || diagnosis.questionVersionId || wq.question_version_id || wq.questionVersionId || 0
)
const diagnosisId = Number(diagnosis.id || 0)
const cacheKey = this._teacherCacheKeyForWrong(wq, diagnosis, action)
const cached = this._teacherCache && this._teacherCache[cacheKey]
this._activeTeacherCacheKey = cacheKey
if (cached) {
this.setData({
teacherLoadingAction: '',
teacherLastAction: action,
teacherErrorText: '',
teacherResult: cached,
teacherSheetVisible: true,
teacherFeedbackSent: (this._teacherFeedbackCache && this._teacherFeedbackCache[cacheKey]) || '',
})
return
}
const requestSeq = ++this._teacherRequestSeq
const sourceWqId = String(wq.id || '')
const payload = { question_id: questionId, action: action }
if (versionId > 0) payload.question_version_id = versionId
if (diagnosisId > 0) payload.diagnosis_id = diagnosisId
if (wq.wrong_answer) payload.user_answer = String(wq.wrong_answer)
if (!this._teacherInflight) this._teacherInflight = Object.create(null)
let requestPromise = this._teacherInflight[cacheKey]
if (!requestPromise) {
requestPromise = api.post('/ai/408-teacher', payload, { timeout: AI_REQUEST_TIMEOUT_MS })
this._teacherInflight[cacheKey] = requestPromise
}
this.setData({
teacherLoadingAction: action,
teacherLastAction: action,
teacherErrorText: '',
teacherResult: null,
teacherSheetVisible: true,
teacherFeedbackSent: '',
})
try {
const raw = await requestPromise
const normalized = aiTeacher408.normalizeResult(raw)
if (!normalized) throw new Error('AI 返回格式异常')
if (!this._teacherCache) this._teacherCache = Object.create(null)
this._teacherCache[cacheKey] = normalized
if (requestSeq !== this._teacherRequestSeq || !this._alive) return
if (String((this.data.wq && this.data.wq.id) || '') !== sourceWqId) {
this.setData({ teacherLoadingAction: '' })
return
}
this._activeTeacherCacheKey = cacheKey
this.setData({ teacherLoadingAction: '', teacherResult: normalized })
} catch (error) {
if (requestSeq !== this._teacherRequestSeq || !this._alive) return
this.setData({
teacherLoadingAction: '',
teacherErrorText: aiTeacher408.errorMessage(error, api),
})
} finally {
if (this._teacherInflight && this._teacherInflight[cacheKey] === requestPromise) {
delete this._teacherInflight[cacheKey]
}
}
},
close408TeacherSheet() {
this.setData({ teacherSheetVisible: false })
},
async feedback408Teacher(e) {
if (this.data.teacherFeedbackSent || !this.data.teacherResult) return
const type = String(e.currentTarget.dataset.type || '')
const wq = this.data.wq || {}
const questionId = Number(wq.question_id || wq.questionId || 0)
if (!type || !questionId) return
try {
await aiTeacher408.submitFeedback(api, {
questionId,
feedbackType: type,
result: this.data.teacherResult,
})
if (this._activeTeacherCacheKey) {
if (!this._teacherFeedbackCache) this._teacherFeedbackCache = Object.create(null)
this._teacherFeedbackCache[this._activeTeacherCacheKey] = type
}
this.setData({ teacherFeedbackSent: type })
wx.showToast({ title: '反馈已记录', icon: 'success' })
} catch (error) {
wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
}
},
_isCurrentAiRequest(requestId, wqId) {
return requestId === this._aiRequestId &&
this._alive &&
this.data.wq &&
String(this.data.wq.id) === String(wqId)
},
async _pollPersistedAiAnalysis(wqId, requestId, options) {
const pollOptions = options || {}
const baselineGeneratedAt = String(pollOptions.baselineGeneratedAt || '')
const requireNewGeneration = !!pollOptions.requireNewGeneration
for (var attempt = 0; attempt < AI_CACHE_POLL_ATTEMPTS; attempt++) {
if (!this._isCurrentAiRequest(requestId, wqId)) return null
if (attempt > 0) await _sleep(_aiPollDelayMs(attempt))
if (!this._isCurrentAiRequest(requestId, wqId)) return null
try {
const status = await api.get(`/ai/error-analysis/status/${wqId}`, {}, {
timeout: 10000,
suppressNetworkToast: true,
})
if (!this._isCurrentAiRequest(requestId, wqId)) return null
if (!status || !status.ready) continue
const generatedAt = String(status.generated_at || '')
if (requireNewGeneration && generatedAt === baselineGeneratedAt) continue
const normalized = _normalizeAiPayload(status.content)
if (_hasAiContent(normalized)) {
const latestWq = Object.assign({}, this.data.wq || {}, {
ai_analysis: normalized,
ai_analysis_status: 'ready',
ai_analysis_generated_at: generatedAt,
})
return { normalized, latestWq, generatedAt }
}
} catch (_) {
}
}
return null
},
_applyRecoveredAiResult(recovered, options) {
if (!recovered) return false
const applyOptions = options || {}
this._resetAiLoadingState()
this._aiResult = recovered.normalized
this._aiGenerationMarker = String(recovered.generatedAt || _generationMarker(recovered.latestWq) || '')
if (recovered.latestWq) {
this._syncWqCacheAi(
recovered.latestWq.id,
recovered.normalized,
this._aiGenerationMarker
)
}
const latestWq = recovered.latestWq || this.data.wq
this.setData({
wq: latestWq,
aiCards: _normalizeAiResult(recovered.normalized),
aiReviewExpanded: false,
aiFallback: false,
aiFromCache: !applyOptions.fromRegeneration,
aiFromQuestionAnalysis: false,
aiErrorText: '',
aiRetryable: true,
aiInlineNotice: '',
})
return true
},
async loadAiAnalysis(wqId) {
if (!wqId) return
if (this.data.aiLoading) return
const baselineGeneratedAt = String(this._aiGenerationMarker || _generationMarker(this.data.wq) || '')
const requestId = ++this._aiRequestId
this.setData({
aiLoading: true,
aiRequested: true,
aiFallback: false,
aiErrorText: '',
aiRetryable: true,
aiInlineNotice: '',
})
try {
const result = await this._requestAiAnalysis(wqId, false)
if (!this._isCurrentAiRequest(requestId, wqId)) {
this._resetAiLoadingState()
return
}
const normalized = _normalizeAiPayload(result)
const hasContent = _hasAiContent(normalized)
const model = (result && result.model) || ''
const fromFallback = !!(result && result.from_fallback)
if (model === 'generating') {
const recovered = await this._pollPersistedAiAnalysis(wqId, requestId, {
requireNewGeneration: true,
baselineGeneratedAt,
})
if (this._applyRecoveredAiResult(recovered)) return
if (!this._isCurrentAiRequest(requestId, wqId)) return
this._resetAiLoadingState()
this.setData({ aiFallback: true, aiErrorText: 'AI 分析正在生成中，请稍后重试' })
return
}
if (fromFallback) {
this._resetAiLoadingState()
this.setData(Object.assign({ aiFallback: true }, this._analysisFailureState(model, result)))
return
}
if (!hasContent) {
this._resetAiLoadingState()
this.setData({ aiFallback: true, aiErrorText: 'AI 分析结果为空，请稍后重试' })
return
}
this._resetAiLoadingState()
this._aiResult = normalized
this._aiGenerationMarker = String((result && result.generated_at) || this._aiGenerationMarker || '')
this._syncWqCacheAi(wqId, normalized, this._aiGenerationMarker)
this.setData({
aiCards: _normalizeAiResult(normalized),
aiReviewExpanded: false,
aiFallback: false,
aiFromCache: !!(result && result.from_cache),
aiFromQuestionAnalysis: false,
aiErrorText: '',
aiRetryable: true,
})
} catch (e) {
console.error('加载 AI 分析失败', e)
if (this._isCurrentAiRequest(requestId, wqId)) {
this.setData({ aiInlineNotice: 'AI 正在继续生成，完成后会自动显示' })
this._enqueueAiRecovery(wqId, false, '')
const recovered = await this._pollPersistedAiAnalysis(wqId, requestId, {
requireNewGeneration: true,
baselineGeneratedAt,
})
if (this._applyRecoveredAiResult(recovered)) return
}
if (this._isCurrentAiRequest(requestId, wqId)) {
const msg = _isTimeoutError(e)
? 'AI 分析生成超时，请稍后重试'
: 'AI 分析生成失败，请稍后重试'
this._resetAiLoadingState()
this.setData({ aiFallback: true, aiErrorText: msg })
}
}
},
async regenerateAiAnalysis() {
const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
if (!wqId || this.data.aiLoading || this.data.aiRegenerating) return
const oldCards = this.data.aiCards
const oldResult = this._aiResult
const baselineGeneratedAt = String(this._aiGenerationMarker || _generationMarker(this.data.wq) || '')
const requestId = ++this._aiRequestId
this.setData({
aiRegenerating: true,
aiSkeletonVisible: true,
aiErrorText: '',
aiRetryable: true,
aiFallback: false,
aiInlineNotice: '',
})
try {
const result = await this._requestAiAnalysis(wqId, true)
if (!this._isCurrentAiRequest(requestId, wqId)) {
this._resetAiLoadingState()
return
}
const normalized = _normalizeAiPayload(result)
const hasContent = _hasAiContent(normalized)
const model = (result && result.model) || ''
const fromFallback = !!(result && result.from_fallback)
const cachePreserved = !!(result && result.cache_preserved)
if (model === 'generating') {
this.setData({ aiInlineNotice: 'AI 正在生成中，完成后会自动更新' })
const recovered = await this._pollPersistedAiAnalysis(wqId, requestId, {
requireNewGeneration: true,
baselineGeneratedAt,
})
if (this._applyRecoveredAiResult(recovered, { fromRegeneration: true })) {
wx.showToast({ title: '已重新生成', icon: 'success' })
return
}
if (!this._isCurrentAiRequest(requestId, wqId)) return
this._resetAiLoadingState()
this.setData({ aiInlineNotice: 'AI 正在生成中，请稍后重试' })
return
}
if (cachePreserved && hasContent) {
this._resetAiLoadingState()
this._aiResult = normalized
this._aiGenerationMarker = String((result && result.generated_at) || baselineGeneratedAt || '')
this._syncWqCacheAi(wqId, normalized, this._aiGenerationMarker)
this.setData({
aiCards: _normalizeAiResult(normalized),
aiFallback: false,
aiFromCache: true,
aiFromQuestionAnalysis: false,
aiInlineNotice: '重新生成失败，已保留历史解析',
})
wx.showToast({ title: '重新生成失败，已保留历史解析', icon: 'none' })
return
}
if (fromFallback) {
this._resetAiLoadingState()
var failure = this._analysisFailureState(model, result)
if (oldCards) {
this.setData({
aiFallback: false,
aiInlineNotice: failure.aiErrorText || '重新生成失败，已保留当前解析',
})
wx.showToast({ title: '重新生成失败，已保留当前解析', icon: 'none' })
} else {
this.setData(Object.assign({ aiFallback: true }, failure))
}
return
}
if (!hasContent) {
if (oldCards) {
this._resetAiLoadingState()
this.setData({
aiFallback: false,
aiInlineNotice: '返回内容为空，已保留当前解析',
})
wx.showToast({ title: '返回内容为空，已保留当前解析', icon: 'none' })
} else {
this._resetAiLoadingState()
this.setData({ aiFallback: true, aiErrorText: 'AI 返回内容为空，请稍后重试' })
}
return
}
this._resetAiLoadingState()
this._aiResult = normalized
this._aiGenerationMarker = String((result && result.generated_at) || this._aiGenerationMarker || '')
this._syncWqCacheAi(wqId, normalized, this._aiGenerationMarker)
this.setData({
aiCards: _normalizeAiResult(normalized),
aiReviewExpanded: false,
aiFallback: false,
aiFromCache: !!(result && result.from_cache),
aiFromQuestionAnalysis: false,
aiErrorText: '',
aiRetryable: true,
})
wx.showToast({ title: '已重新生成', icon: 'success' })
} catch (e) {
console.error('重新生成 AI 分析失败', e)
if (this._isCurrentAiRequest(requestId, wqId)) {
this.setData({ aiInlineNotice: 'AI 正在继续重新生成，完成后会自动更新' })
this._enqueueAiRecovery(wqId, true, baselineGeneratedAt)
const recovered = await this._pollPersistedAiAnalysis(wqId, requestId, {
requireNewGeneration: true,
baselineGeneratedAt,
})
if (this._applyRecoveredAiResult(recovered, { fromRegeneration: true })) {
wx.showToast({ title: '已重新生成', icon: 'success' })
return
}
}
if (this._isCurrentAiRequest(requestId, wqId)) {
const timeoutText = _isTimeoutError(e) ? '重新生成超时' : '重新生成失败'
if (oldCards) {
this._resetAiLoadingState()
this._aiResult = oldResult
this.setData({
aiCards: oldCards,
aiFallback: false,
aiInlineNotice: `${timeoutText}，已保留历史解析`,
})
wx.showToast({ title: `${timeoutText}，已保留历史解析`, icon: 'none' })
} else {
this._resetAiLoadingState()
this.setData({ aiErrorText: `${timeoutText}，请稍后重试` })
wx.showToast({ title: timeoutText, icon: 'none' })
}
}
}
},
openMasterConfirm() {
if (this.data.masterSubmitting || this.data.isCurrentMastered) return
this.setData({ masterConfirmVisible: true })
},
closeMasterConfirm() {
if (this.data.masterSubmitting) return
this.setData({ masterConfirmVisible: false })
},
openUnmasterConfirm() {
if (this.data.masterSubmitting || !this.data.isCurrentMastered) return
this.setData({ unmasterConfirmVisible: true })
},
closeUnmasterConfirm() {
if (this.data.masterSubmitting) return
this.setData({ unmasterConfirmVisible: false })
},
onMasterAction() {
if (this.data.isCurrentMastered) {
this.openUnmasterConfirm()
} else {
this.openMasterConfirm()
}
},
async confirmMastered() {
const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
if (!wqId || this.data.masterSubmitting) return
this.setData({ masterSubmitting: true, masterConfirmVisible: false })
try {
const masterResult = await api.post('/wrong-questions/batch', {
action: 'mark_mastered',
ids: [wqId],
})
if (!this._alive) return
const masterSkipped = !!(
masterResult && Array.isArray(masterResult.skipped_ids) &&
masterResult.skipped_ids.some(id => String(id) === String(wqId))
)
const masterChanged = !masterSkipped && !(
masterResult && masterResult.updated_count != null && Number(masterResult.updated_count) <= 0
)
if (!masterChanged) {
this._clearMasterUndo()
this.setData({ masterSubmitting: false })
await this.loadData(wqId)
if (this._alive) wx.showToast({ title: '题目状态已同步', icon: 'none' })
return
}
this._clearMasterUndo()
this._pendingMasterUndo = {
wqId,
originalIdx: this.data.currentIdx,
}
if (this._wqCache && this._wqCache[wqId]) {
this._wqCache[wqId].data = Object.assign({}, this._wqCache[wqId].data, { is_mastered: true })
}
if (this.data.wq && String(this.data.wq.id) === String(wqId)) {
this.setData({
wq: Object.assign({}, this.data.wq, { is_mastered: true }),
isCurrentMastered: true,
masterSubmitting: false,
masterUndoVisible: true,
})
} else {
this.setData({ masterSubmitting: false, masterUndoVisible: true })
}
this._armMasterUndoExpiry(5000)
if (this.data.currentIdx < this.data.questionIds.length - 1) {
this._masterAdvanceTimer = setTimeout(() => {
this._masterAdvanceTimer = null
this._navigateTo(this.data.currentIdx + 1, 150)
}, 120)
}
} catch (e) {
if (!this._alive) return
console.error('标记已掌握失败', e)
this.setData({ masterSubmitting: false })
wx.showToast({ title: '操作失败，请重试', icon: 'none' })
}
},
async confirmUnmastered() {
const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
if (!wqId || this.data.masterSubmitting) return
this.setData({ masterSubmitting: true, unmasterConfirmVisible: false })
try {
const unmasterResult = await api.post('/wrong-questions/batch', {
action: 'unmark_mastered',
ids: [wqId],
})
if (!this._alive) return
const unmasterSkipped = !!(
unmasterResult && Array.isArray(unmasterResult.skipped_ids) &&
unmasterResult.skipped_ids.some(id => String(id) === String(wqId))
)
if (unmasterSkipped || (unmasterResult && unmasterResult.updated_count != null && Number(unmasterResult.updated_count) <= 0)) {
this._clearMasterUndo()
this.setData({ masterSubmitting: false })
await this.loadData(wqId)
if (this._alive) wx.showToast({ title: '题目状态已同步', icon: 'none' })
return
}
this._clearMasterUndo()
if (this._wqCache && this._wqCache[wqId]) {
this._wqCache[wqId].data = Object.assign({}, this._wqCache[wqId].data, { is_mastered: false })
}
if (this.data.wq && String(this.data.wq.id) === String(wqId)) {
this.setData({
wq: Object.assign({}, this.data.wq, { is_mastered: false }),
isCurrentMastered: false,
masterSubmitting: false,
})
} else {
this.setData({ masterSubmitting: false })
}
wx.showToast({ title: '已重新加入复习', icon: 'none' })
} catch (e) {
if (!this._alive) return
console.error('重新加入复习失败', e)
this.setData({ masterSubmitting: false })
wx.showToast({ title: '操作失败，请重试', icon: 'none' })
}
},
async undoMastered() {
const pending = this._pendingMasterUndo
if (!pending || this._masterUndoInFlight) return
this._masterUndoInFlight = true
if (this._masterUndoTimer) {
clearTimeout(this._masterUndoTimer)
this._masterUndoTimer = null
}
if (this._masterAdvanceTimer) {
clearTimeout(this._masterAdvanceTimer)
this._masterAdvanceTimer = null
}
if (this._switching) this._forceResetSwitchLock()
try {
const undoResult = await api.post('/wrong-questions/batch', {
action: 'unmark_mastered',
ids: [pending.wqId],
})
if (!this._alive) return
const undoSkipped = !!(
undoResult && Array.isArray(undoResult.skipped_ids) &&
undoResult.skipped_ids.some(id => String(id) === String(pending.wqId))
) || !!(
undoResult && undoResult.updated_count != null && Number(undoResult.updated_count) <= 0
)
if (undoSkipped) {
try {
const fresh = await api.get(`/wrong-questions/${pending.wqId}`)
if (!this._alive) return
if (!fresh) throw Object.assign(new Error('not found'), { statusCode: 404 })
if (this._wqCache) this._wqCache[pending.wqId] = { data: fresh, ts: Date.now() }
const targetIdx = (this.data.questionIds || []).findIndex(id => String(id) === String(pending.wqId))
this._clearMasterUndo()
if (targetIdx >= 0 && targetIdx !== this.data.currentIdx) {
await this._navigateTo(targetIdx, 150)
} else if (targetIdx >= 0) {
await this.loadData(pending.wqId)
}
if (this._alive) wx.showToast({ title: '题目状态已同步', icon: 'none' })
return
} catch (freshError) {
const freshStatus = Number(freshError && (freshError.statusCode || freshError.status)) || 0
if (freshStatus === 404 || freshStatus === 410) {
this._clearMasterUndo()
this._dropQuestionFromNavigation(pending.wqId)
if (this._alive) wx.showToast({ title: '该错题已被移除，无法撤销', icon: 'none' })
return
}
throw freshError
}
}
if (this._wqCache && this._wqCache[pending.wqId]) {
this._wqCache[pending.wqId].data = Object.assign({}, this._wqCache[pending.wqId].data, { is_mastered: false })
}
const targetIdx = this.data.questionIds.findIndex(id => String(id) === String(pending.wqId))
this._clearMasterUndo()
if (targetIdx >= 0 && targetIdx !== this.data.currentIdx) {
await this._navigateTo(targetIdx, 150)
} else if (this.data.wq && String(this.data.wq.id) === String(pending.wqId)) {
this.setData({
wq: Object.assign({}, this.data.wq, { is_mastered: false }),
isCurrentMastered: false,
})
} else if (targetIdx >= 0) {
await this.loadData(pending.wqId)
}
wx.showToast({ title: '已撤销掌握', icon: 'none' })
} catch (e) {
if (!this._alive) return
console.error('撤销已掌握失败', e)
if (this._pendingMasterUndo === pending) {
this.setData({ masterUndoVisible: true })
this._armMasterUndoExpiry(5000)
}
wx.showToast({ title: '撤销失败，请重试', icon: 'none' })
} finally {
this._masterUndoInFlight = false
}
},
_armMasterUndoExpiry(ms) {
if (this._masterUndoTimer) clearTimeout(this._masterUndoTimer)
var duration = Number(ms) > 0 ? Number(ms) : 5000
this._masterUndoTimer = setTimeout(() => {
this._pendingMasterUndo = null
this._masterUndoTimer = null
if (this._alive) this.setData({ masterUndoVisible: false })
}, duration)
},
_clearMasterUndo() {
if (this._masterUndoTimer) {
clearTimeout(this._masterUndoTimer)
this._masterUndoTimer = null
}
if (this._masterAdvanceTimer) {
clearTimeout(this._masterAdvanceTimer)
this._masterAdvanceTimer = null
}
this._pendingMasterUndo = null
if (this._alive && this.data && this.data.masterUndoVisible) {
this.setData({ masterUndoVisible: false })
}
},
openMoreMenu() {
this.setData({ moreMenuVisible: true })
},
closeMoreMenu() {
this.setData({ moreMenuVisible: false })
},
openRemoveConfirm() {
this.setData({ moreMenuVisible: false, removeConfirmVisible: true })
},
closeRemoveConfirm() {
if (this.data.removeSubmitting) return
this.setData({ removeConfirmVisible: false })
},
async removeFromWrongBook() {
const wqId = this._currentWqId || (this.data.wq && this.data.wq.id)
if (!wqId || this.data.removeSubmitting) return
this._clearMasterUndo()
this.setData({ removeSubmitting: true })
try {
await api.post('/wrong-questions/batch', {
action: 'remove_from_book',
ids: [wqId],
})
if (!this._alive) return
const oldIds = this.data.questionIds || []
const currentIdx = this.data.currentIdx
const nextIds = oldIds.filter(id => String(id) !== String(wqId))
if (this._wqCache) delete this._wqCache[wqId]
try {
wx.setStorageSync('wrong_detail_nav', { ids: nextIds, ts: Date.now() })
} catch (_) {}
this.setData({
questionIds: nextIds,
totalQuestions: nextIds.length,
removeConfirmVisible: false,
removeSubmitting: false,
})
if (!nextIds.length) {
wx.showToast({ title: '已移出错题本', icon: 'none' })
if (this._removeBackTimer) clearTimeout(this._removeBackTimer)
this._removeBackTimer = setTimeout(() => {
this._removeBackTimer = null
if (this._alive) this.goBack()
}, 220)
return
}
const nextIdx = Math.min(currentIdx, nextIds.length - 1)
this.setData({ currentIdx: nextIdx })
await this.loadData(nextIds[nextIdx])
wx.showToast({ title: '已移出错题本', icon: 'none' })
} catch (e) {
if (!this._alive) return
console.error('移出错题本失败', e)
this.setData({ removeSubmitting: false })
wx.showToast({ title: '移出失败，请重试', icon: 'none' })
}
},
_checkRenderInvariant(renderModel) {
if (!renderModel) return
if (renderModel.mode === 'CODE' && renderModel.rawText) {
var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
if (hasHtmlLeak) {
console.error('[CODE_HTML_LEAK] wrong-detail CODE rawText contains HTML entities')
}
var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
if (hasRenderViolation) {
console.error('[CODE_RENDER_VIOLATION] wrong-detail CODE mode leaked into html/richTextNodes')
}
if ((hasHtmlLeak || hasRenderViolation) && !this.data.safeModeActive) {
this._enterSafeMode()
}
}
if (renderModel.mode === 'MIXED') {
if (!renderModel.blocks || renderModel.blocks.length === 0) {
console.error('[MIXED_RENDER_VIOLATION] wrong-detail MIXED mode but blocks is empty')
return
}
for (var mi = 0; mi < renderModel.blocks.length; mi++) {
var mBlock = renderModel.blocks[mi]
if (mBlock.type === 'CODE' && mBlock.rawText) {
if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
console.error('[CODE_HTML_LEAK] wrong-detail MIXED CODE block #' + mi + ' contains HTML entities')
}
}
}
}
},
_recordRenderTrace(trace) {
if (!trace || !config.debug) return
if (!Array.isArray(this.data.renderTraces)) return
var traces = this.data.renderTraces.concat([trace]).slice(-20)
this.setData({ renderTraces: traces })
},
_enterSafeMode() {
console.warn('[SELF_HEAL] wrong-detail CODE render violation — entering SAFE_MODE')
this.setData({ safeModeActive: true })
if (this.data.wq) {
var raw = _processWqData(this.data.wq, true)
if (raw._renderModel) {
var currentQuestion = Object.assign({}, this.data.wq, {
_optionList: raw._optionList,
_optionKeys: raw._optionKeys,
_opts: raw._opts,
_blankOptionGroups: raw._blankOptionGroups,
_hasBlankOptionGroups: raw._blankOptionGroups.length > 0,
_renderModel: raw._renderModel,
})
this._errorTypeLabelText = raw.errorTypeLabelText
this.setData({
currentQuestion,
subjectLabelText: raw.subjectLabelText,
})
console.warn('[SELF_HEAL] wrong-detail re-rendered in SAFE_MODE, mode=' + raw._renderModel.mode)
}
}
},
onAiSwipeStart(e) {
if (this._switching) return
const touch = e && e.touches && e.touches[0]
if (!touch) return
this._aiSwipeStart = {
x: Number(touch.clientX),
y: Number(touch.clientY),
ts: Date.now(),
}
},
onAiSwipeEnd(e) {
const start = this._aiSwipeStart
this._aiSwipeStart = null
if (!start || this._switching) return
const touch = e && e.changedTouches && e.changedTouches[0]
if (!touch) return
const dx = Number(touch.clientX) - start.x
const dy = Number(touch.clientY) - start.y
const absX = Math.abs(dx)
const absY = Math.abs(dy)
if (absX < 56 || absX <= absY * 1.2) return
const targetIdx = dx < 0 ? this.data.currentIdx + 1 : this.data.currentIdx - 1
if (targetIdx < 0 || targetIdx >= this.data.questionIds.length) return
this._navigateTo(targetIdx, 150, dx < 0 ? 'left' : 'right')
},
onAiSwipeCancel() {
this._aiSwipeStart = null
},
_beginContentSwitchTransition(direction) {
if (!this._alive) return
const dir = direction === 'right' ? 'right' : 'left'
if (this._contentTransitionTimer) {
clearTimeout(this._contentTransitionTimer)
this._contentTransitionTimer = null
}
this._contentTransitionStartedAt = Date.now()
this._contentTransitionDirection = dir
this.setData({
contentTransitionClass: dir === 'left' ? 'content-slide-out-left' : 'content-slide-out-right',
})
},
async _waitForContentSwitchOut(direction, animMs) {
const dir = direction === 'right' ? 'right' : 'left'
if (!this._contentTransitionStartedAt || this._contentTransitionDirection !== dir) {
this._beginContentSwitchTransition(dir)
}
const requested = Number(animMs)
const waitTarget = Number.isFinite(requested) && requested > 0
? Math.min(QUESTION_SWITCH_OUT_MS, requested)
: QUESTION_SWITCH_OUT_MS
const elapsed = Date.now() - this._contentTransitionStartedAt
if (elapsed < waitTarget) await _sleep(waitTarget - elapsed)
},
_finishContentSwitchTransition(direction) {
const dir = direction === 'right' ? 'right' : 'left'
const inClass = dir === 'left' ? 'content-slide-in-right' : 'content-slide-in-left'
if (this._contentTransitionTimer) clearTimeout(this._contentTransitionTimer)
this._contentTransitionStartedAt = 0
this._contentTransitionDirection = ''
this.setData({ contentTransitionClass: inClass })
this._contentTransitionTimer = setTimeout(() => {
this._contentTransitionTimer = null
this._switching = false
this._clearSwitchWatchdog()
if (this._alive) this.setData({ contentTransitionClass: '' })
}, QUESTION_SWITCH_IN_MS)
},
_cancelContentSwitchTransition() {
if (this._contentTransitionTimer) {
clearTimeout(this._contentTransitionTimer)
this._contentTransitionTimer = null
}
this._contentTransitionStartedAt = 0
this._contentTransitionDirection = ''
if (this._alive) this.setData({ contentTransitionClass: '' })
},
_armSwitchWatchdog(ms) {
this._clearSwitchWatchdog()
var duration = Number(ms) > 0 ? Number(ms) : QUESTION_SWITCH_WATCHDOG_MS
var self = this
this._switchWatchdogTimer = setTimeout(function() {
self._switchWatchdogTimer = null
console.warn('[wrong-detail] 切题锁看门狗触发，强制复位')
self._forceResetSwitchLock()
}, duration)
},
_clearSwitchWatchdog() {
if (this._switchWatchdogTimer) {
clearTimeout(this._switchWatchdogTimer)
this._switchWatchdogTimer = null
}
},
_forceResetSwitchLock() {
this._navigationSeq = Number(this._navigationSeq || 0) + 1
this._switching = false
if (this._contentTransitionTimer) {
clearTimeout(this._contentTransitionTimer)
this._contentTransitionTimer = null
}
if (this._switchMaskTimer) {
clearTimeout(this._switchMaskTimer)
this._switchMaskTimer = null
}
this._contentTransitionStartedAt = 0
this._contentTransitionDirection = ''
this._clearSwitchWatchdog()
if (this._alive) {
this.setData({ contentTransitionClass: '', showSwitchMask: false, aiRegenerating: false })
}
},
goPrevWrong(e) {
this._navigateTo(e.detail.index, 150, 'right')
},
goNextWrong(e) {
this._navigateTo(e.detail.index, 150, 'left')
},
goWrongQuestion(e) {
this._navigateTo(e.detail.index, 150)
},
reloadData() {
if (this.data.questionIds.length > 0) {
this.loadData(this.data.questionIds[this.data.currentIdx])
} else if (this._currentWqId) {
this.loadData(this._currentWqId)
} else {
this.goBack()
}
},
goBack() {
const pages = getCurrentPages()
if (pages.length > 1) wx.navigateBack()
else wx.redirectTo({ url: '/subpackages/study/wrong-book/wrong-book' })
},
_dropQuestionFromNavigation(wqId) {
const currentId = this._currentWqId || (this.data.wq && this.data.wq.id)
const oldIds = this.data.questionIds || []
const nextIds = oldIds.filter(id => String(id) !== String(wqId))
if (nextIds.length === oldIds.length) return false
if (this._wqCache) delete this._wqCache[wqId]
try {
wx.setStorageSync('wrong_detail_nav', { ids: nextIds, ts: Date.now() })
} catch (_) {}
let nextCurrentIdx = nextIds.findIndex(id => String(id) === String(currentId))
if (nextCurrentIdx < 0) nextCurrentIdx = 0
const wrongQuestions = nextIds.map(() => ({ _answered: true }))
this.setData({
questionIds: nextIds,
totalQuestions: nextIds.length,
currentIdx: nextCurrentIdx,
wrongQuestions,
runnerProgressPercent: nextIds.length > 0
? Math.round((nextCurrentIdx + 1) / nextIds.length * 100)
: 0,
})
return true
},
async _navigateTo(idx, animMs, direction) {
const wqId = this.data.questionIds[idx]
if (!wqId) return
if (this._switching) return
if (this.data.masterSubmitting || this.data.removeSubmitting) return
if (idx < 0 || idx >= this.data.questionIds.length) return
if (idx === this.data.currentIdx) return
const switchDirection = direction === 'left' || direction === 'right'
? direction
: (idx > this.data.currentIdx ? 'left' : 'right')
this._aiRequestId++
this._resetAiLoadingState()
this._switching = true
var navigationSeq = Number(this._navigationSeq || 0) + 1
this._navigationSeq = navigationSeq
this._armSwitchWatchdog()
var self = this
this._switchMaskTimer = setTimeout(function() {
if (self._alive) self.setData({ showSwitchMask: true })
}, 250)
try {
var wq = null
var cached = this._wqCache && this._wqCache[wqId]
try {
wq = await api.get(`/wrong-questions/${wqId}`)
if (!wq) throw new Error('not found')
if (!this._alive) return
if (this._wqCache) this._wqCache[wqId] = { data: wq, ts: Date.now() }
} catch (fetchError) {
var fetchStatus = Number(fetchError && (fetchError.statusCode || fetchError.status)) || 0
var canFallback = fetchStatus !== 404 && fetchStatus !== 410 &&
cached && Date.now() - Number(cached.ts || 0) < 30000
if (!canFallback) throw fetchError
wq = cached.data
}
if (!this._alive || navigationSeq !== this._navigationSeq) return
this._prefetchWrongQuestion(idx - 1)
this._prefetchWrongQuestion(idx + 1)
const raw = _processWqData(wq, this.data.safeModeActive)
const currentQuestion = Object.assign({}, wq, {
_optionList: raw._optionList,
_optionKeys: raw._optionKeys,
_opts: raw._opts,
_blankOptionGroups: raw._blankOptionGroups,
_hasBlankOptionGroups: raw._blankOptionGroups.length > 0,
_renderModel: raw._renderModel,
})
var totalQ = this.data.totalQuestions || 1
var wrongQuestions = []
for (var wi = 0; wi < totalQ; wi++) {
wrongQuestions.push({ _answered: true })
}
var nextAiResult = null
var nextData = {
wq,
currentIdx: idx,
currentQuestion,
wrongQuestions,
runnerProgressPercent: totalQ > 0 ? Math.round((idx + 1) / totalQ * 100) : 0,
subjectLabelText: raw.subjectLabelText,
aiLoading: false,
aiRegenerating: false,
aiCards: null,
aiRequested: false,
aiFromCache: false,
aiFromQuestionAnalysis: false,
aiFallback: false,
aiErrorText: '',
aiRetryable: true,
aiReviewExpanded: false,
isCurrentMastered: _isWqMastered(wq),
masterSubmitting: false,
removeSubmitting: false,
errorDiagnosis: errorDiagnosis.normalizeDiagnosis(wq.error_diagnosis),
diagnosisSheetVisible: false,
diagnosisSaving: false,
diagnosisAiQueuing: false,
diagnosisAiEnabled: false,
teacherLoadingAction: '',
teacherLastAction: '',
teacherResult: null,
teacherSheetVisible: false,
teacherErrorText: '',
teacherFeedbackSent: '',
teacherActionsExpanded: false,
}
var preferredAnalysis = _resolvePreferredAnalysis(wq)
if (preferredAnalysis) {
nextAiResult = preferredAnalysis.normalized
nextData.aiCards = _normalizeAiResult(nextAiResult)
nextData.aiRequested = true
nextData.aiFromCache = preferredAnalysis.source === 'ai'
nextData.aiFromQuestionAnalysis = preferredAnalysis.source === 'question'
nextData.aiFallback = false
nextData.aiErrorText = ''
}
await this._waitForContentSwitchOut(switchDirection, animMs)
if (!this._alive || navigationSeq !== this._navigationSeq) return
this._currentWqId = wqId
this._errorTypeLabelText = raw.errorTypeLabelText
this._aiResult = nextAiResult
clearTimeout(this._switchMaskTimer)
this._armSwitchWatchdog(QUESTION_SWITCH_ANIM_WATCHDOG_MS)
this.setData(Object.assign({ showSwitchMask: false }, nextData), () => {
this._finishContentSwitchTransition(switchDirection)
})
this._checkRenderInvariant(raw._renderModel)
} catch (e) {
if (!this._alive || navigationSeq !== this._navigationSeq) return
console.error('切换题目失败', e)
clearTimeout(this._switchMaskTimer)
this._switching = false
this._clearSwitchWatchdog()
this._cancelContentSwitchTransition()
const statusCode = Number(e && (e.statusCode || e.status)) || 0
if (statusCode === 404 || statusCode === 410) {
this._dropQuestionFromNavigation(wqId)
this.setData({ showSwitchMask: false, aiRegenerating: false })
wx.showToast({ title: '该错题已被移除，已更新题目列表', icon: 'none' })
return
}
wx.showToast({ title: '加载失败', icon: 'none' })
this.setData({ showSwitchMask: false, aiRegenerating: false })
}
},
openDiagnosisSheet() {
const diagnosis = this.data.errorDiagnosis
const primary = diagnosis && diagnosis.primaryType && diagnosis.primaryType !== 'unknown'
? diagnosis.primaryType
: (this.data.diagnosisAiEnabled && diagnosis && diagnosis.aiPrimaryType && diagnosis.aiPrimaryType !== 'unknown' ? diagnosis.aiPrimaryType : 'knowledge_gap')
const secondary = diagnosis && diagnosis.secondaryTypes && diagnosis.secondaryTypes.length
? diagnosis.secondaryTypes
: (this.data.diagnosisAiEnabled && diagnosis && diagnosis.aiSecondaryTypes || [])
const secondaryMap = {}
secondary.forEach(type => { if (type && type !== primary) secondaryMap[type] = true })
this.setData({
diagnosisSheetVisible: true,
diagnosisPrimary: primary,
diagnosisSecondaryMap: secondaryMap,
})
},
closeDiagnosisSheet() {
if (this.data.diagnosisSaving) return
this.setData({ diagnosisSheetVisible: false })
},
selectDiagnosisPrimary(e) {
const type = e.currentTarget.dataset.type
if (!type) return
const secondaryMap = Object.assign({}, this.data.diagnosisSecondaryMap || {})
delete secondaryMap[type]
this.setData({ diagnosisPrimary: type, diagnosisSecondaryMap: secondaryMap })
},
toggleDiagnosisSecondary(e) {
const type = e.currentTarget.dataset.type
if (!type || type === this.data.diagnosisPrimary) return
const secondaryMap = Object.assign({}, this.data.diagnosisSecondaryMap || {})
if (secondaryMap[type]) delete secondaryMap[type]
else {
if (Object.keys(secondaryMap).length >= 3) {
wx.showToast({ title: '次级错因最多选择 3 个', icon: 'none' })
return
}
secondaryMap[type] = true
}
this.setData({ diagnosisSecondaryMap: secondaryMap })
},
async saveDiagnosis() {
const wqId = Number(this._currentWqId || (this.data.wq && this.data.wq.id))
if (!wqId || this.data.diagnosisSaving) return
const primaryType = this.data.diagnosisPrimary || 'unknown'
const secondaryTypes = Object.keys(this.data.diagnosisSecondaryMap || {}).filter(type => type !== primaryType)
this.setData({ diagnosisSaving: true })
try {
const raw = await api.put(`/wrong-questions/${wqId}/diagnosis`, {
diagnosis_id: this.data.errorDiagnosis ? Number(this.data.errorDiagnosis.id || 0) || undefined : undefined,
primary_type: primaryType,
secondary_types: secondaryTypes,
})
if (!this._alive || wqId !== Number(this._currentWqId)) return
const normalized = errorDiagnosis.normalizeDiagnosis(raw)
const wq = Object.assign({}, this.data.wq || {}, {
error_type: normalized ? normalized.primaryType : primaryType,
error_diagnosis: raw,
})
if (this._wqCache && this._wqCache[wqId]) this._wqCache[wqId] = { data: wq, ts: Date.now() }
this.setData({
wq,
errorDiagnosis: normalized,
diagnosisSheetVisible: false,
diagnosisSaving: false,
})
wx.showToast({ title: '错因已记录', icon: 'success' })
} catch (e) {
this.setData({ diagnosisSaving: false })
wx.showToast({ title: api.getErrorMessage(e) || '保存失败', icon: 'none' })
}
},
async acceptAiDiagnosis() {
const diagnosis = this.data.errorDiagnosis
if (!diagnosis || !diagnosis.aiPrimaryType || diagnosis.aiPrimaryType === 'unknown') return
const secondaryMap = {}
;(diagnosis.aiSecondaryTypes || []).forEach(type => { secondaryMap[type] = true })
this.setData({
diagnosisPrimary: diagnosis.aiPrimaryType,
diagnosisSecondaryMap: secondaryMap,
})
await this.saveDiagnosis()
},
enableDiagnosisAi() {
if (this.data.diagnosisAiEnabled) return
this.setData({ diagnosisAiEnabled: true })
const diagnosis = this.data.errorDiagnosis
if (!diagnosis || diagnosis.aiStatus === 'not_requested' || diagnosis.aiStatus === 'failed' || diagnosis.aiStatus === 'pending') {
this.requestDiagnosisSuggestion()
}
},
disableDiagnosisAi() {
this._diagnosisAiRequestSeq++
this.setData({ diagnosisAiEnabled: false, diagnosisAiQueuing: false })
},
async requestDiagnosisSuggestion() {
const wqId = Number(this._currentWqId || (this.data.wq && this.data.wq.id))
if (!wqId || !this.data.diagnosisAiEnabled || this.data.diagnosisAiQueuing) return
const requestSeq = ++this._diagnosisAiRequestSeq
this.setData({ diagnosisAiQueuing: true })
try {
const response = await api.post(`/wrong-questions/${wqId}/diagnosis/suggest`, {})
if (requestSeq !== this._diagnosisAiRequestSeq || !this._alive || !this.data.diagnosisAiEnabled || wqId !== Number(this._currentWqId)) return
this.setData({ errorDiagnosis: errorDiagnosis.normalizeDiagnosis(response && response.diagnosis) })
for (let i = 0; i < 8; i += 1) {
await _sleep(1500)
if (requestSeq !== this._diagnosisAiRequestSeq || !this._alive || !this.data.diagnosisAiEnabled || wqId !== Number(this._currentWqId)) return
const raw = await api.get(`/wrong-questions/${wqId}/diagnosis`, {}, { suppressNetworkToast: true }).catch(() => null)
if (requestSeq !== this._diagnosisAiRequestSeq || !this.data.diagnosisAiEnabled) return
const normalized = errorDiagnosis.normalizeDiagnosis(raw)
if (normalized) this.setData({ errorDiagnosis: normalized })
if (normalized && normalized.aiStatus !== 'pending') break
}
} catch (e) {
if (requestSeq === this._diagnosisAiRequestSeq && this.data.diagnosisAiEnabled) {
wx.showToast({ title: api.getErrorMessage(e) || 'AI 错因建议暂不可用', icon: 'none' })
}
} finally {
if (requestSeq === this._diagnosisAiRequestSeq && this._alive) this.setData({ diagnosisAiQueuing: false })
}
},
scrollToAiCard() {
wx.pageScrollTo({ selector: '#ai-card', duration: 220 })
},
noop() {},
_prefetchWrongQuestion(idx) {
if (idx < 0 || idx >= this.data.questionIds.length) return
var wqId = this.data.questionIds[idx]
if (!wqId) return
var cached = this._wqCache[wqId]
if (cached && Date.now() - cached.ts < 300000) return
var requestStartedAt = Date.now()
var self = this
api.get(`/wrong-questions/${wqId}`).then(function(wq) {
if (!wq || !self._alive || !self._wqCache) return
var latest = self._wqCache[wqId]
if (latest && Number(latest.ts || 0) >= requestStartedAt) return
self._wqCache[wqId] = { data: wq, ts: Date.now() }
}).catch(function() {})
},
})
