const api = require('../../../utils/api')
const config = require('../../../config')
const { debugLog, saveDebugSnapshot, shouldDebugQuestion } = require('../../../utils/debug')
const { buildRenderModel, setRenderGuardPage, resetRenderGuard } = require('../utils/stem-render')
const adapter = require('../utils/question-runner-adapter')
const questionImageCache = require('../utils/question-image-cache')
const { filter408SubjectTree } = require('../utils/subject-scope')
const { safeDecodeURIComponent } = require('../utils/route-params')
const {
  normalizeSubjectTree,
  flattenSelectableSubjects,
  subjectMark,
  subjectIconMeta,
  decorateRecentSubjects,
  findParentSubjectId,
  subjectHasChildren,
  getPracticeSubjectScopeIds,
} = require('./utils/subject-tree')
const {
  parseLaunchPreset,
  launchPresetOverrides,
  fastLaunchPresetView,
  resolvedLaunchPresetView,
  applyLaunchOverrides,
} = require('./utils/launch-preset')
const {
  buildQuestionRequestParams,
  validateKnowledgeScope,
  findQuestionBatchError,
} = require('./utils/question-batch')
const {
  RECENT_SUBJECTS_STORAGE_KEY,
  selectDefaultSubject,
  rememberSubject,
} = require('./utils/recent-subjects')
const {
  buildResetView,
  applyBatchCredentials,
  hasMissingBatchCredentials,
  buildSequentialRestartView,
  resetSequentialTiming,
  buildLoadedView,
} = require('./utils/question-load-state')
const {
  createSequentialRestartController,
} = require('./utils/sequential-restart-controller')
const PRACTICE_PENDING_SUBMISSION_KEY_PREFIX = 'practice_pending_submission_v1'
const PRACTICE_PENDING_SUBMISSION_TTL_MS = 24 * 60 * 60 * 1000
const SUBJECT_DOUBLE_TAP_INTERVAL = 320
const PRACTICE_ANSWERABLE_TYPES = new Set(['single_choice', 'multiple_choice', 'true_false', 'multi_blank_choice', 'multi_blank_multiple_choice'])
let _practicePerformanceClock = null
function _monotonicNow() {
try {
if (!_practicePerformanceClock && typeof wx !== 'undefined' && typeof wx.getPerformance === 'function') {
_practicePerformanceClock = wx.getPerformance()
}
if (_practicePerformanceClock && typeof _practicePerformanceClock.now === 'function') {
return _practicePerformanceClock.now()
}
} catch (_) {}
return Date.now()
}
function _deduplicateLines(text) {
if (!text) return text
const lines = text.split('\n')
const out = []
for (let i = 0; i < lines.length; i++) {
if (i === 0 || lines[i].trim() !== lines[i - 1].trim()) {
out.push(lines[i])
}
}
return out.join('\n')
}
function _needsRichRender(text) {
if (!text) return false
return /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/.test(text) || /<\/?[a-z][\s\S]*>/i.test(text)
}
function _escapeRegExp(text) {
return String(text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
function _replaceSimpleLatexCommands(text) {
return String(text || '')
.replace(/\\leq/g, '≤')
.replace(/\\geq/g, '≥')
.replace(/\\neq/g, '≠')
.replace(/\\times/g, '×')
.replace(/\\cdot/g, '·')
.replace(/\\lt/g, '<')
.replace(/\\gt/g, '>')
}
function _toPlainInlineMathText(text) {
if (!text) return ''
const source = String(text)
if (/\$\$[\s\S]*?\$\$/.test(source) || /<\/?[a-z][\s\S]*>/i.test(source)) return null
let plain = source.replace(/\$([^$\n]+?)\$/g, function(_, expr) {
return _replaceSimpleLatexCommands(expr).trim()
})
if (/\\[a-zA-Z]+/.test(plain)) return null
plain = plain.replace(/[ \t]+/g, ' ').replace(/\s+([，。！？；：,.!?;:])/g, '$1').trim()
return plain
}
function _stripLeadingOptionLabel(key, value) {
const text = String(value || '').trim()
if (!key || !text) return text
const label = _escapeRegExp(String(key).trim())
const labelPattern = new RegExp(`^${label}[\\s\\u00A0]*[.．、:：）)]\\s*`, 'i')
if (/^\s*\$/.test(text)) {
const inner = text.replace(/^\s*\$\s*/, '')
return '$' + inner.replace(labelPattern, '')
}
return text.replace(labelPattern, '')
}
function _normalizeOptionText(text) {
return String(text || '')
.replace(/<[^>]+>/g, ' ')
.replace(/&nbsp;/gi, ' ')
.replace(/\s+/g, ' ')
.trim()
}
function _buildOptionPattern(key, value) {
const label = _escapeRegExp(String(key || '').trim())
const normalizedValue = _normalizeOptionText(value)
if (!label || !normalizedValue) return ''
const spaces = '[\\s\\u00A0]*'
const separator = '[.．、:：）)]'
const valuePattern = _escapeRegExp(normalizedValue).replace(/\s+/g, '[\\s\\u00A0]+')
return `${label}${spaces}${separator}${spaces}${valuePattern}`
}
function _stripEmbeddedOptionBlock(stemText, options) {
if (!stemText || !options) return stemText
const patterns = Object.keys(options)
.sort()
.map((key) => _buildOptionPattern(key, options[key]))
.filter(Boolean)
if (patterns.length < 2) return stemText
const gap = '(?:\\s|<br>|\\n|\\r|&nbsp;)*'
const blockRegex = new RegExp(`${gap}${patterns.join(gap)}\\s*$`, 'i')
return blockRegex.test(stemText) ? stemText.replace(blockRegex, '').trim() : stemText
}
function _stripTrailingOptionBlockByLabels(stemText, optionKeys) {
if (!stemText || !optionKeys || optionKeys.length < 2) return stemText
const matches = _findOptionLabelMatches(stemText, optionKeys)
if (matches.length < 2) return stemText
for (let matchIndex = 0; matchIndex < matches.length; matchIndex++) {
const index = matches[matchIndex]
const suffix = stemText.slice(index)
if (_hasTrailingOptionBlock(suffix, optionKeys)) return stemText.slice(0, index).trim()
}
return stemText
}
function _findOptionLabelMatches(text, optionKeys) {
if (!text || !optionKeys || optionKeys.length < 2) return []
const labels = optionKeys.map(_escapeRegExp).join('|')
const labelMarker = `(?:^|[\\s\\n\\r])(?:${labels})[\\s\\u00A0]*[.．、:：）)]`
const labelRegex = new RegExp(labelMarker, 'g')
const matches = []
let match
while ((match = labelRegex.exec(text)) !== null) {
const index = match.index + (match[0].match(/^[\s\n\r]/) ? 1 : 0)
matches.push(index)
}
return matches
}
function _containsTrailingOptionBlock(text, optionKeys) {
const matches = _findOptionLabelMatches(text, optionKeys)
if (matches.length < 2) return false
return matches.some(index => _hasTrailingOptionBlock(String(text || '').slice(index), optionKeys))
}
function _hasTrailingOptionBlock(text, optionKeys) {
if (!text || !optionKeys || optionKeys.length < 2) return false
const keys = optionKeys.map(key => String(key || '').trim()).filter(Boolean)
if (keys.length < 2) return false
const spaces = '[\\s\\u00A0]*'
const separator = '[.．、:：）)]'
const marker = (key, prefix) => `${prefix}${_escapeRegExp(key)}${spaces}${separator}`
const first = marker(keys[0], '^' + spaces)
const second = marker(keys[1], '[\\s\\n\\r]+')
const required = new RegExp(first + '[\\s\\S]+?' + second, 'i')
if (!required.test(text)) return false
const labels = keys.map(_escapeRegExp).join('|')
const labelRegex = new RegExp(`(?:^|[\\s\\n\\r])(?:${labels})${spaces}${separator}`, 'g')
const found = []
let match
while ((match = labelRegex.exec(text)) !== null) {
found.push(String(match[0]).replace(/^[\s\n\r]+/, '').charAt(0).toUpperCase())
}
if (found.length < 2) return false
return found[0] === keys[0].toUpperCase() && found[1] === keys[1].toUpperCase()
}
function _shortText(text) {
const normalized = String(text || '').replace(/\s+/g, ' ').trim()
return normalized.length > 80 ? normalized.slice(0, 80) + '...' : normalized
}
function _textToSegments(text) {
if (!text) return []
const lines = String(text).split('\n')
const segments = []
lines.forEach((line, index) => {
if (line) segments.push({ type: 'text', text: line })
if (index < lines.length - 1) segments.push({ type: 'newline' })
})
return segments
}
function _cleanStemText(stemText, options, optionKeys) {
const dedupedStem = _deduplicateLines(stemText)
const withoutExactOptions = _stripEmbeddedOptionBlock(dedupedStem, options)
const withoutLabelOptions = _stripTrailingOptionBlockByLabels(withoutExactOptions, optionKeys)
return _removeTrailingOptionKeys(withoutLabelOptions, optionKeys)
}
function _removeTrailingOptionKeys(text, optionKeys) {
if (!text || !optionKeys || optionKeys.length === 0) return text
const keys = optionKeys.map(_escapeRegExp).join('')
const pattern = new RegExp('\\s+[' + keys + ']\\s*$', 'g')
return text.replace(pattern, '')
}
function _optionTextToHtml(key, value) {
const text = String(value || '').trim()
if (!key) return _textToHtml(text)
const keyPattern = new RegExp(`^${_escapeRegExp(String(key))}[\\s\\u00A0]*[.．、:：）)]?\\s*`, 'i')
const normalized = keyPattern.test(text) ? text : `${key}. ${text}`
return _textToHtml(normalized)
}
Page({
_pageAlive: false,
_practiceSession: {},
_lastSubjectOptionTap: null,
data: {
subjectTree: [],
selectedSubjectId: null,
selectedSubjectName: '',
selectedSubjectHasChildren: false,
expandedSubjectId: null,
selectedMode: 'random',
selectedModeLabel: '随机挑战',
count: 5,
countDisplay: '05',
estimatedMinutes: 10,
settingsExpanded: false,
subjectSheetVisible: false,
subjectSheetClosing: false,
recentSubjects: [],
statusBarHeight: 20,
navBarHeight: 44,
started: false,
loading: false,
launchingPreset: false,
entryResolved: false,
submitting: false,
practiceExitGuardVisible: false,
progressPercent: 0,
errorText: '',
sequentialProgress: null,
questions: [],
currentIndex: 0,
totalQuestions: 0,
currentQuestion: null,
currentAnswerState: null,
answeredCount: 0,
submitted: false,
feedbackVisible: false,
feedbackType: '',
feedbackTitle: '',
feedbackDetail: '',
feedbackComboText: '',
feedbackComboLevel: '',
feedbackStarCount: 0,
elapsedText: '00:00',
_timer: null,
enableMathImage: false,
},
onLoad(options) {
this._pageAlive = true
this._subjectsRequestSeq = 0
this._questionsRequestSeq = 0
this._lastSubjectOptionTap = null
this._exitConfirmInFlight = false
this._systemBackPromptQueued = false
this._systemBackRearming = false
this._systemBackRearmTimer = null
this._returnNavigationLocked = false
this._launchPreset = this._parseLaunchPreset(options || {})
const fastKnowledgeSources = new Set(['knowledge_map', 'knowledge_diagnosis'])
this._fastLaunchEligible = Boolean(
this._launchPreset &&
fastKnowledgeSources.has(this._launchPreset.source) &&
this._launchPreset.autostart &&
this._launchPreset.subjectId &&
this._launchPreset.knowledgePointId
)
this.setData({
entryResolved: true,
launchingPreset: Boolean(this._fastLaunchEligible),
})
this._launchKnowledgePoint = ''
this._launchKnowledgePointId = null
this._launchIncludeDescendants = false
this._launchQuestionIds = ''
this._launchAllowRepeat = false
this._launchSource = ''
this._launchPlanToken = ''
this._launchReturnTo = ''
this._resetSession()
this._pendingResultUrl = ''
this._submittedResultPayload = null
setRenderGuardPage('practice')
resetRenderGuard()
this._initCustomNavigation()
this._updateComputedFields()
},
onUnload() {
this._pageAlive = false
if (this._practiceSession) this._practiceSession.exitGuardActive = false
this._exitConfirmInFlight = false
this._systemBackPromptQueued = false
this._systemBackRearming = false
if (this._systemBackRearmTimer) {
clearTimeout(this._systemBackRearmTimer)
this._systemBackRearmTimer = null
}
this._subjectsRequestSeq++
this._questionsRequestSeq++
this._lastSubjectOptionTap = null
resetRenderGuard()
this._clearTimer()
if (this._feedbackTimer) {
clearTimeout(this._feedbackTimer)
this._feedbackTimer = null
}
if (this._subjectSheetCloseTimer) {
clearTimeout(this._subjectSheetCloseTimer)
this._subjectSheetCloseTimer = null
}
},
_resetSession() {
this._practiceSession = {
traceId: '',
safeModeActive: false,
answerMap: {},
answeredFlags: {},
correctCount: 0,
comboCount: 0,
elapsedSec: 0,
activeStartedMonoMs: 0,
startedAtMs: 0,
questionTimeMap: {},
currentQuestionStartedMonoMs: 0,
requestId: '',
recommendationRequestId: '',
batchToken: '',
batchMode: '',
knowledgeScope: null,
submissionSnapshot: null,
backgroundMs: 0,
_backgroundStartedMonoMs: null,
_timingPauseActive: false,
optionKeys: [],
questionRenderCache: Object.create(null),
exitGuardActive: false,
exitGuardMessage: '',
}
},
_getCurrentUserId() {
try {
const user = wx.getStorageSync('user')
if (!user || typeof user !== 'object') return ''
const candidates = [user.id, user.user_id, user.openid]
for (let candidateIndex = 0; candidateIndex < candidates.length; candidateIndex++) {
const candidate = candidates[candidateIndex]
if (candidate === undefined || candidate === null) continue
const value = String(candidate).trim()
if (value) return value
}
return ''
} catch (_) {
return ''
}
},
_pendingSubmissionStorageKey() {
const userId = this._getCurrentUserId()
return userId ? `${PRACTICE_PENDING_SUBMISSION_KEY_PREFIX}:${userId}` : ''
},
_readPendingSubmission() {
const key = this._pendingSubmissionStorageKey()
if (!key) return null
try {
const item = wx.getStorageSync(key)
if (!item || item.version !== 1 || !item.submission) return null
const createdAt = Number(item.createdAt) || 0
const freshnessAt = Number(item.updatedAt) || createdAt
if (!freshnessAt || Date.now() - freshnessAt > PRACTICE_PENDING_SUBMISSION_TTL_MS) {
wx.removeStorageSync(key)
return null
}
return item
} catch (_) {
return null
}
},
_persistPendingSubmission(submission, status, resultUrl) {
const key = this._pendingSubmissionStorageKey()
if (!key || !submission) return false
const previousPersisted = !!submission.pendingPersisted
try {
const previous = wx.getStorageSync(key)
const createdAt = previous && previous.submission && previous.submission.requestId === submission.requestId
? (Number(previous.createdAt) || Date.now())
: Date.now()
submission.pendingPersisted = true
wx.setStorageSync(key, {
version: 1,
createdAt,
updatedAt: Date.now(),
status: status || 'pending',
resultUrl: resultUrl || '',
submission,
})
return true
} catch (e) {
submission.pendingPersisted = previousPersisted
console.warn('保存待确认交卷失败', e)
return false
}
},
_clearPendingSubmission(requestId) {
const key = this._pendingSubmissionStorageKey()
if (!key) return
try {
const item = wx.getStorageSync(key)
if (!requestId || !item || !item.submission || item.submission.requestId === requestId) {
wx.removeStorageSync(key)
}
} catch (_) {}
},
async _offerPendingSubmissionRecovery() {
const pending = this._readPendingSubmission()
if (!pending || !this._pageAlive) return false
const submission = pending.submission
if (pending.status === 'submitted' && pending.resultUrl) {
const confirmed = await this._showSubmitConfirm({
scenario: 'info',
title: '上次练习已交卷',
message: '结果页尚未确认打开，是否继续查看？',
confirmText: '查看结果',
cancelText: '稍后处理',
hideEyebrow: true,
})
if (confirmed && this._pageAlive) {
this._practiceSession.submissionSnapshot = submission
this._practiceSession.requestId = submission.requestId || ''
this._pendingResultUrl = pending.resultUrl
this.setData({ submitted: true, submitting: false })
this._setPracticeUnloadGuard(false)
this._openSubmittedResult(pending.resultUrl, submission)
return true
}
return false
}
if (pending.status === 'blocked' || submission.retryBlocked) {
const confirmed = await this._showSubmitConfirm({
scenario: 'danger',
title: '上次交卷无法继续确认',
message: '该提交已被服务器拒绝。清除本地状态后即可重新开始。',
confirmText: '清除状态',
cancelText: '暂不处理',
hideEyebrow: true,
})
if (confirmed) this._clearPendingSubmission(submission.requestId)
return false
}
const confirmed = await this._showSubmitConfirm({
scenario: 'info',
title: '发现待确认交卷',
message: '可继续确认上次交卷，不会重复计入答题记录。',
confirmText: '继续确认',
cancelText: '稍后处理',
hideEyebrow: true,
})
if (!confirmed || !this._pageAlive) return false
this._resetSession()
this._practiceSession.submissionSnapshot = submission
this._practiceSession.requestId = submission.requestId || ''
this._practiceSession.traceId = submission.traceId || ''
this.setData({ started: true, submitted: false, submitting: false })
this._setPracticeUnloadGuard(true, '交卷仍在确认中。')
await this.doSubmit(true)
if (!this.data.submitted && this._pageAlive) {
this._setPracticeUnloadGuard(false)
this.setData({ started: false })
return false
}
return true
},
_openSubmittedResult(resultUrl, submission) {
if (!resultUrl || !this._pageAlive) return
if (submission && submission.keepPendingUntilResult && !submission.pendingPersisted) {
try {
if (!this._submittedResultPayload) throw new Error('missing in-memory result payload')
wx.setStorageSync('lastPracticeResult', this._submittedResultPayload)
submission.keepPendingUntilResult = false
} catch (storageError) {
console.warn('结果缓存与待确认快照均不可持久化', storageError)
this._showSubmitConfirm({
scenario: 'info',
title: '复盘数据暂未保存',
message: '成绩已保存。请保持当前页面，释放设备存储后再次打开复盘。',
showCancel: false,
confirmText: '知道了',
hideEyebrow: true,
})
return
}
}
this._pendingResultUrl = resultUrl
wx.redirectTo({
url: resultUrl,
success: () => {
if (this._practiceSession && this._practiceSession.submissionSnapshot === submission) {
this._practiceSession.submissionSnapshot = null
}
this._pendingResultUrl = ''
},
fail: (err) => {
console.error('结果页打开失败', err)
if (!this._pageAlive) return
this.setData({ submitting: false, submitted: true })
this._setPracticeUnloadGuard(false)
this._showSubmitConfirm({
scenario: 'info',
title: '结果页打开失败',
message: submission && submission.pendingPersisted
? '成绩已保存，可稍后再次打开复盘。'
: '成绩已保存，请保持当前页面后再次打开复盘。',
showCancel: false,
confirmText: '知道了',
hideEyebrow: true,
})
},
})
},
onShow() {
const s = this._practiceSession
if (s && s._timingPauseActive) return
if (s && s.activeStartedMonoMs && s._backgroundStartedMonoMs !== null) {
s.backgroundMs = (s.backgroundMs || 0) + (_monotonicNow() - s._backgroundStartedMonoMs)
s._backgroundStartedMonoMs = null
}
if (s && s.activeStartedMonoMs && this.data.started && !this.data.loading && !this.data.submitting && !s.submissionSnapshot) {
s.currentQuestionStartedMonoMs = _monotonicNow()
}
},
onHide() {
const s = this._practiceSession
if (s && s._timingPauseActive) return
if (s && s.activeStartedMonoMs && s._backgroundStartedMonoMs === null) {
if (this.data.started && !this.data.loading && !this.data.submitting && !s.submissionSnapshot) {
this._settleQuestionTime(true)
}
s._backgroundStartedMonoMs = _monotonicNow()
}
},
async onReady() {
if (config.DEV) console.log('[LAYER6_ONREADY]', Date.now())
this.setData({ enableMathImage: config.enableMathImage || false })
const recoveryHandled = await this._offerPendingSubmissionRecovery()
if (recoveryHandled || !this._pageAlive) {
if (this.data.launchingPreset) this.setData({ launchingPreset: false })
return
}
if (this._fastLaunchEligible) {
const applied = await this._applyFastLaunchPreset()
if (applied && this._pageAlive) {
await this.startPractice()
if (this._pageAlive) {
this.loadPracticeSubjects({ skipAutostart: true, preserveSelection: true, silent: true }).catch(() => {})
}
return
}
}
if (this.data.launchingPreset) this.setData({ launchingPreset: false })
this.loadPracticeSubjects()
},
async loadPracticeSubjects(options = {}) {
const requestSeq = ++this._subjectsRequestSeq
try {
const res = await api.get('/practice/subjects')
if (!this._pageAlive || requestSeq !== this._subjectsRequestSeq) return
const subjectTree = this.normalizeSubjectTree(filter408SubjectTree(res || []))
this.setData({ subjectTree })
if (options.preserveSelection && this.data.selectedSubjectId) {
const available = this._flattenSelectableSubjects(subjectTree || [])
const target = available.find(item => Number(item.subject_id) === Number(this.data.selectedSubjectId))
if (target) {
this.setData({
selectedSubjectName: this.data.selectedSubjectName || target.display_name,
selectedSubjectHasChildren: Boolean(target.has_children),
expandedSubjectId: target.parent_subject_id || target.subject_id,
})
}
} else {
this.initDefaultSubject(subjectTree)
}
if (!options.skipAutostart) {
const presetApplied = await this._applyLaunchPreset(subjectTree)
if (presetApplied && this._launchPreset && this._launchPreset.autostart && this._pageAlive) {
await this.startPractice()
}
}
} catch (e) {
if (!this._pageAlive || requestSeq !== this._subjectsRequestSeq) return
console.error('加载科目树失败', e)
if (!options.silent) wx.showToast({ title: '加载科目失败', icon: 'none' })
}
},
_parseLaunchPreset(options) {
return parseLaunchPreset(options, safeDecodeURIComponent)
},
async _applyFastLaunchPreset() {
const preset = this._launchPreset
if (!preset || !preset.subjectId || !preset.autostart) return false
const subjectName = preset.subjectName || this.data.selectedSubjectName || '专项练习'
applyLaunchOverrides(this, launchPresetOverrides(preset))
await new Promise(resolve => {
const view = fastLaunchPresetView(preset, this.data.selectedMode, this.data.count)
view.selectedSubjectName = subjectName
this.setData(view, () => {
this._updateComputedFields()
resolve()
})
})
this._queueRememberSubject(Number(preset.subjectId), subjectName)
return true
},
async _applyLaunchPreset(subjectTree) {
const preset = this._launchPreset
const available = this._flattenSelectableSubjects(subjectTree || [])
if (preset && preset.subjectCode && !preset.subjectId) {
const byCode = available.find(item => String(item.subject_code || '') === String(preset.subjectCode || ''))
if (byCode) preset.subjectId = Number(byCode.subject_id)
}
if (!preset || !preset.subjectId) return false
const target = available.find(item => Number(item.subject_id) === Number(preset.subjectId))
if (!target) {
console.warn('[PRACTICE_LAUNCH_PRESET] subject unavailable', preset.subjectId)
if (preset.autostart) wx.showToast({ title: '推荐科目已不可用，请重新选择', icon: 'none' })
return false
}
if (preset.questionIds && preset.mode && preset.mode !== 'random') {
console.warn('[PRACTICE_LAUNCH_PRESET] targeted questions require random mode')
return false
}
applyLaunchOverrides(this, launchPresetOverrides(preset))
await new Promise((resolve) => {
const view = resolvedLaunchPresetView(preset, target, this.data.selectedMode, this.data.count)
this.setData(view, () => {
this._updateComputedFields()
resolve()
})
})
this._queueRememberSubject(Number(target.subject_id), target.display_name)
return true
},
normalizeSubjectTree(raw) {
  return normalizeSubjectTree(raw)
},
initDefaultSubject(subjectTree) {
if (!subjectTree || subjectTree.length === 0) {
this.setData({
selectedSubjectId: null,
selectedSubjectName: '',
selectedSubjectHasChildren: false,
expandedSubjectId: null,
recentSubjects: [],
})
return
}
let stored = []
try {
const value = wx.getStorageSync(RECENT_SUBJECTS_STORAGE_KEY)
stored = Array.isArray(value) ? value : []
} catch (e) {
stored = []
}
const selection = selectDefaultSubject({
subjectTree,
storedSubjects: stored,
flattenSelectableSubjects: tree => this._flattenSelectableSubjects(tree),
decorateRecentSubjects: subjects => this._decorateRecentSubjects(subjects),
})
if (selection) this.setData(selection.view)
},
_initCustomNavigation() {
try {
const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
const statusBarHeight = Number(windowInfo.statusBarHeight || 20)
let navBarHeight = 44
if (wx.getMenuButtonBoundingClientRect) {
const capsule = wx.getMenuButtonBoundingClientRect()
if (capsule && capsule.height && capsule.top) {
navBarHeight = (capsule.top - statusBarHeight) * 2 + capsule.height
}
}
this.setData({
statusBarHeight: Math.max(20, statusBarHeight),
navBarHeight: Math.max(40, navBarHeight),
})
} catch (e) {
this.setData({ statusBarHeight: 20, navBarHeight: 44 })
}
},
_flattenSelectableSubjects(subjectTree) {
  return flattenSelectableSubjects(subjectTree)
},
_subjectMark(name) {
  return subjectMark(name)
},
_subjectIconMeta(name, code) {
  return subjectIconMeta(name, code)
},
_decorateRecentSubjects(subjects) {
  return decorateRecentSubjects(subjects, id => this._subjectHasChildren(id))
},
_rememberSubject(subjectId, subjectName) {
const id = Number(subjectId)
if (!id || !subjectName) return
const parentId = this._findParentSubjectId(id)
const hasChildren = this._subjectHasChildren(id)
const result = rememberSubject({
subjectId: id,
subjectName,
parentSubjectId: parentId,
hasChildren,
currentRecentSubjects: this.data.recentSubjects || [],
decorateRecentSubjects: subjects => this._decorateRecentSubjects(subjects),
})
this.setData(result.view)
try {
wx.setStorageSync(RECENT_SUBJECTS_STORAGE_KEY, result.storageValue)
} catch (e) {
console.warn('保存最近使用科目失败', e)
}
},
_queueRememberSubject(subjectId, subjectName) {
const id = Number(subjectId)
if (!id || !subjectName) return
this._pendingRememberSubject = { subjectId: id, subjectName }
},
_flushPendingRecentSubject() {
const pending = this._pendingRememberSubject
this._pendingRememberSubject = null
if (!pending) return
this._rememberSubject(pending.subjectId, pending.subjectName)
},
_findParentSubjectId(subjectId) {
  return findParentSubjectId(subjectId, this.data.subjectTree)
},
_subjectHasChildren(subjectId) {
  return subjectHasChildren(subjectId, this.data.subjectTree)
},
_getPracticeSubjectScopeIds(subjectId, includeChildren) {
  return getPracticeSubjectScopeIds(subjectId, includeChildren, this.data.subjectTree)
},
toggleSettings() {
this.setData({ settingsExpanded: !this.data.settingsExpanded })
},
openSubjectSheet() {
if (this._subjectSheetCloseTimer) {
clearTimeout(this._subjectSheetCloseTimer)
this._subjectSheetCloseTimer = null
}
this.setData({
subjectSheetVisible: true,
subjectSheetClosing: false,
})
},
_hideSubjectSheet(afterClose) {
if (!this.data.subjectSheetVisible) {
if (typeof afterClose === 'function') afterClose()
return
}
if (this.data.subjectSheetClosing) return
if (this._subjectSheetCloseTimer) clearTimeout(this._subjectSheetCloseTimer)
this.setData({ subjectSheetClosing: true }, () => {
this._subjectSheetCloseTimer = setTimeout(() => {
this._subjectSheetCloseTimer = null
if (!this._pageAlive) return
this.setData({
subjectSheetVisible: false,
subjectSheetClosing: false,
}, () => {
if (typeof afterClose === 'function') afterClose()
})
}, 180)
})
},
closeSubjectSheet() {
this._hideSubjectSheet()
},
_handleSubjectOptionTap(subjectId, source) {
const id = Number(subjectId)
if (!id || !this.data.subjectSheetVisible || this.data.subjectSheetClosing) return
const now = Date.now()
const key = `${source || 'subject'}:${id}`
const lastTap = this._lastSubjectOptionTap
const isDoubleTap = Boolean(
lastTap &&
lastTap.key === key &&
now - lastTap.time <= SUBJECT_DOUBLE_TAP_INTERVAL
)
this._lastSubjectOptionTap = isDoubleTap ? null : { key, time: now }
if (isDoubleTap) {
this.closeSubjectSheet()
}
},
_clearLaunchOverridesForManualConfig() {
// Home/Study Hub route params are setup defaults, not invisible constraints.
// Once the user changes subject/mode/count, continuing to send the original KP or
// targeted-question scope can silently pin a parent-subject practice to one child
// subject and can also make the signed batch impossible to submit.
this._launchKnowledgePoint = ''
this._launchKnowledgePointId = null
this._launchIncludeDescendants = false
this._launchQuestionIds = ''
this._launchAllowRepeat = false
this._launchPlanToken = ''
},
_selectSubject(subjectId, subjectName, expandedSubjectId, hasChildren) {
const id = Number(subjectId)
if (!id || !subjectName) return
if (Number(this.data.selectedSubjectId) !== id) {
this._clearLaunchOverridesForManualConfig()
}
const resolvedHasChildren = hasChildren != null
? Boolean(hasChildren)
: this._subjectHasChildren(id)
const patch = {
selectedSubjectId: id,
selectedSubjectName: subjectName,
selectedSubjectHasChildren: resolvedHasChildren,
}
if (expandedSubjectId != null) {
patch.expandedSubjectId = Number(expandedSubjectId)
} else if (resolvedHasChildren) {
patch.expandedSubjectId = id
}
this._queueRememberSubject(id, subjectName)
this.setData(patch)
},
chooseRecentSubject(e) {
const ds = e.currentTarget.dataset || {}
const subjectId = Number(ds.subjectId)
const subjectName = ds.subjectName
const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
if (!subjectId || !subjectName) return
const parentId = this._findParentSubjectId(subjectId)
this._selectSubject(subjectId, subjectName, parentId || subjectId, hasChildren)
this._handleSubjectOptionTap(subjectId, 'recent')
},
_findLaunchReturnStackIndex(pages, returnTo) {
if (!Array.isArray(pages) || pages.length < 2 || !returnTo) return -1
const targetPath = String(returnTo).split('?')[0].replace(/^\//, '')
if (!targetPath) return -1
let expectedSubjectId = 0
let expectedPointId = 0
const query = String(returnTo).split('?')[1] || ''
query.split('&').forEach((part) => {
const pair = String(part || '').split('=')
const key = pair[0]
const value = Number(safeDecodeURIComponent(pair.slice(1).join('='), ''))
if (key === 'subject_id' && Number.isInteger(value) && value > 0) expectedSubjectId = value
if (key === 'knowledge_point_id' && Number.isInteger(value) && value > 0) expectedPointId = value
})
const matchesIdentity = (page) => {
if (!page) return false
const route = String(page.route || '').replace(/^\//, '')
if (route !== targetPath) return false
if (targetPath === 'subpackages/knowledge/knowledge-subject/index' && expectedSubjectId) {
const pageSubjectId = Number(page.subjectId || (page.options && page.options.subject_id)) || 0
return !pageSubjectId || pageSubjectId === expectedSubjectId
}
if (targetPath === 'subpackages/knowledge/knowledge-detail/index' && expectedPointId) {
const currentPointId = Number(page.knowledgePointId || (page.options && page.options.knowledge_point_id)) || 0
return !currentPointId || currentPointId === expectedPointId
}
return true
}
let nearest = -1
for (let i = pages.length - 2; i >= 0; i -= 1) {
if (matchesIdentity(pages[i])) {
nearest = i
break
}
}
if (nearest < 0) return -1
let targetIndex = nearest
for (let i = nearest - 1; i >= 0; i -= 1) {
if (!matchesIdentity(pages[i])) break
targetIndex = i
}
return targetIndex
},
_navigateBackToLaunchTarget(returnTo, attempt = 0) {
if (!this._pageAlive) return
const pages = getCurrentPages ? getCurrentPages() : []
const targetIndex = this._findLaunchReturnStackIndex(pages, returnTo)
if (targetIndex < 0) {
this._returnNavigationLocked = false
if (returnTo) {
wx.redirectTo({
url: returnTo,
fail: () => wx.reLaunch({ url: '/pages/home/home' }),
})
return
}
if (pages.length > 1) {
wx.navigateBack({
delta: 1,
fail: () => wx.reLaunch({ url: '/pages/home/home' }),
})
return
}
wx.reLaunch({ url: '/pages/home/home' })
return
}
const delta = Math.max(1, pages.length - 1 - targetIndex)
const retryDelays = [44, 96, 180]
let retryQueued = false
const retry = () => {
if (retryQueued || !this._pageAlive) return
retryQueued = true
if (attempt >= retryDelays.length) {
this._returnNavigationLocked = false
wx.showToast({ title: '返回失败，请再试一次', icon: 'none' })
return
}
setTimeout(() => {
if (!this._pageAlive) return
this._returnNavigationLocked = true
this._navigateBackToLaunchTarget(returnTo, attempt + 1)
}, retryDelays[attempt])
}
wx.navigateBack({
delta,
success: () => {
setTimeout(() => {
if (!this._pageAlive) return
const currentPages = getCurrentPages ? getCurrentPages() : []
const current = currentPages[currentPages.length - 1] || {}
const currentRoute = String(current.route || '').replace(/^\//, '')
if (currentRoute === 'subpackages/study/practice/practice') retry()
}, 64)
},
fail: retry,
})
},
_returnToLaunchOrigin() {
if (this._returnNavigationLocked) return
this._returnNavigationLocked = true
const returnTo = this._launchReturnTo || (this._launchPreset && this._launchPreset.returnTo) || ''
const navigate = () => {
const run = () => setTimeout(() => this._navigateBackToLaunchTarget(returnTo, 0), 20)
if (typeof wx.nextTick === 'function') wx.nextTick(run)
else run()
}
if (this.data.practiceExitGuardVisible) {
this.setData({ practiceExitGuardVisible: false }, navigate)
} else {
navigate()
}
},
goBack() {
this._returnToLaunchOrigin()
},
chooseParentSubject(e) {
const ds = e.currentTarget.dataset || {}
const subjectId = Number(ds.subjectId)
const subjectName = ds.subjectName
const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
if (!subjectId || !subjectName) return
const selectedName = hasChildren ? `${subjectName}（全部）` : subjectName
this._selectSubject(subjectId, selectedName, undefined, hasChildren)
this._handleSubjectOptionTap(subjectId, 'parent')
},
toggleParentExpansion(e) {
const subjectId = Number((e.currentTarget.dataset || {}).subjectId)
if (!subjectId) return
const next = this.data.expandedSubjectId === subjectId ? null : subjectId
this.setData({ expandedSubjectId: next })
},
chooseChildSubject(e) {
const ds = e.currentTarget.dataset || {}
const subjectId = Number(ds.subjectId)
const subjectName = ds.subjectName
const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
if (!subjectId || !subjectName) return
this._selectSubject(subjectId, subjectName, this._findParentSubjectId(subjectId), hasChildren)
this._handleSubjectOptionTap(subjectId, 'child')
},
chooseMode(e) {
const mode = e.currentTarget.dataset.mode
if (String(this.data.selectedMode || '') !== String(mode || '')) {
this._clearLaunchOverridesForManualConfig()
}
this.setData({ selectedMode: mode }, () => {
this._updateComputedFields()
})
},
setCount(e) {
const count = Number(e.currentTarget.dataset.count)
if (Number(this.data.count) !== count) {
this._clearLaunchOverridesForManualConfig()
}
this.setData({ count }, () => {
this._updateComputedFields()
})
},
async startPractice() {
if (this.data.loading || this.data.submitting) return
if (this._readPendingSubmission()) {
await this._offerPendingSubmissionRecovery()
if (this._readPendingSubmission()) return
}
if (!this.data.selectedSubjectId) {
this.openSubjectSheet()
return
}
if (this.data.selectedMode === 'sequential' && this.data.selectedSubjectHasChildren) {
wx.showToast({ title: '顺序练习仅支持具体科目', icon: 'none' })
return
}
const traceId = api.createTraceId()
this._submittedResultPayload = null
this._resetSession()
this._practiceSession.traceId = traceId
this.setData({
traceId,
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
})
this._setPracticeUnloadGuard(true)
this._flushPendingRecentSubject()
await this._loadQuestions()
},
_startTimer() {
this._clearTimer()
this._timer = setInterval(() => {
if (!this._pageAlive || !this._practiceSession.activeStartedMonoMs) return
const now = _monotonicNow()
const backgroundMs = (this._practiceSession.backgroundMs || 0) + (
this._practiceSession._backgroundStartedMonoMs !== null
? Math.max(0, now - this._practiceSession._backgroundStartedMonoMs)
: 0
)
const sec = Math.max(0, Math.floor((now - this._practiceSession.activeStartedMonoMs - backgroundMs) / 1000))
this._practiceSession.elapsedSec = sec
this.setData({ elapsedText: this._fmt(sec) })
}, 1000)
},
_fmt(sec) {
const s = Math.max(0, sec || 0)
const m = Math.floor(s / 60)
const ss = s % 60
return `${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
},
_clearTimer() {
if (this._timer) {
clearInterval(this._timer)
this._timer = null
}
},
_setPracticeUnloadGuard(enabled, message) {
if (this._practiceSession) {
this._practiceSession.exitGuardActive = !!enabled
this._practiceSession.exitGuardMessage = message || ''
}
try {
if (wx.disableAlertBeforeUnload) wx.disableAlertBeforeUnload()
} catch (_) {}
if (!enabled) {
this._systemBackRearming = false
if (this._systemBackRearmTimer) {
clearTimeout(this._systemBackRearmTimer)
this._systemBackRearmTimer = null
}
}
if (!this._pageAlive) return
const visible = !!enabled
if (this.data.practiceExitGuardVisible !== visible) {
this.setData({ practiceExitGuardVisible: visible })
}
},
_shouldInterceptSystemBack() {
const session = this._practiceSession
return !!(
this._pageAlive &&
session &&
session.exitGuardActive &&
this.data.started &&
!this.data.submitted
)
},
_rearmPracticeExitGuard() {
if (!this._shouldInterceptSystemBack() || this._systemBackRearming) return
this._systemBackRearming = true
const rearm = () => {
if (!this._shouldInterceptSystemBack()) {
this._systemBackRearming = false
return
}
this.setData({ practiceExitGuardVisible: true }, () => {
this._systemBackRearming = false
})
}
this.setData({ practiceExitGuardVisible: false }, () => {
if (!this._shouldInterceptSystemBack()) {
this._systemBackRearming = false
return
}
if (typeof wx.nextTick === 'function') {
wx.nextTick(rearm)
return
}
this._systemBackRearmTimer = setTimeout(() => {
this._systemBackRearmTimer = null
rearm()
}, 0)
})
},
onPracticeExitGuardLeave() {
if (!this._shouldInterceptSystemBack()) return
this._rearmPracticeExitGuard()
if (this._systemBackPromptQueued || this._exitConfirmInFlight) return
this._systemBackPromptQueued = true
Promise.resolve().then(async () => {
this._systemBackPromptQueued = false
if (!this._shouldInterceptSystemBack()) return
await this.requestExitPractice({ source: 'system-back' })
}).catch((err) => {
this._systemBackPromptQueued = false
console.warn('系统返回退出确认处理失败', err)
})
},
async _loadQuestions() {
const loadSeq = ++this._questionsRequestSeq
if (!this.data.loading) this.setData({ loading: true })
try {
const subjectId = this.data.selectedSubjectId
if (!subjectId) {
this._clearTimer()
this._setPracticeUnloadGuard(false)
this.setData(buildResetView())
wx.showToast({ title: '请选择科目', icon: 'none' })
return
}
const mode = this.data.selectedMode || 'random'
const params = buildQuestionRequestParams({
subjectId,
selectedMode: this.data.selectedMode,
selectedSubjectHasChildren: this.data.selectedSubjectHasChildren,
count: this.data.count,
traceId: this._practiceSession.traceId,
launchQuestionIds: this._launchQuestionIds,
launchAllowRepeat: this._launchAllowRepeat,
launchPlanToken: this._launchPlanToken,
launchKnowledgePointId: this._launchKnowledgePointId,
launchIncludeDescendants: this._launchIncludeDescendants,
launchKnowledgePoint: this._launchKnowledgePoint,
})
const res = await api.get('/practice/questions', params)
if (!this._pageAlive || loadSeq !== this._questionsRequestSeq) return
if (this._launchIncludeDescendants) {
const scope = res && res.knowledge_scope
if (!validateKnowledgeScope(scope, this._launchKnowledgePointId)) {
console.error('[PRACTICE_KNOWLEDGE_SCOPE_MISMATCH]', {
requestedRootId: this._launchKnowledgePointId,
requestedIncludeDescendants: true,
receivedScope: scope || null,
traceId: res && (res.trace_id || this._practiceSession.traceId),
})
this._clearTimer()
this._setPracticeUnloadGuard(false)
this.setData(buildResetView('章节专项范围校验失败，请更新后端服务后重试。'))
wx.showToast({ title: '章节专项暂不可用', icon: 'none' })
return
}
}
this._practiceSession.knowledgeScope = res && res.knowledge_scope
? Object.assign({}, res.knowledge_scope)
: null
const rawQuestions = Array.isArray(res.questions) ? res.questions : []
const allowedScopeIds = new Set(
this._getPracticeSubjectScopeIds(subjectId, params.include_children).map(Number)
)
const batchError = findQuestionBatchError(rawQuestions, {
answerableTypes: PRACTICE_ANSWERABLE_TYPES,
allowedScopeIds,
})
if (batchError && batchError.kind === 'invalid_ids') {
console.error('[PRACTICE_INVALID_BATCH_QUESTION_IDS]', {
selectedSubjectId: Number(subjectId),
invalidQuestionIds: batchError.invalidQuestionIds,
duplicateQuestionIds: batchError.duplicateQuestionIds,
traceId: res.trace_id || this._practiceSession.traceId,
})
this._clearTimer()
this._setPracticeUnloadGuard(false)
this.setData(buildResetView('检测到练习批次题目异常，请重试。若持续出现，请更新后端服务。'))
wx.showToast({ title: '练习批次异常，请重试', icon: 'none' })
return
}
if (batchError && batchError.kind === 'unsupported_type') {
console.error('[PRACTICE_UNSUPPORTED_QUESTION_TYPE]', {
selectedSubjectId: Number(subjectId),
rejected: batchError.rejected,
traceId: res.trace_id || this._practiceSession.traceId,
})
this._clearTimer()
this._setPracticeUnloadGuard(false)
this.setData(buildResetView('检测到当前版本暂不支持作答的题型，请重试或更新后端服务。'))
wx.showToast({ title: '题型暂不支持，请重试', icon: 'none' })
return
}
if (batchError && batchError.kind === 'subject_scope') {
console.error('[PRACTICE_SUBJECT_SCOPE_MISMATCH]', {
selectedSubjectId: Number(subjectId),
includeChildren: Boolean(params.include_children),
allowedScopeIds: batchError.allowedScopeIds,
rejected: batchError.rejected,
traceId: res.trace_id || this._practiceSession.traceId,
})
this._clearTimer()
this._setPracticeUnloadGuard(false)
this.setData(buildResetView('检测到题目科目异常，请重试。若持续出现，请更新后端服务。'))
wx.showToast({ title: '题目科目异常，请重试', icon: 'none' })
return
}
const questions = adapter.applyAnsweredFlags(rawQuestions, {}, 'id')
const sequentialProgress = mode === 'sequential'
? (res.sequential_progress || null)
: null
this.setData({ sequentialProgress })
if (
mode === 'sequential' &&
questions.length === 0 &&
sequentialProgress &&
sequentialProgress.cycle_completed
) {
if (!this._sequentialRestartController) {
this._sequentialRestartController = createSequentialRestartController({
clearTimer: () => this._clearTimer(),
setUnloadGuard: value => this._setPracticeUnloadGuard(value),
setData: data => this.setData(data),
buildResetView: () => buildResetView(),
showRestartConfirm: options => this._showSubmitConfirm(options),
isPageAlive: () => this._pageAlive,
getRequestSeq: () => this._questionsRequestSeq,
getTraceId: () => this._practiceSession.traceId,
resetSequentialProgress: payload => api.post('/practice/sequential/reset', payload),
logError: (...args) => console.error(...args),
showToast: options => wx.showToast(options),
getSession: () => this._practiceSession,
resetSequentialTiming: session => resetSequentialTiming(session),
buildSequentialRestartView: () => buildSequentialRestartView(),
reloadQuestions: () => this._loadQuestions(),
})
}
await this._sequentialRestartController.restart(
sequentialProgress,
subjectId,
this.data.selectedSubjectName,
loadSeq
)
return
}
debugLog(this._practiceSession.traceId, 'STATE_AFTER_API', {
total: questions.length,
responseTraceId: res.trace_id,
})
saveDebugSnapshot(this._practiceSession.traceId, 'state_after_api', {
total: questions.length,
questionIds: questions.map(q => q.id),
})
applyBatchCredentials(this._practiceSession, res, mode)
if (hasMissingBatchCredentials(this._practiceSession, questions.length)) {
throw new Error('服务器未返回可提交的练习批次凭据')
}
if (questions.length > 0) this._warmQuestionImages(questions, 0)
var firstQuestion = null
var firstIndex = 0
if (questions.length > 0) {
try {
var viewModelResult = this._buildQuestionViewModel(questions[0])
if (!viewModelResult) throw new Error('_buildQuestionViewModel returned null')
firstQuestion = viewModelResult.question
} catch (renderErr) {
console.error('首题渲染失败', renderErr)
this._clearTimer()
this._setPracticeUnloadGuard(false)
this.setData(buildResetView('题目解析失败，可重试或返回选题'))
return
}
}
this.setData(buildLoadedView(questions, viewModelResult))
if (questions.length > 0 && firstQuestion) {
if (!this._practiceSession.activeStartedMonoMs) {
this._practiceSession.activeStartedMonoMs = _monotonicNow()
this._practiceSession.startedAtMs = api.now()
this._practiceSession.backgroundMs = 0
this._practiceSession._backgroundStartedMonoMs = null
this._practiceSession.elapsedSec = 0
}
this._practiceSession.optionKeys = viewModelResult.optionKeys
this._practiceSession.currentQuestionStartedMonoMs = _monotonicNow()
this._setPracticeUnloadGuard(true)
this._startTimer()
this._updateComputedFields()
this._checkRenderInvariant(firstQuestion._renderModel)
} else if (questions.length === 0) {
this._clearTimer()
this._setPracticeUnloadGuard(false)
const name = this.data.selectedSubjectName || String(subjectId)
this.setData(buildResetView())
await this._showSubmitConfirm({
scenario: 'info',
eyebrow: 'NO QUESTIONS',
title: '该科目暂无可练题目',
message: `「${name}」目前没有可在本页作答的已发布题目。\n可检查导入审核状态、题型与科目分类，或选择其他科目。`,
confirmText: '返回选择科目',
hideCancel: true,
})
}
} catch (e) {
if (!this._pageAlive || loadSeq !== this._questionsRequestSeq) return
console.error('加载题目失败', e)
this._clearTimer()
this._setPracticeUnloadGuard(false)
this.setData(buildResetView('加载题目失败，请重试或返回重新选择科目'))
wx.showToast({ title: '加载题目失败', icon: 'none' })
}
},
_getQuestionRenderView(q, forceRebuild) {
if (!q) return null
const session = this._practiceSession
if (!session.questionRenderCache) session.questionRenderCache = Object.create(null)
const questionId = String(q.id == null ? '' : q.id)
const cacheKey = [
questionId || 'anonymous',
String(q.question_version_id || q.question_version || 'version-unknown'),
session.safeModeActive ? 'safe' : 'normal',
config.enableMathImage ? 'math-image' : 'math-native',
].join(':')
if (!forceRebuild && session.questionRenderCache[cacheKey]) {
return session.questionRenderCache[cacheKey]
}
const isBlankChoice = adapter.isMultiBlankChoice(q)
const rawBlankOptionGroups = isBlankChoice
? adapter.getBlankOptionGroups(q)
: []
const isTrueFalse = q.question_type === 'true_false' || q.question_type === 'judgement'
const flatOptions = typeof adapter.getQuestionOptions === 'function'
? adapter.getQuestionOptions(q)
: q.options
const hasFlatOptions = flatOptions && Object.keys(flatOptions).length > 0
const opts = (!isBlankChoice || rawBlankOptionGroups.length === 0) && hasFlatOptions
? flatOptions
: (!isBlankChoice && isTrueFalse ? { A: '正确', B: '错误' } : null)
const optionKeys = opts ? Object.keys(opts) : []
const renderCfg = { enableMathImage: config.enableMathImage || false, DEV: config.DEV }
if (session.safeModeActive) renderCfg.SAFE_MODE = true
const renderModel = buildRenderModel(q, opts, renderCfg)
const result = {
question: Object.assign({}, q, {
_renderModel: renderModel,
_opts: opts,
_optionKeys: optionKeys,
_hasBlankOptionGroups: rawBlankOptionGroups.length > 0,
}),
optionKeys,
rawBlankOptionGroups,
}
session.questionRenderCache[cacheKey] = result
return result
},
_buildQuestionAnswerState(renderView, answer) {
if (!renderView || !renderView.question) return null
const q = renderView.question
const normalizedAnswer = answer || ''
const blankOptionGroups = renderView.rawBlankOptionGroups.length > 0
? adapter.enrichBlankOptionGroups(renderView.rawBlankOptionGroups, normalizedAnswer)
: []
const isMulti = q.question_type === 'multiple_choice'
const selectedFlags = {}
for (let optionIndex = 0; optionIndex < renderView.optionKeys.length; optionIndex++) {
const key = renderView.optionKeys[optionIndex]
selectedFlags[key] = isMulti
? normalizedAnswer.split(',').indexOf(key) >= 0
: normalizedAnswer === key
}
return {
questionId: String(q.id == null ? '' : q.id),
optionList: blankOptionGroups.length > 0
? []
: adapter.buildOptionListFromFlags(q._opts, renderView.optionKeys, selectedFlags),
blankOptionGroups,
hasBlankOptionGroups: blankOptionGroups.length > 0,
}
},
_buildQuestionViewModel(q, forceRebuild) {
const renderView = this._getQuestionRenderView(q, forceRebuild)
if (!renderView) return null
const answer = this._practiceSession.answerMap[String(q.id)] || ''
return {
question: renderView.question,
answerState: this._buildQuestionAnswerState(renderView, answer),
optionKeys: renderView.optionKeys,
renderView,
}
},
_warmQuestionImages(questions, index) {
if (!Array.isArray(questions) || !questions.length) return
const current = questions[index]
if (!current || typeof adapter.getQuestionPrefetchUrls !== 'function') return
const currentId = String(current.id == null ? '' : current.id)
const currentUrls = adapter.getQuestionPrefetchUrls(current)
if (currentUrls.length) {
questionImageCache.preloadMany(currentUrls, 3).then(() => {
if (!this._pageAlive || this.data.currentIndex !== index) return
const visible = this.data.questions[index]
if (!visible || String(visible.id == null ? '' : visible.id) !== currentId) return
try {
const refreshed = this._buildQuestionViewModel(visible, true)
if (!refreshed) return
this._practiceSession.optionKeys = refreshed.optionKeys
this.setData({
currentQuestion: refreshed.question,
currentAnswerState: refreshed.answerState,
})
} catch (err) {
if (config.DEV) console.warn('[practice] image cache refresh failed', err)
}
})
}
const neighborIndexes = [index + 1, index + 2, index - 1]
const neighborUrls = []
for (let i = 0; i < neighborIndexes.length; i++) {
const q = questions[neighborIndexes[i]]
if (!q) continue
const urls = adapter.getQuestionPrefetchUrls(q)
for (let j = 0; j < urls.length; j++) neighborUrls.push(urls[j])
}
if (neighborUrls.length) questionImageCache.preloadMany(neighborUrls, 2)
},
_settleQuestionTime(pause) {
const { currentIndex, questions } = this.data
const { currentQuestionStartedMonoMs, questionTimeMap } = this._practiceSession
if (!currentQuestionStartedMonoMs || !questions.length) return
const q = questions[currentIndex]
if (!q) return
const elapsed = Math.max(0, Math.floor((_monotonicNow() - currentQuestionStartedMonoMs) / 1000))
const key = String(q.id)
const map = { ...questionTimeMap }
map[key] = (map[key] || 0) + elapsed
this._practiceSession.questionTimeMap = map
this._practiceSession.currentQuestionStartedMonoMs = pause ? 0 : _monotonicNow()
},
_showQuestion(index) {
this._settleQuestionTime()
const q = this.data.questions[index]
if (!q) return
this._warmQuestionImages(this.data.questions, index)
var viewModelResult
try {
viewModelResult = this._buildQuestionViewModel(q)
} catch (renderErr) {
console.error('切题渲染失败 index=' + index + ' id=' + q.id, renderErr)
wx.showToast({ title: '题目渲染失败，已保留上一题', icon: 'none' })
return
}
if (!viewModelResult) {
console.error('切题渲染失败 index=' + index + ' id=' + q.id)
wx.showToast({ title: '题目渲染失败，已保留上一题', icon: 'none' })
return
}
const currentQuestion = viewModelResult.question
const optionKeys = viewModelResult.optionKeys
if (shouldDebugQuestion(q.id)) {
debugLog(this._practiceSession.traceId || q.trace_id, 'BEFORE_RENDER', {
questionId: q.id,
index,
optionKeys,
blankGroupCount: (viewModelResult.answerState.blankOptionGroups || []).length,
renderMode: (currentQuestion._renderModel || {}).mode,
sourceLen: ((q.content && (q.content.text || q.content.stem)) || '').length,
})
}
this._practiceSession.optionKeys = optionKeys
this._practiceSession.currentQuestionStartedMonoMs = _monotonicNow()
this.setData({
currentIndex: index,
currentQuestion: currentQuestion,
currentAnswerState: viewModelResult.answerState,
}, () => {
this._updateComputedFields()
})
this._checkRenderInvariant(currentQuestion._renderModel)
},
goQuestion(e) {
const idx = e.detail.index
if (idx >= 0 && idx < this.data.totalQuestions) {
this._showQuestion(idx)
}
},
goNext(e) {
this._showQuestion(e.detail.index)
},
goPrev(e) {
this._showQuestion(e.detail.index)
},
async requestExitPractice() {
if (this._exitConfirmInFlight) return
if (this.data.submitting) {
this._exitConfirmInFlight = true
try {
await this._showSubmitConfirm({
scenario: 'info',
title: '正在交卷',
message: '提交完成前请保持当前页面。',
confirmText: '知道了',
hideCancel: true,
hideEyebrow: true,
})
} finally {
this._exitConfirmInFlight = false
}
return
}
const submission = this._practiceSession && this._practiceSession.submissionSnapshot
if (this.data.submitted && this._pendingResultUrl && submission) {
this._openSubmittedResult(this._pendingResultUrl, submission)
return
}
const hasPendingSubmit = !!submission
const retryBlocked = !!(submission && submission.retryBlocked)
this._exitConfirmInFlight = true
let confirmed = false
try {
const showExitConfirm = hasPendingSubmit
? this._showSubmitConfirm.bind(this)
: this._showSubmitConfirmPaused.bind(this)
confirmed = await showExitConfirm({
scenario: 'info',
layout: 'minimal',
title: '退出练习？',
message: retryBlocked
? '本次提交未通过，退出后可重新开始。'
: (hasPendingSubmit
? '交卷仍在确认中，退出后可下次继续确认。'
: '本组练习尚未提交，确定退出吗？'),
confirmText: '退出',
cancelText: hasPendingSubmit && !retryBlocked ? '继续确认' : '继续作答',
hideEyebrow: true,
})
} finally {
this._exitConfirmInFlight = false
}
if (!confirmed) return
if (!this._pageAlive) return
if (retryBlocked && submission) this._clearPendingSubmission(submission.requestId)
this._setPracticeUnloadGuard(false)
this._questionsRequestSeq++
this._clearTimer()
if (this._feedbackTimer) {
clearTimeout(this._feedbackTimer)
this._feedbackTimer = null
}
this._resetSession()
this._pendingResultUrl = ''
this._submittedResultPayload = null
// The runner lives inside this page. Restore its setup surface rather than
// popping the page back to home (or a knowledge-map launch origin).
this._launchPreset = null
this._fastLaunchEligible = false
this._launchKnowledgePoint = ''
this._launchKnowledgePointId = null
this._launchIncludeDescendants = false
this._launchQuestionIds = ''
this._launchAllowRepeat = false
this._launchSource = ''
this._launchPlanToken = ''
this._launchReturnTo = ''
this.setData({
started: false,
loading: false,
launchingPreset: false,
submitting: false,
submitted: false,
practiceExitGuardVisible: false,
questions: [],
currentQuestion: null,
currentAnswerState: null,
currentIndex: 0,
totalQuestions: 0,
answeredCount: 0,
progressPercent: 0,
elapsedText: '00:00',
errorText: '',
feedbackVisible: false,
})
if (typeof wx.pageScrollTo === 'function') wx.pageScrollTo({ scrollTop: 0, duration: 0 })
},
_isSubmissionLocked() {
if (!this._practiceSession || !this._practiceSession.submissionSnapshot) return false
const submission = this._practiceSession.submissionSnapshot
wx.showToast({
title: submission.serverAccepted
? '本次已交卷，请查看结果'
: (submission.retryBlocked ? '提交已被拒绝，请退出后重试' : '交卷内容已锁定，请确认提交'),
icon: 'none',
})
return true
},
selectOption(e) {
if (this.data.submitted || this._isSubmissionLocked()) return
const opt = e.detail.option
const q = this.data.currentQuestion
if (!q) return
const isMulti = q.question_type === 'multiple_choice'
const key = String(q.id)
const prev = this._practiceSession.answerMap[key] || ''
let newAnswer
if (isMulti) {
const sel = prev ? prev.split(',') : []
const idx = sel.indexOf(opt)
if (idx >= 0) sel.splice(idx, 1)
else sel.push(opt)
sel.sort()
newAnswer = sel.join(',')
} else {
newAnswer = prev === opt ? '' : opt
}
const answerMap = { ...this._practiceSession.answerMap }
if (newAnswer) {
answerMap[key] = newAnswer
} else {
delete answerMap[key]
}
const answeredFlags = adapter.buildAnsweredFlags(this.data.questions, answerMap, 'id')
const answeredCount = adapter.countAnswered(answeredFlags)
const currentIdx = this.data.currentIndex
const answered = !!answeredFlags[key]
if (shouldDebugQuestion(q.id)) {
debugLog(this._practiceSession.traceId || q.trace_id, 'STATE_CHANGE', {
questionId: q.id,
previousAnswer: prev,
nextAnswer: newAnswer,
answeredCount,
})
saveDebugSnapshot(this._practiceSession.traceId || q.trace_id, 'state_change', {
questionId: q.id,
previousAnswer: prev,
nextAnswer: newAnswer,
answeredCount,
})
}
const renderView = this._getQuestionRenderView(q)
const answerState = this._buildQuestionAnswerState(renderView, newAnswer)
this._practiceSession.answerMap = answerMap
this._practiceSession.answeredFlags = answeredFlags
this.setData({
[`questions[${currentIdx}]._answered`]: answered,
answeredCount,
currentAnswerState: answerState,
}, () => {
this._updateComputedFields()
})
},
selectBlankOption(e) {
if (this.data.submitted || this._isSubmissionLocked()) return
const blankId = String(e.detail.blankId || '').trim()
const opt = String(e.detail.option || '').trim().toUpperCase()
const q = this.data.currentQuestion
if (!q || !adapter.isMultiBlankChoice(q) || !blankId || !opt) return
const key = String(q.id)
const prev = this._practiceSession.answerMap[key] || ''
const blankAnswers = adapter.normalizeBlankAnswer(prev)
if (typeof adapter.isMultiBlankMultipleChoice === 'function' && adapter.isMultiBlankMultipleChoice(q)) {
// 多空（多选）：在空内 key 集合中切换
const current = String(blankAnswers[blankId] || '').split(',').filter(Boolean)
const next = current.indexOf(opt) >= 0
? current.filter(function (k) { return k !== opt })
: current.concat([opt]).sort()
if (next.length > 0) blankAnswers[blankId] = next.join(',')
else delete blankAnswers[blankId]
} else if (blankAnswers[blankId] === opt) {
delete blankAnswers[blankId]
} else {
blankAnswers[blankId] = opt
}
const renderView = this._getQuestionRenderView(q)
const rawGroups = renderView ? renderView.rawBlankOptionGroups : adapter.getBlankOptionGroups(q)
const newAnswer = adapter.serializeBlankAnswer(rawGroups, blankAnswers)
const answerMap = { ...this._practiceSession.answerMap }
if (newAnswer) {
answerMap[key] = newAnswer
} else {
delete answerMap[key]
}
const answeredFlags = adapter.buildAnsweredFlags(this.data.questions, answerMap, 'id')
const answeredCount = adapter.countAnswered(answeredFlags)
const answerState = this._buildQuestionAnswerState(renderView, newAnswer)
if (shouldDebugQuestion(q.id)) {
debugLog(this._practiceSession.traceId || q.trace_id, 'STATE_CHANGE', {
questionId: q.id,
previousAnswer: prev,
nextAnswer: newAnswer,
answeredCount,
})
saveDebugSnapshot(this._practiceSession.traceId || q.trace_id, 'state_change', {
questionId: q.id,
previousAnswer: prev,
nextAnswer: newAnswer,
answeredCount,
})
}
this._practiceSession.answerMap = answerMap
this._practiceSession.answeredFlags = answeredFlags
const currentIdx = this.data.currentIndex
const answered = !!answeredFlags[key]
const totalQuestions = this.data.totalQuestions || 0
this.setData({
[`questions[${currentIdx}]._answered`]: answered,
answeredCount,
progressPercent: totalQuestions > 0 ? Math.round(answeredCount / totalQuestions * 100) : 0,
currentAnswerState: answerState,
})
},
_modeLabel: function(m) {
var map = { random: '随机挑战', sequential: '顺序推进', smart: '智能推荐' }
return map[m] || m || ''
},
_updateComputedFields: function(extras) {
var data = {}
data.selectedModeLabel = this._modeLabel(this.data.selectedMode)
var count = Number(this.data.count || 5)
var minutesMap = { 5: 10, 10: 20, 20: 40 }
data.countDisplay = count < 10 ? ('0' + count) : String(count)
data.estimatedMinutes = minutesMap[count] || Math.max(5, count * 2)
var total = this.data.totalQuestions || 0
var answered = this.data.answeredCount || 0
data.progressPercent = total > 0 ? Math.round(answered / total * 100) : 0
if (extras) Object.assign(data, extras)
this.setData(data)
},
noop() {},
_showAnswerFeedback(q, answer) {
const isCorrect = adapter.isAnswerCorrect(q, answer)
const hasAnswer = !!answer
const nextCombo = isCorrect === true ? this._practiceSession.comboCount + 1 : (isCorrect === false ? 0 : this._practiceSession.comboCount)
if (!hasAnswer) {
this._practiceSession.comboCount = nextCombo
this.setData({ feedbackVisible: false })
return
}
if (isCorrect !== true && isCorrect !== false) {
this._practiceSession.comboCount = nextCombo
return
}
const feedbackType = isCorrect === true ? 'correct' : 'wrong'
let feedbackTitle, feedbackDetail, feedbackComboText, feedbackComboLevel, feedbackStarCount
if (isCorrect === true) {
if (nextCombo >= 10) {
feedbackTitle = '学霸连击'
feedbackDetail = '状态火热，无人能挡'
feedbackComboText = `🔥 ${nextCombo} 连对`
feedbackComboLevel = 'fire'
feedbackStarCount = 6
} else if (nextCombo >= 5) {
feedbackTitle = '五连斩'
feedbackDetail = '进入心流状态，继续推进'
feedbackComboText = `⚡ ${nextCombo} 连对`
feedbackComboLevel = 'hot'
feedbackStarCount = 5
} else if (nextCombo >= 3) {
feedbackTitle = '三连对'
feedbackDetail = '手感正热，保持这个状态'
feedbackComboText = `${nextCombo} 连对`
feedbackComboLevel = 'warm'
feedbackStarCount = 3
} else {
feedbackTitle = '回答正确'
feedbackDetail = '这题很稳，保持当前节奏'
feedbackComboText = ''
feedbackComboLevel = ''
feedbackStarCount = 0
}
} else {
feedbackTitle = '继续加油'
feedbackDetail = '先记录选择，交卷后集中复盘'
feedbackComboText = ''
feedbackComboLevel = ''
feedbackStarCount = 0
}
if (this._feedbackTimer) clearTimeout(this._feedbackTimer)
this._practiceSession.comboCount = nextCombo
this.setData({
feedbackVisible: true,
feedbackType,
feedbackTitle,
feedbackDetail,
feedbackComboText,
feedbackComboLevel,
feedbackStarCount,
})
this._feedbackTimer = setTimeout(() => {
this.setData({ feedbackVisible: false })
this._feedbackTimer = null
}, feedbackComboText ? 2000 : 1200)
},
_checkRenderInvariant(renderModel) {
if (!renderModel) return
let activePaths = 0
if (renderModel.mode === 'SEGMENTS') activePaths++
if (renderModel.mode === 'RICH_TEXT') activePaths++
if (renderModel.mode === 'CODE') activePaths++
if (renderModel.mode === 'LATEX') activePaths++
if (renderModel.mode === 'MIXED') {
activePaths++
if (!renderModel.blocks || renderModel.blocks.length === 0) {
console.error('[MIXED_RENDER_VIOLATION] MIXED mode but blocks is empty')
}
}
if (activePaths !== 1) {
console.error('[RENDER_INVARIANT] _renderModel.mode="' + renderModel.mode + '" yields ' + activePaths + ' active paths (expected 1)')
}
if (renderModel.mode === 'CODE' && renderModel.rawText) {
var hasHtmlLeak = /&(?:nbsp|amp|lt|gt|#\d+);/.test(renderModel.rawText)
if (hasHtmlLeak) {
console.error(
'[CODE_HTML_LEAK] CODE rawText contains HTML entities\n' +
'  tail: ' + renderModel.rawText.slice(-60)
)
}
var hasRenderViolation = renderModel.html.length > 0 || renderModel.richTextNodes.length > 0
if (hasRenderViolation) {
console.error(
'[CODE_RENDER_VIOLATION] CODE mode leaked into html/richTextNodes ' +
'(html=' + renderModel.html.length + ', nodes=' + renderModel.richTextNodes.length + ')'
)
}
if ((hasHtmlLeak || hasRenderViolation) && !this._practiceSession.safeModeActive) {
this._enterSafeMode()
}
}
if (renderModel.mode === 'MIXED' && renderModel.blocks) {
for (var mi = 0; mi < renderModel.blocks.length; mi++) {
var mBlock = renderModel.blocks[mi]
if (mBlock.type === 'CODE' && mBlock.rawText) {
if (/&(?:nbsp|amp|lt|gt|#\d+);/.test(mBlock.rawText)) {
console.error('[CODE_HTML_LEAK] MIXED CODE block #' + mi + ' contains HTML entities')
}
}
}
}
},
_enterSafeMode() {
console.warn('[SELF_HEAL] CODE render violation detected — entering SAFE_MODE')
this._practiceSession.safeModeActive = true
this._reRenderCurrentQuestion()
},
_reRenderCurrentQuestion() {
const q = this.data.questions[this.data.currentIndex]
if (!q) return
this._practiceSession.questionRenderCache = Object.create(null)
const viewModelResult = this._buildQuestionViewModel(q, true)
if (!viewModelResult) return
this.setData({
currentQuestion: viewModelResult.question,
currentAnswerState: viewModelResult.answerState,
})
console.warn('[SELF_HEAL] Re-rendered q' + q.id + ' in SAFE_MODE, mode=' + viewModelResult.question._renderModel.mode)
},
_showSubmitConfirm(opts) {
var comp = this.selectComponent('#submitConfirm')
if (!comp || typeof comp.show !== 'function') {
wx.showToast({ title: opts.title || '请稍后重试', icon: 'none' })
return Promise.resolve(false)
}
return comp.show(opts)
},
async _showSubmitConfirmPaused(opts) {
const session = this._practiceSession
const pauseStartedMonoMs = _monotonicNow()
if (session) session._timingPauseActive = true
this._settleQuestionTime(true)
this._clearTimer()
let confirmed = false
try {
confirmed = await this._showSubmitConfirm(opts)
} finally {
const pausedMs = Math.max(0, _monotonicNow() - pauseStartedMonoMs)
if (session) {
session.backgroundMs = (session.backgroundMs || 0) + pausedMs
session._timingPauseActive = false
}
}
if (
!confirmed && this._pageAlive && this._practiceSession === session &&
this.data.started && !this.data.submitted && !this.data.submitting &&
session && !session.submissionSnapshot
) {
session.currentQuestionStartedMonoMs = _monotonicNow()
this._startTimer()
}
return !!confirmed
},
async doSubmit(skipConfirm) {
if (this.data.submitting) return
let submission = this._practiceSession.submissionSnapshot
if (this.data.submitted && this._pendingResultUrl && submission) {
this._openSubmittedResult(this._pendingResultUrl, submission)
return
}
if (submission && submission.retryBlocked) {
await this._showSubmitConfirm({
scenario: 'danger',
title: '本次提交无法继续重试',
message: '请退出本组练习后重新开始。',
showCancel: false,
confirmText: '知道了',
hideEyebrow: true,
})
return
}
const questions = this.data.questions || []
if (!submission) {
const selectedSubjectId = this.data.selectedSubjectId
const selectedSubjectName = this.data.selectedSubjectName
const answerMap = this._practiceSession.answerMap
const activeStartedMonoMs = this._practiceSession.activeStartedMonoMs
const comboCount = this._practiceSession.comboCount
const total = questions.length || 0
const answeredFlags = adapter.buildAnsweredFlags(questions, answerMap, 'id')
const answeredCount = adapter.countAnswered(answeredFlags)
const completedQuestions = questions.filter(function(q) {
return answeredFlags[String(q.id)]
})
const partialQuestionIds = questions
.filter(function(q) {
const key = String(q.id)
return !answeredFlags[key] && adapter.isMultiBlankChoice(q) && !!answerMap[key]
})
.map(function(q) { return q.id })
const skippedQuestionIds = questions
.filter(function(q) { return !answeredFlags[String(q.id)] })
.map(function(q) { return q.id })
const unanswered = total - answeredCount
if (answeredCount === 0 && partialQuestionIds.length === 0) {
wx.showToast({ title: '请至少完成或填写 1 题再提交', icon: 'none' })
return
}
var confirmed = false
if (unanswered > 0) {
confirmed = await this._showSubmitConfirmPaused({
scenario: 'unanswered',
title: `还有 ${unanswered} 题未完成`,
message: '现在交卷会将未完成题记为跳过。',
confirmText: '仍然交卷',
cancelText: '继续答题',
})
} else if (skipConfirm !== true) {
confirmed = await this._showSubmitConfirmPaused({
scenario: 'all-done',
title: '确认交卷？',
message: `已完成 ${answeredCount} / ${total} 题`,
confirmText: '确认交卷',
cancelText: '继续检查',
})
} else {
confirmed = true
}
if (!confirmed) return
this._clearTimer()
this._settleQuestionTime(true)
const finishedMonoMs = _monotonicNow()
const finishedAtMs = api.now()
const duration = Math.max(0, Math.floor(
(finishedMonoMs - activeStartedMonoMs - (this._practiceSession.backgroundMs || 0)) / 1000,
))
const requestId = this._practiceSession.requestId || ('req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8))
this._practiceSession.requestId = requestId
const recommendationRequestId = this._practiceSession.recommendationRequestId || null
const questionTimeMap = this._practiceSession.questionTimeMap
const answers = completedQuestions.map(q => ({
question_id: q.id,
user_answer: answerMap[String(q.id)] || '',
used_time: questionTimeMap[String(q.id)] || 0,
request_id: recommendationRequestId,
}))
const session = {
request_id: requestId,
subject_id: selectedSubjectId,
mode: this._practiceSession.batchMode || this.data.selectedMode || 'random',
started_at: new Date(this._practiceSession.startedAtMs || (finishedAtMs - duration * 1000)).toISOString(),
finished_at: new Date(finishedAtMs).toISOString(),
duration_sec: duration,
question_count: total,
answered_count: answeredCount,
status: 'completed',
}
const recoveryQuestions = questions.map(function(q) {
const stem = (q && q.content && (q.content.text || q.content.stem)) || (q && q.stem) || ''
return {
id: q && q.id,
question_version_id: q && q.question_version_id,
question_version: q && q.question_version,
subject_id: q && q.subject_id,
subject_code: (q && q.subject_code) || '',
subject_name: (q && q.subject_name) || '',
question_type: (q && q.question_type) || '',
content: (q && q.content) || {},
options: (q && q.options) || null,
image_url: (q && q.image_url) || null,
knowledge_points: (q && q.knowledge_points) || [],
difficulty: (q && q.difficulty) || 3,
stem: String(stem || ''),
}
}).filter(function(q) { return !!q.id })
if (!this._practiceSession.batchToken) {
await this._showSubmitConfirm({
scenario: 'info',
title: '练习批次已失效',
message: '请返回后重新获取本组题目。',
showCancel: false,
confirmText: '知道了',
hideEyebrow: true,
})
return
}
submission = {
requestId,
traceId: this._practiceSession.traceId || '',
answers,
skippedQuestionIds: skippedQuestionIds.slice(),
partialQuestionIds: partialQuestionIds.slice(),
session,
duration,
total,
unanswered,
selectedSubjectId,
selectedSubjectName,
comboCount,
answerMap: Object.assign({}, answerMap),
answeredFlags: Object.assign({}, answeredFlags),
recoveryQuestions,
batchToken: this._practiceSession.batchToken || '',
knowledgeScope: this._practiceSession.knowledgeScope
? Object.assign({}, this._practiceSession.knowledgeScope)
: null,
retryBlocked: false,
serverAccepted: false,
pendingPersisted: false,
keepPendingUntilResult: false,
}
this._practiceSession.submissionSnapshot = submission
submission.pendingPersisted = this._persistPendingSubmission(submission, 'pending', '')
this._setPracticeUnloadGuard(
true,
'交卷仍在确认中。',
)
} else {
this._clearTimer()
submission.pendingPersisted = this._persistPendingSubmission(submission, 'pending', '') || submission.pendingPersisted
}
this.setData({ submitting: true })
let submitResult
try {
const submitPayload = {
answers: submission.answers,
skipped_question_ids: submission.skippedQuestionIds,
session: submission.session,
_traceId: submission.traceId || this._practiceSession.traceId,
}
submitPayload.batch_token = submission.batchToken
submitResult = await api.post('/practice/batch-submit', submitPayload)
if (!this._pageAlive) return
} catch (e) {
if (!this._pageAlive) return
console.error('提交失败', e)
this._practiceSession.currentQuestionStartedMonoMs = 0
this.setData({ submitting: false })
const statusCode = Number(e && e.statusCode) || 0
const errorCode = String((e && e.code) || '')
const deterministicReject = (
errorCode === 'PRACTICE_SUBMISSION_CONFLICT' ||
errorCode === 'PRACTICE_QUESTION_VERSION_CONFLICT' ||
errorCode === 'PRACTICE_BATCH_INVALID' ||
errorCode === 'PRACTICE_PAYLOAD_INVALID' ||
(statusCode >= 400 && statusCode < 500 && ![401, 408, 429].includes(statusCode))
)
if (deterministicReject) {
submission.retryBlocked = true
submission.pendingPersisted = this._persistPendingSubmission(submission, 'blocked', '') || submission.pendingPersisted
this._setPracticeUnloadGuard(true, '本次提交未通过。')
let rejectTitle = '交卷内容未通过校验'
let rejectContent = '服务器已明确拒绝本次提交，继续重试相同内容不会成功。请退出后重新开始。'
if (errorCode === 'PRACTICE_SUBMISSION_CONFLICT') {
rejectTitle = '交卷标识冲突'
rejectContent = '该 request_id 已对应另一份提交。为避免结果串单，本次内容不会继续重试，请退出后重新开始。'
} else if (errorCode === 'PRACTICE_QUESTION_VERSION_CONFLICT') {
rejectTitle = '题目版本无法恢复'
rejectContent = '本组练习中有题目的历史版本无法恢复。为避免使用错误版本判题，本次提交已停止，请返回重新获取题目。'
} else if (errorCode === 'PRACTICE_BATCH_INVALID') {
rejectTitle = '练习批次已失效'
rejectContent = '本次题目批次已过期或与提交内容不一致。为避免串题，请退出后重新获取题目。'
}
await this._showSubmitConfirm({
scenario: 'danger',
title: rejectTitle,
message: rejectContent,
showCancel: false,
confirmText: '知道了',
hideEyebrow: true,
})
} else {
const persisted = this._persistPendingSubmission(submission, 'pending', '')
submission.pendingPersisted = persisted || submission.pendingPersisted
this._setPracticeUnloadGuard(
true,
'交卷仍在确认中。',
)
await this._showSubmitConfirm({
scenario: 'info',
title: '交卷结果未确认',
message: submission.pendingPersisted
? '已保存交卷进度，可稍后继续确认。'
: '暂未保存交卷进度，请保持当前页面并重试。',
showCancel: false,
confirmText: '知道了',
hideEyebrow: true,
})
}
return
}
submission.serverAccepted = true
submission.retryBlocked = false
const snapshotAnswerMap = submission.answerMap || {}
const snapshotAnsweredFlags = submission.answeredFlags || {}
const total = Number(submission.total) || 0
const unanswered = Number(submission.unanswered) || 0
const selectedSubjectId = submission.selectedSubjectId
const selectedSubjectName = submission.selectedSubjectName
const duration = Number(submission.duration) || 0
const comboCount = Number(submission.comboCount) || 0
const partialQuestionIdSet = {}
;(submission.partialQuestionIds || []).forEach(function(id) { partialQuestionIdSet[String(id)] = true })
let storedResults = (submitResult.results || []).map(function(rr) {
const questionId = String(rr.question_id)
const isPartial = rr.status === 'skipped' && partialQuestionIdSet[questionId]
return Object.assign({}, rr, {
status: isPartial ? 'partial' : rr.status,
_local_partial: !!isPartial,
user_answer: snapshotAnswerMap[questionId] || '',
})
})
var submittedResultMap = {}
storedResults.forEach(function(rr) { submittedResultMap[String(rr.question_id)] = true })
const questionSource = questions.length ? questions : (submission.recoveryQuestions || [])
questionSource.forEach(function(q) {
if (!q || !q.id || submittedResultMap[String(q.id)] || snapshotAnsweredFlags[String(q.id)]) return
const isPartial = !!partialQuestionIdSet[String(q.id)]
storedResults.push({
question_id: q.id,
user_answer: snapshotAnswerMap[String(q.id)] || '',
is_correct: false,
status: isPartial ? 'partial' : 'skipped',
_local_partial: isPartial,
_local_skipped: !isPartial,
})
})
var lightQuestions = []
for (var qi = 0; qi < questionSource.length; qi++) {
var qq = questionSource[qi]
if (qq && qq.id) {
lightQuestions.push({
id: qq.id,
question_version_id: qq.question_version_id || null,
question_version: qq.question_version || null,
stem: (qq.content && (qq.content.text || qq.content.stem)) || qq.stem || '',
options: qq.options || null,
question_type: qq.question_type || '',
})
}
}
const partialCount = (submission.partialQuestionIds || []).length
const serverSkippedCount = Number(submitResult.total_skipped ?? unanswered) || 0
const displaySkippedCount = Math.max(0, serverSkippedCount - partialCount)
var userId = this._getCurrentUserId()
var cacheCreatedAt = Date.now()
var cacheKey = 'pr_' + cacheCreatedAt + '_' + Math.random().toString(36).slice(2, 8)
const localResultPayload = {
correct: submitResult.total_correct || 0,
wrong: submitResult.total_wrong || 0,
skipped: displaySkippedCount,
partial: partialCount,
total,
subject_id: selectedSubjectId,
subject_name: selectedSubjectName,
duration,
traceId: submitResult.trace_id || submission.traceId || this._practiceSession.traceId,
results: storedResults,
questions: lightQuestions,
comboCount,
knowledge_session: submitResult.knowledge_session || submission.knowledgeScope || null,
request_id: submission.requestId || '',
_cacheKey: cacheKey,
_userId: userId,
_createdAt: cacheCreatedAt,
}
this._submittedResultPayload = localResultPayload
var resultCacheStored = false
try {
wx.setStorageSync('lastPracticeResult', localResultPayload)
resultCacheStored = true
} catch (storageError) {
console.warn('答题已提交成功，但本地结果缓存失败', storageError)
}
const resultUrl = [
`/subpackages/study/practice-result/index`,
`?correct=${submitResult.total_correct || 0}`,
`&wrong=${submitResult.total_wrong || 0}`,
`&skipped=${displaySkippedCount}`,
`&partial=${partialCount}`,
`&total=${total}`,
`&subject_id=${selectedSubjectId}`,
`&subject_name=${encodeURIComponent(selectedSubjectName || '')}`,
`&duration=${duration}`,
`&_ck=${cacheKey}`,
`&_rid=${encodeURIComponent(submission.requestId || '')}`,
`&_recover=${resultCacheStored ? '0' : '1'}`,
`&source=${encodeURIComponent(this._launchSource || '')}`,
`&return_to=${encodeURIComponent(this._launchReturnTo || '')}`,
].join('')
submission.keepPendingUntilResult = !resultCacheStored
this._pendingResultUrl = resultUrl
submission.pendingPersisted = this._persistPendingSubmission(submission, 'submitted', resultUrl) || submission.pendingPersisted
this._setPracticeUnloadGuard(false)
this.setData({ submitting: false, submitted: true })
this._openSubmittedResult(resultUrl, submission)
},
})
