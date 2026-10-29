async function undoMastered(page, deps) {
    const pending = page._pendingMasterUndo
    if (!pending || page._masterUndoInFlight) return
    page._masterUndoInFlight = true
    page._clearMasterUndoTimers()
    try {
      await page._performUndoMastered(pending)
      deps.platform.showToast({ title: '已撤销掌握', icon: 'none' })
    } catch (e) {
      page._handleUndoMasterError(e, pending)
    } finally {
      page._masterUndoInFlight = false
    }
  }

function _clearMasterUndoTimers(page) {
    if (page._masterUndoTimer) { clearTimeout(page._masterUndoTimer); page._masterUndoTimer = null }
    if (page._masterAdvanceTimer) { clearTimeout(page._masterAdvanceTimer); page._masterAdvanceTimer = null }
  }

async function _performUndoMastered(page, pending, deps) {
    try {
      await deps.requestClient.post('/wrong-questions/batch', {
        action: 'unmark_mastered', ids: [pending.wqId],
      })
    } catch (freshError) {
      await page._handleUndoRequestError(freshError, pending)
    }
    page._commitUndoMastered(pending)
  }

async function _handleUndoRequestError(page, freshError, pending, deps) {
    const freshStatus = Number(freshError && (freshError.statusCode || freshError.status)) || 0
    if (freshStatus === 404 || freshStatus === 410) {
      page._clearMasterUndo()
      page._dropQuestionFromNavigation(pending.wqId)
      if (page._alive) deps.platform.showToast({ title: '该错题已被移除，无法撤销', icon: 'none' })
      return
    }
    throw freshError
  }

function _commitUndoMastered(page, pending) {
    if (page._wqCache && page._wqCache[pending.wqId]) {
      page._wqCache[pending.wqId].data = Object.assign({}, page._wqCache[pending.wqId].data, { is_mastered: false })
    }
    const targetIdx = page.data.questionIds.findIndex(id => String(id) === String(pending.wqId))
    page._clearMasterUndo()
    if (targetIdx >= 0 && targetIdx !== page.data.currentIdx) {
      page._navigateTo(targetIdx, 150)
    } else if (page.data.wq && String(page.data.wq.id) === String(pending.wqId)) {
      page.setData({ wq: Object.assign({}, page.data.wq, { is_mastered: false }), isCurrentMastered: false })
    } else if (targetIdx >= 0) {
      page.loadData(pending.wqId)
    }
  }

function _handleUndoMasterError(page, e, pending, deps) {
    if (!page._alive) return
    console.error('撤销已掌握失败', e)
    if (page._pendingMasterUndo === pending) {
      page.setData({ masterUndoVisible: true })
      page._armMasterUndoExpiry(5000)
    }
    deps.platform.showToast({ title: '撤销失败，请重试', icon: 'none' })
  }

function _armMasterUndoExpiry(page, ms) {
if (page._masterUndoTimer) clearTimeout(page._masterUndoTimer)
var duration = Number(ms) > 0 ? Number(ms) : 5000
page._masterUndoTimer = setTimeout(() => {
page._pendingMasterUndo = null
page._masterUndoTimer = null
if (page._alive) page.setData({ masterUndoVisible: false })
}, duration)
}

function _clearMasterUndo(page) {
if (page._masterUndoTimer) {
clearTimeout(page._masterUndoTimer)
page._masterUndoTimer = null
}
if (page._masterAdvanceTimer) {
clearTimeout(page._masterAdvanceTimer)
page._masterAdvanceTimer = null
}
page._pendingMasterUndo = null
if (page._alive && page.data && page.data.masterUndoVisible) {
page.setData({ masterUndoVisible: false })
}
}

module.exports = { undoMastered, _clearMasterUndoTimers, _performUndoMastered, _handleUndoRequestError, _commitUndoMastered, _handleUndoMasterError, _armMasterUndoExpiry, _clearMasterUndo }
