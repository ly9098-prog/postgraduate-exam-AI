async function _handleBatchMastered(pageContext, result, ids, { getPlatform }) {
    const hasSkippedIds = Array.isArray(result && result.skipped_ids)
    const skippedSet = new Set(hasSkippedIds ? result.skipped_ids.map(id => String(id)) : [])
    const reportedUpdatedCount = result && result.updated_count != null ? Number(result.updated_count) : ids.length
    const undoIds = hasSkippedIds
      ? ids.filter(id => !skippedSet.has(String(id)))
      : (reportedUpdatedCount === ids.length ? ids.slice() : [])
    const updatedCount = Math.max(0, Number.isFinite(reportedUpdatedCount) ? reportedUpdatedCount : undoIds.length)
    pageContext._clearBatchMasterUndo()
    pageContext._batchMasterUndoIds = undoIds.slice()
    const canUndo = undoIds.length > 0
    pageContext.setData({
      batchSubmitting: false, batchMasterUndoVisible: canUndo,
      _batchMasterUndoCount: canUndo ? undoIds.length : 0,
      selectionPulse: false, selectedIds: [], selectedIdMap: {},
      selectedCount: 0, allVisibleSelected: false,
    })
    if (canUndo) {
      pageContext._batchMasterUndoTimer = setTimeout(() => { pageContext._clearBatchMasterUndo() }, 5000)
    } else {
      getPlatform().showToast({ title: updatedCount > 0 ? `已标记掌握 ${updatedCount} 项` : '所选题目状态未变化', icon: 'none' })
    }
    await pageContext._reloadAfterBatch()
  }

function undoBatchMaster(pageContext, { requestClient, getPlatform }) {
const ids = (pageContext._batchMasterUndoIds || []).slice()
if (!ids.length || pageContext._batchMasterUndoInFlight) return
pageContext._batchMasterUndoInFlight = true
if (pageContext._batchMasterUndoTimer) {
clearTimeout(pageContext._batchMasterUndoTimer)
pageContext._batchMasterUndoTimer = null
}
getPlatform().showLoading({ title: '正在撤销', mask: true })
requestClient.post('/wrong-questions/batch', { action: 'unmark_mastered', ids }).then(result => {
getPlatform().hideLoading()
pageContext._batchMasterUndoInFlight = false
if (pageContext._destroyed) return
pageContext._clearBatchMasterUndo()
getPlatform().showToast({
title: `已撤销掌握 ${result.updated_count != null ? result.updated_count : ids.length} 项`,
icon: 'success',
})
pageContext._reloadAfterBatch()
}).catch(err => {
getPlatform().hideLoading()
pageContext._batchMasterUndoInFlight = false
if (pageContext._destroyed) return
getPlatform().showToast({ title: (err && err.message) || '撤销失败，可再次尝试', icon: 'none' })
pageContext._batchMasterUndoTimer = setTimeout(() => {
pageContext._clearBatchMasterUndo()
}, 5000)
})
}

function _clearBatchMasterUndo(pageContext, skipSetData) {
if (pageContext._batchMasterUndoTimer) {
clearTimeout(pageContext._batchMasterUndoTimer)
pageContext._batchMasterUndoTimer = null
}
pageContext._batchMasterUndoIds = []
if (!skipSetData && !pageContext._destroyed) {
pageContext.setData({ batchMasterUndoVisible: false, _batchMasterUndoCount: 0 })
}
}

module.exports = { _handleBatchMastered, undoBatchMaster, _clearBatchMasterUndo }
