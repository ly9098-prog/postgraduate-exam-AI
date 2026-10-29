function _showAppOptions(pageContext, opts) {
const dialog = pageContext.selectComponent('#appDialog')
if (!dialog || typeof dialog.showOptions !== 'function') return Promise.resolve(-1)
return dialog.showOptions(opts || {})
}

async function openBatchMore(pageContext, { getPlatform }) {
if (!pageContext.data.selectedCount) {
getPlatform().showToast({ title: '请先选择错题', icon: 'none' })
return
}
const index = await pageContext._showAppOptions({
title: '批量处理',
message: `将作用于已选择的 ${pageContext.data.selectedCount} 道错题`,
items: ['移出错题本', '永久删除'],
dangerIndexes: [1],
})
if (index < 0) return
const action = index === 0 ? 'remove_from_book' : 'delete'
pageContext.onBatchAction({ currentTarget: { dataset: { action } } })
}

async function onBatchAction(pageContext, e, { requestClient, getPlatform }) {
    if (pageContext.data.batchSubmitting || pageContext._batchMasterUndoInFlight) return
    const action = e.currentTarget.dataset.action
    if (pageContext.data.batchMoreVisible) pageContext.setData({ batchMoreVisible: false })
    const ids = pageContext._resolveBatchIds()
    if (!ids.length) { getPlatform().showToast({ title: '请先选择错题', icon: 'none' }); return }
    const labels = pageContext._batchActionLabels()
    if (pageContext._isDangerousBatchAction(action)) {
      const confirmed = await pageContext._confirmBatchAction(labels[action], pageContext._batchConfirmMessage(action, ids.length))
      if (!confirmed) return
    }
    pageContext.setData({ batchSubmitting: true })
    getPlatform().showLoading({ title: '正在处理', mask: true })
    try {
      const result = await requestClient.post('/wrong-questions/batch', { action, ids })
      getPlatform().hideLoading()
      if (pageContext._destroyed) return
      if (action === 'mark_mastered') {
        await pageContext._handleBatchMastered(result, ids)
        return
      }
      pageContext._handleBatchSuccess(result, labels, action)
      await pageContext._reloadAfterBatch()
    } catch (err) {
      pageContext._handleBatchError(err)
    }
  }

function _resolveBatchIds(pageContext) {
    return (pageContext.data.selectedIds || []).map(id => {
      const n = Number(id)
      return Number.isFinite(n) && String(n) === String(id) ? n : id
    })
  }

function _batchActionLabels() {
    return {
      add_to_review: '加入今日复习', mark_mastered: '标记为已掌握',
      remove_from_book: '移出错题本', delete: '永久删除',
    }
  }

function _isDangerousBatchAction(action) {
    return action === 'delete' || action === 'remove_from_book'
  }

function _batchConfirmMessage(action, count) {
    return action === 'delete'
      ? `将永久删除已选择的 ${count} 道错题记录，是否继续？`
      : `将把已选择的 ${count} 道题移出错题本，是否继续？`
  }

function _handleBatchSuccess(pageContext, result, labels, action, { getPlatform }) {
    getPlatform().showToast({
      title: `${labels[action]}成功 ${result.updated_count != null ? result.updated_count : ids.length} 项`,
      icon: 'success',
    })
    pageContext._clearBatchCapsuleIdleTimer()
    pageContext.setData({
      batchSubmitting: false, batchMode: false, batchCapsuleVisible: true,
      batchMoreVisible: false, selectionPulse: false, selectedIds: [],
      selectedIdMap: {}, selectedCount: 0, allVisibleSelected: false,
    })
  }

function _handleBatchError(pageContext, err, { getPlatform }) {
    getPlatform().hideLoading()
    if (pageContext._destroyed) return
    pageContext.setData({ batchSubmitting: false })
    const isMissingEndpoint = err && (err.statusCode === 404 || err.statusCode === 405)
    if (isMissingEndpoint) {
      pageContext._showBatchMissingEndpoint()
    } else {
      getPlatform().showToast({ title: (err && err.message) || '批量操作失败', icon: 'none' })
    }
  }

async function _showBatchMissingEndpoint(pageContext, { getPlatform }) {
    const modal = pageContext.selectComponent('#actionConfirm')
    if (modal) {
      await modal.show({
        scenario: 'info', eyebrow: 'NOTICE', title: '批量接口尚未接入',
        message: '当前页面交互已经完成，但后端暂不支持该批量操作。',
        confirmText: '知道了', hideCancel: true,
      })
    } else {
      getPlatform().showToast({ title: '批量接口尚未接入', icon: 'none' })
    }
  }

function _reloadAfterBatch(pageContext) {
if (pageContext._destroyed) return Promise.resolve([])
return Promise.all([pageContext.loadStats(), pageContext.loadList(true)])
}

function _confirmBatchAction(pageContext, title, content) {
const modal = pageContext.selectComponent('#actionConfirm')
if (!modal) return Promise.resolve(false)
return modal.show({
scenario: 'danger',
eyebrow: 'IRREVERSIBLE',
title,
message: content,
confirmText: '继续操作',
cancelText: '取消',
})
}

module.exports = { _showAppOptions, openBatchMore, onBatchAction, _resolveBatchIds, _batchActionLabels, _isDangerousBatchAction, _batchConfirmMessage, _handleBatchSuccess, _handleBatchError, _showBatchMissingEndpoint, _reloadAfterBatch, _confirmBatchAction }
