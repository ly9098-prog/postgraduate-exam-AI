function _beginFilterReload(pageContext, patch) {
pageContext._listRequestSeq++
pageContext._taskFlowRequestSeq++
pageContext.setData(Object.assign({
list: [],
listTotal: 0,
page: 1,
hasMore: false,
loading: true,
listError: '',
taskGroups: [],
ungroupedCount: 0,
selectedIds: [],
selectedIdMap: {},
selectedCount: 0,
allVisibleSelected: false,
batchMoreVisible: false,
}, patch || {}))
pageContext._updateFilterCount()
pageContext.loadList(true)
}

async function _loadPage(pageContext) {
pageContext.setData({ list: [], page: 1 })
await Promise.all([
pageContext.loadStats(),
pageContext.loadList(true),
])
if (pageContext._destroyed) return
await pageContext._checkAiDiagnosis()
}

async function loadStats(pageContext, { requestClient }) {
const requestSeq = ++pageContext._statsRequestSeq
try {
const stats = await requestClient.get('/wrong-questions/stats', { product_scope: 'exam408' })
if (pageContext._destroyed || requestSeq !== pageContext._statsRequestSeq) return
pageContext._aiStatsLoaded = true
const masteredCount = typeof stats.unmastered === 'number'
? Math.max(0, (stats.total || 0) - stats.unmastered)
: pageContext.data.list.filter(item => item._isMastered).length
const primaryStatCount = typeof stats.unmastered === 'number' ? stats.unmastered : (stats.total || 0)
const patch = {
stats,
primaryStatCount,
masteredCount,
highFrequencyCount: pageContext._positiveNumber(
stats.high_frequency_count,
pageContext.data.highFrequencyCount || 0
),
}
pageContext.setData(patch)
const hasFilter = pageContext._hasFilters()
if (!hasFilter && pageContext.data.list.length > 0) {
const analysis = pageContext._buildAnalysis(stats, pageContext.data.list)
pageContext.setData({
analysis,
aiInsightText: pageContext.data.aiDiagnosis
? pageContext._oneLineInsight(pageContext.data.aiDiagnosis.summary)
: pageContext._getAiInsightIdleText(pageContext.data.autoAiInsightEnabled),
})
}
} catch (e) {
if (pageContext._destroyed || requestSeq !== pageContext._statsRequestSeq) return
console.error('加载错题统计失败', e)
}
}

async function loadList(pageContext, reset = false, { requestClient }) {
const previousRange = `${pageContext.data.dateFrom}/${pageContext.data.dateTo}`
pageContext._syncDateFilter()
if (previousRange !== `${pageContext.data.dateFrom}/${pageContext.data.dateTo}`) {
reset = true
pageContext._taskFlowRequestSeq++
}
const page = reset ? 1 : pageContext.data.page
const seq = ++pageContext._listRequestSeq
pageContext.setData({ loading: true, listError: '' })
try {
const params = Object.assign({ page, page_size: 20 }, pageContext._filterParams())
const data = await requestClient.get('/wrong-questions', params)
if (seq !== pageContext._listRequestSeq || !pageContext._alive) return
const items = (data.items || []).map(item => pageContext._decorateItem(item))
const nextList = reset ? items : (pageContext.data.list || []).concat(items)
const hasFilter = pageContext._hasFilters()
const statsForAnalysis = hasFilter ? {} : (pageContext.data.stats || {})
if (seq !== pageContext._listRequestSeq || !pageContext._alive) return
const analysis = pageContext._buildAnalysis(statsForAnalysis, nextList)
const taskVm = pageContext._buildTaskGroups(nextList)
const statsHighFrequency = Number((pageContext.data.stats || {}).high_frequency_count)
const highFrequencyCount = Number.isFinite(statsHighFrequency)
? Math.max(0, Math.round(statsHighFrequency))
: nextList.filter(item => !item._isMastered && item._wrongCount >= 3).length
pageContext.setData({
list: nextList,
listTotal: Math.max(0, Number(data.total) || 0),
analysis,
taskGroups: taskVm.groups,
ungroupedCount: taskVm.ungroupedCount,
highFrequencyCount,
aiInsightText: pageContext.data.aiDiagnosis
? pageContext._oneLineInsight(pageContext.data.aiDiagnosis.summary)
: pageContext._getAiInsightIdleText(pageContext.data.autoAiInsightEnabled),
hasMore: page < data.total_pages,
page: reset ? 2 : page + 1,
loading: false,
})
pageContext._syncSelectionState()
if (reset) pageContext.loadTaskFlow()
} catch (e) {
console.error('加载错题列表失败', e)
if (seq === pageContext._listRequestSeq && pageContext._alive) {
pageContext.setData({ loading: false, listError: requestClient.getErrorMessage(e) })
}
}
}

async function loadTaskFlow(pageContext, { requestClient }) {
const requestSeq = ++pageContext._taskFlowRequestSeq
const params = Object.assign({ preview_size: 3 }, pageContext._filterParams())
try {
const data = await requestClient.get('/wrong-questions/task-flow', params)
if (pageContext._destroyed || !pageContext._alive || requestSeq !== pageContext._taskFlowRequestSeq) return
const meta = {
today_due: { desc: '基于复习计划，今天最值得先做的题', icon: '今', tone: 'lime' },
high_frequency: { desc: '重复出错次数较多，建议集中攻克', icon: '频', tone: 'orange' },
recent_added: { desc: '近 14 天新加入错题本的题目', icon: '新', tone: 'blue' },
to_consolidate: { desc: '尚未到复习日，但仍未完全掌握', icon: '固', tone: 'neutral' },
mastered: { desc: '已达到掌握标准，不再进入正常复习；再次答错会重新加入', icon: '✓', tone: 'green' },
}
const groups = (data.groups || []).map(group => {
const cfg = meta[group.key] || { desc: '', icon: '·', tone: 'neutral' }
return {
key: group.key,
title: group.title || '',
total: Math.max(0, Number(group.total) || 0),
items: (group.items || []).map(item => pageContext._decorateItem(item)),
desc: cfg.desc,
icon: cfg.icon,
tone: cfg.tone,
}
}).filter(group => group.total > 0 || group.items.length > 0)
const summary = data.summary || {}
const totalCount = Math.max(0, Number(summary.total_count) || 0)
const previewCount = groups.reduce((sum, group) => sum + group.items.length, 0)
const hasFilter = pageContext._hasFilters()
const globalHighFrequency = Number((pageContext.data.stats || {}).high_frequency_count)
const highFrequencyCount = Number.isFinite(globalHighFrequency)
? Math.max(0, Math.round(globalHighFrequency))
: (!hasFilter
? Math.max(0, Number(summary.high_frequency_count) || 0)
: pageContext._positiveNumber(pageContext.data.highFrequencyCount, 0))
pageContext.setData({
taskGroups: groups,
ungroupedCount: Math.max(0, totalCount - previewCount),
highFrequencyCount,
})
pageContext._syncSelectionState()
} catch (e) {
if (pageContext._destroyed || requestSeq !== pageContext._taskFlowRequestSeq) return
console.warn('加载错题任务流失败，保留当前列表分组兜底', e)
}
}

async function loadSubjects(pageContext, { requestClient }) {
if (pageContext.data.subjectsLoading) return
const requestSeq = ++pageContext._subjectsRequestSeq
pageContext.setData({ subjectsLoading: true, subjectsError: false })
try {
const raw = await requestClient.get('/practice/subjects')
if (pageContext._destroyed || requestSeq !== pageContext._subjectsRequestSeq) return
const subjects = pageContext._flattenSubjectOptions(raw)
pageContext.setData({
subjects: [{ value: '', label: '全部' }].concat(subjects),
subjectsLoading: false,
subjectsError: false,
subjectsLoaded: true,
})
} catch (e) {
if (pageContext._destroyed || requestSeq !== pageContext._subjectsRequestSeq) return
console.error('加载学科筛选失败', e)
pageContext.setData({
subjects: [{ value: '', label: '全部' }],
subjectsLoading: false,
subjectsError: true,
subjectsLoaded: false,
})
}
}

module.exports = { _beginFilterReload, _loadPage, loadStats, loadList, loadTaskFlow, loadSubjects }
