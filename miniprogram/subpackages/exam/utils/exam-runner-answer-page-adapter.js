const api = require('../../../utils/api')
const view = require('./exam-runner-view')

function buildExamInteractionPageCapabilities(page) {
  return {
    isTimeExpired: () => page.data.timeExpired,
    isSubmitting: () => page.data.submitting,
    isNavigationLocked: () => page._navigationLocked,
    getCurrentItemId: () => page._currentItemId(),
    getAnswer: itemId => page._answers[itemId],
    setAnswer: (itemId, answer) => { page._answers[itemId] = answer },
    queueItem: itemId => page._queueItem(itemId),
    updateQuestionFlags: itemId => page._updateQuestionFlags(itemId),
    getRenderView: itemId => page._renderCache[itemId],
    buildAnswerState: (renderView, answer) => view.buildAnswerState(renderView, answer),
    setData: patch => page.setData(patch),
    setCountsOnly: () => page._setCountsOnly(),
    syncItem: itemId => page._syncItem(itemId),
  }
}

function buildExamQuestionTimePageCapabilities(page) {
  return {
    getCurrentItemId: () => page._currentItemId(),
    getQuestionEnterAt: () => page._questionEnterAt,
    setQuestionEnterAt: value => { page._questionEnterAt = value },
    now: () => api.now(),
    getAnswer: itemId => page._answers[itemId],
    setAnswer: (itemId, answer) => { page._answers[itemId] = answer },
    queueItem: itemId => page._queueItem(itemId),
    syncItem: itemId => page._syncItem(itemId),
  }
}

function buildExamAnswerSyncPageCapabilities(page) {
  return {
    getPendingItem: itemId => page._pending[String(itemId)],
    removePendingItem: itemId => { delete page._pending[String(itemId)] },
    getPendingItemIds: () => page._pendingItemIds(),
    isPendingItemUnchanged: (itemId, snapshot) => {
      const current = page._pending[String(itemId)]
      return !!current && JSON.stringify(current) === JSON.stringify(snapshot)
    },
    getMaxSyncPasses: () => 2,
    persistPending: () => page._persistPending(),
    patchAnswer: (itemId, snapshot) => api.request(
      'PATCH',
      `/exams/attempts/${page.data.attemptId}/answers/${itemId}`,
      snapshot
    ),
    onTerminalSync: () => {
      page._attemptTerminal = true
      if (page._pageAlive && !page.data.submitting) page._navigateToResult()
    },
    resolveTerminalSyncConflict: error => page._resolveTerminalSyncConflict(error),
    showFlushError: () => wx.showToast({ title: '还有答案未同步，请检查网络', icon: 'none' }),
  }
}

function buildExamAttemptReconcilePageCapabilities(page) {
  return {
    isPageAlive: () => page._pageAlive,
    getAttempt: () => api.get(
      `/exams/attempts/${page.data.attemptId}`,
      {},
      { timeout: 10000, suppressNetworkToast: true }
    ),
    clearPending: () => {
      page._pending = Object.create(null)
      page._retainPendingForSubmit = false
      page._clearPendingStorage()
    },
    setAttemptTerminal: value => { page._attemptTerminal = value },
    setAttemptAbandoned: value => { page._attemptAbandoned = value },
    onAbandoned: () => {
      if (page._pageAlive && !page.data.submitting) page._navigateToPaperList()
    },
    onTerminal: () => {
      if (page._pageAlive && !page.data.submitting) page._navigateToResult()
    },
  }
}

module.exports = {
  buildExamInteractionPageCapabilities,
  buildExamQuestionTimePageCapabilities,
  buildExamAnswerSyncPageCapabilities,
  buildExamAttemptReconcilePageCapabilities,
}
