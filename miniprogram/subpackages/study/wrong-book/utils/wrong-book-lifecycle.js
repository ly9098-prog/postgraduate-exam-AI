function onLoad(pageContext, options, { settings, safeDecodeURIComponent }) {
pageContext._destroyed = false
pageContext._statsRequestSeq = 0
pageContext._subjectsRequestSeq = 0
pageContext._taskFlowRequestSeq = 0
pageContext._batchMasterUndoInFlight = false
pageContext.setData({ enableMathImage: settings.enableMathImage || false })
pageContext._syncDateFilter()
const subjectId = options && options.subject_id != null ? Number(options.subject_id) : null
const topic = safeDecodeURIComponent(options && options.topic, '')
if (subjectId && Number.isFinite(subjectId)) {
pageContext.setData({ selectedSubjectId: subjectId })
}
if (topic) {
pageContext.setData({ selectedTopic: topic })
}
pageContext._updateFilterCount()
pageContext._checkExportCapability()
pageContext._restoreAiAutoSetting()
pageContext._restoreAiDiagnosisFromCache()
}

function onReady(pageContext) {
pageContext._ready = true
pageContext.loadSubjects()
pageContext._loadPage()
}

function onShow(pageContext) {
pageContext._alive = true
pageContext._syncDateFilter()
if (pageContext.data.batchMode) pageContext._showBatchCapsuleAndRefreshTimer()
if (!pageContext._ready) return
Promise.all([
pageContext.loadStats(),
pageContext.loadList(true),
]).then(() => pageContext._checkAiDiagnosis())
}

function onHide(pageContext) {
pageContext._alive = false
pageContext._clearBatchCapsuleIdleTimer()
}

function onUnload(pageContext) {
pageContext._alive = false
pageContext._destroyed = true
pageContext._exportCapabilityRequestId++
pageContext._statsRequestSeq++
pageContext._subjectsRequestSeq++
pageContext._taskFlowRequestSeq++
pageContext._listRequestSeq++
pageContext._aiDiagnosisRequestId++
pageContext._clearBatchCapsuleIdleTimer()
if (pageContext._selectionPulseTimer) {
clearTimeout(pageContext._selectionPulseTimer)
pageContext._selectionPulseTimer = null
}
if (pageContext._aiAutoSwitchTimer) {
clearTimeout(pageContext._aiAutoSwitchTimer)
pageContext._aiAutoSwitchTimer = null
}
pageContext._batchMasterUndoInFlight = false
pageContext._clearBatchMasterUndo(true)
}

module.exports = { onLoad, onReady, onShow, onHide, onUnload }
