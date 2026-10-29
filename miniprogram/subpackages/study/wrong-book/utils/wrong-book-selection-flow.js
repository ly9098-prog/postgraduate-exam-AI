function switchView(pageContext, e) {
const view = e.currentTarget.dataset.view === 'all' ? 'all' : 'task'
pageContext.setData({ activeView: view })
pageContext._syncSelectionState()
}

function openAllQuestions(pageContext) {
pageContext.setData({ activeView: 'all' })
pageContext._syncSelectionState()
}

function toggleBatchMode(pageContext) {
const next = !pageContext.data.batchMode
if (!next) pageContext._clearBatchCapsuleIdleTimer()
pageContext.setData({
batchMode: next,
batchCapsuleVisible: true,
batchMoreVisible: false,
showFilter: next ? false : pageContext.data.showFilter,
selectedIds: [],
selectedIdMap: {},
selectedCount: 0,
allVisibleSelected: false,
selectionPulse: false,
}, () => {
if (next) pageContext._showBatchCapsuleAndRefreshTimer()
})
}

function onPageInteraction(pageContext) {
pageContext._showBatchCapsuleAndRefreshTimer()
}

function onPageScroll(pageContext) {
pageContext._showBatchCapsuleAndRefreshTimer()
}

function _clearBatchCapsuleIdleTimer(pageContext) {
if (!pageContext._batchCapsuleIdleTimer) return
clearTimeout(pageContext._batchCapsuleIdleTimer)
pageContext._batchCapsuleIdleTimer = null
}

function _scheduleBatchCapsuleAutoHide(pageContext, idleMs) {
pageContext._clearBatchCapsuleIdleTimer()
if (!pageContext._alive || !pageContext.data.batchMode) return
pageContext._batchCapsuleIdleTimer = setTimeout(() => {
pageContext._batchCapsuleIdleTimer = null
if (!pageContext._alive || !pageContext.data.batchMode || !pageContext.data.batchCapsuleVisible) return
pageContext.setData({ batchCapsuleVisible: false })
}, idleMs)
}

function _showBatchCapsuleAndRefreshTimer(pageContext) {
if (!pageContext.data.batchMode) return
if (pageContext.data.batchCapsuleVisible) {
pageContext._scheduleBatchCapsuleAutoHide()
return
}
pageContext.setData({ batchCapsuleVisible: true }, () => {
pageContext._scheduleBatchCapsuleAutoHide()
})
}

function onQuestionTap(pageContext, e) {
if (Date.now() < pageContext._suppressQuestionTapUntil) return
const id = e.currentTarget.dataset.id
if (pageContext.data.batchMode) {
pageContext._toggleQuestionSelection(id)
return
}
pageContext._navigateToDetail(id)
}

function onSelectControlTap(pageContext, e) {
if (Date.now() < pageContext._suppressQuestionTapUntil) return
const id = e.currentTarget.dataset.id
if (!pageContext.data.batchMode) {
pageContext.setData({ batchMode: true, batchCapsuleVisible: true, showFilter: false }, () => {
pageContext._showBatchCapsuleAndRefreshTimer()
})
}
pageContext._toggleQuestionSelection(id)
}

function onQuestionLongPress(pageContext, e, { getPlatform }) {
const id = e.currentTarget.dataset.id
pageContext._suppressQuestionTapUntil = Date.now() + 700
if (!pageContext.data.batchMode) {
pageContext.setData({ batchMode: true, batchCapsuleVisible: true, showFilter: false }, () => {
pageContext._showBatchCapsuleAndRefreshTimer()
})
}
try {
getPlatform().vibrateShort({ type: 'light' })
} catch (_e) {}
pageContext._toggleQuestionSelection(id)
}

function _toggleQuestionSelection(pageContext, id) {
const key = String(id)
const map = { ...(pageContext.data.selectedIdMap || {}) }
const wasSelected = !!map[key]
if (wasSelected) delete map[key]
else map[key] = true
const ids = Object.keys(map)
pageContext.setData({
selectedIdMap: map,
selectedIds: ids,
selectedCount: ids.length,
})
pageContext._syncSelectionState()
if (!wasSelected) pageContext._pulseSelectionBadge()
}

function _pulseSelectionBadge(pageContext) {
if (pageContext._selectionPulseTimer) clearTimeout(pageContext._selectionPulseTimer)
pageContext.setData({ selectionPulse: false })
setTimeout(() => {
if (!pageContext._alive) return
pageContext.setData({ selectionPulse: true })
pageContext._selectionPulseTimer = setTimeout(() => {
if (pageContext._alive) pageContext.setData({ selectionPulse: false })
}, 260)
}, 16)
}

function _getVisibleIds(pageContext) {
if (pageContext.data.activeView === 'all') {
return (pageContext.data.list || []).map(item => String(item.id))
}
const ids = []
;(pageContext.data.taskGroups || []).forEach(group => {
;(group.items || []).forEach(item => ids.push(String(item.id)))
})
return Array.from(new Set(ids))
}

function toggleSelectAll(pageContext) {
const visibleIds = pageContext._getVisibleIds()
if (!visibleIds.length) return
const current = pageContext.data.selectedIdMap || {}
const allSelected = visibleIds.every(id => !!current[id])
const next = { ...current }
visibleIds.forEach(id => {
if (allSelected) delete next[id]
else next[id] = true
})
const ids = Object.keys(next)
pageContext.setData({
selectedIdMap: next,
selectedIds: ids,
selectedCount: ids.length,
allVisibleSelected: !allSelected,
})
if (!allSelected) pageContext._pulseSelectionBadge()
}

function _syncSelectionState(pageContext) {
const validIds = new Set((pageContext.data.list || []).map(item => String(item.id)))
;(pageContext.data.taskGroups || []).forEach(group => {
;(group.items || []).forEach(item => validIds.add(String(item.id)))
})
const nextMap = {}
Object.keys(pageContext.data.selectedIdMap || {}).forEach(id => {
if (validIds.has(String(id))) nextMap[String(id)] = true
})
const selectedIds = Object.keys(nextMap)
const visibleIds = pageContext._getVisibleIds()
const allVisibleSelected = visibleIds.length > 0 && visibleIds.every(id => !!nextMap[id])
pageContext.setData({
selectedIdMap: nextMap,
selectedIds,
selectedCount: selectedIds.length,
allVisibleSelected,
})
}

module.exports = { switchView, openAllQuestions, toggleBatchMode, onPageInteraction, onPageScroll, _clearBatchCapsuleIdleTimer, _scheduleBatchCapsuleAutoHide, _showBatchCapsuleAndRefreshTimer, onQuestionTap, onSelectControlTap, onQuestionLongPress, _toggleQuestionSelection, _pulseSelectionBadge, _getVisibleIds, toggleSelectAll, _syncSelectionState }
