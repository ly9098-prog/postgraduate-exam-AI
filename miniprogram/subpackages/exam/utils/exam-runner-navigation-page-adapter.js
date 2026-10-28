const api = require('../../../utils/api')
const view = require('./exam-runner-view')

function buildExamQuestionNavigationPageCapabilities(page) {
  return {
    getQuestions: () => page.data.questions || [],
    getAnswer: itemId => page._answers[itemId],
    getRenderView: itemId => page._renderCache[itemId],
    setQuestionEnterAt: value => { page._questionEnterAt = value },
    now: () => api.now(),
    setData: patch => page.setData(patch),
    buildAnswerState: (renderView, answer) => view.buildAnswerState(renderView, answer),
    isTimeExpired: () => page.data.timeExpired,
    isSubmitting: () => page.data.submitting,
    isNavigationLocked: () => page._navigationLocked,
    getCurrentItemId: () => page._currentItemId(),
    settleCurrentTime: options => page._settleCurrentTime(options),
    syncItem: itemId => page._syncItem(itemId),
    setCurrent: index => page._setCurrent(index),
  }
}

function buildExamExitRequestPageCapabilities(page) {
  return {
    isSubmitting: () => page.data.submitting,
    isNavigationLocked: () => page._navigationLocked,
    settleCurrentTime: options => page._settleCurrentTime(options),
    showExitDialog: () => page._showAppDialog({
      scenario: 'all-done',
      title: '暂时退出考试？',
      message: '60 分钟内回来可继续作答；超过 60 分钟草稿将被清除，需要重新作答。',
      confirmText: '退出',
      cancelText: '继续作答',
      hideEyebrow: true,
    }),
    navigateBack: options => wx.navigateBack(options),
  }
}

module.exports = {
  buildExamQuestionNavigationPageCapabilities,
  buildExamExitRequestPageCapabilities,
}
