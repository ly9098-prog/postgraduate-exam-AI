function _updateFilterCount(pageContext) {
const count = (pageContext.data.selectedSubjectId ? 1 : 0) + (pageContext.data.selectedErrorType ? 1 : 0) + (pageContext.data.selectedTopic ? 1 : 0) + (pageContext.data.dateFrom || pageContext.data.dateTo ? 1 : 0)
pageContext.setData({ filterCount: count })
}

function _hasFilters(pageContext) {
return !!(pageContext.data.selectedSubjectId || pageContext.data.selectedErrorType || pageContext.data.selectedTopic || pageContext.data.dateFrom || pageContext.data.dateTo)
}

function _syncDateFilter(pageContext, { requestClient, rangeHelper }) {
const now = requestClient.now()
const patch = {}
if (pageContext.data.selectedDatePreset !== 'custom') {
Object.assign(patch, rangeHelper.presetRange(pageContext.data.selectedDatePreset, now))
}
pageContext.setData(patch)
}

function _filterParams(pageContext) {
const params = { product_scope: 'exam408' }
if (pageContext.data.selectedSubjectId) params.subject_id = pageContext.data.selectedSubjectId
if (pageContext.data.selectedErrorType) params.error_type = pageContext.data.selectedErrorType
if (pageContext.data.selectedTopic) params.topic = pageContext.data.selectedTopic
if (pageContext.data.dateFrom) params.date_from = pageContext.data.dateFrom
if (pageContext.data.dateTo) params.date_to = pageContext.data.dateTo
return params
}

function toggleFilter(pageContext) {
pageContext._syncDateFilter()
if (!pageContext.data.subjectsLoaded && !pageContext.data.subjectsLoading) pageContext.loadSubjects()
pageContext.setData({ showFilter: !pageContext.data.showFilter })
}

function selectSubject(pageContext, e) {
const val = e.detail.value
const subjectId = (val === '' || val === null || val === undefined) ? null : Number(val)
pageContext._beginFilterReload({ selectedSubjectId: subjectId })
}

function selectErrorType(pageContext, e) {
const val = e.detail.value
pageContext._beginFilterReload({ selectedErrorType: val })
}

function onDateFilterChange(pageContext, e) {
const range = e.detail || {}
pageContext._beginFilterReload({ selectedDatePreset: range.preset || '', dateFrom: range.dateFrom || '', dateTo: range.dateTo || '' })
}

function retryList(pageContext) {
return pageContext.loadList(pageContext.data.list.length === 0)
}

function clearTopic(pageContext) {
pageContext._beginFilterReload({ selectedTopic: '' })
}

function loadMore(pageContext) {
if (pageContext.data.loading || !pageContext.data.hasMore) return
pageContext.loadList()
}

function resetFilters(pageContext) {
pageContext._beginFilterReload({
selectedSubjectId: null,
selectedErrorType: '',
selectedTopic: '',
selectedDatePreset: '',
dateFrom: '',
dateTo: '',
filterCount: 0,
})
}

module.exports = { _updateFilterCount, _hasFilters, _syncDateFilter, _filterParams, toggleFilter, selectSubject, selectErrorType, onDateFilterChange, retryList, clearTopic, loadMore, resetFilters }
