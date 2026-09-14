const api = require('../../../utils/api')
const config = require('../../../config')
const storage = require('../../../utils/storage')
const {
buildRenderModel, resetRenderGuard, setRenderGuardPage,
stripLeadingOptionLabel, toPlainInlineMathText, needsRichRender,
textToHtml
} = require('../utils/stem-render')
const {
isMultipleChoiceType, isTrueFalseType,
normalizeChoiceAnswer, serializeChoiceAnswer, serializeBlankAnswer,
} = require('../utils/answer')
const adapter = require('../utils/question-runner-adapter')
const { getSubjectName } = require('../utils/subject-meta')
const { getChinaWallParts, getChinaDate } = require('../../../utils/china-time')
var KF = 'schedule_id'
var REVIEW_BATCH_SIZE_OPTIONS = [5, 10, 20, 30]
var REVIEW_DRAFT_PREFIX = 'review_today_draft_v1'
var _reviewPerformanceClock = null
function _reviewMonotonicNow() {
try {
if (!_reviewPerformanceClock && typeof wx !== 'undefined' && typeof wx.getPerformance === 'function') {
_reviewPerformanceClock = wx.getPerformance()
}
if (_reviewPerformanceClock && typeof _reviewPerformanceClock.now === 'function') {
return _reviewPerformanceClock.now()
}
} catch (_) {}
return Date.now()
}
function normalizeReviewBatchSize(value) {
var num = Number(value)
if (isNaN(num) || num <= 0) return 10
for (var i = 0; i < REVIEW_BATCH_SIZE_OPTIONS.length; i++) {
if (num === REVIEW_BATCH_SIZE_OPTIONS[i]) return num
}
return 10
}
function formatReviewElapsed(sec) {
var s = Math.max(0, sec || 0)
var m = Math.floor(s / 60)
var ss = s % 60
return (m < 10 ? '0' : '') + m + ':' + (ss < 10 ? '0' : '') + ss
}
function _mergeResultsByScheduleId(oldResults, newResults) {
var order = []
var map = {}
;(oldResults || []).forEach(function(item) {
var sid = String(item && item.schedule_id || '')
if (!sid) return
if (!map[sid]) order.push(sid)
map[sid] = item
})
;(newResults || []).forEach(function(item) {
var sid = String(item && item.schedule_id || '')
if (!sid) return
if (!map[sid]) order.push(sid)
map[sid] = item
})
return order.map(function(sid) {
return map[sid]
})
}
function _reviewFailureNeedsRefresh(result) {
if (!result || result.success !== false) return false
if (result.refresh_required === true) return true
if (result.retryable === false && result.retryable !== undefined && result.retryable !== null) return true
var text = String(result.error || '')
return /刷新|已失效|已经提交|已标记掌握|复习记录不存在|版本.*(?:更新|不存在)|不匹配|request_id.*不同提交/.test(text)
}
function normalizeReviewQuestion(raw) {
if (!raw || typeof raw !== 'object') return null
var content = raw.content
if (typeof content === 'string') {
content = { text: content }
} else if (!content || typeof content !== 'object') {
content = { text: raw.stem || '' }
}
var opts = raw.options
if (!opts || typeof opts !== 'object' || Array.isArray(opts)) {
opts = {}
}
return {
schedule_id: raw.schedule_id,
question_id: raw.question_id,
question_version_id: raw.question_version_id,
occurrence_seq: raw.occurrence_seq,
id: raw.id || raw.question_id,
subject_id: raw.subject_id != null ? raw.subject_id : null,
subject_code: raw.subject_code || '',
subject_name: raw.subject_name || '',
question_type: raw.question_type || '',
stem: raw.stem || '',
options: opts,
content: content,
image_url: raw.image_url || null,
interval: raw.interval || 0,
repetitions: raw.repetitions || 0,
ease_factor: raw.ease_factor || 2.5,
}
}
Page({
data: {
phase: 'loading',
elapsedText: '00:00',
todayDueCount: 0,
todayCompletedCount: 0,
todayRemainingCount: 0,
todayOverdueCount: 0,
todayNewDueCount: 0,
estimatedMinutes: 0,
reviewBatchSize: 10,
currentBatchNo: 0,
totalBatchCount: 0,
remainingBatchCount: 0,
todayProgressPercent: 0,
isStarting: false,
isContinuing: false,
batchLoading: false,
errorText: '',
groups: [],
currentGroupIdx: 0,
groupQuestions: [],
currentIndex: 0,
currentQuestion: null,
masterConfirmId: null,
masterSubmitting: false,
runnerProgressPercent: 0,
runnerSubtitle: '',
runnerSubjectName: '',
submittingGroup: false,
resultTransitioning: false,
groupResults: [],
groupWrongResults: [],
groupCorrect: 0,
groupWrong: 0,
_groupSkipped: 0,
groupAccuracyPercent: 0,
showGroupDetails: false,
resultDockVisible: true,
exitConfirmVisible: false,
masterUndoVisible: false,
masterUndoText: '',
_dateStr: '',
_groupProgressStyle: '',
batchSizeOptions: [5, 10, 20, 30],
showBatchSizeSheet: false,
pendingBatchSize: 10,
skeletonOptions: [1, 2, 3, 4],
},
_createReviewSession() {
return {
allTodayQuestionIds: [],
completedQuestionIds: [],
remainingQuestionIds: [],
allQuestions: [],
answers: {},
sessionId: '',
currentGroupId: '',
allGroupResults: [],
totalCorrect: 0,
totalWrong: 0,
totalCompleted: 0,
todayTaskTotalCount: 0,
completedBeforeSession: 0,
safeModeActive: false,
renderTraces: [],
optionKeys: [],
reviewOverview: null,
overviewLoading: false,
reviewRequestIds: {},
taskDate: getChinaDate(0),
timerStartedAt: 0,
timerLastTickAt: 0,
timerElapsedMs: 0,
timerRunning: false,
}
},
_getReviewDraftKey() {
const session = this._reviewSession || (this._reviewSession = this._createReviewSession())
const user = storage.get(storage.KEYS.USER) || {}
const userId = user.id != null ? user.id : (user.user_id != null ? user.user_id : 'current')
const taskDate = String(session.taskDate || getChinaDate(0))
return REVIEW_DRAFT_PREFIX + ':' + String(userId) + ':' + taskDate
},
_readReviewDraft() {
const raw = storage.get(this._getReviewDraftKey())
if (!raw || typeof raw !== 'object') return { answers: {}, position: null }
return {
answers: raw.answers && typeof raw.answers === 'object' ? raw.answers : {},
position: raw.position && typeof raw.position === 'object' ? raw.position : null,
}
},
_writeReviewDraft(payload) {
const answers = payload && payload.answers && typeof payload.answers === 'object' ? payload.answers : {}
const hasAnswers = Object.keys(answers).length > 0
if (!hasAnswers) {
storage.remove(this._getReviewDraftKey())
return
}
storage.set(this._getReviewDraftKey(), {
version: 1,
date: String(this._reviewSession.taskDate || getChinaDate(0)),
updated_at: Date.now(),
answers,
position: payload.position || null,
})
},
_persistReviewDraft() {
if (!this._reviewSession || this.data.phase !== 'reviewing') return
const questions = this.data.groupQuestions || []
if (!questions.length) return
const stored = this._readReviewDraft()
const entries = { ...stored.answers }
const answers = this._reviewSession.answers || {}
questions.forEach(q => {
const sid = String(q.schedule_id || '')
if (!sid) return
const answer = answers[q.schedule_id] != null ? answers[q.schedule_id] : answers[sid]
if (answer !== undefined && answer !== null && String(answer) !== '') {
entries[sid] = {
schedule_id: q.schedule_id,
question_id: q.question_id,
question_version_id: q.question_version_id,
occurrence_seq: q.occurrence_seq,
answer: String(answer),
}
} else {
delete entries[sid]
}
})
const current = this.data.currentQuestion
const position = current ? {
schedule_id: current.schedule_id,
question_version_id: current.question_version_id,
occurrence_seq: current.occurrence_seq,
} : stored.position
this._writeReviewDraft({ answers: entries, position })
},
_restoreReviewDraft(questions) {
const list = questions || []
const stored = this._readReviewDraft()
const answers = {}
let restoredCount = 0
let currentIndex = 0
list.forEach((q, index) => {
const sid = String(q.schedule_id || '')
const entry = sid ? stored.answers[sid] : null
if (
entry &&
String(entry.question_id) === String(q.question_id) &&
String(entry.question_version_id) === String(q.question_version_id) &&
String(entry.occurrence_seq) === String(q.occurrence_seq) &&
String(entry.answer || '') !== ''
) {
answers[q.schedule_id] = String(entry.answer)
restoredCount++
}
const pos = stored.position
if (
pos &&
String(pos.schedule_id) === sid &&
String(pos.question_version_id) === String(q.question_version_id) &&
String(pos.occurrence_seq) === String(q.occurrence_seq)
) {
currentIndex = index
}
})
return { answers, currentIndex, restoredCount }
},
_clearSubmittedReviewDraft(groupQuestions, groupResults) {
const successfulIds = new Set(
(groupResults || []).filter(item => item && item.wasSubmitted).map(item => String(item.schedule_id))
)
if (!successfulIds.size) return
const stored = this._readReviewDraft()
const entries = { ...stored.answers }
successfulIds.forEach(sid => { delete entries[sid] })
let position = stored.position
if (position && successfulIds.has(String(position.schedule_id))) position = null
this._writeReviewDraft({ answers: entries, position })
},
onLoad(options) {
this._alive = true
this._overviewRequestSeq = 0
this._flowRequestSeq = 0
this._masterUndoInFlight = false
this._autoStartPending = !!(
options && (
String(options.autostart || '') === '1' ||
String(options.autostart || '').toLowerCase() === 'true'
)
)
this._reviewSession = this._createReviewSession()
this._timerInterval = null
this._resultDockFadeTimer = null
this._userSelectedReviewBatchSize = false
setRenderGuardPage('review-today')
this._setDateStr()
this.loadTodayReviewOverview()
},
onShow() {
this._setDateStr()
const phase = this.data.phase
if (phase === 'overview' || phase === 'empty') {
this.loadTodayReviewOverview()
}
if (phase === 'reviewing' && this._reviewSession && this._reviewSession.timerStartedAt > 0 && !this._reviewSession.timerRunning) {
this._resumeReviewTimer()
}
if (phase === 'group-result' && this.data.todayRemainingCount <= 0) {
this._showResultDockAndRefreshTimer()
}
},
onHide() {
if (typeof this._persistReviewDraft === 'function') this._persistReviewDraft()
this._pauseReviewTimer()
if (this._resultDockFadeTimer) {
clearTimeout(this._resultDockFadeTimer)
this._resultDockFadeTimer = null
}
},
onUnload() {
if (typeof this._persistReviewDraft === 'function') this._persistReviewDraft()
this._alive = false
this._overviewRequestSeq++
this._flowRequestSeq++
this._autoStartPending = false
resetRenderGuard()
this._clearMasterUndo()
this._clearReviewTimer()
if (this._resultDockFadeTimer) {
clearTimeout(this._resultDockFadeTimer)
this._resultDockFadeTimer = null
}
},
_setDateStr() {
const now = getChinaWallParts(Date.now())
const weekdays = ['日', '一', '二', '三', '四', '五', '六']
this.setData({
_dateStr: `${now.month}月${now.day}日 星期${weekdays[now.weekday]}`
})
},
async loadTodayReviewOverview() {
const requestSeq = ++this._overviewRequestSeq
this._reviewSession.overviewLoading = true
this.setData({ phase: 'loading', isStarting: false, isContinuing: false })
try {
const overview = await api.get('/review/today/overview')
if (!this._alive || requestSeq !== this._overviewRequestSeq) return
const vm = this.buildReviewOverviewVM(overview)
this._reviewSession.reviewOverview = overview
this._reviewSession.taskDate = String(overview.date || getChinaDate(0))
this._reviewSession.allTodayQuestionIds = overview.all_question_ids || []
this._reviewSession.completedQuestionIds = overview.completed_question_ids || []
this._reviewSession.remainingQuestionIds = overview.remaining_question_ids || []
const targetPhase = vm.todayRemainingCount > 0 ? 'overview' : 'empty'
const shouldAutoStart = this._autoStartPending && targetPhase === 'overview'
if (targetPhase === 'empty') this._autoStartPending = false
this._reviewSession.overviewLoading = false
this.setData({
...vm,
phase: targetPhase,
}, () => {
if (shouldAutoStart && this._alive && requestSeq === this._overviewRequestSeq) {
this._autoStartPending = false
this.startTodayReview()
}
})
} catch (e) {
if (!this._alive || requestSeq !== this._overviewRequestSeq) return
console.error('加载复习概览失败', e)
this._reviewSession.overviewLoading = false
this.setData({
phase: 'error',
errorText: '复习计划加载失败，请稍后重试',
})
}
},
async refreshOverviewStatsSilently() {
const requestSeq = ++this._overviewRequestSeq
try {
const overview = await api.get('/review/today/overview')
if (!this._alive || requestSeq !== this._overviewRequestSeq) return
const vm = this.buildReviewOverviewVM(overview)
this._reviewSession.reviewOverview = overview
this._reviewSession.allTodayQuestionIds = overview.all_question_ids || []
this._reviewSession.completedQuestionIds = overview.completed_question_ids || []
this._reviewSession.remainingQuestionIds = overview.remaining_question_ids || []
if (this._reviewSession.todayTaskTotalCount > 0 && (this.data.phase === 'reviewing' || this.data.phase === 'group-result')) {
const taskTotalCount = Math.max(
Number(this._reviewSession.todayTaskTotalCount || 0),
Number(this.data.todayDueCount || 0)
)
const remainingCount = Math.min(taskTotalCount, Math.max(0, Number(vm.todayRemainingCount || 0)))
vm.todayDueCount = taskTotalCount
vm.todayRemainingCount = remainingCount
vm.todayCompletedCount = Math.max(0, taskTotalCount - remainingCount)
vm.todayProgressPercent = taskTotalCount > 0 ? Math.round(vm.todayCompletedCount / taskTotalCount * 100) : 0
}
this.setData({
...vm,
})
} catch (e) {
if (!this._alive || requestSeq !== this._overviewRequestSeq) return
console.error('刷新复习概览失败', e)
}
},
async _syncReviewSessionDayIfNeeded() {
const session = this._reviewSession
const currentDate = getChinaDate(0)
if (!session || !session.taskDate || String(session.taskDate) === currentDate) return true
try {
const overview = await api.get('/review/today/overview')
if (!this._alive) return false
const vm = this.buildReviewOverviewVM(overview || {})
session.taskDate = String((overview && overview.date) || currentDate)
session.reviewOverview = overview || {}
session.allTodayQuestionIds = (overview && overview.all_question_ids) || []
session.completedQuestionIds = (overview && overview.completed_question_ids) || []
session.remainingQuestionIds = (overview && overview.remaining_question_ids) || []
session.allGroupResults = []
session.totalCorrect = 0
session.totalWrong = 0
session.totalCompleted = 0
session.todayTaskTotalCount = Math.max(0, Number(vm.todayDueCount || 0))
session.completedBeforeSession = Math.max(0, Number(vm.todayCompletedCount || 0))
this._setDateStr()
this.setData({
...vm,
})
wx.showToast({ title: '日期已切换，已同步今日复习进度', icon: 'none' })
return true
} catch (e) {
if (!this._alive) return false
console.error('跨天同步复习进度失败', e)
wx.showToast({ title: '日期已切换，请联网同步后继续', icon: 'none' })
return false
}
},
buildReviewOverviewVM(overview) {
const due = Number(overview.today_due_count || 0)
const completed = Number(overview.today_completed_count || 0)
const remaining = Number(overview.today_remaining_count || 0)
const progress = due > 0 ? Math.round((completed / due) * 100) : 0
const overdue = Number(overview.today_overdue_count || 0)
let todayAdviceText = '按当前节奏完成一组，今天的复习就会更轻松。'
if (overdue > 0) {
todayAdviceText = `先完成 ${overdue} 道逾期题，把最容易遗忘的内容拉回来。`
} else if (remaining <= 5) {
todayAdviceText = `只剩 ${remaining} 道，适合一次完成今天的记忆任务。`
} else if (completed > 0) {
todayAdviceText = `已经完成 ${completed} 道，继续一组就能保持复习节奏。`
}
var batchSize = Number(overview.batch_size || 10)
batchSize = normalizeReviewBatchSize(batchSize)
if (this._userSelectedReviewBatchSize) {
batchSize = this.data.reviewBatchSize
}
return {
todayDueCount: due,
todayCompletedCount: completed,
todayRemainingCount: remaining,
todayOverdueCount: overdue,
todayNewDueCount: Number(overview.today_new_due_count || 0),
estimatedMinutes: Number(overview.estimated_minutes || Math.ceil(remaining * 0.5)),
reviewBatchSize: batchSize,
currentBatchNo: Number(overview.current_batch_no || 0),
totalBatchCount: Number(overview.total_batch_count || 0),
remainingBatchCount: Number(overview.remaining_batch_count || 0),
todayProgressPercent: Math.min(100, Math.max(0, progress)),
todayAdviceText,
}
},
async startTodayReview() {
if (this.data.todayRemainingCount <= 0) return
if (this.data.isStarting || this.data.isContinuing) return
const flowSeq = ++this._flowRequestSeq
this.setData({
isStarting: true,
batchLoading: true,
phase: 'loading',
})
try {
const batch = await api.post('/review/today/next-batch', {
batch_size: this.data.reviewBatchSize,
})
if (!this._alive || flowSeq !== this._flowRequestSeq) return
const rawQuestions = batch.questions || []
if (!rawQuestions.length) {
wx.showToast({ title: '今日没有待复习题目', icon: 'none' })
await this.loadTodayReviewOverview()
return
}
const allQuestions = rawQuestions.map(normalizeReviewQuestion).filter(Boolean)
if (!allQuestions.length) {
throw new Error('所有题目标准化后为空')
}
this._reviewSession.allQuestions = allQuestions
const restoredDraft = this._restoreReviewDraft(allQuestions)
this._reviewSession.answers = restoredDraft.answers
this._reviewSession.sessionId = batch.session_id || ''
this._reviewSession.currentGroupId = batch.group_id || ''
this._reviewSession.allGroupResults = []
this._reviewSession.totalCorrect = 0
this._reviewSession.totalWrong = 0
this._reviewSession.totalCompleted = 0
this._reviewSession.safeModeActive = false
this._reviewSession.renderTraces = []
var firstEnriched = this._enrichQuestion(allQuestions[0])
var preparedQuestions = allQuestions.slice()
preparedQuestions[0] = firstEnriched
var currentIndex = Math.min(Math.max(0, restoredDraft.currentIndex || 0), preparedQuestions.length - 1)
if (currentIndex > 0) preparedQuestions[currentIndex] = this._enrichQuestion(preparedQuestions[currentIndex])
this._reviewSession.allQuestions = preparedQuestions
var currentEnriched = preparedQuestions[currentIndex]
var currentOptionList = adapter.buildOptionList(currentEnriched, restoredDraft.answers, KF)
var currentBlankOptionGroups = currentEnriched._blankOptionGroups || []
if (currentEnriched._hasBlankOptionGroups) {
const restoredAnswer = restoredDraft.answers[currentEnriched.schedule_id] || ''
currentBlankOptionGroups = adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(currentEnriched), restoredAnswer)
}
var firstQuestion = Object.assign({}, currentEnriched, {
_optionList: currentOptionList,
_blankOptionGroups: currentBlankOptionGroups,
_hasBlankOptionGroups: currentBlankOptionGroups.length > 0,
})
this._reviewSession.optionKeys = currentEnriched._optionKeys
this._checkSetDataSize({ phase: 'reviewing', currentQuestion: firstQuestion })
const batchDueCount = Number(batch.today_due_count || 0)
const batchCompletedCount = Number(batch.today_completed_count || 0)
const taskTotalCount = Math.max(
Number(this._reviewSession.todayTaskTotalCount || 0),
Number(this.data.todayDueCount || 0),
batchDueCount,
allQuestions.length
)
const completedBeforeSession = Math.max(
Number(this._reviewSession.completedBeforeSession || 0),
Number(this.data.todayCompletedCount || 0),
batchCompletedCount
)
this._reviewSession.todayTaskTotalCount = taskTotalCount
this._reviewSession.completedBeforeSession = completedBeforeSession
this.setData({
phase: 'reviewing',
groups: [preparedQuestions],
currentGroupIdx: 0,
groupQuestions: preparedQuestions,
currentIndex: currentIndex,
currentQuestion: firstQuestion,
_answeredCount: adapter.computeAnsweredCount(preparedQuestions, restoredDraft.answers, KF),
currentBatchNo: batch.batch_no || 1,
totalBatchCount: batch.total_batch_count || this.data.totalBatchCount,
todayDueCount: taskTotalCount,
todayCompletedCount: completedBeforeSession,
todayRemainingCount: Math.max(0, taskTotalCount - completedBeforeSession),
groupResults: [],
groupWrongResults: [],
groupCorrect: 0,
groupWrong: 0,
_groupSkipped: 0,
groupAccuracyPercent: 0,
showGroupDetails: false,
masterConfirmId: null,
submittingGroup: false,
resultTransitioning: false,
batchLoading: false,
isStarting: false,
isContinuing: false,
})
this._syncAnsweredFlags()
this._updateRunnerFields()
this._checkRenderInvariant(currentEnriched._renderModel)
this._recordRenderTrace(currentEnriched._renderModel && currentEnriched._renderModel.renderTrace)
this._startReviewTimer()
if (restoredDraft.restoredCount > 0) {
wx.showToast({ title: `已恢复 ${restoredDraft.restoredCount} 题草稿`, icon: 'none' })
}
} catch (e) {
if (!this._alive || flowSeq !== this._flowRequestSeq) return
console.error('[REVIEW_ERROR] startTodayReview failed',
'batchSize=' + this.data.reviewBatchSize,
'statusCode=' + (e.statusCode || 'N/A'),
'detail=' + (e.detail || e.message || 'unknown'))
this.setData({
isStarting: false,
isContinuing: false,
batchLoading: false,
phase: 'error',
errorText: '获取复习题失败，请检查网络后重试',
})
wx.showToast({ title: '获取复习题失败，请重试', icon: 'none' })
}
},
_splitGroups(questions, size) {
const groups = []
for (let i = 0; i < questions.length; i += size) {
groups.push(questions.slice(i, i + size))
}
return groups
},
_enrichQuestion(q) {
const stemText = (q.content && (q.content.text || q.content.stem)) || q.stem || ''
let opts = null
let optionKeys = []
if (q.options && Object.keys(q.options).length > 0) {
opts = q.options
optionKeys = Object.keys(opts)
}
if (isTrueFalseType(q.question_type)) {
opts = { A: '正确', B: '错误' }
optionKeys = ['A', 'B']
}
const hasBlankGroups = adapter.isMultiBlankChoice(q) && adapter.getBlankOptionGroups(q).length > 0
const blankOptionGroups = hasBlankGroups ? adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(q), '') : []
var renderCfg = { enableMathImage: false, DEV: config.DEV }
if (this._reviewSession.safeModeActive) renderCfg.SAFE_MODE = true
const _renderModel = buildRenderModel(q, opts, renderCfg)
const optText = {}
const optNeedsRich = {}
const optHtml = {}
for (let optionIndex = 0; optionIndex < optionKeys.length; optionIndex++) {
const key = optionKeys[optionIndex]
const raw = (opts && opts[key]) || ''
const text = stripLeadingOptionLabel(key, raw)
const plain = toPlainInlineMathText(text)
optText[key] = plain || text
optNeedsRich[key] = !plain && needsRichRender(text)
optHtml[key] = optNeedsRich[key] ? textToHtml(text) : ''
}
return {
...q,
_opts: opts,
_optionKeys: optionKeys,
_optText: optText,
_optNeedsRich: optNeedsRich,
_optHtml: optHtml,
_blankOptionGroups: blankOptionGroups,
_hasBlankOptionGroups: blankOptionGroups.length > 0,
_optionList: [],
_renderModel,
_stemPreview: stemText.length > 60 ? `${stemText.slice(0, 60)}...` : stemText,
_subjectLabel: this.subjectLabel(q.subject_name, q.subject_code),
}
},
_enrichForResult(q) {
if (q._renderModel) return q
try {
return this._enrichQuestion(q)
} catch (e) {
console.error('题目渲染数据生成失败，退化为纯文本预览', e)
const stemText = (q.content && (q.content.text || q.content.stem)) || q.stem || ''
return Object.assign({}, q, {
_renderModel: null,
_stemPreview: stemText.length > 60 ? `${stemText.slice(0, 60)}...` : stemText,
})
}
},
_checkRenderInvariant(renderModel) {
if (!renderModel) return
if (renderModel.mode === 'CODE' && renderModel.rawText) {
var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
if (hasHtmlLeak) {
console.error('[CODE_HTML_LEAK] review-today CODE rawText contains HTML entities')
}
var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
if (hasRenderViolation) {
console.error('[CODE_RENDER_VIOLATION] review-today CODE mode leaked into html/richTextNodes')
}
if ((hasHtmlLeak || hasRenderViolation) && !this._reviewSession.safeModeActive) {
this._enterSafeMode()
}
}
if (renderModel.mode === 'MIXED') {
if (!renderModel.blocks || renderModel.blocks.length === 0) {
console.error('[MIXED_RENDER_VIOLATION] review-today MIXED mode but blocks is empty')
return
}
for (var mi = 0; mi < renderModel.blocks.length; mi++) {
var mBlock = renderModel.blocks[mi]
if (mBlock.type === 'CODE' && mBlock.rawText) {
if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
console.error('[CODE_HTML_LEAK] review-today MIXED CODE block #' + mi + ' contains HTML entities')
}
}
}
}
},
_recordRenderTrace(trace) {
if (!trace) return
var traces = this._reviewSession.renderTraces
traces = traces.concat([trace])
if (traces.length > 200) traces = traces.slice(-200)
this._reviewSession.renderTraces = traces
},
_enterSafeMode() {
console.warn('[SELF_HEAL] review-today CODE render violation — entering SAFE_MODE')
this._reviewSession.safeModeActive = true
if (this.data.currentQuestion) {
const idx = this.data.currentIndex
const q = this.data.groupQuestions[idx]
if (q) {
const enriched = this._enrichQuestion(q)
const groupQuestions = (this.data.groupQuestions || []).slice()
groupQuestions[idx] = enriched
this.setData({ groupQuestions })
this._showQuestion(idx)
}
console.warn('[SELF_HEAL] review-today re-rendered at index ' + idx + ' in SAFE_MODE')
}
},
_checkSetDataSize(data) {
if (!config.DEV) return
var THRESHOLD = 200 * 1024
try {
var size = new Blob([JSON.stringify(data)]).size
if (size > THRESHOLD) {
console.warn('[SETDATA_SIZE] payload ~' + (size / 1024).toFixed(0) + 'KB for keys: ' + Object.keys(data).join(', ') + ' (threshold: ' + (THRESHOLD / 1024) + 'KB)')
}
} catch (e) {
}
},
_syncAnsweredFlags() {
const enriched = adapter.applyAnsweredFlags(this.data.groupQuestions, adapter.buildAnsweredFlags(this.data.groupQuestions, this._reviewSession.answers, KF), KF)
this.setData({ groupQuestions: enriched })
},
_showQuestion(index) {
const q = this.data.groupQuestions[index]
if (!q) return
var enriched = q._renderModel ? q : this._enrichQuestion(q)
const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, this._reviewSession.answers, KF)
const optionList = adapter.buildOptionList(enriched, this._reviewSession.answers, KF)
var blankOptionGroups = enriched._blankOptionGroups || []
var hasBlankOptionGroups = enriched._hasBlankOptionGroups || false
if (hasBlankOptionGroups) {
const answer = this._reviewSession.answers[enriched.schedule_id] || ''
blankOptionGroups = adapter.enrichBlankOptionGroups(adapter.getBlankOptionGroups(enriched), answer)
}
const currentQuestion = Object.assign({}, enriched, {
_optionList: optionList,
_blankOptionGroups: blankOptionGroups,
_hasBlankOptionGroups: blankOptionGroups.length > 0,
})
this._reviewSession.optionKeys = enriched._optionKeys
if (!q._renderModel) {
var gq = this.data.groupQuestions.slice()
gq[index] = enriched
this.setData({ groupQuestions: gq })
}
this._checkSetDataSize({ currentIndex: index, currentQuestion: currentQuestion })
this.setData({
currentIndex: index,
currentQuestion: currentQuestion,
_answeredCount: answeredCount,
})
this._updateRunnerFields()
this._checkRenderInvariant(enriched._renderModel)
this._recordRenderTrace(enriched._renderModel && enriched._renderModel.renderTrace)
},
_updateRunnerFields() {
var grp = this.data.groupQuestions || []
var total = grp.length || 1
var answered = this.data._answeredCount || 0
this.setData({
runnerProgressPercent: Math.round(answered / total * 100),
runnerSubtitle: '第 ' + (this.data.currentBatchNo || this.data.currentGroupIdx + 1) + ' / ' + (this.data.totalBatchCount || 1) + ' 组',
runnerSubjectName: this.data.currentQuestion
? (this.data.currentQuestion.subject_name || this.data.currentQuestion._subjectLabel || '')
: '',
})
},
selectOption(e) {
if (this.data.submittingGroup) return
const opt = e.detail.option
if (!opt) return
const q = this.data.currentQuestion
const answers = { ...this._reviewSession.answers }
if (isMultipleChoiceType(q.question_type)) {
const prev = answers[q.schedule_id] || ''
const sel = normalizeChoiceAnswer(prev)
const idx = sel.indexOf(opt)
if (idx >= 0) sel.splice(idx, 1)
else sel.push(opt)
sel.sort()
const newAnswer = serializeChoiceAnswer(sel.join(','))
if (newAnswer) answers[q.schedule_id] = newAnswer
else delete answers[q.schedule_id]
} else {
if (answers[q.schedule_id] === opt) {
delete answers[q.schedule_id]
} else {
answers[q.schedule_id] = opt
}
}
this._reviewSession.answers = answers
this._persistReviewDraft()
const optionList = adapter.buildOptionList(q, answers, KF)
const currentQuestion = Object.assign({}, q, { _optionList: optionList })
const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, answers, KF)
this.setData({ currentQuestion, _answeredCount: answeredCount })
this._syncAnsweredFlags()
this._updateRunnerFields()
},
selectBlankOption(e) {
if (this.data.submittingGroup) return
const blankId = String(e.detail.blankId || '').trim()
const opt = String(e.detail.option || '').trim().toUpperCase()
const q = this.data.currentQuestion
if (!q || !adapter.isMultiBlankChoice(q) || !blankId || !opt) return
const answer = this._reviewSession.answers[q.schedule_id] || ''
const blankAnswers = adapter.normalizeBlankAnswer(answer)
if (blankAnswers[blankId] === opt) {
delete blankAnswers[blankId]
} else {
blankAnswers[blankId] = opt
}
const rawGroups = adapter.getBlankOptionGroups(q)
const newAnswer = serializeBlankAnswer(rawGroups, blankAnswers)
const answers = { ...this._reviewSession.answers }
if (newAnswer) answers[q.schedule_id] = newAnswer
else delete answers[q.schedule_id]
const enrichedGroups = adapter.enrichBlankOptionGroups(rawGroups, newAnswer)
this._reviewSession.answers = answers
this._persistReviewDraft()
const answeredCount = adapter.computeAnsweredCount(this.data.groupQuestions, answers, KF)
const enrichedQuestions = adapter.applyAnsweredFlags(this.data.groupQuestions,
adapter.buildAnsweredFlags(this.data.groupQuestions, answers, KF), KF)
this.setData({
_answeredCount: answeredCount,
runnerProgressPercent: Math.round(answeredCount / (enrichedQuestions.length || 1) * 100),
runnerSubtitle: '第 ' + (this.data.currentBatchNo || this.data.currentGroupIdx + 1) + ' / ' + (this.data.totalBatchCount || 1) + ' 组',
runnerSubjectName: q ? (q.subject_name || q._subjectLabel || '') : '',
'currentQuestion._blankOptionGroups': enrichedGroups,
'currentQuestion._hasBlankOptionGroups': enrichedGroups.length > 0,
groupQuestions: enrichedQuestions,
})
},
goQuestion(e) {
var index = e.detail.index
if (index === this.data.currentIndex) return
this._showQuestion(index)
this._persistReviewDraft()
},
goNext(e) {
this._showQuestion(e.detail.index)
this._persistReviewDraft()
},
goPrev(e) {
this._showQuestion(e.detail.index)
this._persistReviewDraft()
},
tapMaster(e) {
if (this.data.masterSubmitting || this.data.submittingGroup || this._masterUndoInFlight) return
var q = e.detail && e.detail.question
var scheduleId = q && q.schedule_id
if (!scheduleId) return
this.setData({ masterConfirmId: scheduleId })
},
cancelMaster() {
if (this.data.masterSubmitting) return
this.setData({ masterConfirmId: null })
},
async confirmMaster() {
if (this.data.masterSubmitting || this.data.submittingGroup) return
const scheduleId = this.data.masterConfirmId
const currentGroupSnapshot = (this.data.groupQuestions || []).slice()
const question = currentGroupSnapshot.find(q => String(q.schedule_id) === String(scheduleId))
const originalIndex = currentGroupSnapshot.findIndex(q => String(q.schedule_id) === String(scheduleId))
const originalGroupIdx = Number(this.data.currentGroupIdx || 0)
const groupsBeforeMaster = (this.data.groups || []).map(group => Array.isArray(group) ? group.slice() : [])
if (!scheduleId || !question || originalIndex < 0) return
this.setData({ masterSubmitting: true })
if (!await this._syncReviewSessionDayIfNeeded()) {
if (this._alive) this.setData({ masterSubmitting: false, masterConfirmId: null })
return
}
try {
const masterResult = await api.post(`/review/${scheduleId}/master`)
if (!this._alive) return
const serverTaskActive = !(masterResult && masterResult.active === false)
const changedByThisRequest = serverTaskActive && !(masterResult && masterResult.changed === false)
await this.refreshOverviewStatsSilently()
if (!this._alive) return
this._clearMasterUndo()
if (changedByThisRequest) {
this._pendingMasterUndo = {
scheduleId,
question,
originalAnswer: this._reviewSession.answers[scheduleId],
originalIndex: Math.max(0, originalIndex),
originalGroupIdx,
groupsBeforeMaster,
}
}
const groupQuestions = currentGroupSnapshot.filter(q => String(q.schedule_id) !== String(scheduleId))
const groups = groupsBeforeMaster.length > 0 ? groupsBeforeMaster.map(group => group.slice()) : [currentGroupSnapshot.slice()]
let safeGroupIdx = originalGroupIdx
if (safeGroupIdx < 0 || safeGroupIdx >= groups.length) safeGroupIdx = 0
if (!groups.length) groups.push(groupQuestions.slice())
else groups[safeGroupIdx] = groupQuestions.slice()
let currentIndex = Number(this.data.currentIndex || 0)
const answers = { ...this._reviewSession.answers }
delete answers[scheduleId]
this._reviewSession.answers = answers
if (changedByThisRequest) this._masteredCount = (this._masteredCount || 0) + 1
this._reviewSession.allQuestions = groupQuestions.slice()
this.setData({
masterConfirmId: null,
masterSubmitting: false,
groups,
currentGroupIdx: safeGroupIdx,
groupQuestions,
masterUndoVisible: changedByThisRequest,
masterUndoText: changedByThisRequest ? '已标记掌握，不再进入复习计划' : '',
})
if (changedByThisRequest) {
this._armMasterUndoExpiry(5000)
} else {
wx.showToast({
title: serverTaskActive ? '题目状态已同步' : '该题已移出复习计划',
icon: 'none',
})
}
if (groupQuestions.length === 0) {
this._clearReviewTimer()
const nextPhase = this.data.todayRemainingCount > 0 ? 'overview' : 'empty'
this.setData({
phase: nextPhase,
groupQuestions: [],
currentQuestion: null,
currentIndex: 0,
})
return
}
if (currentIndex >= groupQuestions.length) {
currentIndex = Math.max(0, groupQuestions.length - 1)
}
this.setData({ currentIndex })
this._syncAnsweredFlags()
this._showQuestion(currentIndex)
} catch (e) {
if (!this._alive) return
console.error('标记掌握失败', e)
this.setData({ masterSubmitting: false, masterConfirmId: null })
wx.showToast({ title: '操作失败，请重试', icon: 'none' })
}
},
async undoMaster() {
const pending = this._pendingMasterUndo
if (!pending || this._masterUndoInFlight || this.data.masterSubmitting) return
this._masterUndoInFlight = true
if (this._masterUndoTimer) {
clearTimeout(this._masterUndoTimer)
this._masterUndoTimer = null
}
try {
if (!await this._syncReviewSessionDayIfNeeded()) {
if (this._alive && this._pendingMasterUndo === pending) {
this.setData({ masterUndoVisible: true })
this._armMasterUndoExpiry(5000)
}
return
}
const unmasterResult = await api.post(`/review/${pending.scheduleId}/unmaster`)
if (!this._alive) return
if (unmasterResult && unmasterResult.active === false) {
this._clearMasterUndo()
await this.refreshOverviewStatsSilently()
if (this._alive) wx.showToast({ title: '该题已移出复习计划，无法撤销', icon: 'none' })
return
}
const restoredQuestion = {
...pending.question,
occurrence_seq: unmasterResult && unmasterResult.occurrence_seq != null
? unmasterResult.occurrence_seq
: pending.question.occurrence_seq,
}
let restoredGroups = Array.isArray(pending.groupsBeforeMaster)
? pending.groupsBeforeMaster.map(group => Array.isArray(group) ? group.slice() : [])
: []
let restoredGroupIdx = Number(pending.originalGroupIdx || 0)
if (!restoredGroups.length) {
restoredGroups = [(this._reviewSession.allQuestions || []).slice()]
restoredGroupIdx = 0
}
if (restoredGroupIdx < 0 || restoredGroupIdx >= restoredGroups.length) restoredGroupIdx = 0
let restoredGroup = restoredGroups[restoredGroupIdx].slice()
let targetIndex = restoredGroup.findIndex(q => String(q.schedule_id) === String(pending.scheduleId))
if (targetIndex >= 0) {
restoredGroup[targetIndex] = restoredQuestion
} else {
targetIndex = Math.min(Math.max(0, Number(pending.originalIndex || 0)), restoredGroup.length)
restoredGroup.splice(targetIndex, 0, restoredQuestion)
}
restoredGroups[restoredGroupIdx] = restoredGroup
this._reviewSession.allQuestions = restoredGroup.slice()
const restoredAnswers = { ...this._reviewSession.answers }
if (pending.originalAnswer !== undefined) {
restoredAnswers[pending.scheduleId] = pending.originalAnswer
}
this._reviewSession.answers = restoredAnswers
this._masteredCount = Math.max(0, (this._masteredCount || 1) - 1)
this._clearMasterUndo()
const restoredIndex = Math.min(targetIndex, Math.max(0, restoredGroup.length - 1))
this.setData({
phase: 'reviewing',
groups: restoredGroups,
currentGroupIdx: restoredGroupIdx,
groupQuestions: restoredGroup,
currentIndex: restoredIndex,
masterUndoVisible: false,
})
this._syncAnsweredFlags()
if (restoredGroup.length > 0) {
this._showQuestion(restoredIndex)
this._startReviewTimer()
}
await this.refreshOverviewStatsSilently()
if (!this._alive) return
wx.showToast({ title: '已撤销掌握', icon: 'none' })
} catch (e) {
if (!this._alive) return
console.error('撤销掌握失败', e)
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
const duration = Number(ms) > 0 ? Number(ms) : 5000
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
this._pendingMasterUndo = null
if (this._alive && this.data && this.data.masterUndoVisible) {
this.setData({ masterUndoVisible: false })
}
},
_getReviewRequestId(question) {
const session = this._reviewSession || (this._reviewSession = this._createReviewSession())
const key = [
String(question.schedule_id || ''),
String(question.question_version_id || ''),
String(question.occurrence_seq != null ? question.occurrence_seq : ''),
].join(':')
if (!key || key === '::') return ''
if (!session.reviewRequestIds) session.reviewRequestIds = {}
if (!session.reviewRequestIds[key]) {
const randomPart = Math.random().toString(36).slice(2, 10)
session.reviewRequestIds[key] = `review_${Date.now().toString(36)}_${randomPart}_${question.schedule_id}`
}
return session.reviewRequestIds[key]
},
async submitGroup() {
this._clearMasterUndo()
const { groupQuestions, submittingGroup } = this.data
const answers = this._reviewSession.answers
if (submittingGroup) return
const answeredCount = adapter.computeAnsweredCount(groupQuestions, answers, KF)
const totalCount = groupQuestions.length
const unansweredCount = totalCount - answeredCount
let treatUnansweredAsWrong = false
if (unansweredCount > 0) {
try {
const confirm = this.selectComponent('#submitConfirm')
if (!confirm) return
const choice = await confirm.show({
scenario: 'unanswered',
title: '还有未作答题目',
message: `共 ${totalCount} 题，已作答 ${answeredCount} 题，还有 ${unansweredCount} 题未作答。选择「按不会处理」将把未答题判为错误并进入复习。`,
confirmText: '按不会处理',
cancelText: '仅提交已答',
})
treatUnansweredAsWrong = !!choice
} catch (_) { return }
} else {
try {
const confirm = this.selectComponent('#submitConfirm')
if (!confirm) return
const confirmed = await confirm.show({
scenario: 'all-done',
title: '确认提交',
message: `共 ${totalCount} 题，已全部作答。确认提交并复盘？`,
confirmText: '确定提交',
cancelText: '继续检查',
})
if (!confirmed) return
} catch (_) { return }
}
this.setData({ submittingGroup: true })
if (!await this._syncReviewSessionDayIfNeeded()) {
if (this._alive) this.setData({ submittingGroup: false })
return
}
const reviews = []
for (let questionIndex = 0; questionIndex < groupQuestions.length; questionIndex++) {
const q = groupQuestions[questionIndex]
const isAnswered = adapter.isQuestionAnswered(q, answers, KF)
if (!isAnswered && !treatUnansweredAsWrong) continue
const requestId = this._getReviewRequestId(q)
if (!q.question_version_id || q.occurrence_seq === undefined || q.occurrence_seq === null || !requestId) {
wx.showToast({ title: '复习任务版本信息缺失，请刷新后重试', icon: 'none' })
this.setData({ submittingGroup: false })
return
}
reviews.push({
schedule_id: q.schedule_id,
question_id: q.question_id,
question_version_id: q.question_version_id,
occurrence_seq: q.occurrence_seq,
request_id: requestId,
user_answer: isAnswered ? (answers[q.schedule_id] || '') : '',
})
}
if (reviews.length === 0) {
wx.showToast({ title: '请至少作答 1 题，或选择按不会处理', icon: 'none' })
this.setData({ submittingGroup: false })
return
}
try {
const res = await api.post('/review/grade-batch', { reviews })
if (!this._alive) return
const results = Array.isArray(res && res.results) ? res.results : []
const submittedScheduleIds = new Set(reviews.map(item => String(item.schedule_id)))
if (results.length < reviews.length) {
wx.showToast({
title: results.length ? '部分题目批改失败' : '批改结果为空，请重试',
icon: 'none'
})
if (!results.length) {
this.setData({ submittingGroup: false })
return
}
}
const groupResults = groupQuestions.map(q => {
const resultQuestion = this._enrichForResult(q)
const r = results.find(rr => {
if (rr.schedule_id !== undefined && rr.schedule_id !== null) {
if (String(rr.schedule_id) !== String(q.schedule_id)) return false
if (rr.question_version_id != null && String(rr.question_version_id) !== String(q.question_version_id)) return false
if (rr.occurrence_seq != null && String(rr.occurrence_seq) !== String(q.occurrence_seq)) return false
return true
}
return String(rr.question_id) === String(q.question_id)
})
const isAnswered = adapter.isQuestionAnswered(q, answers, KF)
const expectedResult = submittedScheduleIds.has(String(q.schedule_id))
const resultMissing = expectedResult && !r
const submitFailed = resultMissing || !!(r && r.success === false)
const wasSubmitted = !!r && !submitFailed
const refreshRequired = !!(r && _reviewFailureNeedsRefresh(r))
const retryable = resultMissing || !!(r && r.success === false && !refreshRequired && r.retryable !== false)
return {
...resultQuestion,
isCorrect: wasSubmitted ? !!r.is_correct : false,
correctAnswer: wasSubmitted ? (r.correct_answer || '') : '',
userAnswer: answers[q.schedule_id] || '',
wasAnswered: isAnswered,
wasSubmitted,
submitFailed,
submitError: submitFailed ? ((r && r.error) || (resultMissing ? '批改结果缺失，已保留待重试' : '提交失败，请重试')) : '',
submitErrorCode: r && r.error_code ? String(r.error_code) : '',
refreshRequired,
retryable,
wasSkipped: !expectedResult && !isAnswered && !wasSubmitted && !submitFailed,
masteryPercent: wasSubmitted && Number.isFinite(Number(r.mastery_percent)) ? Number(r.mastery_percent) : null,
mastered: !!(wasSubmitted && r.mastered),
}
})
// Drafts are removed only after the server confirms that exact immutable task
// occurrence was submitted. Failed/skipped items remain available for retry.
this._clearSubmittedReviewDraft(groupQuestions, groupResults)
const groupCorrect = groupResults.filter(r => r.isCorrect && r.wasSubmitted).length
const groupWrong = groupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
const groupSkipped = groupResults.filter(r => !r.wasSubmitted).length
const groupFailed = groupResults.filter(r => r.submitFailed).length
const groupRefreshRequired = groupResults.filter(r => r.submitFailed && r.refreshRequired).length
const groupRetryableFailed = groupResults.filter(r => r.submitFailed && !r.refreshRequired).length
if (groupFailed > 0) {
const title = groupRefreshRequired > 0 && groupRetryableFailed > 0
? `${groupRefreshRequired} 题需刷新，${groupRetryableFailed} 题待重试`
: (groupRefreshRequired > 0
? `${groupRefreshRequired} 题任务已更新，将重新获取`
: `${groupRetryableFailed} 题提交失败，已保留待重试`)
wx.showToast({ title, icon: 'none' })
}
const allGroupResults = _mergeResultsByScheduleId(this._reviewSession.allGroupResults, groupResults)
const totalCorrect = allGroupResults.filter(r => r.isCorrect && r.wasSubmitted).length
const totalWrong = allGroupResults.filter(r => r.wasSubmitted && !r.isCorrect).length
const totalCompleted = allGroupResults.filter(r => r.wasSubmitted).length
const pendingQuestionIds = new Set(
groupResults
.filter(r => !r.wasSubmitted && (!r.submitFailed || !r.refreshRequired))
.map(r => String(r.schedule_id))
)
const pendingQuestions = groupQuestions.filter(q => pendingQuestionIds.has(String(q.schedule_id)))
const newGroups = pendingQuestions.length > 0
? (this.data.groups || []).concat([pendingQuestions])
: this.data.groups
const todayTaskTotalCount = Math.max(
Number(this._reviewSession.todayTaskTotalCount || 0),
Number(this.data.todayDueCount || 0),
totalCompleted
)
const completedBeforeSession = Number(this._reviewSession.completedBeforeSession || 0)
const todayCompletedCount = Math.min(
todayTaskTotalCount,
Math.max(Number(this.data.todayCompletedCount || 0), completedBeforeSession + totalCompleted)
)
const todayRemainingCount = Math.max(0, todayTaskTotalCount - todayCompletedCount)
this._reviewSession.todayTaskTotalCount = todayTaskTotalCount
this._reviewSession.allGroupResults = allGroupResults
this._reviewSession.totalCorrect = totalCorrect
this._reviewSession.totalWrong = totalWrong
this._reviewSession.totalCompleted = totalCompleted
this._pauseReviewTimer()
this.setData({
phase: 'group-result',
groups: newGroups,
groupResults,
groupWrongResults: groupResults.filter(r => r.wasSubmitted && !r.isCorrect),
groupCorrect,
groupWrong,
_groupSkipped: groupSkipped,
groupAccuracyPercent: Math.round((groupCorrect + groupWrong) > 0 ? groupCorrect / (groupCorrect + groupWrong) * 100 : 0),
todayDueCount: todayTaskTotalCount,
todayCompletedCount: todayCompletedCount,
todayRemainingCount: todayRemainingCount,
todayProgressPercent: todayTaskTotalCount > 0 ? Math.round(todayCompletedCount / todayTaskTotalCount * 100) : 0,
showGroupDetails: false,
submittingGroup: false,
_groupProgressStyle: 'width: ' + Math.round((this.data.currentGroupIdx + 1) / Math.max(1, newGroups.length) * 100) + '%',
resultDockVisible: true,
}, () => {
if (todayRemainingCount <= 0) this._showResultDockAndRefreshTimer()
})
} catch (e) {
if (!this._alive) return
console.error('提交失败', e)
wx.showToast({ title: '提交失败，请重试', icon: 'none' })
this.setData({ submittingGroup: false })
}
},
async nextGroup() {
this._clearMasterUndo()
this._clearResultDockFadeTimer()
if (this.data.resultTransitioning) return
const flowSeq = ++this._flowRequestSeq
this.setData({ resultTransitioning: true })
if (!await this._syncReviewSessionDayIfNeeded()) {
if (this._alive && flowSeq === this._flowRequestSeq) this.setData({ resultTransitioning: false })
return
}
const currentGroups = this.data.groups
const nextGroupIdx = this.data.currentGroupIdx + 1
if (nextGroupIdx < currentGroups.length && currentGroups[nextGroupIdx] && currentGroups[nextGroupIdx].length > 0) {
const retryQuestions = currentGroups[nextGroupIdx]
const previousAnswers = this._reviewSession.answers || {}
const retryAnswers = {}
retryQuestions.forEach(q => {
const sid = String(q.schedule_id)
if (Object.prototype.hasOwnProperty.call(previousAnswers, sid)) retryAnswers[sid] = previousAnswers[sid]
else if (Object.prototype.hasOwnProperty.call(previousAnswers, q.schedule_id)) retryAnswers[q.schedule_id] = previousAnswers[q.schedule_id]
})
this._reviewSession.answers = retryAnswers
this._reviewSession.allQuestions = retryQuestions.slice()
this.setData({
phase: 'reviewing',
currentGroupIdx: nextGroupIdx,
groupQuestions: retryQuestions,
currentIndex: 0,
groupResults: [],
groupWrongResults: [],
groupCorrect: 0,
groupWrong: 0,
groupAccuracyPercent: 0,
showGroupDetails: false,
resultTransitioning: false,
})
this._syncAnsweredFlags()
this._showQuestion(0)
this._startReviewTimer()
return
}
if (this.data.todayRemainingCount > 0) {
try {
const batch = await api.post('/review/today/next-batch', {
batch_size: this.data.reviewBatchSize,
})
if (!this._alive || flowSeq !== this._flowRequestSeq) return
const rawQuestions = batch.questions || []
if (rawQuestions.length > 0) {
const questions = rawQuestions.map(normalizeReviewQuestion).filter(Boolean)
const restoredDraft = this._restoreReviewDraft(questions)
this._reviewSession.allQuestions = questions
this._reviewSession.answers = restoredDraft.answers
this.setData({
phase: 'reviewing',
groups: [questions],
currentGroupIdx: 0,
groupQuestions: questions,
currentIndex: restoredDraft.currentIndex,
currentBatchNo: batch.batch_no || this.data.currentBatchNo + 1,
totalBatchCount: batch.total_batch_count || this.data.totalBatchCount,
todayDueCount: this._reviewSession.todayTaskTotalCount || this.data.todayDueCount,
todayCompletedCount: this.data.todayCompletedCount,
todayRemainingCount: this.data.todayRemainingCount,
groupResults: [],
groupWrongResults: [],
groupCorrect: 0,
groupWrong: 0,
groupAccuracyPercent: 0,
showGroupDetails: false,
resultTransitioning: false,
})
this._syncAnsweredFlags()
this._showQuestion(restoredDraft.currentIndex)
this._startReviewTimer()
if (restoredDraft.restoredCount > 0) {
wx.showToast({ title: `已恢复 ${restoredDraft.restoredCount} 题草稿`, icon: 'none' })
}
return
}
await this.refreshOverviewStatsSilently()
if (!this._alive || flowSeq !== this._flowRequestSeq) return
if (this.data.todayRemainingCount > 0) {
wx.showToast({ title: '任务状态已更新，请稍后重试', icon: 'none' })
this.setData({ resultTransitioning: false })
return
}
} catch (e) {
if (!this._alive || flowSeq !== this._flowRequestSeq) return
console.error('获取下一组失败', e)
wx.showToast({ title: '获取下一组失败', icon: 'none' })
this.setData({ resultTransitioning: false })
return
}
}
this.setData({
todayRemainingCount: 0,
resultTransitioning: false,
resultDockVisible: true,
}, () => this._showResultDockAndRefreshTimer())
},
_clearResultDockFadeTimer() {
if (this._resultDockFadeTimer) {
clearTimeout(this._resultDockFadeTimer)
this._resultDockFadeTimer = null
}
},
_showResultDockAndRefreshTimer() {
if (this.data.phase !== 'group-result' || this.data.todayRemainingCount > 0) return
this._clearResultDockFadeTimer()
if (!this.data.resultDockVisible) {
this.setData({ resultDockVisible: true })
}
this._resultDockFadeTimer = setTimeout(() => {
this._resultDockFadeTimer = null
if (this._alive && this.data.phase === 'group-result' && this.data.todayRemainingCount <= 0) {
this.setData({ resultDockVisible: false })
}
}, 5000)
},
onResultPageInteraction() {
this._showResultDockAndRefreshTimer()
},
onPageScroll() {
this._showResultDockAndRefreshTimer()
},
goWrongBook() {
wx.navigateTo({ url: '/subpackages/study/wrong-book/wrong-book' })
},
goPractice() {
wx.navigateTo({ url: '/subpackages/study/practice/practice' })
},
onNavBack() {
if (this.data.phase === 'reviewing') {
this.setData({ exitConfirmVisible: true })
return
}
const pages = getCurrentPages()
if (pages.length > 1) wx.navigateBack()
else wx.reLaunch({ url: '/pages/home/home' })
},
closeExitConfirm() {
this.setData({ exitConfirmVisible: false })
},
confirmExitReview() {
this._clearMasterUndo()
this._clearReviewTimer()
this.setData({ exitConfirmVisible: false })
const pages = getCurrentPages()
if (pages.length > 1) wx.navigateBack()
else wx.reLaunch({ url: '/pages/home/home' })
},
toggleGroupDetails() {
this._showResultDockAndRefreshTimer()
this.setData({ showGroupDetails: !this.data.showGroupDetails })
},
retryLoad() {
this.loadTodayReviewOverview()
},
noop() {},
subjectLabel(name, code) {
if (name) return name
return getSubjectName(code || name)
},
_safeTickDelta(rawMs) {
if (rawMs < 0) return 0
if (rawMs > 10000) return 10000
return rawMs
},
_startReviewTimer() {
if (this._timerInterval) return
this._reviewSession.timerElapsedMs = 0
this._reviewSession.timerStartedAt = _reviewMonotonicNow()
this._reviewSession.timerLastTickAt = this._reviewSession.timerStartedAt
this._reviewSession.timerRunning = true
var self = this
this._timerInterval = setInterval(function () {
if (!self._alive) return
var session = self._reviewSession
var now = _reviewMonotonicNow()
var lastTickAt = session.timerLastTickAt || session.timerStartedAt || now
session.timerElapsedMs += self._safeTickDelta(now - lastTickAt)
session.timerLastTickAt = now
self.setData({ elapsedText: formatReviewElapsed(Math.floor(session.timerElapsedMs / 1000)) })
}, 1000)
},
_pauseReviewTimer() {
if (!this._timerInterval) return
var now = _reviewMonotonicNow()
var lastTickAt = this._reviewSession.timerLastTickAt || this._reviewSession.timerStartedAt || now
this._reviewSession.timerElapsedMs += this._safeTickDelta(now - lastTickAt)
this._reviewSession.timerLastTickAt = 0
this._reviewSession.timerRunning = false
clearInterval(this._timerInterval)
this._timerInterval = null
},
_resumeReviewTimer() {
if (this._timerInterval || this._reviewSession.timerRunning) return
this._reviewSession.timerStartedAt = _reviewMonotonicNow()
this._reviewSession.timerLastTickAt = this._reviewSession.timerStartedAt
this._reviewSession.timerRunning = true
var self = this
this._timerInterval = setInterval(function () {
if (!self._alive) return
var session = self._reviewSession
var now = _reviewMonotonicNow()
var lastTickAt = session.timerLastTickAt || session.timerStartedAt || now
session.timerElapsedMs += self._safeTickDelta(now - lastTickAt)
session.timerLastTickAt = now
self.setData({ elapsedText: formatReviewElapsed(Math.floor(session.timerElapsedMs / 1000)) })
}, 1000)
},
_resetReviewTimer() {
this._pauseReviewTimer()
this._reviewSession.timerElapsedMs = 0
this._reviewSession.timerStartedAt = 0
this._reviewSession.timerLastTickAt = 0
this._reviewSession.timerRunning = false
this.setData({ elapsedText: '00:00' })
},
_clearReviewTimer() {
if (this._timerInterval) {
clearInterval(this._timerInterval)
this._timerInterval = null
}
this._reviewSession.timerLastTickAt = 0
this._reviewSession.timerRunning = false
},
showBatchSizeSelector() {
if (this.data.phase !== 'overview') return
if (this.data.isStarting || this.data.isContinuing) return
this.setData({
pendingBatchSize: this.data.reviewBatchSize,
showBatchSizeSheet: true,
})
},
handleBatchSheetMaskTap() {
this.closeBatchSizeSheet()
},
stopBatchSheetPropagation() {
},
closeBatchSizeSheet() {
this.setData({ showBatchSizeSheet: false })
},
selectPendingBatchSize(e) {
var value = Number(e.currentTarget.dataset.value)
if (REVIEW_BATCH_SIZE_OPTIONS.indexOf(value) === -1) return
this.setData({ pendingBatchSize: value })
},
confirmBatchSize() {
var pending = this.data.pendingBatchSize
pending = normalizeReviewBatchSize(pending)
this._userSelectedReviewBatchSize = true
this.setData({
reviewBatchSize: pending,
showBatchSizeSheet: false,
})
},
})
if (typeof module !== 'undefined' && module.exports) {
module.exports = {
normalizeReviewBatchSize,
formatReviewElapsed,
normalizeReviewQuestion,
REVIEW_BATCH_SIZE_OPTIONS,
REVIEW_DRAFT_PREFIX,
BATCH_SIZE_OPTIONS_META: [
{ value: 5, label: '快速复习' },
{ value: 10, label: '推荐' },
{ value: 20, label: '集中巩固' },
{ value: 30, label: '深度复习' },
],
}
}
