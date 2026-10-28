const api = require('../../../utils/api')
const { isRetryableSubmitError } = require('./submit-helpers')

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, Math.max(0, Number(ms) || 0))) }

function buildExamSubmitRetryPageCapabilities(page) {
  return {
    isPageAlive: () => page._pageAlive,
    isTerminalNavigation: () => page._terminalNavigation,
    getRetryDelays: () => [0, 450, 1200],
    sleep,
    postSubmit: finalAnswers => api.post(
      `/exams/attempts/${page.data.attemptId}/submit`,
      { answers: finalAnswers },
      { timeout: 12000, suppressNetworkToast: true }
    ),
    reconcileAttemptState: () => page._reconcileAttemptState(),
    isRetryableSubmitError,
    getPageClosedMessage: () => '页面已关闭',
    getSubmitFailedMessage: () => '交卷失败',
  }
}

function buildExamSubmitEntryPageCapabilities(page) {
  return {
    isAttemptTerminal: () => page._attemptTerminal,
    isNavigationLocked: () => page._navigationLocked,
    getSubmitPromise: () => page._submitPromise,
    isSubmitting: () => page.data.submitting,
    isTimeExpired: () => page.data.timeExpired,
    isConfirmingSubmit: () => page._confirmingSubmit,
    setConfirmingSubmit: value => { page._confirmingSubmit = value },
    showConfirmDialog: dialog => page._showAppDialog(dialog),
    buildConfirmDialog: () => {
      const unanswered = Math.max(0, page.data.totalCount - page.data.answeredCount)
      const marked = (page.data.questions || []).filter((q) => q._marked).length
      return {
        scenario: unanswered ? 'unanswered' : 'all-done',
        title: '确认交卷',
        message: `${unanswered ? `还有 ${unanswered} 题未作答。` : '所有题目均已作答。'}${marked ? `\n另有 ${marked} 题待检查。` : ''}\n交卷后不可修改。`,
        confirmText: '确认交卷',
        cancelText: '继续检查',
        hideEyebrow: true,
      }
    },
    performSubmit: auto => page._performSubmit(auto),
    setSubmitPromise: task => { page._submitPromise = task },
    clearSubmitPromise: task => {
      if (page._submitPromise === task) page._submitPromise = null
    },
  }
}

function buildExamSubmitPreparationPageCapabilities(page) {
  return {
    getCurrentRemainingSec: () => page._currentRemainingSec(),
    isTimeExpired: () => page.data.timeExpired,
    setRetainPendingForSubmit: value => { page._retainPendingForSubmit = value },
    persistPending: () => page._persistPending(),
    setSubmitting: value => page.setData({ submitting: value }),
    clearTimer: () => page._clearTimer(),
    settleCurrentTime: options => page._settleCurrentTime(options),
    buildFinalSubmitAnswers: () => page._buildFinalSubmitAnswers(),
    onAutoResolved: value => { page._lastSubmitAuto = value },
  }
}

function buildExamSubmitOutcomePageCapabilities(page) {
  return {
    isPageAlive: () => page._pageAlive,
    clearPending: () => {
      page._pending = Object.create(null)
      page._retainPendingForSubmit = false
      page._clearPendingStorage()
    },
    setAttemptTerminal: value => { page._attemptTerminal = value },
    navigateReconciled: () => {
      if (page._pageAlive && !page._terminalNavigation) {
        if (page._attemptAbandoned) page._navigateToPaperList()
        else page._navigateToResult()
      }
    },
    navigateToResult: () => page._navigateToResult(),
    reconcileAttemptState: () => page._reconcileAttemptState(),
    setSubmitting: value => page.setData({ submitting: value }),
    showAutoSubmitPending: () => {
      page.setData({ timeExpired: true, remainingText: '已到时 · 待联网交卷' })
      wx.showToast({ title: '时间已到，答案已保留，联网后将自动交卷', icon: 'none' })
    },
    showManualSubmitError: error => {
      wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
      const remaining = page._currentRemainingSec()
      if (remaining == null || remaining > 0) page._startTimer(remaining)
      else {
        page.setData({ timeExpired: true, remainingText: '已到时 · 待联网交卷' })
        // Run after the current single-flight promise releases; otherwise
        // submitExam() would simply return the promise that is finishing now.
        setTimeout(() => {
          if (page._pageAlive && !page._attemptTerminal && !page._terminalNavigation) {
            page.submitExam({ auto: true }).catch(() => {})
          }
        }, 0)
      }
    },
  }
}

module.exports = {
  buildExamSubmitRetryPageCapabilities,
  buildExamSubmitEntryPageCapabilities,
  buildExamSubmitPreparationPageCapabilities,
  buildExamSubmitOutcomePageCapabilities,
}
