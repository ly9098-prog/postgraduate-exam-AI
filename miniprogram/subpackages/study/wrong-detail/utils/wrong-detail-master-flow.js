function openMasterConfirm(page) {
if (page.data.masterSubmitting || page.data.isCurrentMastered) return
page.setData({ masterConfirmVisible: true })
}

function closeMasterConfirm(page) {
if (page.data.masterSubmitting) return
page.setData({ masterConfirmVisible: false })
}

function openUnmasterConfirm(page) {
if (page.data.masterSubmitting || !page.data.isCurrentMastered) return
page.setData({ unmasterConfirmVisible: true })
}

function closeUnmasterConfirm(page) {
if (page.data.masterSubmitting) return
page.setData({ unmasterConfirmVisible: false })
}

function onMasterAction(page) {
if (page.data.isCurrentMastered) {
page.openUnmasterConfirm()
} else {
page.openMasterConfirm()
}
}

async function confirmMastered(page, deps) {
    const wqId = page._currentWqId || (page.data.wq && page.data.wq.id)
    if (!wqId || page.data.masterSubmitting) return
    page.setData({ masterSubmitting: true, masterConfirmVisible: false })
    try {
      const masterResult = await deps.requestClient.post('/wrong-questions/batch', {
        action: 'mark_mastered', ids: [wqId],
      })
      if (!page._alive) return
      await page._handleMasterResult(masterResult, wqId)
    } catch (e) {
      if (!page._alive) return
      console.error('标记已掌握失败', e)
      page.setData({ masterSubmitting: false })
    }
  }

async function _handleMasterResult(page, masterResult, wqId, deps) {
    const masterSkipped = !!(
      masterResult && Array.isArray(masterResult.skipped_ids) &&
      masterResult.skipped_ids.some(id => String(id) === String(wqId))
    )
    const masterChanged = !masterSkipped && !(
      masterResult && masterResult.updated_count != null && Number(masterResult.updated_count) <= 0
    )
    if (!masterChanged) {
      page._clearMasterUndo()
      page.setData({ masterSubmitting: false })
      await page.loadData(wqId)
      if (page._alive) deps.platform.showToast({ title: '题目状态已同步', icon: 'none' })
      return
    }
    page._applyMasterChanged(wqId)
  }

function _applyMasterChanged(page, wqId) {
    page._clearMasterUndo()
    page._pendingMasterUndo = { wqId, originalIdx: page.data.currentIdx }
    if (page._wqCache && page._wqCache[wqId]) {
      page._wqCache[wqId].data = Object.assign({}, page._wqCache[wqId].data, { is_mastered: true })
    }
    if (page.data.wq && String(page.data.wq.id) === String(wqId)) {
      page.setData({
        wq: Object.assign({}, page.data.wq, { is_mastered: true }),
        isCurrentMastered: true, masterSubmitting: false, masterUndoVisible: true,
      })
    } else {
      page.setData({ masterSubmitting: false, masterUndoVisible: true })
    }
    page._armMasterUndoExpiry(5000)
    if (page.data.currentIdx < page.data.questionIds.length - 1) {
      page._masterAdvanceTimer = setTimeout(() => {
        page._masterAdvanceTimer = null
        page._navigateTo(page.data.currentIdx + 1, 150)
      }, 120)
    }
  }

async function confirmUnmastered(page, deps) {
const wqId = page._currentWqId || (page.data.wq && page.data.wq.id)
if (!wqId || page.data.masterSubmitting) return
page.setData({ masterSubmitting: true, unmasterConfirmVisible: false })
try {
const unmasterResult = await deps.requestClient.post('/wrong-questions/batch', {
action: 'unmark_mastered',
ids: [wqId],
})
if (!page._alive) return
const unmasterSkipped = !!(
unmasterResult && Array.isArray(unmasterResult.skipped_ids) &&
unmasterResult.skipped_ids.some(id => String(id) === String(wqId))
)
if (unmasterSkipped || (unmasterResult && unmasterResult.updated_count != null && Number(unmasterResult.updated_count) <= 0)) {
page._clearMasterUndo()
page.setData({ masterSubmitting: false })
await page.loadData(wqId)
if (page._alive) deps.platform.showToast({ title: '题目状态已同步', icon: 'none' })
return
}
page._clearMasterUndo()
if (page._wqCache && page._wqCache[wqId]) {
page._wqCache[wqId].data = Object.assign({}, page._wqCache[wqId].data, { is_mastered: false })
}
if (page.data.wq && String(page.data.wq.id) === String(wqId)) {
page.setData({
wq: Object.assign({}, page.data.wq, { is_mastered: false }),
isCurrentMastered: false,
masterSubmitting: false,
})
} else {
page.setData({ masterSubmitting: false })
}
deps.platform.showToast({ title: '已重新加入复习', icon: 'none' })
} catch (e) {
if (!page._alive) return
console.error('重新加入复习失败', e)
page.setData({ masterSubmitting: false })
deps.platform.showToast({ title: '操作失败，请重试', icon: 'none' })
}
}

module.exports = { openMasterConfirm, closeMasterConfirm, openUnmasterConfirm, closeUnmasterConfirm, onMasterAction, confirmMastered, _handleMasterResult, _applyMasterChanged, confirmUnmastered }
