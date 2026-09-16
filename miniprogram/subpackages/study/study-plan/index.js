const api = require('../../../utils/api')
const { getChinaDate } = require('../../../utils/china-time')
const storage = require('../../../utils/storage')
const { studyStrategy } = storage
const DAILY_OPTIONS = [30, 45, 60, 90, 120, 150, 180, 240]
const WEEKLY_OPTIONS = [3, 4, 5, 6, 7]
const QUESTION_GOAL_OPTIONS = [10, 20, 30, 50]
const QUESTION_GOAL_KEY = 'home_today_goal_total'
const DEFAULT_QUESTION_GOAL = 30
const FAB_IDLE_DELAY = 3000
const FAB_SIZE_RPX = 120
const FAB_RIGHT_RPX = 32
const FAB_BOTTOM_RPX = 160
const FAB_POSITION_KEY = 'study-plan-fab-position'
const PRIORITY_OPTIONS = [
{ value: 'balanced', label: '均衡推进' },
{ value: 'review', label: '记忆复习优先' },
{ value: 'weakness', label: '薄弱点优先' },
{ value: 'new', label: '新知识推进优先' },
{ value: 'exam', label: '真题检测优先' },
]
const CATEGORY_META = {
review: { label: '复习', code: 'R' },
weakness: { label: '弱项', code: 'W' },
new: { label: '新题', code: 'N' },
exam: { label: '真题', code: 'E' },
}
function clampIndex(index, values) {
const i = Number(index)
if (!Number.isFinite(i) || i < 0 || i >= values.length) return 0
return Math.floor(i)
}
function formatTargetDate(value) {
const text = String(value || '')
const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
if (!match) return '请选择目标日期'
return `${match[1]}年${Number(match[2])}月${Number(match[3])}日`
}
Page({
data: {
loading: true,
saving: false,
configured: false,
errorText: '',
targetDate: '',
targetDateText: '请选择目标日期',
minDate: '',
dailyOptions: DAILY_OPTIONS,
weeklyOptions: WEEKLY_OPTIONS,
questionGoalOptions: QUESTION_GOAL_OPTIONS,
priorityOptions: PRIORITY_OPTIONS.map(item => item.label),
dailyIndex: 3,
weeklyIndex: 3,
questionGoalIndex: QUESTION_GOAL_OPTIONS.indexOf(DEFAULT_QUESTION_GOAL),
priorityIndex: 0,
daysRemaining: 0,
phaseLabel: '',
weeklyText: '',
todayTargetText: '',
todayProgressText: '',
todayProgressPercent: 0,
focusMinutes: 0,
isRestDay: false,
allocations: [],
stageOptions: studyStrategy.STAGES.map(item => item.label),
subjectStrategies: [],
strategyWeightTotal: 100,
strategyWeightValid: true,
fabX: 0,
fabY: 0,
fabReady: false,
fabIdle: false,
},
onLoad() {
this.setData({ minDate: getChinaDate(0), questionGoalIndex: this._getQuestionGoalIndex() })
this._loadStudyStrategy()
this._initFabPosition()
this.loadOverview()
},
onShow() {
this._loadStudyStrategy()
this._syncQuestionGoalFromStorage()
if (this._loadedOnce) this.loadOverview()
this._showFabAndScheduleHide()
},
onHide() {
this._clearFabTimers()
},
onUnload() {
this._clearFabTimers()
},
_clearFabTimers() {
if (this._fabIdleTimer) clearTimeout(this._fabIdleTimer)
if (this._fabDragClearTimer) clearTimeout(this._fabDragClearTimer)
this._fabIdleTimer = null
this._fabDragClearTimer = null
},
_getFabBounds() {
let windowWidth = 375
let windowHeight = 667
let safeBottom = 0
try {
const info = wx.getWindowInfo ? wx.getWindowInfo() : {}
windowWidth = Number(info.windowWidth || info.screenWidth || windowWidth)
windowHeight = Number(info.windowHeight || info.screenHeight || windowHeight)
if (info.safeArea && Number.isFinite(Number(info.safeArea.bottom))) {
safeBottom = Math.max(0, windowHeight - Number(info.safeArea.bottom))
}
} catch (_) {}
const rpx = windowWidth / 750
const size = FAB_SIZE_RPX * rpx
return {
windowWidth,
windowHeight,
safeBottom,
size,
maxX: Math.max(0, windowWidth - size),
maxY: Math.max(0, windowHeight - size),
rpx,
}
},
_initFabPosition() {
const bounds = this._getFabBounds()
let stored = null
try {
stored = wx.getStorageSync(FAB_POSITION_KEY)
} catch (_) {}
const storedX = stored && Number(stored.x)
const storedY = stored && Number(stored.y)
const defaultX = bounds.windowWidth - bounds.size - FAB_RIGHT_RPX * bounds.rpx
const defaultY = bounds.windowHeight - bounds.size - bounds.safeBottom - FAB_BOTTOM_RPX * bounds.rpx
const x = Number.isFinite(storedX) ? storedX : defaultX
const y = Number.isFinite(storedY) ? storedY : defaultY
this._lastFabPosition = {
x: Math.max(0, Math.min(bounds.maxX, x)),
y: Math.max(0, Math.min(bounds.maxY, y)),
}
this.setData({
fabX: this._lastFabPosition.x,
fabY: this._lastFabPosition.y,
fabReady: true,
fabIdle: false,
}, () => this._showFabAndScheduleHide())
},
_showFabAndScheduleHide() {
if (!this.data.fabReady) return
if (this._fabIdleTimer) clearTimeout(this._fabIdleTimer)
if (this.data.fabIdle) this.setData({ fabIdle: false })
this._fabIdleTimer = setTimeout(() => {
this._fabIdleTimer = null
if (this.data.saving) {
this._showFabAndScheduleHide()
return
}
this.setData({ fabIdle: true })
}, FAB_IDLE_DELAY)
},
onPlanInteraction() {
this._showFabAndScheduleHide()
},
onFabTouchStart() {
if (this._fabDragClearTimer) clearTimeout(this._fabDragClearTimer)
this._fabDragClearTimer = null
this._fabMoved = false
this._showFabAndScheduleHide()
},
onFabMove(e) {
const detail = e && e.detail ? e.detail : {}
const x = Number(detail.x)
const y = Number(detail.y)
if (Number.isFinite(x) && Number.isFinite(y)) this._lastFabPosition = { x, y }
if (String(detail.source || '').indexOf('touch') === 0) {
this._fabMoved = true
this._showFabAndScheduleHide()
}
},
onFabTouchEnd() {
if (this._lastFabPosition) {
try {
wx.setStorageSync(FAB_POSITION_KEY, this._lastFabPosition)
} catch (_) {}
}
this._showFabAndScheduleHide()
this._fabDragClearTimer = setTimeout(() => {
this._fabMoved = false
this._fabDragClearTimer = null
}, 300)
},
onFabTap() {
this._showFabAndScheduleHide()
if (this._fabMoved) return
this.savePlan()
},
onPullDownRefresh() {
this.loadOverview().finally(() => wx.stopPullDownRefresh())
},
async loadOverview() {
this.setData({ loading: true, errorText: '' })
try {
const overview = await api.get('/study-plan/overview')
this.applyOverview(overview)
} catch (error) {
this.setData({ errorText: api.getErrorMessage(error) })
} finally {
this._loadedOnce = true
this.setData({ loading: false })
}
},
applyOverview(overview) {
const data = overview || {}
const defaults = data.suggested_defaults || {}
if (!data.configured || !data.plan) {
const dailyValue = Number(defaults.daily_minutes) || 90
const weeklyValue = Number(defaults.weekly_days) || 6
const priorityValue = String(defaults.priority_mode || 'balanced')
this.setData({
configured: false,
dailyIndex: Math.max(0, DAILY_OPTIONS.indexOf(dailyValue)),
weeklyIndex: Math.max(0, WEEKLY_OPTIONS.indexOf(weeklyValue)),
priorityIndex: Math.max(0, PRIORITY_OPTIONS.findIndex(item => item.value === priorityValue)),
allocations: [],
})
return
}
const plan = data.plan
const countdown = data.countdown || {}
const weekly = data.weekly || {}
const today = data.today || {}
const dailyIndex = DAILY_OPTIONS.indexOf(Number(plan.daily_minutes))
const weeklyIndex = WEEKLY_OPTIONS.indexOf(Number(plan.weekly_days))
const priorityIndex = PRIORITY_OPTIONS.findIndex(item => item.value === String(plan.priority_mode))
const allocations = (Array.isArray(today.allocations) ? today.allocations : []).map(item => {
const meta = CATEGORY_META[item.category] || { label: '任务', code: 'T' }
const adjusted = Math.max(0, Number(item.adjusted_minutes) || 0)
const planned = Math.max(0, Number(item.planned_minutes) || 0)
const completed = Math.max(0, Number(item.completed_minutes) || 0)
let statusText = '等待安排'
if (item.status === 'done') statusText = '本项已完成'
else if (item.status === 'unavailable') statusText = '时间已转给其他任务'
else if (adjusted > 0) statusText = `接下来 ${adjusted} 分钟`
return {
category: item.category,
label: meta.label,
code: meta.code,
title: item.title || `${meta.label}任务`,
reason: item.reason || '',
plannedMinutes: planned,
completedMinutes: completed,
adjustedMinutes: adjusted,
status: item.status || 'available',
statusText,
actionLabel: item.action_label || '开始',
route: item.route || '',
routeParams: item.route_params || {},
canOpen: !!item.route && adjusted > 0,
}
})
this._overview = data
this.setData({
configured: true,
targetDate: String(plan.target_date || ''),
targetDateText: formatTargetDate(plan.target_date),
dailyIndex: dailyIndex >= 0 ? dailyIndex : 3,
weeklyIndex: weeklyIndex >= 0 ? weeklyIndex : 3,
priorityIndex: priorityIndex >= 0 ? priorityIndex : 0,
daysRemaining: Math.max(0, Number(countdown.days_remaining) || 0),
phaseLabel: countdown.phase_label || '',
weeklyText: `本周 ${Number(weekly.active_days) || 0}/${Number(weekly.target_days) || plan.weekly_days} 天`,
todayTargetText: today.is_rest_day
? '今天建议休息 / 轻量复盘'
: `今日 ${Number(today.target_minutes) || 0} 分钟`,
todayProgressText: `${Number(today.completed_minutes) || 0} / ${Number(today.target_minutes) || 0} 分钟`,
todayProgressPercent: Math.max(0, Math.min(100, Number(today.completion_percent) || 0)),
focusMinutes: Math.max(0, Number(today.focus_minutes) || 0),
isRestDay: !!today.is_rest_day,
allocations,
})
},

_getQuestionGoalIndex() {
const stored = Number(storage.get(QUESTION_GOAL_KEY))
const value = QUESTION_GOAL_OPTIONS.includes(stored) ? stored : DEFAULT_QUESTION_GOAL
const index = QUESTION_GOAL_OPTIONS.indexOf(value)
return index >= 0 ? index : 0
},
_syncQuestionGoalFromStorage() {
const index = this._getQuestionGoalIndex()
if (index !== this.data.questionGoalIndex) this.setData({ questionGoalIndex: index })
},
_saveQuestionGoal(index) {
const safeIndex = clampIndex(index, QUESTION_GOAL_OPTIONS)
const value = QUESTION_GOAL_OPTIONS[safeIndex]
storage.set(QUESTION_GOAL_KEY, value)
return safeIndex
},
_loadStudyStrategy() {
const profile = studyStrategy.getProfile()
const subjectStrategies = studyStrategy.SUBJECTS.map(meta => {
const current = profile.subjects.find(item => item.code === meta.code) || {}
const stageIndex = Math.max(0, studyStrategy.STAGES.findIndex(item => item.value === current.stage))
return {
code: meta.code,
name: meta.shortName,
stage: current.stage || meta.defaultStage,
stageIndex,
stageLabel: studyStrategy.stageLabel(current.stage || meta.defaultStage),
weight: Number(current.weight == null ? meta.defaultWeight : current.weight),
}
})
this._applySubjectStrategies(subjectStrategies)
},
_applySubjectStrategies(subjectStrategies) {
const rows = Array.isArray(subjectStrategies) ? subjectStrategies : []
const total = rows.reduce((sum, item) => sum + Number(item.weight || 0), 0)
this.setData({
subjectStrategies: rows,
strategyWeightTotal: total,
strategyWeightValid: total === 100,
})
},
onStrategyStageChange(e) {
const index = Number(e.currentTarget.dataset.index)
const stageIndex = clampIndex(e.detail.value, studyStrategy.STAGES)
if (!Number.isInteger(index) || index < 0 || index >= this.data.subjectStrategies.length) return
const rows = this.data.subjectStrategies.map((item, rowIndex) => rowIndex === index ? {
...item,
stageIndex,
stage: studyStrategy.STAGES[stageIndex].value,
stageLabel: studyStrategy.STAGES[stageIndex].label,
} : item)
this._applySubjectStrategies(rows)
},
onStrategyWeightChange(e) {
const index = Number(e.currentTarget.dataset.index)
if (!Number.isInteger(index) || index < 0 || index >= this.data.subjectStrategies.length) return
const value = Math.max(0, Math.min(100, Math.round((Number(e.detail.value) || 0) / 5) * 5))
const rows = this.data.subjectStrategies.map((item, rowIndex) => rowIndex === index ? { ...item, weight: value } : item)
this._applySubjectStrategies(rows)
},
_buildStrategyProfile() {
return {
version: studyStrategy.SCHEMA_VERSION,
subjects: this.data.subjectStrategies.map(item => ({ code: item.code, stage: item.stage, weight: Number(item.weight || 0) })),
}
},
onTargetDateChange(e) {
const value = String(e.detail.value || '')
this.setData({ targetDate: value, targetDateText: formatTargetDate(value) })
},
onDailyChange(e) {
this.setData({ dailyIndex: clampIndex(e.detail.value, DAILY_OPTIONS) })
},
onQuestionGoalChange(e) {
const questionGoalIndex = this._saveQuestionGoal(e.detail.value)
this.setData({ questionGoalIndex })
},
onWeeklyChange(e) {
this.setData({ weeklyIndex: clampIndex(e.detail.value, WEEKLY_OPTIONS) })
},
onPriorityChange(e) {
this.setData({ priorityIndex: clampIndex(e.detail.value, PRIORITY_OPTIONS) })
},
goBack() {
wx.navigateBack({ delta: 1 })
},
onPlanEnabledChange(e) {
const checked = !!(e && e.detail && e.detail.value)
if (checked) {
if (!this.data.configured) {
wx.showToast({ title: '请继续设置目标后保存', icon: 'none' })
}
return
}
if (this.data.configured && !this.data.saving) {
this.deletePlan()
return
}
this.setData({
targetDate: '',
targetDateText: '请选择目标日期',
})
},
_showAppDialog(opts) {
const dialog = this.selectComponent('#appDialog')
if (!dialog || typeof dialog.show !== 'function') return Promise.resolve(false)
return dialog.show(opts || {})
},
async savePlan() {
if (this.data.saving) return
this._saveQuestionGoal(this.data.questionGoalIndex)
const strategyValidation = studyStrategy.validateProfile(this._buildStrategyProfile())
if (!strategyValidation.valid) {
wx.showToast({ title: strategyValidation.message, icon: 'none' })
return
}
try {
studyStrategy.saveProfile(strategyValidation.profile)
} catch (error) {
wx.showToast({ title: error.message || '四科策略保存失败', icon: 'none' })
return
}
if (!this.data.targetDate) {
wx.showToast({ title: '四科策略已保存', icon: 'success' })
return
}
const payload = {
target_date: this.data.targetDate,
daily_minutes: DAILY_OPTIONS[this.data.dailyIndex],
weekly_days: WEEKLY_OPTIONS[this.data.weeklyIndex],
priority_mode: PRIORITY_OPTIONS[this.data.priorityIndex].value,
}
this.setData({ saving: true })
try {
await api.put('/study-plan', payload)
wx.showToast({ title: this.data.configured ? '计划已更新' : '计划已创建', icon: 'success' })
await this.loadOverview()
} catch (error) {
wx.showToast({ title: `计划保存失败，四科策略已保留：${api.getErrorMessage(error)}`, icon: 'none', duration: 2600 })
} finally {
this.setData({ saving: false })
}
},
async deletePlan() {
if (!this.data.configured || this.data.saving) return
const confirmed = await this._showAppDialog({
scenario: 'unanswered',
title: '暂停学习计划？',
message: '已有学习记录会保留，之后可随时重新设置计划。',
confirmText: '暂停计划',
cancelText: '继续使用',
hideEyebrow: true,
})
if (!confirmed) return
this.setData({ saving: true })
try {
await api.del('/study-plan')
wx.showToast({ title: '计划已暂停', icon: 'success' })
this.setData({ targetDate: '', targetDateText: '请选择目标日期' })
await this.loadOverview()
} catch (error) {
wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
} finally {
this.setData({ saving: false })
}
},
openAllocation(e) {
const category = String(e.currentTarget.dataset.category || '')
const item = (this._overview && this._overview.today && Array.isArray(this._overview.today.allocations))
? this._overview.today.allocations.find(row => row && row.category === category)
: null
if (!item || !item.route || Number(item.adjusted_minutes || 0) <= 0) return
if (item.route === 'review_today') {
wx.navigateTo({ url: '/subpackages/study/review-today/review-today' })
return
}
if (item.route === 'exam_list') {
const paperId = Number(item.route_params && item.route_params.suggested_paper_id)
wx.navigateTo({
url: `/subpackages/exam/paper-list/index${paperId ? '?suggested_paper_id=' + paperId : ''}`,
})
return
}
if (item.route !== 'practice') return
const params = item.route_params && typeof item.route_params === 'object' ? item.route_params : {}
const query = Object.keys(params)
.filter(key => params[key] !== undefined && params[key] !== null && params[key] !== '')
.map(key => `${encodeURIComponent(key)}=${encodeURIComponent(String(params[key]))}`)
.join('&')
wx.navigateTo({ url: `/subpackages/study/practice/practice${query ? '?' + query : ''}` })
},
})
